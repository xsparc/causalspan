import json

import pytest

from causalspan import AgentTracer
from causalspan.reader import TraceFormatError, load_traces, select_trace
from causalspan.report import compare, evaluate, summarize, timeline_html


def mutate(recording, transform):
    documents = [json.loads(line) for line in recording.read_text().splitlines()]
    spans = [
        s
        for d in documents
        for r in d["resourceSpans"]
        for scope in r["scopeSpans"]
        for s in scope["spans"]
    ]
    transform(spans)
    recording.write_text("\n".join(json.dumps(d) for d in documents))


@pytest.mark.parametrize(
    "field,value",
    [
        ("traceId", "0" * 32),
        ("spanId", "invalid"),
        ("startTimeUnixNano", "-1"),
        ("endTimeUnixNano", "0"),
        ("status", {"code": "ERROR"}),
        ("name", None),
        ("attributes", [{"key": "gen_ai.usage.input_tokens", "value": {"intValue": "-3"}}]),
    ],
)
def test_invalid_span_rejected(recording, field, value):
    mutate(recording, lambda spans: spans[0].update({field: value}))
    with pytest.raises(TraceFormatError):
        load_traces(recording)


def test_parent_cycle_rejected(recording):
    mutate(recording, lambda spans: spans[0].update({"parentSpanId": spans[0]["spanId"]}))
    with pytest.raises(TraceFormatError, match="cycle"):
        load_traces(recording)


def test_duplicate_span_rejected(recording):
    recording.write_text(recording.read_text() * 2)
    with pytest.raises(TraceFormatError, match="duplicate"):
        load_traces(recording)


def test_bounded_input(recording):
    with pytest.raises(TraceFormatError, match="size limit"):
        load_traces(recording, max_bytes=8)


@pytest.mark.parametrize(
    "content", ["", "{}", "[]", "{broken", '{"resourceSpans":null}', '{"resourceSpans":[NaN]}']
)
def test_malformed_input(tmp_path, content):
    path = tmp_path / "bad.json"
    path.write_text(content)
    with pytest.raises(TraceFormatError):
        load_traces(path)


def test_unknown_fields_ignored_and_pretty_json_supported(recording):
    document = json.loads(recording.read_text().splitlines()[0])
    document["futureField"] = {"anything": True}
    recording.write_text(json.dumps(document, indent=2))
    assert len(load_traces(recording)) == 1


def test_incomplete_trace_fails_threshold(recording):
    mutate(recording, lambda spans: spans[0].update({"parentSpanId": "f" * 16}))
    spans = load_traces(recording)
    assert summarize(spans)["missing_parents"] == 1
    assert not evaluate(spans)["passed"]
    assert "missing parent" in timeline_html(spans)


def test_summary_comparison_and_threshold(recording):
    spans = load_traces(recording)
    assert compare(spans, spans)["delta"]["total_tokens"] == 0
    assert evaluate(spans, max_tokens=15)["passed"]
    assert not evaluate(spans, max_tokens=14)["passed"]
    with pytest.raises(ValueError):
        evaluate(spans, max_duration_ms=float("nan"))


def test_missing_tokens_are_not_treated_as_zero(tmp_path):
    path = tmp_path / "unknown.jsonl"
    with AgentTracer(path) as tracer, tracer.model("model", provider="example"):
        pass
    result = evaluate(load_traces(path), max_tokens=100)
    assert not result["passed"]
    assert "model token usage is incomplete" in result["failures"]


def test_html_escapes_untrusted_labels(recording):
    mutate(recording, lambda spans: spans[0].update({"name": '<script>alert("x")</script>'}))
    report = timeline_html(load_traces(recording))
    assert "<script>" not in report
    assert "&lt;script&gt;" in report
    assert "default-src 'none'" in report


def test_multiple_runs_require_selection(tmp_path):
    path = tmp_path / "multi.jsonl"
    with AgentTracer(path) as tracer:
        for name in ["first", "second"]:
            with tracer.agent(name):
                pass
    spans = load_traces(path)
    with pytest.raises(TraceFormatError, match="choose one"):
        select_trace(spans)
    assert len(select_trace(spans, spans[0].trace_id)) == 1


def test_agent_aggregate_tokens_are_not_counted_twice(tmp_path):
    path = tmp_path / "aggregate.jsonl"
    with AgentTracer(path) as tracer:
        with tracer.agent("planner") as root:
            root.set_attribute("gen_ai.request.model", "legacy-agent-model")
            tracer.usage(root, input_tokens=10, output_tokens=5)
            with tracer.model("model", provider="example") as model:
                tracer.usage(model, input_tokens=10, output_tokens=5)
    assert summarize(load_traces(path))["total_tokens"] == 15


def test_nonfinite_attribute_is_rejected(recording):
    mutate(
        recording,
        lambda spans: spans[0].update(
            {"attributes": [{"key": "future.number", "value": {"doubleValue": 1.0}}]}
        ),
    )
    recording.write_text(
        recording.read_text().replace('"doubleValue": 1.0', '"doubleValue": 1e999')
    )
    with pytest.raises(TraceFormatError):
        load_traces(recording)


def test_unset_span_status_is_not_reported_as_ok(recording):
    report = timeline_html(load_traces(recording))
    assert "<td>unset</td>" in report
