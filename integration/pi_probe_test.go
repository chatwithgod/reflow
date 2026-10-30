//go:build pi_probe

package integration

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/chatwithgod/reflow/core"
	"github.com/chatwithgod/reflow/internal/testfixture"
)

func TestPiProbeOffline(t *testing.T) {
	cli, reflow := os.Getenv("REFLOW_PI_CLI"), os.Getenv("REFLOW_PROXY_BIN")
	if cli == "" || reflow == "" {
		t.Skip("set REFLOW_PI_CLI and REFLOW_PROXY_BIN for the no-account Pi probe check")
	}
	node := os.Getenv("REFLOW_NODE_BIN")
	if node == "" {
		node = "node"
	}
	python, err := exec.LookPath("python")
	if err != nil {
		t.Skip("Python is required for the probe process")
	}
	root, err := filepath.Abs("..")
	if err != nil {
		t.Fatal(err)
	}
	for _, mode := range []string{"success", "rate_limit", "blocked_read"} {
		t.Run(mode, func(t *testing.T) {
			var mu sync.Mutex
			calls := 0
			authSeen := false
			upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				mu.Lock()
				calls++
				n := calls
				authSeen = authSeen || r.Header.Get("Authorization") == "Bearer synthetic-pi-public-oauth"
				mu.Unlock()
				if r.URL.Path != "/v1/responses" {
					http.Error(w, "synthetic bad route", 404)
					return
				}
				if mode == "rate_limit" {
					w.Header().Set("Content-Type", "application/json")
					w.WriteHeader(429)
					io.WriteString(w, `{"error":{"code":"rate_limit","message":"429 SYNTHETIC_PRIVATE_SENTINEL"}}`)
					return
				}
				body, _ := io.ReadAll(io.LimitReader(r.Body, 1<<20))
				id, tokens, tool, path := "finish", 20, false, "probe.txt"
				if mode == "blocked_read" {
					id, tool, path = "blocked", true, "../outside.txt"
				} else if n == 1 {
					id, tokens, tool, path = "discarded", 516, true, "../outside.txt"
				} else if n == 2 {
					id, tool = "chosen", true
				}
				marker := regexp.MustCompile(`REFLOW_PI_PROBE_[0-9a-f]{32}`).FindString(string(body))
				args, _ := json.Marshal(core.Object{"path": path})
				patch := func(item core.Object) {
					if item["type"] == "function_call" {
						item["id"] = "fc_" + id + "_tool"
						item["name"], item["arguments"] = "read", string(args)
					} else if item["type"] == "message" {
						item["content"] = []any{core.Object{"type": "output_text", "text": marker, "annotations": []any{}}}
					}
				}
				events := testfixture.Round(id, tokens, tool)
				for _, event := range events {
					if item, ok := event["item"].(map[string]any); ok {
						patch(item)
					}
					if response, ok := event["response"].(map[string]any); ok {
						if output, ok := response["output"].([]any); ok {
							for _, value := range output {
								if item, ok := value.(map[string]any); ok {
									patch(item)
								}
							}
						}
					}
				}
				testfixture.WriteSSE(w, events)
			}))
			defer upstream.Close()
			ctx, cancel := context.WithTimeout(context.Background(), 45*time.Second)
			defer cancel()
			command := exec.CommandContext(ctx, python, filepath.Join(root, "evaluations/pi_probe.py"),
				"--synthetic-upstream", upstream.URL+"/v1", "--pi-cli", cli, "--node", node, "--reflow", reflow, "--timeout", "30")
			if adapters := os.Getenv("REFLOW_PI_ADAPTER_DIR"); adapters != "" {
				command.Args = append(command.Args, "--adapter-dir", adapters)
			}
			command.Dir = root
			out, err := command.CombinedOutput()
			if err != nil {
				t.Fatalf("synthetic probe process failed: %v", err)
			}
			var header struct{ Report string }
			if json.Unmarshal(out, &header) != nil || !strings.HasPrefix(header.Report, "build/pi-probes/") {
				t.Fatal("probe did not return its fixed report locator")
			}
			content, err := os.ReadFile(filepath.Join(root, filepath.FromSlash(header.Report), "results.json"))
			if err != nil {
				t.Fatal("missing probe report")
			}
			for _, private := range []string{"SYNTHETIC_PRIVATE_SENTINEL", "synthetic-pi-public-oauth", "REFLOW_PI_PROBE_"} {
				if strings.Contains(string(content), private) {
					t.Fatal("private fixture content survived redaction")
				}
			}
			var report map[string]any
			if json.Unmarshal(content, &report) != nil {
				t.Fatal("invalid probe report")
			}
			result := report["result"].(map[string]any)
			mu.Lock()
			defer mu.Unlock()
			if !authSeen || result["remaining_trial_profiles"] != float64(0) || report["credential_read"] != false || report["real_account_inference_requests"] != float64(0) {
				t.Fatal("auth, cleanup or synthetic isolation evidence differs")
			}
			if mode == "success" {
				if calls != 3 || result["read_tool_roundtrip_passed"] != true || result["continuation_tool_finish_observed"] != true || result["real_account_continuation_tool_finish_observed"] != false {
					t.Fatalf("successful simulated flow not verified: calls=%d status=%v tool=%v", calls, result["status"], result["read_tool_roundtrip_passed"])
				}
			} else if mode == "rate_limit" {
				if calls != 1 || result["rate_limit_detected"] != true || result["read_tool_roundtrip_passed"] != false {
					t.Fatalf("rate-limit stop differed: calls=%d status=%v", calls, result["status"])
				}
			} else {
				guard, _ := result["guard"].(map[string]any)
				if calls != 1 || guard["blocked"] != float64(1) || guard["allowed"] != float64(0) || result["read_tool_roundtrip_passed"] != false {
					t.Fatalf("guard stop differed: calls=%d status=%v", calls, result["status"])
				}
			}
			t.Logf("Pi read probe: %s, requests=%d, redacted report, no existing login read, temporary profile removed", mode, calls)
		})
	}
}
