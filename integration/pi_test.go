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
	adapterDir := os.Getenv("REFLOW_PI_ADAPTER_DIR")
	if adapterDir == "" {
		adapterDir = "../adapters/pi"
	}
	for _, mode := range []struct {
		name, provider, transport, extension, path, authType string
		endpointOnly                                         bool
	}{
		{"sse", "openai-codex", "sse", "reflow.ts", "/backend-api/codex/responses", "oauth", false},
		{"websocket", "openai-codex", "websocket", "reflow.ts", "/backend-api/codex/responses", "oauth", false},
		{"public_oauth_sse", "openai", "sse", "reflow-openai.ts", "/v1/responses", "oauth", false},
		{"public_api_key_sse", "openai", "sse", "reflow-openai.ts", "/v1/responses", "api_key", false},
		{"public_endpoint_only_control", "openai", "sse", "reflow-openai.ts", "/v1/responses", "oauth", true},
	} {
		t.Run(mode.name, func(t *testing.T) {
			extension, err := filepath.Abs(filepath.Join(adapterDir, mode.extension))
			if err != nil {
				t.Fatal(err)
			}
			base := t.TempDir()
			if mode.endpointOnly {
				extension = filepath.Join(base, "endpoint-only-control.ts")
				control := `export default function (pi) { pi.registerProvider("openai", {baseUrl: process.env.REFLOW_URL + "/v1"}); }`
				if err := os.WriteFile(extension, []byte(control), 0600); err != nil {
					t.Fatal(err)
				}
			}
			agent := filepath.Join(base, "agent")
			work := filepath.Join(base, "workspace")
			for _, dir := range []string{agent, work, filepath.Join(base, "temp")} {
				if err := os.MkdirAll(dir, 0700); err != nil {
					t.Fatal(err)
				}
			}
			probe := filepath.Join(work, "probe.txt")
			discarded := filepath.Join(work, "discarded.txt")
			os.WriteFile(probe, []byte("REFLOW_PI_TOOL_OK\n"), 0600)
			os.WriteFile(discarded, []byte("REFLOW_PI_DISCARDED_EXECUTED\n"), 0600)
			jwt := syntheticJWT(core.Object{"exp": time.Now().Add(time.Hour).Unix(), "https://api.openai.com/auth": core.Object{"chatgpt_account_id": "synthetic-pi-account"}})
			credential := core.Object{"type": "oauth", "access": jwt, "refresh": "synthetic-refresh", "expires": time.Now().Add(time.Hour).UnixMilli(), "accountId": "synthetic-pi-account"}
			bearer := jwt
			if mode.provider == "openai" {
				credential["clientId"] = "synthetic-public-client"
				credential["scopes"] = []string{"resource.invoke", "chatgpt.tokens.use.direct"}
			}
			if mode.authType == "api_key" {
				bearer = "sk-synthetic-offline"
				credential = core.Object{"type": "api_key", "key": bearer}
			}
			auth := core.Object{mode.provider: credential}
			b, _ := json.Marshal(auth)
			os.WriteFile(filepath.Join(agent, "auth.json"), b, 0600)
			settings := core.Object{"transport": mode.transport, "retry": core.Object{"enabled": false}, "compaction": core.Object{"enabled": false}}
			b, _ = json.Marshal(settings)
			os.WriteFile(filepath.Join(agent, "settings.json"), b, 0600)
			var mu sync.Mutex
			calls, wsCalls, httpCalls := 0, 0, 0
			authSeen, toolSeen := false, false
			requestContract := true
			respond := func(body core.Object, headers http.Header) []core.Object {
				mu.Lock()
				calls++
				n := calls
				authSeen = authSeen || headers.Get("Authorization") == "Bearer "+bearer
				if mode.provider == "openai" {
					requestContract = requestContract && body["stream"] == true && body["store"] == false
					if mode.authType == "oauth" {
						for _, field := range []string{"max_output_tokens", "temperature", "prompt_cache_retention", "prompt_cache_options"} {
							_, present := body[field]
							requestContract = requestContract && !present
						}
						input, validInput := body["input"].([]any)
						requestContract = requestContract && validInput
						for _, value := range input {
							if item, ok := value.(map[string]any); ok && item["type"] == "configuration_update" {
								requestContract = false
							}
						}
					} else {
						maximum, ok := body["max_output_tokens"].(float64)
						requestContract = requestContract && ok && maximum > 0
					}
				}
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
							item["id"] = "fc_" + id + "_tool"
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
				if r.URL.Path != mode.path {
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
			url := startProxy(t, upstream.URL+strings.TrimSuffix(mode.path, "/responses"))
			ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
			defer cancel()
			args := []string{cli, "--offline", "--print", "--mode", "json", "--no-session", "--no-extensions", "--no-mcp", "--no-skills", "--no-prompt-templates", "--no-themes", "--no-context-files", "--extension", extension, "--tools", "read", "--provider", mode.provider, "--model", "gpt-6.1-sol", "--thinking", "low", "Synthetic local test. Read the fixture file when requested and return the final marker."}
			cmd := exec.CommandContext(ctx, node, args...)
			cmd.Dir = work
			for _, key := range []string{"PATH", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "TEMP", "TMP"} {
				if value := os.Getenv(key); value != "" {
					cmd.Env = append(cmd.Env, key+"="+value)
				}
			}
			cmd.Env = append(cmd.Env, "PI_CODING_AGENT_DIR="+agent, "PI_OFFLINE=1", "PI_TELEMETRY=0", "REFLOW_URL="+url, "HOME="+base, "USERPROFILE="+base, "TMPDIR="+filepath.Join(base, "temp"), "NO_PROXY=127.0.0.1,localhost")
			out, err := cmd.CombinedOutput()
			mu.Lock()
			defer mu.Unlock()
			correctTransport := (mode.transport == "sse" && httpCalls == 3 && wsCalls == 0) || (mode.transport == "websocket" && wsCalls == 3 && httpCalls == 0)
			expectedContract := !mode.endpointOnly
			if err != nil || calls != 3 || !correctTransport || requestContract != expectedContract || !authSeen || !toolSeen || !strings.Contains(string(out), "REFLOW_PI_DONE") || strings.Contains(string(out), "REFLOW_PI_DISCARDED_EXECUTED") {
				text := strings.ReplaceAll(string(out), jwt, "[synthetic token]")
				if len(text) > 6500 {
					text = text[len(text)-6500:]
				}
				t.Fatalf("Pi %s err=%v calls=%d ws=%d http=%d contract=%t auth=%t tool=%t output=%s", mode.name, err, calls, wsCalls, httpCalls, requestContract, authSeen, toolSeen, text)
			}
			t.Log(fmt.Sprintf("Pi synthetic %s + %s extension: %s, 3 requests, real read-tool result returned, discarded read not executed", mode.authType, mode.provider, mode.transport))
			if mode.endpointOnly {
				t.Log("Negative control: endpoint-only override emitted fields forbidden for ChatGPT sign-in")
			}
			stats := proxyMetrics(t, url)
			if stats.Requests != 3 || stats.Continuations != 1 || stats.InputTokens != 300 || stats.OutputTokens != 586 || !stats.UsageComplete ||
				stats.ContinuedToolResponses != 1 || stats.ContinuedToolCalls != 1 || stats.ContinuedToolResults != 1 || stats.ToolTrackingDrops != 0 {
				t.Fatalf("Pi upstream accounting mismatch: %+v", stats)
			}
		})
	}
}

func TestPiTransportBoundaries(t *testing.T) {
	node := os.Getenv("REFLOW_NODE_BIN")
	if node == "" {
		node = "node"
	}
	if _, err := exec.LookPath(node); err != nil {
		t.Skip("Node is required for Pi transport boundary checks")
	}
	ctx, cancel := context.WithTimeout(context.Background(), 20*time.Second)
	defer cancel()
	command := exec.CommandContext(ctx, node, "--test", "pi_openai_transport.test.mjs")
	output, err := command.CombinedOutput()
	if err != nil {
		t.Fatalf("Pi transport boundary checks failed: %v\n%s", err, output)
	}
	t.Log("Five no-account transport checks passed: loopback, payload/headers, route scope, cancellation, no fallback")
}
