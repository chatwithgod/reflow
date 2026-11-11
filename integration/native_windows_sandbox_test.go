package integration

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

// Only the CI orchestrator sets this after checking the disposable runner and
// claiming cleanup responsibility. Local native tests continue to use MXC.
func nativeWindowsSandboxSettings(getenv func(string) string, base string) (string, string, error) {
	mode := getenv("REFLOW_NATIVE_WINDOWS_SANDBOX")
	if mode == "" {
		return "mxc", "", nil
	}
	if mode != "elevated" || getenv("REFLOW_NATIVE_WINDOWS_SETUP_READY") != "1" {
		return "", "", fmt.Errorf("native_windows_setup_not_prepared")
	}
	root, user := getenv("REFLOW_NATIVE_WINDOWS_ROOT"), getenv("REFLOW_NATIVE_WINDOWS_USER")
	if !filepath.IsAbs(root) || user == "" || strings.ContainsAny(user, "\r\n\x00") {
		return "", "", fmt.Errorf("native_windows_setup_identity_missing")
	}
	root, err := filepath.EvalSymlinks(root)
	if err != nil {
		return "", "", fmt.Errorf("native_windows_setup_root_missing")
	}
	base, err = filepath.EvalSymlinks(base)
	if err != nil {
		return "", "", fmt.Errorf("native_windows_setup_profile_missing")
	}
	relative, err := filepath.Rel(root, base)
	if err != nil || relative == "." || relative == ".." || strings.HasPrefix(relative, ".."+string(filepath.Separator)) || filepath.IsAbs(relative) {
		return "", "", fmt.Errorf("native_windows_setup_profile_outside_run")
	}
	return mode, user, nil
}

func nativeClientEnv(base, home string) []string {
	var env []string
	for _, name := range []string{"PATH", "SystemRoot", "SystemDrive", "WINDIR", "COMSPEC", "PATHEXT", "ProgramData"} {
		if value := os.Getenv(name); value != "" {
			env = append(env, name+"="+value)
		}
	}
	return append(env, "CODEX_HOME="+home, "HOME="+base, "USERPROFILE="+base,
		"APPDATA="+filepath.Join(base, "appdata"), "LOCALAPPDATA="+filepath.Join(base, "localappdata"),
		"TEMP="+filepath.Join(base, "temp"), "TMP="+filepath.Join(base, "temp"), "TMPDIR="+filepath.Join(base, "temp"),
		"NO_PROXY=127.0.0.1,localhost", "RUST_LOG=warn")
}

func prepareNativeWindowsSandbox(t *testing.T, bin, base, home, work string) string {
	t.Helper()
	mode, user, err := nativeWindowsSandboxSettings(os.Getenv, base)
	if err != nil {
		t.Fatal(err)
	}
	if mode == "mxc" {
		return mode
	}
	ctx, cancel := context.WithTimeout(context.Background(), 120*time.Second)
	defer cancel()
	cmd := exec.CommandContext(ctx, bin, "sandbox", "setup", "--elevated", "--user", user, "--codex-home", home)
	cmd.Dir, cmd.Env = work, nativeClientEnv(base, home)
	// Setup output can include user identities and protected paths. Never log it.
	if err := cmd.Run(); err != nil {
		t.Fatalf("native_windows_setup_failed: timed_out=%t", ctx.Err() != nil)
	}
	return mode
}

func TestNativeWindowsSandboxSettings(t *testing.T) {
	root := t.TempDir()
	base := filepath.Join(root, "case")
	if err := os.Mkdir(base, 0700); err != nil {
		t.Fatal(err)
	}
	valid := map[string]string{"REFLOW_NATIVE_WINDOWS_SANDBOX": "elevated", "REFLOW_NATIVE_WINDOWS_SETUP_READY": "1",
		"REFLOW_NATIVE_WINDOWS_ROOT": root, "REFLOW_NATIVE_WINDOWS_USER": `fixture\runner`}
	for _, test := range []struct {
		name, key, value, base string
		ok                     bool
	}{
		{"prepared", "", "", base, true},
		{"unprepared", "REFLOW_NATIVE_WINDOWS_SETUP_READY", "", base, false},
		{"unsupported", "REFLOW_NATIVE_WINDOWS_SANDBOX", "unelevated", base, false},
		{"missing_user", "REFLOW_NATIVE_WINDOWS_USER", "", base, false},
		{"invalid_user", "REFLOW_NATIVE_WINDOWS_USER", "a\nb", base, false},
		{"relative_root", "REFLOW_NATIVE_WINDOWS_ROOT", "relative", base, false},
		{"outside_root", "", "", t.TempDir(), false},
		{"root_itself", "", "", root, false},
	} {
		t.Run(test.name, func(t *testing.T) {
			env := make(map[string]string)
			for key, value := range valid {
				env[key] = value
			}
			if test.key != "" {
				env[test.key] = test.value
			}
			mode, _, err := nativeWindowsSandboxSettings(func(k string) string { return env[k] }, test.base)
			if (err == nil) != test.ok || test.ok && mode != "elevated" {
				t.Fatalf("unexpected selection: mode=%q error=%v", mode, err)
			}
		})
	}
	mode, user, err := nativeWindowsSandboxSettings(func(string) string { return "" }, base)
	if err != nil || mode != "mxc" || user != "" {
		t.Fatal("default native sandbox changed")
	}
}
