package integration

import (
	"encoding/json"
	"strings"
	"testing"
)

// These are fixed observations, not inferred causes. Native tool output is
// classified in memory before the fixture discards it; no payload is retained.
type nativeToolDiagnostics struct {
	ObservedOutputs int            `json:"observed_outputs"`
	EmptyOutputs    int            `json:"empty_outputs"`
	MatchingOutputs map[string]int `json:"matching_outputs"`
}

var nativeToolSignals = map[string][]string{
	"permission_denied":          {"permission denied", "access is denied", "access denied", "eacces"},
	"operation_not_permitted":    {"operation not permitted", "eperm"},
	"namespace_setup":            {"unshare", "user namespace", "creating new namespace"},
	"bubblewrap":                 {"bwrap:", "bubblewrap"},
	"windows_mxc":                {"windows_mxc", "mxc"},
	"hypervisor":                 {"hyper-v", "hypervisor", "virtualization"},
	"macos_sandbox":              {"sandbox-exec", "seatbelt"},
	"systemroot":                 {"systemroot"},
	"permission_profile":         {"permission profile", "permission_profile", "default_permissions"},
	"configuration_error":        {"error loading config", "failed to load config", "invalid value", "unrecognized subcommand"},
	"process_launch_error":       {"failed to spawn", "failed to start", "failed to launch"},
	"code_mode_host":             {"code-mode-host", "code_mode_host"},
	"workspace_file_not_updated": {"native tool did not update its permitted workspace file"},
	"discarded_write_observed":   {"discarded native patch was executed"},
	"filesystem_error":           {"failed to write file", "failed_to_write_file", "failed to read file", "unable to write file", "cannot write file", "filesystem error"},
	"missing_file_or_executable": {"no such file", "file not found", "cannot find the file", "cannot find the path", "path not found"},
	"unsupported_operation":      {"not supported", "unsupported", "not implemented"},
	"approval_required":          {"approval required", "requires approval", "approval request", "approval_policy"},
	"tool_unavailable":           {"tool unavailable", "unknown tool", "tool not found", "no tool named"},
	"invalid_tool_arguments":     {"invalid arguments", "invalid tool input", "invalid parameters", "invalid params"},
}

func (d *nativeToolDiagnostics) observe(output []byte) {
	d.ObservedOutputs++
	if d.MatchingOutputs == nil {
		d.MatchingOutputs = make(map[string]int)
	}
	text := strings.ToLower(string(output))
	if text == "null" || text == `""` || strings.TrimSpace(text) == "" {
		d.EmptyOutputs++
	}
	for label, markers := range nativeToolSignals {
		for _, marker := range markers {
			if strings.Contains(text, marker) {
				d.MatchingOutputs[label]++
				break
			}
		}
	}
}

func TestNativeToolDiagnostics(t *testing.T) {
	var observed nativeToolDiagnostics
	observed.observe([]byte(`{"output":"bwrap: creating new namespace failed: Operation not permitted; SECRET_TOKEN_CANARY REQUEST_BODY_CANARY ANSWER_BODY_CANARY PRIVATE_PATH_CANARY"}`))
	observed.observe([]byte(`null`))
	observed.observe([]byte(`"REFLOW_TOOL_OK"`))
	if observed.ObservedOutputs != 3 || observed.EmptyOutputs != 1 || observed.MatchingOutputs["namespace_setup"] != 1 || observed.MatchingOutputs["operation_not_permitted"] != 1 || observed.MatchingOutputs["bubblewrap"] != 1 {
		t.Fatal("native tool diagnostic counts do not distinguish failure, empty output and normal output")
	}
	encoded, err := json.Marshal(observed)
	if err != nil {
		t.Fatal(err)
	}
	for _, forbidden := range []string{"SECRET_TOKEN_CANARY", "REQUEST_BODY_CANARY", "ANSWER_BODY_CANARY", "PRIVATE_PATH_CANARY", "REFLOW_TOOL_OK", "creating new namespace failed"} {
		if strings.Contains(string(encoded), forbidden) {
			t.Fatal("native tool diagnostic retained source content")
		}
	}
}
