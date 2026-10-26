//go:build native_write_probe

package integration

import (
	"os"
	"testing"
)

// This opt-in compatibility probe must be reported separately from the normal
// suite. A failure blocks claims of full native workspace-edit compatibility;
// it is not an expected pass or a substitute for real-account acceptance.
func TestCodexNativeWriteProbe(t *testing.T) {
	if os.Getenv("REFLOW_CODEX_BIN") == "" {
		t.Skip("set REFLOW_CODEX_BIN for the native workspace-write compatibility probe")
	}
	for _, item := range []struct {
		name string
		mode nativeLoginMode
	}{
		{"patch_via_reflow", nativeLoginMode{codeMode: true, nativeWrite: true}},
		{"patch_direct", nativeLoginMode{codeMode: true, nativeWrite: true, direct: true}},
		{"patch_add_direct", nativeLoginMode{codeMode: true, nativeWrite: true, direct: true, add: true}},
		{"patch_direct_no_daemon", nativeLoginMode{codeMode: true, nativeWrite: true, direct: true, noDaemon: true}},
		{"command_via_reflow", nativeLoginMode{codeMode: true, nativeWrite: true, command: true}},
	} {
		t.Run(item.name, func(t *testing.T) { verifyNativeLoginOffline(t, item.mode) })
	}
}
