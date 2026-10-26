package integration

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/chatwithgod/reflow/core"
	"github.com/chatwithgod/reflow/internal/testfixture"
	"github.com/chatwithgod/reflow/proxy"
	"github.com/coder/websocket"
)

// Uses the published Pi CLI and Reflow extension with synthetic OAuth storage.
// Both wire transports must actually execute Pi's read tool and return its data.
func TestPiOAuthOffline(t *testing.T) {
	cli := os.Getenv("REFLOW_PI_CLI")
	if cli == "" {
		t.Skip("set REFLOW_PI_CLI to the pinned Pi CLI entry point")
	}
	node := os.Getenv("REFLOW_NODE_BIN")
	if node == "" {
		node = "node"
	}
	extension, err := filepath.Abs("../adapters/pi/reflow.ts")
	if err != nil {
		t.Fatal(err)
	}
	for _, transport := range []string{"sse", "websocket"} {
		t.Run(transport, func(t *testing.T) {
			base := t.TempDir()
			agent := filepath.Join(base, "agent")
			work := filepath.Join(base, "workspace")
			for _, dir := range []string{agent, work} {
				if err := os.MkdirAll(dir, 0700); err != nil {
					t.Fatal(err)
				}
			}
			probe := filepath.Join(work, "probe.txt")
			discarded := filepath.Join(work, "discarded.txt")
			os.WriteFile(probe, []byte("REFLOW_PI_TOOL_OK\n"), 0600)
			os.WriteFile(discarded, []byte("REFLOW_PI_DISCARDED_EXECUTED\n"), 0600)
			jwt := syntheticJWT(core.Object{"exp": time.Now().Add(time.Hour).Unix(), "https://api.openai.com/auth": core.Object{"chatgpt_account_id": "synthetic-pi-account"}})
			auth := core.Object{"openai-codex": core.Object{"type": "oauth", "access": jwt, "refresh": "synthetic-refresh", "expires": time.Now().Add(time.Hour).UnixMilli(), "accountId": "synthetic-pi-account"}}
			b, _ := json.Marshal(auth)
			os.WriteFile(filepath.Join(agent, "auth.json"), b, 0600)
			settings := core.Object{"transport": transport, "retry": core.Object{"enabled": false}, "compaction": core.Object{"enabled": false}}
			b, _ = json.Marshal(settings)
			os.WriteFile(filepath.Join(agent, "settings.json"), b, 0600)
			var mu sync.Mutex
			calls, wsCalls, httpCalls := 0, 0, 0
			authSeen, toolSeen := false, false
			respond := func(body core.Object, headers http.Header) []core.Object {
				mu.Lock()
				calls++
				n := calls
				authSeen = authSeen || headers.Get("Authorization") == "Bearer "+jwt
				mu.Unlock()
				id, tokens, tool := "finish", 20, false
				if n == 1 {
					id, tokens, tool = "discarded", 516, true
				}
				if n == 2 {
					id, tool = "chosen", true
				}
				events := testfixture.Round(id, tokens, tool)
				if tool {
					path := probe
					if n == 1 {
						path = discarded
					}
					args, _ := json.Marshal(core.Object{"path": path})
					patch := func(item core.Object) {
						if item["type"] == "function_call" {
							item["name"] = "read"
							item["arguments"] = string(args)
						}
					}
					for _, ev := range events {
						if item, ok := ev["item"].(map[string]any); ok {
							patch(item)
						}
						if response, ok := ev["response"].(map[string]any); ok {
							if output, ok := response["output"].([]any); ok {
								for _, value := range output {
									if item, ok := value.(map[string]any); ok {
										patch(item)
									}
								}
							}
						}
					}
				} else {
					input, _ := body["input"].([]any)
					for _, value := range input {
						if item, ok := value.(map[string]any); ok && item["type"] == "function_call_output" {
							out, _ := json.Marshal(item["output"])
							if strings.Contains(string(out), "REFLOW_PI_TOOL_OK") {
								mu.Lock()
								toolSeen = true
								mu.Unlock()
							}
						}
					}
					for _, ev := range events {
						if item, ok := ev["item"].(map[string]any); ok && item["type"] == "message" {
							item["content"] = []any{core.Object{"type": "output_text", "text": "REFLOW_PI_DONE", "annotations": []any{}}}
						}
					}
				}
				return events
			}
			upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				if r.URL.Path != "/backend-api/codex/responses" {
					http.Error(w, "unexpected synthetic path", 404)
					return
				}
				if strings.EqualFold(r.Header.Get("Upgrade"), "websocket") {
					conn, err := websocket.Accept(w, r, nil)
					if err != nil {
						return
					}
					defer conn.CloseNow()
					conn.SetReadLimit(proxy.MaxRequestBytes)
					ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
					defer cancel()
					for {
						_, b, err := conn.Read(ctx)
						if err != nil {
							return
						}
						var body core.Object
						if json.Unmarshal(b, &body) != nil {
							return
						}
						mu.Lock()
						wsCalls++
						mu.Unlock()
						for _, ev := range respond(body, r.Header) {
							if lane, ok := body["stream_id"]; ok {
								ev["stream_id"] = lane
							}
							b, _ := json.Marshal(ev)
							if conn.Write(ctx, websocket.MessageText, b) != nil {
								return
							}
						}
					}
				}
				var body core.Object
				if json.NewDecoder(r.Body).Decode(&body) != nil {
					http.Error(w, "invalid synthetic input", 400)
					return
				}
				mu.Lock()
				httpCalls++
				mu.Unlock()
				testfixture.WriteSSE(w, respond(body, r.Header))
			}))
			defer upstream.Close()
			url := startProxy(t, upstream.URL+"/backend-api/codex")
			ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
			defer cancel()
			args := []string{cli, "--offline", "--print", "--mode", "json", "--no-session", "--no-extensions", "--no-mcp", "--no-skills", "--no-prompt-templates", "--no-themes", "--no-context-files", "--extension", extension, "--tools", "read", "--provider", "openai-codex", "--model", "gpt-6.1-sol", "--thinking", "low", "Synthetic local test. Read the fixture file when requested and return the final marker."}
			cmd := exec.CommandContext(ctx, node, args...)
			cmd.Dir = work
			for _, key := range []string{"PATH", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP"} {
				if value := os.Getenv(key); value != "" {
					cmd.Env = append(cmd.Env, key+"="+value)
				}
			}
			cmd.Env = append(cmd.Env, "PI_CODING_AGENT_DIR="+agent, "PI_OFFLINE=1", "PI_TELEMETRY=0", "REFLOW_URL="+url, "USERPROFILE="+base, "NO_PROXY=127.0.0.1,localhost")
			out, err := cmd.CombinedOutput()
			mu.Lock()
			defer mu.Unlock()
			correctTransport := (transport == "sse" && httpCalls == 3 && wsCalls == 0) || (transport == "websocket" && wsCalls == 3 && httpCalls == 0)
			if err != nil || calls != 3 || !correctTransport || !authSeen || !toolSeen || !strings.Contains(string(out), "REFLOW_PI_DONE") || strings.Contains(string(out), "REFLOW_PI_DISCARDED_EXECUTED") {
				text := strings.ReplaceAll(string(out), jwt, "[synthetic token]")
				if len(text) > 6500 {
					text = text[len(text)-6500:]
				}
				t.Fatalf("Pi %s err=%v calls=%d ws=%d http=%d auth=%t tool=%t output=%s", transport, err, calls, wsCalls, httpCalls, authSeen, toolSeen, text)
			}
			t.Log(fmt.Sprintf("Pi OAuth storage + endpoint extension: %s, 3 requests, real read-tool result returned, discarded read not executed", transport))
			stats := proxyMetrics(t, url)
			if stats.Requests != 3 || stats.Continuations != 1 || stats.InputTokens != 300 || stats.OutputTokens != 586 || !stats.UsageComplete {
				t.Fatalf("Pi upstream accounting mismatch: %+v", stats)
			}
		})
	}
}
