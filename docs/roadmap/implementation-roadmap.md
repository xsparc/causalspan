# Implementation roadmap

## CS-001: local tracing and replay foundation

Initial project creation authorized by the maintainer on 2026-11-17.
Acceptance: instrument a synthetic agent with nested model/tool spans; read the
result as OTLP JSON; inspect parentage and token usage; generate a safe HTML
timeline; compare two runs; evaluate a token/error threshold; replay captured
tool results without calling a live tool; reject mismatches and malformed input.
Provide installation instructions, tests, CI, a license, and maintenance guidance.

Expected paths: `src/`, `tests/`, `examples/`, `scripts/`, `docs/`, `.github/`,
and root package/community files. Validate with pytest, Ruff, wheel installation,
the offline demo and CLI, and static plus dated strict governance checks.

## CS-005: replay ordering on coarse clocks

Initial GitHub CI exposed tied timestamps on Windows/Python 3.11. Preserve explicit
tool invocation order and detect same-trace overlap independently of clock
resolution. Reject ambiguous external recordings. Acceptance: deterministic tied
timestamp, nested-parent, concurrent-sibling, and invalid-metadata regressions pass,
followed by the four-platform/version CI matrix. Merge remains a maintainer action.

## Future slices

- CS-002: external OTLP fixture matrix and semantic convention compatibility.
- CS-003: MCP and A2A context propagation adapters with protocol-specific tests.
- CS-004: asynchronous tool wrappers, richer comparison alignment, and evaluation
  datasets after the core API has user feedback.

These are proposed directions. Review scope and evidence before implementation.
No release, deployment, paid provider call, or merge is authorized by this roadmap.
