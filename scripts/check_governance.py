"""Check CausalSpan's local evidence index without third-party dependencies."""

import argparse
import json
import re
import tomllib
from datetime import date
from pathlib import Path, PurePosixPath

PRIORITY = [
    "docs/architecture/overview.md",
    "docs/roadmap/implementation-roadmap.md",
    "docs/architecture/decisions/",
    "code-and-tests",
    "supporting-documentation",
]


def check(root: Path, as_of: date | None = None) -> dict:
    root = root.resolve()
    errors, warnings = [], []
    try:
        evidence = tomllib.loads(
            (root / "docs/governance/project-evidence.toml").read_text("utf-8")
        )
        if evidence.get("schema_version") != 1 or evidence.get("project") != "causalspan":
            errors.append("registry identity or schema is invalid")
        authority = evidence["authority"]
        if (
            authority.get("source_priority") != PRIORITY
            or authority.get("dhf_is_authoritative") is not False
        ):
            errors.append("authority must match AGENTS.md and remain a derived index")
        reviewed = date.fromisoformat(evidence["review"]["last_reviewed"])
        due = date.fromisoformat(evidence["review"]["review_due"])
        if due < reviewed:
            errors.append("review dates are reversed")
        if as_of and due < as_of:
            warnings.append("project evidence review is overdue")
        ids, objective_ids, requirement_ids, designs = set(), set(), set(), set()

        def refs(record, field, required=True):
            values = record.get(field, [])
            if not isinstance(values, list) or (required and not values):
                errors.append(f"{record['id']}: missing {field}")
                return
            for value in values:
                if not isinstance(value, str):
                    errors.append(f"{record['id']}: non-string reference")
                    continue
                path = PurePosixPath(value)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or ":" in value
                    or "\\" in value
                    or any(part.startswith(".") for part in path.parts)
                ):
                    errors.append(f"{record['id']}: unsafe reference")
                    continue
                resolved = (root / value).resolve()
                if root not in resolved.parents or not resolved.is_file():
                    errors.append(f"{record['id']}: missing referenced file {value}")
                if field == "design_refs":
                    designs.add(value)

        for group in ("objectives", "requirements", "work_items", "research_decisions"):
            records = evidence[group]
            if not isinstance(records, list) or (group != "research_decisions" and not records):
                errors.append(f"missing {group}")
                continue
            for record in records:
                identity = record["id"]
                if not re.fullmatch(r"[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+", identity) or identity in ids:
                    errors.append("invalid or duplicate record ID")
                ids.add(identity)
                if group == "objectives":
                    objective_ids.add(identity)
                    refs(record, "source_refs")
                    refs(record, "validation_refs")
                elif group == "requirements":
                    requirement_ids.add(identity)
                    if (
                        not record.get("objective_ids")
                        or not set(record["objective_ids"]) <= objective_ids
                    ):
                        errors.append(f"{identity}: unknown objective")
                    status = record["status"]
                    if status not in {"planned", "implemented", "deferred", "retired"}:
                        errors.append(f"{identity}: invalid status")
                    for field in (
                        "roadmap_refs",
                        "design_refs",
                        "implementation_refs",
                        "verification_refs",
                        "validation_refs",
                        "risk_refs",
                    ):
                        refs(
                            record,
                            field,
                            status == "implemented" or field in {"roadmap_refs", "design_refs"},
                        )
                    if status == "deferred" and not all(
                        record.get(k) for k in ("deferral_reason", "reconsideration_trigger")
                    ):
                        errors.append(f"{identity}: deferral needs reason and trigger")
                elif group == "work_items":
                    if (
                        not record.get("requirement_ids")
                        or not set(record["requirement_ids"]) <= requirement_ids
                    ):
                        errors.append(f"{identity}: unknown requirement")
                    status = record["status"]
                    if status not in {
                        "proposed",
                        "approved",
                        "in-progress",
                        "verified",
                        "closed",
                        "blocked",
                    }:
                        errors.append(f"{identity}: invalid status")
                    if status in {
                        "approved",
                        "in-progress",
                        "verified",
                        "closed",
                    } and not re.fullmatch(
                        r"conversation:\d{4}-\d{2}-\d{2}-[a-z0-9-]+|"
                        r"https://github\.com/xsparc/causalspan/(issues|pull)/[1-9][0-9]*",
                        record.get("approval_ref", ""),
                    ):
                        errors.append(f"{identity}: missing concrete approval")
                    for field in ("roadmap_refs", "acceptance_refs", "evidence_refs"):
                        refs(
                            record,
                            field,
                            field != "evidence_refs" or status in {"verified", "closed"},
                        )
                else:
                    if record["disposition"] not in {"adopted", "monitoring", "rejected"}:
                        errors.append(f"{identity}: invalid research disposition")
                    if not record.get("source_urls") or not all(
                        url.startswith("https://") for url in record["source_urls"]
                    ):
                        errors.append(f"{identity}: missing research sources")
                    observed = date.fromisoformat(record["observed_on"])
                    reviewed = date.fromisoformat(record["reviewed_on"])
                    due = date.fromisoformat(record["review_due"])
                    if not observed <= reviewed <= due:
                        errors.append(f"{identity}: invalid research dates")
                    if as_of and due < as_of:
                        warnings.append(f"{identity}: research review is overdue")
                    refs({"id": identity, "decision": [record["decision_ref"]]}, "decision")
        for adr in (root / "docs/architecture/decisions").glob("*.md"):
            if re.search(r"(?im)^Status: accepted$", adr.read_text("utf-8")):
                if adr.relative_to(root).as_posix() not in designs:
                    errors.append("accepted ADR has no requirement reference")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        errors.append("registry is missing or malformed")
    return {
        "status": "fail" if errors else "warn" if warnings else "pass",
        "errors": errors,
        "warnings": warnings,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--as-of", type=date.fromisoformat)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    result = check(args.repository_root, args.as_of)
    print(json.dumps(result, indent=2))
    return 1 if result["status"] == "fail" or (args.strict and result["status"] == "warn") else 0


if __name__ == "__main__":
    raise SystemExit(main())
