"""OTLP JSON-lines export through the official OpenTelemetry protobuf encoder."""

import base64
import json
import threading
from pathlib import Path

from google.protobuf.json_format import MessageToDict
from opentelemetry.exporter.otlp.proto.common.trace_encoder import encode_spans
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from .privacy import capture_json

_METADATA = frozenset(
    {
        "gen_ai.operation.name",
        "gen_ai.provider.name",
        "gen_ai.agent.name",
        "gen_ai.request.model",
        "gen_ai.response.model",
        "gen_ai.usage.input_tokens",
        "gen_ai.usage.output_tokens",
        "gen_ai.tool.name",
        "gen_ai.tool.type",
        "gen_ai.tool.call.id",
        "error.type",
        "causalspan.capture.redacted",
        "causalspan.capture.omitted",
        "causalspan.retry.attempt",
        "causalspan.policy.name",
        "causalspan.policy.allowed",
    }
)
_PAYLOADS = frozenset({"gen_ai.tool.call.arguments", "gen_ai.tool.call.result"})


def _hex_ids(record: dict) -> None:
    for key in ("traceId", "spanId", "parentSpanId"):
        if record.get(key):
            record[key] = base64.b64decode(record[key]).hex()


class LocalTraceExporter(SpanExporter):
    """Append one OTLP ExportTraceServiceRequest per line; no network transport.

    Resource attributes are limited to service.name; arbitrary span attributes,
    exception text, stack traces, link attributes, and trace state are omitted.
    Names and allowlisted metadata remain the caller's privacy responsibility.
    """

    def __init__(self, path: str | Path, *, capture_payloads: bool = False):
        self.path = Path(path)
        self.capture_payloads = capture_payloads
        self._lock = threading.Lock()
        self._closed = False
        self.failed_exports = 0
        # Open once to surface path/permission errors before instrumenting work.
        self._stream = self.path.open("a", encoding="utf-8", newline="\n")

    def _attributes(self, attributes: list[dict]) -> list[dict]:
        selected = []
        redacted = omitted = False
        for attr in attributes:
            key = attr["key"]
            if key in _METADATA:
                selected.append(attr)
            elif key in _PAYLOADS and self.capture_payloads:
                try:
                    value, changed = capture_json(json.loads(attr["value"]["stringValue"]))
                    selected.append({"key": key, "value": {"stringValue": value}})
                    redacted |= changed
                except (ValueError, KeyError, TypeError, RecursionError):
                    omitted = True
        # Merge flags rather than introducing duplicate OTLP attribute keys.
        for key, changed in (
            ("causalspan.capture.redacted", redacted),
            ("causalspan.capture.omitted", omitted),
        ):
            if changed:
                selected = [attr for attr in selected if attr["key"] != key]
                selected.append({"key": key, "value": {"boolValue": True}})
        return selected

    def export(self, spans) -> SpanExportResult:
        with self._lock:
            if self._closed:
                self.failed_exports += 1
                return SpanExportResult.FAILURE
            try:
                payload = MessageToDict(encode_spans(spans), use_integers_for_enums=True)
                for resource in payload.get("resourceSpans", []):
                    attrs = resource.get("resource", {}).get("attributes", [])
                    resource["resource"] = {
                        "attributes": [attr for attr in attrs if attr["key"] == "service.name"]
                    }
                    for scope in resource.get("scopeSpans", []):
                        scope["scope"] = {
                            key: value
                            for key, value in scope.get("scope", {}).items()
                            if key in {"name", "version"}
                        }
                        for span in scope.get("spans", []):
                            _hex_ids(span)
                            span.pop("traceState", None)
                            span["attributes"] = self._attributes(span.get("attributes", []))
                            span.get("status", {}).pop("message", None)
                            events = []
                            for event in span.get("events", []):
                                if event["name"] in {"causalspan.retry", "causalspan.policy"}:
                                    event["attributes"] = self._attributes(
                                        event.get("attributes", [])
                                    )
                                    events.append(event)
                            span["events"] = events
                            for link in span.get("links", []):
                                _hex_ids(link)
                                link.pop("traceState", None)
                                link.pop("attributes", None)
                line = json.dumps(payload, separators=(",", ":"), allow_nan=False)
                self._stream.write(line + "\n")
                self._stream.flush()
                return SpanExportResult.SUCCESS
            except (OSError, ValueError, TypeError, RecursionError):
                self.failed_exports += 1
                return SpanExportResult.FAILURE

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        with self._lock:
            return self.failed_exports == 0

    def shutdown(self) -> None:
        with self._lock:
            if not self._closed:
                self._stream.close()
                self._closed = True
