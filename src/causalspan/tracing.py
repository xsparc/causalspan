"""Explicit instrumentation without changing the global tracer provider."""

from contextlib import contextmanager
from pathlib import Path
from threading import Lock
from typing import Any

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanLimits, TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.trace import SpanKind, Status, StatusCode

from .exporter import LocalTraceExporter
from .privacy import capture_json


def _count(value: int) -> int:
    if type(value) is not int or value < 0 or value > 2**63 - 1:
        raise ValueError("count must be a nonnegative signed 64-bit integer")
    return value


class AgentTracer:
    """Own a local SDK provider. Use as a context manager to close the exporter."""

    def __init__(
        self, path: str | Path, *, service_name: str = "agent", capture_payloads: bool = False
    ):
        self.exporter = LocalTraceExporter(path, capture_payloads=capture_payloads)
        self.capture_payloads = capture_payloads
        self.provider = TracerProvider(
            resource=Resource({"service.name": service_name}),
            shutdown_on_exit=False,
            span_limits=SpanLimits(max_attribute_length=131_072),
        )
        self.provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        self.tracer = self.provider.get_tracer("causalspan", "0.1.0a1")
        self._closed = False
        self._tool_lock = Lock()
        self._tool_sequence = 0
        self._active_tools = {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def close(self) -> None:
        if not self._closed:
            self.provider.shutdown()
            self._closed = True
        if self.exporter.failed_exports:
            raise OSError("local trace export failed; trace may be incomplete")

    @contextmanager
    def _span(self, name: str, kind: SpanKind, attributes: dict):
        if self._closed:
            raise RuntimeError("tracer is closed")
        with self.tracer.start_as_current_span(
            name,
            kind=kind,
            attributes=attributes,
            record_exception=False,
            set_status_on_exception=False,
        ) as span:
            try:
                yield span
            except BaseException as exc:
                span.set_attribute("error.type", type(exc).__name__)
                span.set_status(Status(StatusCode.ERROR))
                raise

    def agent(self, name: str):
        return self._span(
            f"invoke_agent {name}",
            SpanKind.INTERNAL,
            {
                "gen_ai.operation.name": "invoke_agent",
                "gen_ai.agent.name": name,
            },
        )

    def model(self, model: str, *, provider: str, operation: str = "chat"):
        return self._span(
            f"{operation} {model}",
            SpanKind.CLIENT,
            {
                "gen_ai.operation.name": operation,
                "gen_ai.request.model": model,
                "gen_ai.provider.name": provider,
            },
        )

    @contextmanager
    def tool(self, name: str):
        with self._span(
            f"execute_tool {name}",
            SpanKind.INTERNAL,
            {
                "gen_ai.operation.name": "execute_tool",
                "gen_ai.tool.name": name,
                "gen_ai.tool.type": "function",
            },
        ) as span:
            trace_id = span.get_span_context().trace_id
            with self._tool_lock:
                sequence = self._tool_sequence
                span.set_attribute("causalspan.tool.sequence", sequence)
                self._tool_sequence += 1
                active = self._active_tools.setdefault(trace_id, {})
                if active:
                    span.set_attribute("causalspan.tool.overlap", True)
                    for other in active.values():
                        other.set_attribute("causalspan.tool.overlap", True)
                active[sequence] = span
            try:
                yield span
            finally:
                with self._tool_lock:
                    active = self._active_tools[trace_id]
                    active.pop(sequence)
                    if not active:
                        del self._active_tools[trace_id]

    @staticmethod
    def usage(span, *, input_tokens: int, output_tokens: int) -> None:
        counts = (_count(input_tokens), _count(output_tokens))
        span.set_attribute("gen_ai.usage.input_tokens", counts[0])
        span.set_attribute("gen_ai.usage.output_tokens", counts[1])

    @staticmethod
    def retry(span, *, attempt: int) -> None:
        span.add_event("causalspan.retry", {"causalspan.retry.attempt": _count(attempt)})

    @staticmethod
    def policy(span, *, name: str, allowed: bool) -> None:
        if type(allowed) is not bool:
            raise ValueError("allowed must be a boolean")
        span.add_event(
            "causalspan.policy",
            {
                "causalspan.policy.name": name,
                "causalspan.policy.allowed": allowed,
            },
        )

    def _capture(self, span, key: str, value: Any) -> None:
        try:
            encoded, redacted = capture_json(value)
            span.set_attribute(key, encoded)
            if redacted:
                span.set_attribute("causalspan.capture.redacted", True)
        except (ValueError, TypeError, RecursionError):
            span.set_attribute("causalspan.capture.omitted", True)

    def call_tool(self, name: str, function, arguments: dict) -> Any:
        """Call a synchronous tool once. Capture JSON payloads only when opted in.

        Unlike Replay.call(), this method intentionally executes the supplied tool.
        """
        if not isinstance(arguments, dict):
            raise ValueError("tool arguments must be an object")
        with self.tool(name) as span:
            if self.capture_payloads:
                self._capture(span, "gen_ai.tool.call.arguments", arguments)
            result = function(**arguments)
            if self.capture_payloads:
                self._capture(span, "gen_ai.tool.call.result", result)
            return result
