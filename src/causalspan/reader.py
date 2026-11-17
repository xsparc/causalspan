"""Bounded reading of OTLP JSON export requests and JSON-lines collections."""

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_SPANS = 50_000


class TraceFormatError(ValueError):
    """Input is not a supported, structurally valid trace collection."""


def _object(value: Any) -> dict:
    if not isinstance(value, dict):
        raise TraceFormatError("expected an OTLP object")
    return value


def _array(value: Any) -> list:
    if not isinstance(value, list):
        raise TraceFormatError("expected an OTLP array")
    return value


def _uint(value: Any) -> int:
    if type(value) is int:
        number = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]{1,20}", value):
        number = int(value)
    else:
        raise TraceFormatError("expected an unsigned integer")
    if not 0 <= number < 2**64:
        raise TraceFormatError("integer is out of range")
    return number


def _id(value: Any, length: int) -> str:
    if not isinstance(value, str) or not re.fullmatch(rf"[0-9a-fA-F]{{{length}}}", value):
        raise TraceFormatError("invalid trace or span ID")
    if int(value, 16) == 0:
        raise TraceFormatError("zero trace or span ID")
    return value.lower()


def _value(value: Any, depth: int = 0) -> Any:
    value = _object(value)
    if depth > 32:
        raise TraceFormatError("attribute nesting limit exceeded")
    known = set(value) & {
        "stringValue",
        "boolValue",
        "intValue",
        "doubleValue",
        "bytesValue",
        "arrayValue",
        "kvlistValue",
    }
    if len(known) != 1:
        raise TraceFormatError("invalid OTLP attribute value")
    kind = known.pop()
    item = value[kind]
    if kind in {"stringValue", "bytesValue"} and isinstance(item, str):
        return item
    if kind == "boolValue" and type(item) is bool:
        return item
    if kind == "intValue":
        if isinstance(item, str) and re.fullmatch(r"-?[0-9]{1,20}", item):
            item = int(item)
        if type(item) is int and -(2**63) <= item < 2**63:
            return item
    if kind == "doubleValue" and type(item) in {int, float}:
        try:
            if math.isfinite(item):
                return item
        except OverflowError as exc:
            raise TraceFormatError("double attribute is out of range") from exc
    if kind == "arrayValue":
        return [_value(v, depth + 1) for v in _array(_object(item).get("values", []))]
    if kind == "kvlistValue":
        return _attributes(_object(item).get("values", []), depth + 1)
    raise TraceFormatError("invalid OTLP attribute type")


def _attributes(value: Any, depth: int = 0) -> dict:
    result = {}
    for pair in _array(value):
        pair = _object(pair)
        key = pair.get("key")
        if not isinstance(key, str) or not key or key in result:
            raise TraceFormatError("invalid or duplicate attribute key")
        result[key] = _value(pair.get("value"), depth)
    return result


@dataclass(frozen=True)
class SpanRecord:
    trace_id: str
    span_id: str
    parent_id: str | None
    name: str
    start_ns: int
    end_ns: int
    attributes: dict
    status: int
    events: tuple[dict, ...]
    dropped: int

    @property
    def duration_ms(self) -> float:
        return (self.end_ns - self.start_ns) / 1_000_000

    @property
    def operation(self) -> str:
        return self.attributes.get("gen_ai.operation.name", "unknown")


def _span(value: Any) -> SpanRecord:
    span = _object(value)
    trace_id = _id(span.get("traceId"), 32)
    span_id = _id(span.get("spanId"), 16)
    parent = span.get("parentSpanId")
    parent = _id(parent, 16) if parent is not None and parent != "" else None
    name = span.get("name")
    if not isinstance(name, str) or not name:
        raise TraceFormatError("span name is missing")
    start, end = _uint(span.get("startTimeUnixNano")), _uint(span.get("endTimeUnixNano"))
    if end < start:
        raise TraceFormatError("span ends before it starts")
    attrs = _attributes(span.get("attributes", []))
    for key in ("gen_ai.operation.name", "gen_ai.request.model", "gen_ai.tool.name"):
        if key in attrs and not isinstance(attrs[key], str):
            raise TraceFormatError("invalid GenAI metadata type")
    for key in ("gen_ai.usage.input_tokens", "gen_ai.usage.output_tokens"):
        if key in attrs and (type(attrs[key]) is not int or attrs[key] < 0):
            raise TraceFormatError("invalid token count")
    status = _object(span.get("status", {})).get("code", 0)
    if type(status) is not int or status not in {0, 1, 2}:
        raise TraceFormatError("invalid span status")
    events = []
    for event in _array(span.get("events", [])):
        event = _object(event)
        if not isinstance(event.get("name"), str):
            raise TraceFormatError("invalid span event")
        events.append(
            {"name": event["name"], "attributes": _attributes(event.get("attributes", []))}
        )
    dropped = sum(
        _uint(span.get(key, 0))
        for key in (
            "droppedAttributesCount",
            "droppedEventsCount",
            "droppedLinksCount",
        )
    )
    return SpanRecord(
        trace_id, span_id, parent, name, start, end, attrs, status, tuple(events), dropped
    )


def _reject_constant(value):
    raise TraceFormatError("non-finite JSON numbers are unsupported")


def load_traces(path: str | Path, *, max_bytes: int = MAX_FILE_BYTES) -> list[SpanRecord]:
    if type(max_bytes) is not int or max_bytes < 1:
        raise ValueError("max_bytes must be a positive integer")
    with Path(path).open("rb") as stream:
        raw = stream.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise TraceFormatError("trace file exceeds the size limit")
    try:
        text = raw.decode("utf-8-sig")
        try:
            documents = [json.loads(text, parse_constant=_reject_constant)]
        except json.JSONDecodeError:
            documents = [
                json.loads(line, parse_constant=_reject_constant)
                for line in text.splitlines()
                if line.strip()
            ]
        spans = []
        seen = set()
        for document in documents:
            resources = _object(document).get("resourceSpans")
            for resource in _array(resources):
                for scope in _array(_object(resource).get("scopeSpans", [])):
                    for value in _array(_object(scope).get("spans", [])):
                        span = _span(value)
                        key = (span.trace_id, span.span_id)
                        if key in seen:
                            raise TraceFormatError("duplicate span ID in trace")
                        seen.add(key)
                        spans.append(span)
                        if len(spans) > MAX_SPANS:
                            raise TraceFormatError("span count limit exceeded")
        if not spans:
            raise TraceFormatError("trace file contains no spans")
        _check_cycles(spans)
        return sorted(spans, key=lambda s: (s.start_ns, s.span_id))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise TraceFormatError("invalid trace JSON") from exc


def _check_cycles(spans: list[SpanRecord]) -> None:
    parents = {(s.trace_id, s.span_id): (s.trace_id, s.parent_id) for s in spans}
    finished = set()
    for key in parents:
        chain = set()
        current = key
        while current in parents and current not in finished:
            if current in chain:
                raise TraceFormatError("parent cycle in trace")
            chain.add(current)
            current = parents[current]
        finished.update(chain)


def select_trace(spans: list[SpanRecord], trace_id: str | None = None) -> list[SpanRecord]:
    ids = {s.trace_id for s in spans}
    if trace_id is None:
        if len(ids) != 1:
            raise TraceFormatError("choose one trace ID when a file contains multiple runs")
        trace_id = next(iter(ids))
    selected = [s for s in spans if s.trace_id == trace_id.lower()]
    if not selected:
        raise TraceFormatError("trace ID was not found")
    return selected
