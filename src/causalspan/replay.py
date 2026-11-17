"""Ordered mocked tool responses. This module has no tool execution path."""

import json

from .privacy import capture_json
from .reader import load_traces, select_trace


class ReplayError(ValueError):
    """A recording cannot satisfy the requested call safely."""


class RecordedToolError(ReplayError):
    """The selected recorded tool call failed; the original exception is not executed."""


class Replay:
    def __init__(self, path, *, trace_id: str | None = None):
        spans = select_trace(load_traces(path), trace_id)
        self.calls = [s for s in spans if s.operation == "execute_tool"]
        if not self.calls:
            raise ReplayError("recording contains no tool calls")
        # Parentage and explicit overlap flags survive coarse or tied wall clocks.
        parents = {s.span_id: s.parent_id for s in spans}
        tool_ids = {s.span_id for s in self.calls}
        clear_ancestors = set()
        for span in self.calls:
            overlap = span.attributes.get("causalspan.tool.overlap", False)
            if type(overlap) is not bool:
                raise ReplayError("invalid tool overlap metadata")
            if overlap:
                raise ReplayError("overlapping tool calls require explicit ordering support")
            current, chain = span.parent_id, []
            while current in parents and current not in clear_ancestors:
                if current in tool_ids:
                    raise ReplayError("overlapping tool calls require explicit ordering support")
                chain.append(current)
                current = parents[current]
            clear_ancestors.update(chain)
        chronological = sorted(self.calls, key=lambda s: s.start_ns)
        for left, right in zip(chronological, chronological[1:], strict=False):
            if right.start_ns < left.end_ns:
                raise ReplayError("overlapping tool calls require explicit ordering support")
        sequences = [s.attributes.get("causalspan.tool.sequence") for s in self.calls]
        if any(value is not None for value in sequences):
            if any(type(value) is not int or value < 0 for value in sequences) or len(
                set(sequences)
            ) != len(sequences):
                raise ReplayError("invalid or incomplete tool ordering metadata")
            self.calls.sort(key=lambda s: s.attributes["causalspan.tool.sequence"])
        else:
            if len({s.start_ns for s in self.calls}) != len(self.calls):
                raise ReplayError("ambiguous tool order: tied timestamps need ordering metadata")
            self.calls = chronological
        self._position = 0

    def call(self, name: str, arguments: dict):
        if self._position >= len(self.calls):
            raise ReplayError("recording is exhausted")
        span = self.calls[self._position]
        attrs = span.attributes
        if attrs.get("causalspan.capture.redacted") or attrs.get("causalspan.capture.omitted"):
            raise ReplayError("recorded payload was redacted or omitted")
        if span.dropped:
            raise ReplayError("recorded tool span has dropped data")
        if not isinstance(arguments, dict):
            raise ReplayError("tool arguments must be an object")
        try:
            actual, changed = capture_json(arguments)
            recorded = attrs["gen_ai.tool.call.arguments"]
            expected, was_redacted = capture_json(json.loads(recorded))
        except (ValueError, KeyError, TypeError, RecursionError) as exc:
            raise ReplayError("tool arguments were not captured as valid JSON") from exc
        if changed or was_redacted:
            raise ReplayError("sensitive arguments cannot be matched for replay")
        if attrs.get("gen_ai.tool.name") != name or actual != expected:
            raise ReplayError("tool name or arguments do not match the next recorded call")
        if span.status == 2:
            self._position += 1
            raise RecordedToolError("recorded tool call failed")
        try:
            result = json.loads(attrs["gen_ai.tool.call.result"])
            _, changed = capture_json(result)
        except (ValueError, KeyError, TypeError, RecursionError) as exc:
            raise ReplayError("tool result was not captured as valid JSON") from exc
        if changed:
            raise ReplayError("sensitive results cannot be replayed")
        self._position += 1
        return result

    def assert_complete(self) -> None:
        if self._position != len(self.calls):
            raise ReplayError("recording has unused tool calls")
