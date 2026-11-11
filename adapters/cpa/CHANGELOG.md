# Changelog

## 0.1.3

Published on 2026-11-04 as latest stable with five native packages. All six public assets were anonymously downloaded and matched against the tested CI bytes. See [release verification](docs/RELEASE-2026-11-04-0.1.3.md).

- Repair collaboration tool parameter types changed by CPA's plugin executor before the first upstream call. Restore only the known number-to-integer mutation from the client's original declaration; keep the tools, legitimate integer types and other CPA request transformations intact. Addresses [Issue #2](https://github.com/chatwithgod/cpa-plugin-codexreflow/issues/2).
- Apply the repair to root tools, scoped dynamic `additional_tools`, continuation rounds and native WebSocket replay settings. Missing or ambiguous original declarations are left unchanged rather than guessed. No new configuration is required; SDK remains pinned to v8.0.13.
- Require 46 native ABI cases on each original and ZIP-extracted platform library, add schema fuzzing to native release validation, and retain HTTP/WS and prewarm regression coverage. The local candidate passed isolated comparisons; the user reported normal use of both existing and new chats. That feedback applies to the trial candidate, not every model, transport or release binary.
- Five-platform formal artifacts are built separately from the trial DLL. The trial installation is not automatically switched during publication; prior releases and assets are retained.

## 0.1.3-dev.2 (local candidate; unreleased)

- Address [Issue #2](https://github.com/chatwithgod/cpa-plugin-codexreflow/issues/2) without removing collaboration tools: compare processed schemas with `OriginalRequest` and undo only matching `number` to `integer` normalization, including nullable unions. Preserve original integers, ordinary tools, host routing edits and tool membership.
- Cover root `tools`, scoped `input[].additional_tools`, initial execution, continuation rounds and cached native WebSocket replays. Missing originals and ambiguous identities remain unchanged; no new configuration or schema/payload logging.
- Add 12 C ABI schema scenarios (46 required in total), bounded Go tests/fuzzing, and strict real-CPA 8.0.47 mock-upstream checks with an old-v0.1.2 negative control. Keep SDK v8.0.13, continuation policy and published v0.1.2 artifacts unchanged.
- Windows candidate only; not a store release, production install or live-model acceptance. See [the scoped validation record](docs/VALIDATION-2026-11-04-0.1.3-dev.2.md).
- Subsequently trial-installed on the user's CPA 8.0.53 after separate authorization and an idle check. Preserve the previous 0.1.2-dev.1 DLL and all non-version plugin settings; document an initial protective rollback caused by harmless host serialization of empty match defaults, followed by a verified version-only retry. Four targeted isolated preflights pass; no live-model test call or public release. See [the deployment record](docs/DEPLOYMENT-2026-11-04-0.1.3-dev.2.md).

## 0.1.2

Published on 2026-10-24 with five native platform packages. See [release and byte-level verification](docs/RELEASE-2026-10-24-0.1.2.md).

- Fix HTTP 400 during Codex WebSocket warmup: requests with `generate: false` remain on CPA's native route, preserving empty `input: []` and the response ID used by the next turn.
- Preserve non-nil empty input arrays when copying ordinary streaming requests, so the executor does not serialize them as `input: null`.
- Add routing and actual-library regression coverage for empty/non-empty warmups and empty-array forwarding, plus an isolated CPA 8.0.38 WebSocket test that continues on the same connection.
- Require all 34 native ABI scenarios when packaging both original and ZIP-extracted libraries. Derive per-platform and bundle counts from the complete required suite and use the repository's current `chatwithgod` URL in release metadata. CPA SDK remains pinned to `v8.0.13`.

## 2026-10-11 Windows isolated validation (documented 2026-10-12; no new binary release)

- Validate the exact published v0.1.1 Windows ZIP/DLL bytes without rebuilding. The DLL passes 31 native ABI cases and 50 synthetic isolated HTTP/WS scenario executions on each pinned CPA 8.0.13/8.0.15/8.0.16 host, totaling 150 executions rather than 150 distinct scenarios. Read back report and host hashes; see [the independent validation record](docs/VALIDATION-2026-10-12-0.1.1.md).
- Preserve the initial orchestration safety stop: its 14 WS cases passed, but an overstrict empty-temp guard rejected Windows host shadow DLL residue. Update only the ignored test runner to verify stopped PIDs, owned paths and identical DLL hashes before removing individual copies; retain initial logs and rerun the full suite in a new output directory. No plugin/SDK/host implementation change.
- No production installation/configuration changes, real-model calls, Release/tag changes or additional store PR. Linux/macOS full CPA integration, real clients and answer quality remain unvalidated.

## 2026-10-10 store listing (verified 2026-10-11; no new binary release)

- [Store PR #225](https://github.com/router-for-me/CLIProxyAPI-Plugins-Store/pull/225) was merged at 06:06:14 UTC+8. Read back its merge commit on official main and exactly one `codexreflow` registry entry matching the submitted template. Preserve the earlier submission/publication records as historical snapshots; see [the listing verification](docs/STORE-LISTING-2026-10-11.md).
- Synchronize current documentation only. Do not change plugin implementation, SDK, version, Release tags/assets or production installation; store registration is not desktop UI, live-model or answer-quality acceptance.

## 2026-10-09 store resubmission (no new binary release)

- With separate authorization, submit [store PR #225](https://github.com/router-for-me/CLIProxyAPI-Plugins-Store/pull/225) after the closed #222: append one `codexreflow` entry to `registry.json`, preserving all 111 existing entries and schema metadata. Keep the old PR/branch and fork main unchanged. Read back the new PR as open, unmerged and registry-only; this is not store acceptance.
- Recheck store rules and ID uniqueness; anonymously download all five v0.1.1 ZIPs and checksums again, verifying exact tested bytes, SHA256, CRC, architecture and retained licenses. Keep plugin implementation, SDK, release tags/assets and production unchanged; no extra live-model test calls. Update documentation separately. See [the submission record](docs/STORE-SUBMISSION-2026-10-09-0.1.1.md).

## 0.1.1 (2026-10-09)

- Publish the separately authorized five-platform Release from tested main source `6c71eee479e9939a3d300b9231117fae11eef296` and CI run `37916034316`. Read back latest stable; anonymously download all five ZIPs and unified checksums, verifying exact tested bytes, SHA256, CRC, architecture and retained licenses. The public Windows DLL additionally passes the same 31 native cases locally. No store resubmission, production installation or live-model test calls. See [the publication record](docs/RELEASE-2026-10-09-0.1.1.md).
- Address the missing-platform feedback in store PR #222 / project issue #1 without changing Go implementation, SDK pin, continuation policy or production configuration. Preserve the sealed `v0.1.0` Release and inherited tags; publish a separate `0.1.1` package version, not an overwrite.
- Add native CI for Windows amd64, Linux amd64/arm64 and Darwin amd64/arm64 using pinned Go and action revisions. On each target run unit/race/vet/fuzz, Python tests, actual C ABI tests and the same suite against packaged library bytes. CI has read-only repository permissions and uploads candidate artifacts only.
- Extend the release packager with PE/ELF/Mach-O type/architecture checks, native identity/report guards, exact root/license layout and immutable outputs. Collect exactly five same-commit, same-source packages with verified reports/checksums; fail on missing targets, mismatched provenance, unpassed cases or additional files.
- Add synthetic container/provenance regression tests. The released-source CI passes all 47 Python tests and 31 native cases on each original and packaged library: 155 case executions per group, not 310 distinct scenarios. Native mock tests are not full CPA integration or live-model acceptance on every platform.

## 0.1.0 (2026-10-08)

- Publish the separately authorized Windows amd64 Release, then anonymously download both public assets and verify exact bytes, SHA256, checksum contents and all ZIP members against the sealed formal package. Fix the remote `v0.1.0` tag to tested source `875864934cf82dbba90a7f85985f36ebd3a256d1`; preserve inherited local upstream tags and update only documentation on `main`. No production upgrade, model calls or store PR. See [the publication record](docs/RELEASE-2026-10-08-0.1.0.md).

- Build a new Windows amd64 artifact from source commit `875864934cf82dbba90a7f85985f36ebd3a256d1`, registering numeric version `0.1.0` and the confirmed project repository. Keep runtime source, SDK pin and policy unchanged; do not rename the old development DLL into a release.
- Re-run local Go unit/race/vet/fuzz, 31 native ABI cases, 19 Python tests and 150 isolated case executions across CPA 8.0.13/8.0.15/8.0.16 on the identical formal DLL. Package its bytes with retained licenses, check ZIP/checksum integrity and rerun the same 31 native cases on the packaged DLL.
- Keep prior artifacts and production untouched. No additional live-model calls, production installation, commit/push, tag, Release upload or store PR in this validation step. Source CI passes independently; it is a development build, not remote validation of this formal DLL hash. See [the formal-package record](docs/VALIDATION-2026-10-08-0.1.0.md).

## 2026-10-08 source repository bootstrap (no binary release)

- Establish the public source repository under `LaoPiLao/cpa-plugin-codexreflow` with separate authorization for creation and code push only. Preserve upstream history/attribution; do not publish inherited tags, a Release or a store PR.
- Set the Go module and registry-entry draft to the confirmed repository. Keep the SDK pin and runtime policy unchanged; retain local-development source metadata for existing DLLs.
- Revalidate the exact current Go source in a clean snapshot: unit/race/vet/fuzz, a newly built development-only source-check DLL with 31 native ABI cases, and 19 Python tests pass. Do not overwrite installed DLLs, the immutable candidate ZIP or historical reports; no extra model calls or production changes.

## 0.1.0-dev.5 (unreleased; subsequently installed locally with authorization)

- Add payload-free `fold_started` and per-round `round_finished` diagnostics linked to the existing random per-fold `run_id`. Whitelist five provider-reported token counters; preserve unknown as null and actual zero as zero. Keep continuation policy, routing, cache bounds and transport behavior unchanged.
- Record lifecycle-only failure/cancellation evidence when native state exists but the host preempts its terminal stream hook; do not log free-form host errors or claim client delivery.
- Explicitly mark `usage_join: unavailable`: CPA's usage execution UUID is not the independently generated interceptor lifecycle UUID or the parent request/WS trace. Do not infer exact billing joins from matching counters or timestamps.
- Add a bounded offline diagnostic summary with missing/duplicate/conflicting evidence detection, plus privacy/concurrency/error tests and same-run assertions in native ABI and real isolated HTTP/WS harnesses.
- Add a separate immutable local-candidate ZIP packager with version/source/platform and same-DLL report checks. Preserve the formal release guard; no production installation or remote publication is performed.
- Pass Go unit/race/vet/fuzz, 31 native ABI cases, 19 Python tests, and 50 isolated scenario executions on each of CPA 8.0.13/8.0.15/8.0.16 with one DLL. SDK remains pinned; live-model acceptance of this candidate is pending.
- Subsequently install the same validated DLL with separate authorization after both designated chats are idle. Verify rollback backups and change only the Reflow local version selector; preserve other plugins, configuration, enable states and transport. Read back stable effective registration on CPA 8.0.16 and rerun 31 native ABI cases against installed bytes. Initial read-only diagnostics contain one complete new run, not attributed to the designated chats. No additional model test request, explicit service restart or publication; see the separate deployment record.
- On October 8, audit the two designated existing chats through 01:42:48 UTC+8 without production writes or extra model calls. Match 16 folds to client merged usage across 22 completed upstream WS rows, all HTTP 200; observe six continuations, four on the native incremental path, with tool round trips and final answers in both chats. Include a `516 -> 0` continuation and retain interruption/in-flight exclusions. This updates the earlier pending status with limited live evidence, not comprehensive acceptance or a quality claim; exact usage execution joins remain unavailable. See [the scoped audit](docs/VALIDATION-2026-10-08-live-dev5.md).

## 2026-10-07 validation follow-up (no new DLL)

- Read back the installed dev.4 on CPA 8.0.16 and verify its unchanged artifact hash. Do not modify production configuration, restart services, or generate extra model test requests.
- Audit retained records for two user-selected existing chats: 14 live folds matched client merged usage, 12 through the new WS incremental path. Preserve scope limitations, client interruption evidence and the distinction between raw upstream token rows, delivery and answer quality.
- Add explicit CPA 8.0.16 selection to the three isolated harnesses; rerun 14 incremental, 13 bridge and 23 auto-selection cases with the unchanged dev.4 DLL, all meeting expectations. Keep the SDK and Go implementation unchanged. See the October 7 validation record.

## 0.1.0-dev.4 (unreleased; locally installed with authorization)

- Keep incremental WS model routing and the first upstream delta native. Add a response-stream interceptor that reuses folding only with known complete socket/model/lane context; never remove a parent and replay only its delta.
- Retain the latest canonical input/output, settings and opaque encrypted reasoning in bounded process memory. Inherit omitted settings while respecting explicit replacements; exclude tentative tools/text and continuation markers from committed history. No payload persistence or logging. This is a privacy change from the dev.3 ID-only bridge.
- Bound replay entries, serialized bytes, TTL and active request/stream accounting. Unknown, expired or oversized history causes no additional model calls; stream resource exhaustion returns explicit incomplete output. Clean up on request lifecycle and shutdown.
- Preserve stable visible response IDs and bridge the next parent to the final upstream ID. Add `path: ws_incremental` diagnostics and distinguish hook-returned bytes from host acceptance and client delivery.
- Validate the identical Windows DLL against isolated CPA 8.0.13 and 8.0.15, with 14 incremental-fold, 13 bridge and 23 auto-selection cases per host; 29 native ABI cases plus Go unit/race/vet tests pass. Keep the SDK pinned to 8.0.13. The dev.3 control reproduces its native incremental no-fold behavior.
- Test tool return followed by folding and folding followed by tool return, repeated truncation, omitted settings, limits, zero-added-reasoning, native failure/incomplete and concurrent sockets. Native failed events may be preempted by the host and close the socket; do not relabel that as success.
- The build/repair phase made no production changes or billable model tests. Subsequently install the same validated DLL with explicit authorization after both user-designated chats were idle: verify config/DLL backups, change only Reflow's local version selector, preserve other settings/transports/enable states and read back stable registration on CPA 8.0.15. Re-run 29 native mock cases against the installed bytes. No new chat, extra model test, commit/push, release or store submission; new incremental-path real-model acceptance remains pending. See the dev.4 validation record.

## 0.1.0-dev.3 (unreleased)

- Bridge a folded response's client-visible ID to its final upstream ID on the next native WS turn, scoped by host-owned execution session, exact requested model and lane. Keep delta/tool input, credential pinning and transport policy unchanged; do not fold native incremental generations.
- Accept the `codex` source format supplied by CPA's self-executor adapter when committing the alias. The first candidate mistakenly accepted only the pre-translation Responses format; real isolated CPA exposed and verified the fix.
- Bound ID-only cache entries by capacity and TTL, clear on shutdown, and revoke the relevant revision if terminal emission fails. Unknown parents, different sockets/models/lanes and missing host scope remain untouched.
- Add per-fold `proxy_reflow` terminal metadata and payload-free INFO logs with independent run IDs, attempted/terminal round counts, stop reason, bridge status and emission outcome. Distinguish upstream errors/EOF/failed/incomplete from normal completion.
- Pass 29 native ABI scenarios, the existing 23 auto-selection and eight legacy cases, and 13 strict WS regressions, including subsequent text/tool turns, repeated continuation, replay, reconnect, prefixed/suffixed model IDs and concurrent sockets reusing a visible ID. Reproduce the older DLL's expected failures separately.
- Verify that pinned CPA configuration reload shuts down upstream execution sessions even with this plugin disabled; recover through a new socket with full context rather than claiming seamless reload continuity.
- The build/repair phase made no production changes or live model calls. Subsequently install the same tested DLL with explicit authorization, changing only the local Reflow version selector and preserving enable states, other settings and transport; read back registration and rerun 29 native mock cases on the installed bytes. No GitHub publication or store submission; real-model/Desktop acceptance and quality evaluation remain pending.

## 0.1.0-dev.2 (unreleased)

- Default new configurations to automatic GPT-5+ text-name matching without a fixed model list; CPA retains availability, alias resolution and routing. This is not exact catalog synchronization or capability detection.
- Add an `auto` / `manual` configuration enum and optional priority exclusions; recognize route prefixes and final reasoning suffixes for matching only, while excluding named non-text families.
- Preserve models-only legacy configurations, including their historical empty-list fallback. Explicit manual with no models intercepts nothing; explicit auto ignores a retained list.
- Retain encrypted-state checks, request-shape guards, continuation budget and disabled experimental thresholds; reject invalid mode reloads without replacing the current configuration.
- Pass 20 native C ABI scenarios, 23 zero-config/selection cases and eight independent legacy cases with real isolated CPA 8.0.13 + synthetic HTTP/WS upstream; verify the default three-additional-round limit and no continuation without encrypted state.
- Build locally only; no production replacement, settings changes, real model calls, GitHub publication or store submission in this revision. Live 516 acceptance remains pending.

## 0.1.0-dev.1 (unreleased)

- Reproduce the dev build's HTTP `upstream_error` with a real CPA 8.0.13 process and a synthetic upstream; upstream replies complete while plugin output is lost.
- Restore SSE control-line boundaries removed by CPA's Scanner callbacks; never insert boundaries into JSON content.
- Add native Scanner-line regression cases and a loopback-only CPA integration harness with actual bidirectional WebSocket handshakes, no HTTP fallback, continuation, and tool-event checks.
- Compile a new local development artifact, then install its versioned DLL with explicit user authorization and a rollback backup, keeping it disabled at installation. The user subsequently reported successful HTTP/WS communication; real 516 continuation and broader client acceptance remain pending.

## 0.1.0-dev (unreleased)

- Independent CodexComp v0.1.7 fork with plugin ID `codexreflow` and preserved attribution.
- Pin CPA v8.0.13 SDK; remove sibling-checkout dependency.
- Declare direct `openai-response` output alongside `codex`, avoiding CPA's identity-frame filter for Responses clients.
- Decode SSE and raw JSON host events with bounded incremental scanning, fragmented frame support, and explicit parse/EOF errors.
- Normalize `response.done` without treating failed/incomplete status as successful completion.
- Add unit/fuzz coverage, Windows native DLL mock-host regression tests, and project-local build tools.
- Keep production installation, live WS acceptance, remote creation, and release publishing separate. Initial installation was later authorized but failed client acceptance; see dev.1.
- Provide explicit local-development source metadata required by CPA registration; release packaging still rejects non-GitHub sources.
