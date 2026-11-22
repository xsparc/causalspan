import asyncio
import base64
import json
import os
import stat

import pytest
from google.protobuf.json_format import ParseDict
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor

from causalspan import AgentTracer, LocalTraceExporter
from causalspan.reader import load_traces
from causalspan.report import summarize


def test_native_otlp_parentage_and_tokens(recording):
    spans = load_traces(recording)
    root = next(s for s in spans if s.operation == "invoke_agent")
    assert all(s.parent_id == root.span_id for s in spans if s != root)
    assert len({s.trace_id for s in spans}) == 1
    assert summarize(spans)["total_tokens"] == 15
    # OTLP differs from protobuf JSON only in ID encoding. Parse with the official schema.
    for line in recording.read_text().splitlines():
        document = json.loads(line)
        for resource in document["resourceSpans"]:
            for scope in resource["scopeSpans"]:
                for span in scope["spans"]:
                    assert isinstance(span["kind"], int)
                    for key in ("traceId", "spanId", "parentSpanId"):
                        if key in span:
                            span[key] = base64.b64encode(bytes.fromhex(span[key])).decode()
        assert ParseDict(document, ExportTraceServiceRequest()).resource_spans


def test_payloads_are_absent_by_default_and_exceptions_are_sanitized(tmp_path):
    path = tmp_path / "private.jsonl"
    with AgentTracer(path) as tracer:
        with pytest.raises(RuntimeError), tracer.agent("safe-name"):
            tracer.call_tool("safe-tool", lambda secret: {"content": secret}, {"secret": "PRIVATE"})
            raise RuntimeError("PRIVATE exception detail")
    text = path.read_text()
    assert "PRIVATE" not in text
    assert "stacktrace" not in text
    assert "gen_ai.tool.call.arguments" not in text
    assert summarize(load_traces(path))["errors"] == 1


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits only")
def test_trace_creation_uses_private_mode_without_changing_existing_permissions(tmp_path):
    path = tmp_path / "run.jsonl"
    previous_umask = os.umask(0o022)
    try:
        with AgentTracer(path) as tracer, tracer.agent("first"):
            pass
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        path.chmod(0o640)
        with AgentTracer(path) as tracer, tracer.agent("second"):
            pass
    finally:
        os.umask(previous_umask)
    assert stat.S_IMODE(path.stat().st_mode) == 0o640
    assert [span.attributes["gen_ai.agent.name"] for span in load_traces(path)] == [
        "first",
        "second",
    ]


def test_nested_redaction(tmp_path):
    path = tmp_path / "redacted.jsonl"
    with AgentTracer(path, capture_payloads=True) as tracer:
        tracer.call_tool("echo", lambda data: data, {"data": [{"api_key": "PRIVATE"}]})
    assert "PRIVATE" not in path.read_text()
    assert "[REDACTED]" in path.read_text()
    assert load_traces(path)[0].attributes["causalspan.capture.redacted"] is True


def test_capture_failure_does_not_change_tool_result(tmp_path):
    path = tmp_path / "omitted.jsonl"
    result = object()
    with AgentTracer(path, capture_payloads=True) as tracer:
        assert tracer.call_tool("object", lambda: result, {}) is result
    assert load_traces(path)[0].attributes["causalspan.capture.omitted"] is True


@pytest.mark.parametrize("count", [-1, True, 1.2, 2**63])
def test_invalid_token_counts(tmp_path, count):
    with AgentTracer(tmp_path / "counts.jsonl") as tracer:
        with tracer.model("model", provider="example") as span, pytest.raises(ValueError):
            tracer.usage(span, input_tokens=count, output_tokens=0)


def test_async_contexts_remain_separate(tmp_path):
    path = tmp_path / "concurrent.jsonl"

    async def work(tracer, name):
        with tracer.agent(name):
            await asyncio.sleep(0)
            with tracer.tool(name):
                await asyncio.sleep(0)

    async def run(tracer):
        await asyncio.gather(work(tracer, "one"), work(tracer, "two"))

    with AgentTracer(path) as tracer:
        asyncio.run(run(tracer))
    spans = load_traces(path)
    assert len({s.trace_id for s in spans}) == 2
    for span in spans:
        if span.operation == "execute_tool":
            parent = next(p for p in spans if p.span_id == span.parent_id)
            assert parent.attributes["gen_ai.agent.name"] == span.attributes["gen_ai.tool.name"]


def test_existing_provider_exporter_filters_arbitrary_content(tmp_path):
    path = tmp_path / "external.jsonl"
    exporter = LocalTraceExporter(path)
    provider = TracerProvider(shutdown_on_exit=False)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    with provider.get_tracer("external").start_as_current_span("safe") as span:
        span.set_attribute("private", "PRIVATE")
        span.add_event("exception", {"exception.message": "PRIVATE"})
    provider.shutdown()
    assert "PRIVATE" not in path.read_text()
    assert load_traces(path)[0].name == "safe"
    payload = json.loads(path.read_text())
    assert payload["resourceSpans"][0]["scopeSpans"][0]["scope"]["name"] == "external"


def test_close_reports_export_failure(tmp_path):
    tracer = AgentTracer(tmp_path / "failed.jsonl")
    tracer.exporter.shutdown()
    with tracer.agent("run"):
        pass
    with pytest.raises(OSError, match="export failed"):
        tracer.close()


def test_closed_tracer_rejects_new_work(tmp_path):
    tracer = AgentTracer(tmp_path / "closed.jsonl")
    tracer.close()
    with pytest.raises(RuntimeError, match="closed"), tracer.agent("late"):
        pass
