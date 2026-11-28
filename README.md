# CausalSpan

[![CI](https://github.com/xsparc/causalspan/actions/workflows/ci.yml/badge.svg)](https://github.com/xsparc/causalspan/actions/workflows/ci.yml)

Local OpenTelemetry tracing, run comparison, and mocked tool replay for AI agents.

Follow a run from agent to model to tool, inspect observed token use and failures,
and reproduce recorded tool returns without a provider account or tracing server.
Traces use standard OTLP JSON export requests, one per line.

**Early alpha:** explicit Python instrumentation is implemented. Automatic framework
instrumentation, MCP/A2A adapters, and model-quality judges are planned. This is an
independent project; it is not affiliated with OpenTelemetry or other tracing tools.

## Try the offline demo

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```sh
git clone https://github.com/xsparc/causalspan.git
cd causalspan
uv sync --locked
uv run causalspan demo --output-dir traces/demo
```

Open `traces/demo/timeline.html` in a browser. The demo records two synthetic runs,
compares 180 observed tokens with 130, and replays a weather-tool response. It makes
no network or model calls. Choose a new output directory when running it again.

```sh
uv run causalspan inspect traces/demo/baseline.otlp.jsonl
uv run causalspan compare traces/demo/baseline.otlp.jsonl traces/demo/candidate.otlp.jsonl
uv run causalspan evaluate traces/demo/candidate.otlp.jsonl --max-tokens 150 --max-errors 0
uv run causalspan replay traces/demo/baseline.otlp.jsonl --calls traces/demo/calls.json
uv run causalspan timeline traces/demo/baseline.otlp.jsonl --output baseline-timeline.html
```

You can also install from the checkout with `python -m pip install .`. No package
release to PyPI has been made; install from source for now.

## Instrument a run

```python
from causalspan import AgentTracer

with AgentTracer("run.otlp.jsonl") as tracer:
    with tracer.agent("planner"):
        with tracer.model("example-model", provider="example") as span:
            # Wrap a real model call here; report the usage returned by its provider.
            tracer.usage(span, input_tokens=20, output_tokens=8)
        result = tracer.call_tool("add", lambda a, b: {"sum": a + b}, {"a": 2, "b": 3})
```

Nested agent spans represent local delegation. OpenTelemetry carries parent context
through ordinary `with` blocks and async tasks. Each tracer owns a provider and does
not replace the application's global provider. To use an existing provider, attach
`LocalTraceExporter` through an OpenTelemetry `SimpleSpanProcessor` or
`BatchSpanProcessor` and check the exporter's `failed_exports` after flushing.

Use `tracer.retry(span, attempt=1)` to record a retry event and
`tracer.policy(span, name="allowed-tools", allowed=True)` to record a policy decision.
These record what happened; they do not perform retries or enforce policy.

## Capture and replay tool results

Tool arguments and results are **not recorded by default**. Set
`capture_payloads=True` on `AgentTracer` to capture JSON-compatible tool payloads.
Use this only for data you are permitted to record. See
[record_and_replay.py](examples/record_and_replay.py) for a complete offline example.

```python
from causalspan.replay import Replay

recording = Replay("captured.otlp.jsonl")
result = recording.call("add", {"a": 2, "b": 3})
recording.assert_complete()
```

Replay uses explicit tool-call sequence metadata, then matches the next recorded
tool name and exact JSON arguments. External recordings without sequence metadata
must have distinct start times; tied timestamps are rejected as ambiguous. A mismatch,
missing payload, redacted payload, overlapping call, or exhausted recording raises
`ReplayError`. Failed recorded calls raise `RecordedToolError`. Replay has no live
tool fallback. It reproduces tool returns, not model output or a whole distributed
agent process. `call_tool` is a synchronous recording API; do not pass an async function.

## Reports and limits

| Capability | Current behavior |
| --- | --- |
| Local storage | OTLP JSON or newline-separated export requests; 32 MiB / 50,000-span input limits |
| Timeline | Parent-linked spans, relative timing, error status; standalone HTML with no scripts or remote assets |
| Comparison | Observed duration, model token counters, error spans, retries, and policy denials |
| Evaluation | Token/error/duration thresholds; exit `1` on failure, `2` on invalid input |
| Multiple runs | `inspect` lists all; use `--trace-id` for a selected timeline, evaluation, or replay |
| Replay | Ordered synchronous tool-call recordings with JSON arguments/results |

Comparison accepts `--before-trace-id` and `--after-trace-id`. Reports do not align
semantic steps between runs or judge answer quality. Error counts include errors
propagated through parent spans. Missing model counters, missing parents, and dropped
items remain visible; token thresholds fail when observed usage is incomplete.
Recorded data cannot prove that all spans were sampled or exported.

The exporter allows a small metadata set and omits arbitrary attributes, exception
messages, and stack traces. Payload capture redacts common sensitive **keys**, not
all sensitive values. Names, model identifiers, free text, and trace files can still
contain private data. JSON payloads are limited to 64 KiB and 32 nesting levels;
unsupported payloads are marked omitted without changing the live tool return.
Use separate files for separate processes and protect recordings with filesystem
permissions. Read the [security policy](SECURITY.md) before sharing traces.

Use `causalspan timeline TRACE --output REPORT.html --hide-identifiers` to omit
span names, span IDs, and the trace ID from the HTML. Numbered span labels keep
the parent-linked layout. Relative timings, topology, status, and aggregate
metrics remain visible and can still be sensitive. Inspect the report before
sharing it; the input trace is unchanged.

For a smaller JSON report, run `causalspan inspect TRACE --counts-only`.
The output is limited to numeric span, error, token, retry, policy-denial and
completeness counts. It omits trace IDs, timings, parent relationships and
labels. If the file contains multiple runs, choose one with `--trace-id`.
Counts can still be sensitive; inspect the output before sharing.

Compare shared counts-only reports without exchanging the original traces:

```sh
uv run causalspan compare-counts before-counts.json after-counts.json
```

Provide the UTF-8 JSON written by `inspect --counts-only` in two unchanged
local regular files in an operator-controlled directory, not symlinks, pipes
or network mounts. The command returns after-minus-before deltas only, and
rejects unknown, duplicate or malformed fields and files larger than 4 KiB.
This compares observed counts; it does not authenticate the reports, enforce
budgets or prove trace completeness.

## Development

```sh
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
uv run python scripts/check_governance.py
uv build
```

See [contributing](CONTRIBUTING.md), [architecture](docs/architecture/overview.md),
[roadmap](docs/roadmap/implementation-roadmap.md), and the
[maintenance workflow](docs/maintenance.md). CI covers Python 3.11 and 3.14 on Linux
and Windows. Dependency updates are proposed through pull requests; no automatic
merge, release, deployment, or scheduled agent maintenance is configured.

Licensed under [MIT](LICENSE).

[Otlp compatibility](docs/otlp-compatibility.md) documents the new behavior and limits.
