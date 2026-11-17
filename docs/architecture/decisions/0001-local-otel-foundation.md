# ADR 0001: local OpenTelemetry foundation

Status: accepted
Date: 2026-11-17

## Context

Agent debugging needs parent relationships, timing, model usage, and tool outcomes
without requiring a hosted observability service. The initial project brief calls
for OpenTelemetry-native tracing and local replay. GenAI conventions remain in
development, so adapters must be small and testable.

## Decision

Use the Python OpenTelemetry SDK and its protobuf encoder. Persist standard OTLP
JSON export requests separated by newlines. Normalize only the OTLP-specific ID
encoding to hexadecimal and use integer enums. Preserve a small metadata allowlist;
make tool JSON payload capture explicit. Add custom fields only under `causalspan.*`.

Keep replay separate from live instrumentation. Require one trace, ordered calls,
exact tool names and JSON arguments, complete unredacted payloads, and no overlapping
tool calls. Return recorded JSON or a safe recorded-failure exception. Never invoke
a tool from the replay implementation.

## Consequences

Existing SDK providers can attach the local exporter. The CLI requires no server
and no provider credentials. It compares observed metrics and threshold results,
not model answer quality. File export is synchronous and intended for development.
One output file per process is required. MCP/A2A adapters and auto-instrumentation
remain future work. Payload key redaction is a guardrail, not a confidentiality
guarantee.

See the dated [direction brief](../../governance/direction-brief.json) for sources
and unresolved compatibility questions.
