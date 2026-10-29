//go:build native_event_probe

package integration

import (
	"bytes"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
)

// Uses a real installed CLI, synthetic login and loopback upstream only.
// Fixed command output is held in memory and fed to the real Python classifier.
func TestCodexNativeEventProbe(t *testing.T) {
	if os.Getenv("REFLOW_CODEX_BIN") == "" {
		t.Skip("set REFLOW_CODEX_BIN for the isolated JSON event probe")
	}
	python, err := exec.LookPath("python")
	if err != nil {
		t.Fatal("Python is required for this explicitly selected event probe")
	}
	evaluationDir, err := filepath.Abs("../evaluations")
	if err != nil {
		t.Fatal(err)
	}
	for _, marked := range []bool{true, false} {
		name, wantMarker := "silent_nonzero", "unclassified"
		command := "printf 'REFLOW_TOOL_OK\\n' > probe.txt; exit 1"
		if marked {
			name, wantMarker = "assertion_marker", "python_assertion"
			command = "printf 'REFLOW_TOOL_OK\\n' > probe.txt; printf 'AssertionError: SYNTHETIC_PRIVATE_SENTINEL\\n' >&2; exit 1"
		}
		if runtime.GOOS == "windows" {
			command = "cmd.exe /d /c \"echo REFLOW_TOOL_OK>probe.txt & exit /b 1\""
			if marked {
				command = "cmd.exe /d /c \"echo REFLOW_TOOL_OK>probe.txt & echo AssertionError: SYNTHETIC_PRIVATE_SENTINEL 1>&2 & exit /b 1\""
			}
		}
		t.Run(name, func(t *testing.T) {
			observe := func(t *testing.T, raw []byte) {
				t.Helper()
				var matched int
				for _, line := range bytes.Split(raw, []byte{'\n'}) {
					var event struct {
						Type string         `json:"type"`
						Item map[string]any `json:"item"`
					}
					if json.Unmarshal(line, &event) != nil || event.Type != "item.completed" || event.Item["type"] != "command_execution" {
						continue
					}
					matched++
					output, present := event.Item["aggregated_output"].(string)
					if !present || event.Item["exit_code"] != float64(1) || event.Item["status"] != "failed" {
						t.Fatal("native command event schema or fixed exit status differs")
					}
					if marked != strings.Contains(output, "AssertionError: SYNTHETIC_PRIVATE_SENTINEL") {
						t.Fatal("fixed marker did not reach aggregated_output as expected")
					}
					body, _ := json.Marshal(event.Item)
					checker := exec.Command(python, "-I", "-B", "-c", "import json,sys; sys.path.insert(0,sys.argv[1]); from event_diagnostics import failure_markers; print(json.dumps(failure_markers(json.load(sys.stdin))))", evaluationDir)
					checker.Stdin = bytes.NewReader(body)
					classified, checkErr := checker.Output()
					var markers []string
					if checkErr != nil || json.Unmarshal(classified, &markers) != nil || len(markers) != 1 || markers[0] != wantMarker {
						t.Fatal("native event did not reach the expected fixed Python classification")
					}
					// Numeric/fixed labels only; never emit event IDs, commands, output or auth.
					summary, _ := json.Marshal(map[string]any{"aggregated_output_present": present, "output_bytes": len(output),
						"exit_code": 1, "fixed_marker": wantMarker, "classifier_match": true,
						"native_command_exit_exception": strings.Contains(output, "NativeCommandExitException"),
						"exit_code_envelope":            strings.Contains(output, "Exit code:"),
						"output_envelope":               strings.Contains(output, "Output:")})
					t.Logf("REFLOW_NATIVE_EVENT_SCHEMA %s", summary)
				}
				if matched != 1 {
					t.Fatalf("expected one fixed command completion, got %d", matched)
				}
			}
			verifyNativeLoginOffline(t, nativeLoginMode{codeMode: true, nativeWrite: true, command: true,
				probeCommand: command, observeOutput: observe})
		})
	}
}

func TestCodexXHighOffline(t *testing.T) {
	verifyNativeLoginOffline(t, nativeLoginMode{codeMode: true, reasoningEffort: "xhigh"})
}
