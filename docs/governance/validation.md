# Validation evidence

Date: 2026-11-17
Scope: CS-001, local tracing and replay foundation.

The starter's final Python 3.14 test run passed 52 tests after moving test temporary files
into the project and running outside the Windows execution sandbox. The sandboxed
async test stalled during event-loop initialization; that run was interrupted and
was not counted as a pass. The native async isolation test is included in the pass.

The suite exercises native OTLP protobuf decoding, span parentage, async context
isolation, absent payloads by default, key redaction, omitted payloads, safe exception
metadata, export failures, input bounds, malformed IDs/times/status/JSON, duplicate
spans, parent cycles, incomplete traces, HTML escaping, metric comparisons,
threshold failures, ordered tool replay, mismatch rejection, and CLI exit behavior.

Ruff lint and formatting checks passed. The source distribution and wheel built
successfully. The wheel installed into a clean virtual environment, where its
demo and token-threshold check passed. The example script also passed. The
synthetic CLI demo recorded 180 and 130 observed tokens and replayed its expected
result. Static and dated strict project governance checks
passed with no findings. GitHub CI results are available in the repository's
Actions tab after publication; local evidence does not claim a remote CI result.
No live model provider, MCP/A2A transport, multi-process
writer, hosted ingestion server, deployment, or package publication is validated
by these tests.

## Replay ordering correction

The initial GitHub CI run passed on Linux/Python 3.11 and 3.14 and on
Windows/Python 3.14. Windows/Python 3.11 exposed tied span timestamps that reordered
sequential tool calls and concealed nested overlap. The correction adds explicit
tool sequences, overlap metadata, and parentage checks. External recordings with
tied timestamps and no sequence now fail as ambiguous. Regression tests flatten
timestamps and reverse export order to avoid depending on host clock resolution.
The correction passes 59 local tests, Ruff lint/format checks, and static plus dated
strict governance checks. Pull-request CI is pending. This result is separate from
the original 52-test starter result.

## Governance checker scope

OpenSteward's bundled checker was executed and returned one `project.identity`
failure because it requires `opensteward-control-plane` as the project name. This
is a known checker applicability limit; it was not reported as a pass or bypassed
by relabeling the project. CausalSpan uses `scripts/check_governance.py`, a project-local
checker for identity, source priority, requirement/work-item links, safe file
references, accepted ADR coverage, approval references, and review freshness.
It checks traceability structure; it cannot prove that a cited test passed or
that a maintainer approved work. Those claims require the actual execution and
conversation evidence.
