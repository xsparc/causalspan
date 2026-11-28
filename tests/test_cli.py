import json
import os
import stat

import pytest

from causalspan.cli import main


def test_demo_and_commands(tmp_path, capsys):
    output = tmp_path / "demo"
    assert main(["demo", "--output-dir", str(output)]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["comparison"]["delta"]["total_tokens"] == -50
    assert result["replayed_result"]["city"] == "Sydney"
    baseline = str(output / "baseline.otlp.jsonl")
    assert main(["inspect", baseline]) == 0
    capsys.readouterr()
    assert main(["compare", baseline, str(output / "candidate.otlp.jsonl")]) == 0
    capsys.readouterr()
    assert main(["evaluate", baseline, "--max-tokens", "100"]) == 1
    capsys.readouterr()
    assert main(["replay", baseline, "--calls", str(output / "calls.json")]) == 0
    capsys.readouterr()
    report = str(tmp_path / "timeline.html")
    assert main(["timeline", baseline, "--output", report]) == 0
    assert main(["timeline", baseline, "--output", report]) == 2
    assert main(["demo", "--output-dir", str(output)]) == 2


def test_missing_file_reports_safe_error(tmp_path, capsys):
    assert main(["inspect", str(tmp_path / "PRIVATE.json")]) == 2
    assert "PRIVATE" not in capsys.readouterr().err


@pytest.mark.skipif(os.name != "posix", reason="POSIX mode bits only")
def test_timeline_output_is_private_and_does_not_overwrite(tmp_path):
    demo = tmp_path / "demo"
    assert main(["demo", "--output-dir", str(demo)]) == 0
    output = tmp_path / "report.html"
    command = ["timeline", str(demo / "baseline.otlp.jsonl"), "--output", str(output)]
    previous_umask = os.umask(0o022)
    try:
        assert main(command) == 0
    finally:
        os.umask(previous_umask)
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    original = output.read_bytes()
    assert b"<html" in original
    assert main(command) == 2
    assert output.read_bytes() == original
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


def test_timeline_can_hide_names_and_identifiers(tmp_path):
    from causalspan import AgentTracer
    from causalspan.reader import load_traces

    trace = tmp_path / "run.jsonl"
    with AgentTracer(trace) as tracer, tracer.agent("synthetic-private-label"):
        with tracer.tool("synthetic-private-child"):
            pass
    spans = load_traces(trace)
    original = trace.read_bytes()
    full, reduced = tmp_path / "full.html", tmp_path / "reduced.html"
    assert main(["timeline", str(trace), "--output", str(full)]) == 0
    assert main(["timeline", str(trace), "--output", str(reduced), "--hide-identifiers"]) == 0
    full_html, reduced_html = full.read_text(encoding="utf-8"), reduced.read_text(encoding="utf-8")
    for sensitive in (
        {span.name for span in spans}
        | {span.trace_id for span in spans}
        | {span.span_id for span in spans}
    ):
        assert sensitive in full_html
        assert sensitive not in reduced_html
    assert "Span 1" in reduced_html
    assert "Span 2" in reduced_html
    assert "RELATIVE TIMING" in reduced_html
    assert trace.read_bytes() == original


def test_counts_only_omits_identifiers_timings_and_labels(tmp_path, capsys):
    from causalspan import AgentTracer
    from causalspan.reader import load_traces

    trace = tmp_path / "run.jsonl"
    with AgentTracer(trace) as tracer:
        for label in ("synthetic-first", "synthetic-second"):
            with tracer.agent(label):
                with tracer.model("synthetic-model", provider="test") as model:
                    tracer.usage(model, input_tokens=7, output_tokens=3)
    spans = load_traces(trace)
    source = trace.read_bytes()
    assert main(["inspect", str(trace), "--counts-only"]) == 2
    rejected = capsys.readouterr()
    assert not rejected.out
    trace_id = spans[0].trace_id
    assert trace_id not in rejected.err
    command = ["inspect", str(trace), "--trace-id", trace_id]
    assert main(command) == 0
    full = json.loads(capsys.readouterr().out)
    assert full["trace_id"] == trace_id
    assert "duration_ms" in full
    assert main([*command, "--counts-only"]) == 0
    reduced = json.loads(capsys.readouterr().out)
    assert reduced == {
        "spans": 2,
        "errors": 0,
        "input_tokens": 7,
        "output_tokens": 3,
        "total_tokens": 10,
        "model_spans_missing_usage": 0,
        "dropped_items": 0,
        "retries": 0,
        "policy_denials": 0,
    }
    assert all(type(count) is int for count in reduced.values())
    assert trace.read_bytes() == source


def test_compare_counts_cli_uses_only_exported_reports(tmp_path, capsys):
    demo = tmp_path / "demo"
    assert main(["demo", "--output-dir", str(demo)]) == 0
    capsys.readouterr()
    reports = []
    for name in ("baseline", "candidate"):
        trace = demo / f"{name}.otlp.jsonl"
        assert main(["inspect", str(trace), "--counts-only"]) == 0
        report = tmp_path / f"{name}-counts.json"
        report.write_text(capsys.readouterr().out, encoding="utf-8")
        trace.unlink()
        reports.append(report)
    command = ["compare-counts", *map(str, reports)]
    assert main(command) == 0
    result = json.loads(capsys.readouterr().out)
    before, after = (json.loads(path.read_bytes()) for path in reports)
    assert result == {"delta": {key: after[key] - value for key, value in before.items()}}
    assert result["delta"]["total_tokens"] == -50

    baseline = json.dumps(before)
    malformed = (
        baseline[:-1] + ', "spans": 99}',
        json.dumps(before | {"spans": True}),
        json.dumps(before | {"total_tokens": 1}),
        json.dumps(before | {"synthetic-private-label": 1}),
        baseline + " " * 4096,
    )
    for payload in malformed:
        reports[0].write_text(payload, encoding="utf-8")
        assert main(command) == 2
        captured = capsys.readouterr()
        assert not captured.out
        assert "synthetic-private-label" not in captured.err


def test_compare_counts_cli_rejects_invalid_files_with_fixed_diagnostic(tmp_path, capsys):
    report = tmp_path / "synthetic-private-filename.json"
    for bad_path in (report, tmp_path):
        assert main(["compare-counts", str(bad_path), str(report)]) == 2
        captured = capsys.readouterr()
        assert not captured.out
        assert captured.err.startswith("causalspan: compare-counts requires two readable")
        assert str(bad_path) not in captured.err
    for payload in (b"\xff", b"[" * 1800 + b"]" * 1800):
        report.write_bytes(payload)
        assert main(["compare-counts", str(report), str(report)]) == 2
        captured = capsys.readouterr()
        assert not captured.out
        assert captured.err.startswith("causalspan: compare-counts requires two readable")
        assert "Traceback" not in captured.err
        assert report.name not in captured.err


@pytest.mark.skipif(os.name != "posix", reason="POSIX filesystem objects")
def test_compare_counts_cli_rejects_symlinks_and_pipes(tmp_path, capsys):
    from subprocess import run
    from sys import executable

    target = tmp_path / "target.json"
    demo = tmp_path / "demo"
    assert main(["demo", "--output-dir", str(demo)]) == 0
    capsys.readouterr()
    assert main(["inspect", str(demo / "baseline.otlp.jsonl"), "--counts-only"]) == 0
    target.write_text(capsys.readouterr().out, encoding="utf-8")
    for path in (tmp_path / "link", tmp_path / "pipe"):
        if path.name == "link":
            path.symlink_to(target)
        else:
            os.mkfifo(path)
        result = run(
            [executable, "-m", "causalspan", "compare-counts", str(path), str(target)],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        assert result.returncode == 2
        assert not result.stdout
        assert "local regular files" in result.stderr
        assert str(path) not in result.stderr
