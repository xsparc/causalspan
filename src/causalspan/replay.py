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
        self.calls = [
            s for s in select_trace(load_traces(path), trace_id) if s.operation == "execute_tool"
        ]
        if not self.calls:
            raise ReplayError("recording contains no tool calls")
        for left, right in zip(self.calls, self.calls[1:], strict=False):
            if right.start_ns < left.end_ns:
                raise ReplayError("overlapping tool calls require explicit ordering support")
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
