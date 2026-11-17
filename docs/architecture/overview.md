# Architecture

CausalSpan is a Python library and offline CLI for debugging agent runs. It uses
the OpenTelemetry SDK for context, parentage, span IDs, timing, and status. A local
exporter writes OTLP JSON export requests, one request per line. It does not define
a replacement trace format or require a server.

The first slice provides explicit agent, model, and tool instrumentation; safe
metadata capture; local trace loading; parent-linked timelines; run summaries and
comparison; threshold evaluation; and strict mocked tool replay. Public APIs live
under `src/causalspan/`. Tests use synthetic traces without model providers.

GenAI fields follow the upstream development conventions. Product-specific retry,
policy, and replay metadata use the `causalspan.*` namespace. Model token counts
are recorded on model spans; summaries avoid adding agent-level token totals.

The exporter defaults to an allowlist of metadata and omits tool payloads. Payload
capture requires explicit opt-in, redacts sensitive mapping keys, and is not a
secret detector. Span names and allowed metadata are caller-supplied and can still
contain sensitive information. Captured payloads must be reviewed before sharing.

Replay reads recorded tool arguments and results from OTLP attributes. It matches
calls in recorded order and checks the tool name and exact JSON arguments. It has
no live-tool fallback. It is an explicit test double, not deterministic replay of
an entire model or distributed application.

Each local exporter serializes writes within one process. Concurrent processes
must use separate files. Input loading is size-bounded and validates required span
fields, IDs, timestamps, duplicate spans, and parent cycles. Missing parents are
shown as incomplete roots. HTML is escaped and has no scripts or remote assets.

Future integrations may attach the exporter to existing SDK providers. Automatic
framework instrumentation, OTLP ingestion servers, distributed MCP/A2A adapters,
model quality judges, live policy enforcement, and hosted services are out of
scope for this slice.
