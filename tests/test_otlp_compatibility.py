import copy
import json
from pathlib import Path

import pytest

from causalspan.cli import main
from causalspan.reader import TraceFormatError, load_traces
from causalspan.report import evaluate, summarize

FIXTURE = Path(__file__).parent / "fixtures" / "external-otlp.json"


def document():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def span(data):
    return data["resourceSpans"][0]["scopeSpans"][0]["spans"][0]


def test_external_json_jsonl_metadata_and_cli(tmp_path, capsys):
    data = document()
    second = copy.deepcopy(data)
    span(second)["spanId"] = "ef" * 8
    span(second)["parentSpanId"] = "cd" * 8
    span(second)["startTimeUnixNano"] = "1001000001"
    span(second)["endTimeUnixNano"] = "1002000000"
    path = tmp_path / "external.jsonl"
    path.write_text(json.dumps(data) + "\n" + json.dumps(second) + "\n", encoding="utf-8")
    saved = path.read_bytes()
    spans = load_traces(path)
    assert spans[0].trace_id == "ab" * 16
    assert spans[1].parent_id == spans[0].span_id
    assert spans[0].resource_attributes == {"service.name": "synthetic-service"}
    assert spans[0].scope_name == "external.fixture" and spans[0].scope_version == "1.0"
    assert spans[0].scope_attributes == {"scope.tag": "test"}
    assert spans[0].scope_schema_url == spans[0].resource_schema_url
    spans[0].resource_attributes["service.name"] = "changed"
    assert spans[1].resource_attributes["service.name"] == "synthetic-service"
    assert spans[0].attributes["external.empty"] is None
    assert spans[0].attributes["external.bytes"] == "aGk="
    assert spans[0].attributes["external.array"] == [True, 1.25, -(2**63)]
    assert spans[0].attributes["external.map"] == {"nested": "value"}
    assert summarize(spans)["total_tokens"] == 30
    assert evaluate(spans, max_tokens=30)["passed"]
    assert main(["inspect", str(path)]) == 0
    assert json.loads(capsys.readouterr().out)["runs"][0]["total_tokens"] == 30
    assert main(["evaluate", str(path), "--max-tokens", "29"]) != 0
    output = tmp_path / "review.html"
    assert main(["timeline", str(path), "--output", str(output)]) == 0
    assert "default-src 'none'" in output.read_text(encoding="utf-8")
    assert path.read_bytes() == saved


def test_duplicate_json_fields_at_every_level(tmp_path):
    raw = FIXTURE.read_text(encoding="utf-8")
    for token in ['"resourceSpans":', '"scopeSpans":', '"traceId":', '"intValue":']:
        bad = raw.replace(token, '"duplicate":1,"duplicate":2,' + token, 1)
        path = tmp_path / "bad.json"
        path.write_text(bad, encoding="utf-8")
        with pytest.raises(TraceFormatError, match="duplicate"):
            load_traces(path)


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"futureValue": 123},
        {"stringValue": None},
        {"bytesValue": "aGk"},
        {"bytesValue": "-_8="},
        {"intValue": str(2**63 - 1)},
    ],
)
def test_anyvalue_compatible_forms(tmp_path, value):
    data = document()
    span(data)["attributes"] = [{"key": "external", "value": value}]
    path = tmp_path / "valid.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    assert len(load_traces(path)) == 1


@pytest.mark.parametrize(
    "value",
    [
        {"intValue": True},
        {"intValue": str(2**63)},
        {"bytesValue": "%%%"},
        {"bytesValue": "é"},
        {"intValue": 1, "stringValue": "two"},
        {"boolValue": "true"},
    ],
)
def test_anyvalue_invalid_forms(tmp_path, value):
    data = document()
    span(data)["attributes"] = [{"key": "external", "value": value}]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(TraceFormatError):
        load_traces(path)


def test_metadata_validation_and_unknown_fields(tmp_path):
    for change in ("scope_name", "resource_attributes"):
        data = document()
        resource = data["resourceSpans"][0]
        if change == "scope_name":
            resource["scopeSpans"][0]["scope"]["name"] = 123
        else:
            resource["resource"]["attributes"] = [
                {"key": "x", "value": {}},
                {"key": "x", "value": {}},
            ]
        path = tmp_path / "bad.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(TraceFormatError):
            load_traces(path)
    assert len(load_traces(FIXTURE)) == 1


def test_expanded_metadata_is_bounded(monkeypatch):
    monkeypatch.setattr("causalspan.reader.MAX_METADATA_BYTES", 8)
    with pytest.raises(TraceFormatError, match="metadata limit"):
        load_traces(FIXTURE)
