# Otlp compatibility

This milestone implements five bounded parts of the external OTLP roadmap:

1. Add a synthetic external request fixture independent of the local exporter,
   covering pretty JSON/JSONL, uppercase hexadecimal IDs, numeric/string int64,
   nested AnyValue data and unknown fields.
2. Reject duplicate JSON fields at every nesting level instead of silently keeping
   the last value. This deliberately rejects ambiguous local evidence, including
   duplicate unknown fields; distinct unknown fields remain ignored.
3. Accept empty/unknown-only or null-valued AnyValue as unset (None); validate bytes
   as standard or URL-safe base64 with optional padding, retaining the encoded
   string. Keep strict signed-int64 bounds, finite numbers and oneof checks.
4. Preserve resource attributes/schema URL and instrumentation scope name, version,
   attributes/schema URL as separate SpanRecord fields. They are never merged into
   span attributes or counted as model token usage. Defaults preserve existing SDK
   constructors. Copies prevent mutation leaking between span records. Expanded
   normalized metadata is capped at 32 MiB across all materialized spans.
5. Exercise inspect/evaluate/timeline against external fixtures, token totals,
   parentage, unchanged input bytes and safe script-free output. Existing replay
   tests retain the no-live-fallback boundary.

File input remains capped at 32 MiB, count at 50,000 spans, and attribute nesting at
32. Scope metadata is available through the SDK but not added to default reports.
The fixtures are synthetic protocol cases, not captures from a vendor SDK. This is
a supported local subset, not full OTLP receiver conformance: non-finite doubles,
ambiguous duplicates, unsupported status values and missing span identity/timing
remain errors. General protobuf null/default handling, event/link metadata, binary
OTLP, network ingestion and automatic semantic-convention migrations remain out of
scope. No provider, collector, MCP/A2A transport or live tool is called.
