# Security

This project is an early alpha. It has no stable security support window yet.

Report vulnerabilities using GitHub's private vulnerability reporting under the
repository's Security tab. Do not put exploit details, private traces, credentials,
or personal data in public issues. If private reporting is unavailable, open an
issue asking for a private reporting route without disclosing the vulnerability.

Tool payload capture is off by default. Opt-in capture redacts common sensitive
mapping keys but cannot recognize every secret or sensitive free-text value.
Names and metadata can also be private. Review trace files before sharing, use
filesystem access controls, and delete recordings when they are no longer needed.

The replay implementation never calls a live tool. The recording API's `call_tool`
method deliberately executes the supplied function. Instrumentation is not a
sandbox, and evaluation reports do not enforce runtime policy or spending limits.
