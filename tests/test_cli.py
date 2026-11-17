import json

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
