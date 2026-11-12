# Reflow

- Base completion claims on observed execution evidence.
- This project provides an independent Reflow core and integration layers. Keep the core independent of CPA, Codex, and Magpie SDKs.
- Preserve stable CPA CodexReflow sources, release artifacts, and the user's uncommitted changes.
- Use isolated processes, temporary directories, synthetic credentials, and mock upstreams by default for development and automated testing.
- Do not use real accounts or billable models, modify production configuration, push, publish, or submit anything externally without user authorization for that specific step.
- Do not log credentials, request bodies, response bodies, or encrypted reasoning content. Do not save them in diagnostic bundles or disk caches.
- Preserve upstream provenance, copyrights, and licenses. Store artifacts separately by version without overwriting earlier versions.
- Do not treat 516 tokens as proof of truncation or guarantee that continuation improves answer quality.
- For core or integration changes, run `go test ./...`, `go test -race ./...`, and `go vet ./...`. Cover failures, cancellation, tool calls, and multi-turn state.
- The CPA adapter is a separate Go module under `adapters/cpa`; root tests do not cover it. When changing the shared core, also run normal tests, race tests, vet, and native ABI mock-host tests in that module. Package source fingerprints must include both the CPA module and the shared `core`.
