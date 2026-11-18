# DirectionBriefV1: Otlp compatibility

schema_version: 1
baseline_commit: `043149bc2e37a0aef473b838d1c965d924bf8863`
scanned_at: 2026-11-18
coverage: architecture, roadmap, prior ADRs, code/tests and focused primary specifications.

## Findings

- finding: Unknown message fields are ignored; enums use integers and 64-bit integers permit numbers or decimal strings. [OTLP JSON encoding](https://opentelemetry.io/docs/specs/otlp/). source_event_date: living specification, publication date unspecified; accessed 2026-11-18. confidence: high (primary source). relevance: portable evidence. direction_alignment: explicit bounded contracts. opportunity_or_risk: avoid ambiguous interpretation. engineering_cost: bounded reader/CLI tests. disposition: adopt. roadmap_delta: CS-002. verification_needed: positive/negative fixtures and preservation checks.
- finding: Base64 bytes support standard and URL-safe encodings; null values leave fields unset. [ProtoJSON](https://protobuf.dev/programming-guides/json/). source_event_date: living specification, publication date unspecified; accessed 2026-11-18. confidence: high (primary source). relevance: portable evidence. direction_alignment: explicit bounded contracts. opportunity_or_risk: avoid ambiguous interpretation. engineering_cost: bounded reader/CLI tests. disposition: adopt. roadmap_delta: CS-002. verification_needed: positive/negative fixtures and preservation checks.

overall_recommendation: implement the approved bounded milestone and queue the shared five-item handoff.
evidence_gaps: synthetic local tests do not prove vendor interoperability, authorship, physical-device performance or hosted service behavior. Broader ecosystem work is outside this focused request.

GenAI conventions now point to their [separate upstream repository](https://github.com/open-telemetry/semantic-conventions-genai). Monitor migration separately; this slice does not rename instrumentation attributes.
