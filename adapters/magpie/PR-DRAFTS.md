# Local review material and upstream discussion

The review files were published in Reflow commit `b357a58`. After reading the complete maintainer discussion on [#2118](https://github.com/yetone/magpie/issues/2118#issuecomment-6216502171), one authorized [integration-boundary discussion, #4497](https://github.com/yetone/magpie/issues/4497), was opened. It acknowledges client-owned loops and asks about supported external placement and stable account/model selection. It does not request reversing that policy or merging the compiled hook. The original hook proposal below remains a historical draft, not the text posted upstream. No Magpie PR, merge or binary release has occurred.

## Current discussion candidate — 2026-10-31

The [host-only patch](patches/host-review-2026-10-31/manifest.json) is based on the observed upstream `bca0d6d69a806ae941bf9a5a6fafe4c7e03322b9`, with local review commit `cb1a4062f644da15c2fa7715ecf0b0c8325415e3`. It contains the twelve host execution files and their design reference. It does not include the Reflow bridge or its dependency. Three bridge-specific documentation paragraphs now arrive with the bridge, so the minimal host commit has no references to module files or tests that it does not provide.

The complete Reflow integration still uses the fixed `ffa07395` base. Its seven published patches have been reorganized into six local review commits, with the bridge and alternate module delivered together. Reapplying all six reproduces the previously tested Git tree `79bdbc861cc268147de69a6a05fb1c6c37fa87e4` exactly. This extraction changes no runtime code. The two sets are alternative review scopes on different bases, not a series to apply together.

| Local commit | Review scope |
| --- | --- |
| `f136f424` | Host execution extension on `ffa07395`, independently checked with original dependencies |
| `97f10ea0` | Cgroup root-walk termination |
| `b38d3b7b` | Windows keychain and configuration-directory fixtures |
| `8ba32563` | Niri fixture connection cleanup |
| `f295ab90` | Valid zero masking duration and virtual-clock tests |
| `ea4fccc8` | Optional Reflow bridge, public alternate module, translations and bridge documentation |

The independently extracted host extension passed ordinary and race checks on both `ffa07395` and `bca0d6d`, with 10 pass / 0 skip / 0 fail in each run. Disabling the registered executor made `TestExecutionExtensionThroughNativeCodexGateway` fail behaviorally: HTTP 200 with one upstream request instead of two. Source was restored before each passing race run. All checks were serial, used temporary homes and synthetic accounts, and preserved the original module files. The stored diagnostics contain test events, numbers and fixed markers; raw reply bodies were not saved. Commands, artifacts and hashes are in the [review packet evidence](../../docs/evidence/magpie-review-packet-2026-10-31.json).

Only the host extension has been checked on `bca0d6d`. The complete bridge, its GUI checks and the interrupted full host run remain tied to `ffa07395`. A full suite, whole-host build/vet matrix, native Linux/macOS use and real accounts were not run for the host-only new-base candidate. These materials support a design discussion, not merge or release acceptance.

The observed [upstream contribution policy](https://github.com/yetone/magpie/blob/bca0d6d69a806ae941bf9a5a6fafe4c7e03322b9/docs/contributors.md) says community fixes may arrive through issues because PRs are limited to collaborators. The connected account has read access and no push permission. The first external step was the single authorized discussion #4497 described above; it is not upstream acceptance of these patches.

### Proposed discussion: bounded compiled execution for streaming Responses

Streaming Responses middleware can transform requests and observe replies, but a continuation executor needs to hold an intermediate response and make another request on the same selected upstream before releasing a visible response. Would a small compiled execution hook be an acceptable extension point for that use case?

The prototype exposes `Info`, `Next` and `Executor` through `internal/gwexec`. The gateway keeps the selected account, endpoint, model, request context and transport. One executor runs per request, with at most eight upstream calls including the first; each response must be closed before the next call. Cancellation follows the client request. Failure or panic returns an error without replaying the initial call. With no registered executor, forwarding follows the existing path.

The hook is limited to native Codex and streaming Responses-to-Responses passthrough. Translations, non-streaming requests and compaction bypass it. It is for trusted compiled code, not an untrusted plugin sandbox. An optional Reflow bridge is maintained separately; the host-only proposal adds no Reflow dependency or listener. Folded billing totals are recorded separately from visible context usage, without rewriting the client stream.

At base `bca0d6d`, the selected Windows tests pass normally and with race (10 items each), and disabling the hook fails the native gateway behavior test. The test exercises the real handler and LAN guard with a synthetic upstream. Full-host and cross-platform merge checks are still required; no production service or real account was used. The question for the maintainer is whether this ownership boundary fits Magpie, or whether an existing supported extension contract should serve the same purpose.

### Reproduce the host-only candidate

Use a clean isolated Magpie checkout at the base in [the host manifest](patches/host-review-2026-10-31/manifest.json), verify the patch SHA-256, then apply `host-execution.patch`. Keep `go.mod` and `go.sum` unchanged and do not add the `reflow` tag or alternate module. Run the command below under a temporary HOME with pinned Go caches, as required by Magpie's test instructions; append `-race` for the race run.

```sh
go test -mod=readonly -tags nogui -p=1 -parallel=1 -count=1 -timeout=3m -run '^(TestBoundsCancellationAndNoFailureReplay|TestRegistrationRemovalAndUnchangedDefault|TestExecutionExtension.*|TestFoldedUsageCountsUpstreamWithoutChangingClientContext)$' ./internal/gwexec ./internal/gateway
```

For the negative control, replace only `e := gwexec.Current()` in `executeResponses` with `var e gwexec.Executor`, run `TestExecutionExtensionThroughNativeCodexGateway`, require its behavioral failure, then restore the file. The full bridge's existing positive/negative and GUI evidence is linked below and is not a substitute for running those checks on a newer base.

## Historical drafts on the original base

The original draft bodies below retain their `a1174674` evidence. The [2026-10-30 port](UPSTREAM-2026-10-30.md) targets `ffa07395` with a [separate patch series](patches/2026-10-30/manifest.json), adds downstream WebSocket continuation coverage, and records its host checks separately. Neither series has been submitted upstream; old full-suite numbers do not describe the new tree.

These drafts describe the patches in [manifest.json](patches/manifest.json). They do not represent an upstream issue or review. The optional Reflow bridge is a separate development patch; [the fifth patch](PUBLIC-MODULE.md) adds a pinned public module as an alternative to the local Go workspace, plus enabled-build test compatibility and settings translations. Full host acceptance remains incomplete.

## fix(cgroup): terminate parent walk at the host filesystem root

When evaluating Linux cgroup fixtures on Windows, `memLimit` checks the parent directory against `/`. At the Windows root, `filepath.Dir(dir)` returns the same path, so that check never ends the walk. This patch terminates when `filepath.Dir(dir) == dir`.

`TestCgroupRootWalkTerminates` runs in a bounded 30-second subprocess and verifies fallback to `MemTotal`. Restoring the old comparison produces a real failure: `cgroup parent walk did not terminate at the host filesystem root`. The fixed test passes. The subprocess prevents the regression from leaving a spinning goroutine.

Local commit: `86f6f917f1f29740e42ef1d45a293761ddac2c06`, based on `a1174674da9d1435443e95ffac7d0300ce8b59d6`. Synthetic Windows fixture verification only; native Linux/macOS execution was not run. See [verification](VERIFICATION.md) for positive and negative evidence.

## feat(gateway): add a trusted Responses execution extension

Streaming Responses passthrough previously offered no execution callback for holding an intermediate reply and calling the same selected upstream again. `gwexec` adds that callback for trusted compiled Go code.

Native Codex and Responses-to-Responses streaming routes enter the extension; translations, non-streaming and compact requests bypass it. The host retains the account, endpoint, model and transport. The last registered executor runs, with at most eight upstream calls and a close requirement between replies. Cancellation follows the request. Errors and panics do not replay the original request automatically; existing gateway fallback remains outside the interface.

The patch also labels WS-to-SSE responses correctly and reads validated aggregate usage without rewriting the client stream. The owning reference, `docs/subsystems/gateway-middleware.md`, is updated.

Positive and race checks pass. Disabling the native wiring makes `TestExecutionExtensionThroughNativeCodexGateway` fail with one request and the first round visible. Windows normal/nogui and Linux nogui build/vet checks pass.

The full host suite remains red: 12180 pass, 615 skip, 60 fail items. Selected-failure rechecks give the same 12 pass and 50 fail on clean upstream and the modified branch. This draft is not ready for upstream acceptance until remaining host failures are triaged; see [evidence](VERIFICATION.md).

The later fixture-only patch below leaves 36 failures in a new full run. The original records above remain historical evidence; the execution extension still has no upstream acceptance claim.

## test(provider, agent, gui): exercise keychain and config directory fixtures on Windows

The fake macOS keychain fixtures inherit Codex's Windows encrypted-storage default, so several tests never reach the fake keychain. Select `secret_auth_storage=false` only in those synthetic configurations and require the fallback test to contact the refusing fake. Keep the GUI sandbox's `APPDATA` and `LOCALAPPDATA` inside its temporary home so Windows can resolve application config paths. Runtime defaults and production files are unchanged.

At local commit `e69f473d157577054ccd48ee1cf77d7e3704ac78`, 14 previously failing items now pass. The initial focused selection passes 14 items with one existing symlink-permission skip, normally and with race; two additional GUI import cases pass with race. Removing the keychain fixture setting produces `fallback did not ask the refusing keychain`; restoring empty AppData makes all three GUI cases fail with `%AppData% is not defined`.

The full `nogui` suite remains red: 12204 pass, 615 skip, 36 fail, all remaining failure names present in the earlier recheck. Windows normal and Linux nogui vet/build pass, Windows nogui Reflow builds, and seven dev.4 bridge/default-off checks pass with race. These are fixed-base local results, not latest-main runtime validation or native Linux/macOS acceptance. See [fixture evidence](WINDOWS-FIXTURES.md); nothing has been submitted.

## test(omarchy): close accepted fixture connections before waiting for shutdown

The fake Niri server closed its listener during cleanup, then waited for a goroutine still reading an accepted connection. A full Windows run reached the 45-minute timeout in that cleanup. Track the current connection and stopping state under the existing mutex, close outside the mutex, and reject a connection whose Accept finishes during shutdown. Production window behavior is unchanged.

The regression keeps a client open across a subtest's cleanup, after a successful handshake proves the server accepted it. Restoring the old fixture makes the child hit its 20-second timeout and the parent report a real failure. With the fix, three targeted cases pass 20 rounds with race (60 pass entries), and the original-dependency omarchy package passes all 17 entries with race. The corresponding package also finishes in the full optional-module run. Other host failures remain separate; see [the complete evidence](NIRI-FIXTURE.md). This draft has not been submitted upstream.

## test(gateway): accept zero masking duration and check elapsed values with a virtual clock

The masking-record integration test required a positive duration even when both clock samples were equal. A numeric-only diagnostic saw 34 zero-nanosecond measurements in 50 requests, with every measured value preserved into the record. Accept nonnegative durations in that test, retaining its restoration and sent-body checks. Add virtual-clock cases for both JSON and text, covering zero, sub-microsecond truncation, and positive duration through measurement and recording.

With a forced zero measurement, the old assertion fails and the corrected assertion passes. Independently dropping either path's elapsed value or the final recorded value makes the new cases fail. The corrected real-clock diagnostic passes 50 requests including 36 zero measurements; 20 race rounds pass 160 entries. Production timing and masking code are unchanged. See [commands, full-suite results, and limits](MASKING-TIME.md); this draft is not an upstream submission.
