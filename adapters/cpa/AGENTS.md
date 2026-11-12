# CodexReflow working rules

- Evaluate claims independently.
- Keep changes narrow, reversible, and covered by regression tests. End task reports with a useful next step.
- This is an independent fork of CodexComp v0.1.7. Retain upstream attribution and licenses.
- This subtree now builds against the repository's shared core via its own Go module. Keep CPA SDK dependencies here; retain the shared core in source snapshots and provenance fingerprints. Nested .github workflows are historical; active workflows are at the repository root.
- Never modify production ECPA/CPA/Codex configuration, enable either plugin, switch transports, or make billable model calls without explicit authorization for that step.
- Do not publish a repository, push commits/tags, create a Release, or submit a store PR without explicit authorization.
- Do not embed local paths, prompts, API keys, management secrets, OAuth records, or live response/encrypted content in committed fixtures.
- Keep `.tools`, `build`, and `dist` ignored. Download build tools only from their original sources and verify checksums.
- Pin the CPA SDK; do not silently change to latest. Declared capability, compiled artifact, offline test, and live integration are different evidence levels.
- Do not claim 516 tokens prove degradation or continuation guarantees improved quality.
- Never enable CodexComp and CodexReflow over the same model set in integration tests.
- Run `go test ./...`, `go test ./... -race`, `go vet ./...`, and the offline native smoke test before declaring an implementation validated.
