# Risks and boundaries

- GenAI semantic conventions are in development. Isolate mappings and review
  upstream changes before changing emitted attributes.
- Payload capture is opt-in and key redaction cannot detect every secret. Names,
  model identifiers, arbitrary strings, and values inside payloads can be private.
  Use synthetic data for public examples and review files before sharing.
- Replay reproduces captured tool returns only. It does not execute, sandbox, or
  reproduce a model, environment, remote service, or whole agent process.
- A threshold report describes recorded data; it is not a live budget or policy
  enforcement mechanism, nor a measure of response correctness.
- Incomplete traces may omit errors or token usage. Missing parents and absent
  counters must stay visible; no cost estimate is inferred from tokens.
- Local files are not encrypted. Use filesystem permissions and retention rules.
  Each process needs its own output file. Large inputs are bounded before parsing.
- HTML is an offline artifact. Treat imported labels and values as untrusted text.
