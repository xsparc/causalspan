import runpy
import shutil
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
check = runpy.run_path(str(ROOT / "scripts/check_governance.py"))["check"]


def test_real_evidence_and_freshness():
    assert check(ROOT, date(2026, 11, 17))["status"] == "pass"
    assert check(ROOT, date(2099, 1, 1))["status"] == "warn"


@pytest.mark.parametrize(
    "old,new",
    [
        ('project = "causalspan"', 'project = "other"'),
        ('"REQ-001", "REQ-002", "REQ-003"', '"REQ-999"'),
        ('"src/causalspan/replay.py"', '"../outside.py"'),
        ('"conversation:2026-11-17-start-open-source-project"', '"roadmap-is-not-approval"'),
    ],
)
def test_bad_evidence_is_rejected(tmp_path, old, new):
    for directory in ("docs", "src", "tests", "examples"):
        shutil.copytree(
            ROOT / directory, tmp_path / directory, ignore=shutil.ignore_patterns("__pycache__")
        )
    registry = tmp_path / "docs/governance/project-evidence.toml"
    registry.write_text(registry.read_text("utf-8").replace(old, new), encoding="utf-8")
    assert check(tmp_path, date(2026, 11, 17))["status"] == "fail"
