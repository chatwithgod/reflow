# Local PR drafts — not submitted

These drafts describe the patches in [manifest.json](patches/manifest.json). They do not represent an upstream issue or review. The optional Reflow bridge is a separate development patch, currently requiring a local Go workspace.

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
