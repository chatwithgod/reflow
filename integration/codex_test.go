package integration

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/chatwithgod/reflow/core"
	"github.com/chatwithgod/reflow/internal/testfixture"
	"github.com/chatwithgod/reflow/proxy"
	"github.com/coder/websocket"
)

func syntheticJWT(claims core.Object) string {
	b, _ := json.Marshal(claims)
	header, _ := json.Marshal(core.Object{"alg": "none", "typ": "JWT"})
	return base64.RawURLEncoding.EncodeToString(header) + "." + base64.RawURLEncoding.EncodeToString(b) + ".synthetic"
}

// Uses the installed CLI, a fresh home, synthetic ChatGPT credentials and an
// actual local read-only MCP tool. No real model call is made.
func TestCodexNativeLoginOffline(t *testing.T) {
	if os.Getenv("REFLOW_CODEX_BIN") == "" {
		t.Skip("set REFLOW_CODEX_BIN for the isolated installed-CLI test")
	}
	for _, codeMode := range []bool{false, true} {
		name := "direct_mcp"
		if codeMode {
			name = "code_mode"
		}
		t.Run(name, func(t *testing.T) { verifyNativeLoginOffline(t, nativeLoginMode{codeMode: codeMode}) })
	}
}

type nativeLoginMode struct {
	codeMode, nativeWrite, direct, command, add, noDaemon, appServer, paginated bool
	// Optional fixed synthetic command and in-memory JSON observer for opt-in diagnostics.
	probeCommand    string
	observeOutput   func(*testing.T, []byte)
	reasoningEffort string
}

func verifyNativeLoginOffline(t *testing.T, mode nativeLoginMode) {
	codeMode, nativeWrite := mode.codeMode, mode.nativeWrite
	bin := os.Getenv("REFLOW_CODEX_BIN")
	if bin == "" {
		t.Skip("set REFLOW_CODEX_BIN for the isolated installed-CLI test")
	}
	base := t.TempDir()
	home, work := filepath.Join(base, "codex-home"), filepath.Join(base, "workspace")
	for _, p := range []string{home, work, filepath.Join(base, "temp"), filepath.Join(base, "appdata"), filepath.Join(base, "localappdata")} {
		if err := os.MkdirAll(p, 0700); err != nil {
			t.Fatal(err)
		}
	}
	if nativeWrite && !mode.add {
		if err := os.WriteFile(filepath.Join(work, "probe.txt"), []byte("before\n"), 0600); err != nil {
			t.Fatal(err)
		}
	}
	jwt := syntheticJWT(core.Object{"exp": time.Now().Add(time.Hour).Unix(), "email": "synthetic@example.invalid", "https://api.openai.com/auth": core.Object{"chatgpt_account_id": "synthetic-account", "chatgpt_user_id": "synthetic-user", "chatgpt_plan_type": "pro"}})
	auth := core.Object{"auth_mode": "chatgpt", "tokens": core.Object{"id_token": jwt, "access_token": jwt, "refresh_token": "synthetic-refresh", "account_id": "synthetic-account"}, "last_refresh": time.Now().UTC().Format(time.RFC3339)}
	b, _ := json.Marshal(auth)
	if err := os.WriteFile(filepath.Join(home, "auth.json"), b, 0600); err != nil {
		t.Fatal(err)
	}
	var mu sync.Mutex
	var calls, wsCalls, httpCalls, chosenTools, discardedTools, effortMatches int
	var authSeen, toolSeen, resumeSeen bool
	var paths []string
	var toolDiagnostics nativeToolDiagnostics

	mcp := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != "POST" {
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}
		var req struct {
			ID     any
			Method string
			Params core.Object
		}
		if json.NewDecoder(r.Body).Decode(&req) != nil {
			http.Error(w, "invalid RPC", 400)
			return
		}
		if req.ID == nil {
			w.WriteHeader(202)
			return
		}
		var result any
		switch req.Method {
		case "initialize":
			result = core.Object{"protocolVersion": req.Params["protocolVersion"], "capabilities": core.Object{"tools": core.Object{}}, "serverInfo": core.Object{"name": "reflow-synthetic-fixture", "version": "1"}}
		case "tools/list":
			result = core.Object{"tools": []any{core.Object{"name": "probe", "description": "Return a fixed synthetic test marker. Read-only, no external access.", "inputSchema": core.Object{"type": "object", "properties": core.Object{"marker": core.Object{"type": "string"}}, "required": []any{"marker"}}, "annotations": core.Object{"readOnlyHint": true, "destructiveHint": false, "openWorldHint": false}}}}
		case "tools/call":
			args, _ := req.Params["arguments"].(map[string]any)
			marker, _ := args["marker"].(string)
			mu.Lock()
			if marker == "chosen" {
				chosenTools++
			} else {
				discardedTools++
			}
			mu.Unlock()
			text := "REFLOW_TOOL_OK"
			if nativeWrite {
				contents, err := os.ReadFile(filepath.Join(work, "probe.txt"))
				if err != nil {
					text = "fixture read failed"
				} else {
					text = string(contents)
				}
			}
			result = core.Object{"content": []any{core.Object{"type": "text", "text": text}}, "isError": false}
		default:
			result = core.Object{}
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(core.Object{"jsonrpc": "2.0", "id": req.ID, "result": result})
	}))
	defer mcp.Close()

	respond := func(body core.Object, header http.Header) []core.Object {
		if body["generate"] == false {
			return []core.Object{{"type": "response.completed", "response": core.Object{"id": "warmup", "status": "completed", "output": []any{}}}}
		}
		mu.Lock()
		calls++
		n := calls
		authSeen = authSeen || header.Get("Authorization") == "Bearer "+jwt
		if reasoning, ok := body["reasoning"].(map[string]any); ok && mode.reasoningEffort != "" && reasoning["effort"] == mode.reasoningEffort {
			effortMatches++
		}
		mu.Unlock()
		var events []core.Object
		if (n <= 2 && !mode.direct) || (n == 1 && mode.direct) {
			tokens, id := 20, "chosen"
			if n == 1 && !mode.direct {
				tokens, id = 516, "discarded"
			}
			events = testfixture.Round(id, tokens, true)
			args, _ := json.Marshal(core.Object{"marker": id})
			patch := func(item core.Object) {
				if item["type"] == "function_call" {
					if codeMode {
						item["type"], item["name"], item["namespace"] = "custom_tool_call", "exec", "functions"
						item["input"] = "const spec=ALL_TOOLS.find(x=>x.name.includes('reflow_fixture')&&x.name.endsWith('probe')); if(!spec) throw new Error('Fixture tool unavailable'); text(await tools[spec.name](" + string(args) + "));"
						if nativeWrite {
							patch := "*** Begin Patch\n*** Update File: probe.txt\n@@\n-before\n+REFLOW_TOOL_OK\n*** End Patch"
							if mode.add {
								patch = "*** Begin Patch\n*** Add File: probe.txt\n+REFLOW_TOOL_OK\n*** End Patch"
							}
							if id == "discarded" {
								patch = "*** Begin Patch\n*** Add File: discarded.txt\n+discarded write must remain invisible\n*** End Patch"
							}
							encoded, _ := json.Marshal(patch)
							item["input"] = "const writer=ALL_TOOLS.find(x=>x.name.endsWith('apply_patch')); if(!writer) throw new Error('Fixture patch tool unavailable'); text(await tools[writer.name](" + string(encoded) + ")); " + item["input"].(string)
							if mode.command {
								file := "probe.txt"
								if id == "discarded" {
									file = "discarded.txt"
								}
								command := "printf 'REFLOW_TOOL_OK\\n' > " + file
								if runtime.GOOS == "windows" {
									command = "cmd.exe /d /c \"echo REFLOW_TOOL_OK>" + file + "\""
								}
								if mode.probeCommand != "" && id == "chosen" {
									command = mode.probeCommand
								}
								params, _ := json.Marshal(core.Object{"cmd": command, "workdir": work, "yield_time_ms": 10000, "max_output_tokens": 200})
								item["input"] = "const writer=ALL_TOOLS.find(x=>x.name.endsWith('exec_command')); if(!writer) throw new Error('Fixture command tool unavailable'); text(await tools[writer.name](" + string(params) + ")); const spec=ALL_TOOLS.find(x=>x.name.includes('reflow_fixture')&&x.name.endsWith('probe')); text(await tools[spec.name](" + string(args) + "));"
							}
						}
						delete(item, "arguments")
					} else {
						item["name"] = "probe"
						item["namespace"] = "mcp__reflow_fixture"
						item["arguments"] = string(args)
					}
				}
			}
			for _, ev := range events {
				if item, ok := ev["item"].(map[string]any); ok {
					patch(item)
				}
				if response, ok := ev["response"].(map[string]any); ok {
					if items, ok := response["output"].([]any); ok {
						for _, value := range items {
							if item, ok := value.(map[string]any); ok {
								patch(item)
							}
						}
					}
				}
			}
			if codeMode {
				var streamed []core.Object
				for _, event := range events {
					item, _ := event["item"].(map[string]any)
					if event["type"] == "response.output_item.added" && item["type"] == "custom_tool_call" {
						input := item["input"].(string)
						start, _ := core.Clone(item)
						start["input"], start["status"] = "", "in_progress"
						event["item"] = start
						streamed = append(streamed, event)
						for _, delta := range []string{input[:len(input)/2], input[len(input)/2:]} {
							streamed = append(streamed, core.Object{"type": "response.custom_tool_call_input.delta", "output_index": 1, "item_id": item["id"], "delta": delta})
						}
						streamed = append(streamed, core.Object{"type": "response.custom_tool_call_input.done", "output_index": 1, "item_id": item["id"], "input": input})
					} else {
						streamed = append(streamed, event)
					}
				}
				events = streamed
			}
		} else {
			if mode.appServer && n == 4 {
				raw, _ := json.Marshal(body["input"])
				mu.Lock()
				resumeSeen = strings.Contains(string(raw), "chosen-call") && strings.Contains(string(raw), "REFLOW_TOOL_OK") && strings.Contains(string(raw), "REFLOW_NATIVE_OK")
				mu.Unlock()
			}
			input, _ := body["input"].([]any)
			for _, value := range input {
				item, ok := value.(map[string]any)
				if !ok {
					continue
				}
				if (item["type"] == "function_call_output" || item["type"] == "custom_tool_call_output") && item["call_id"] == "chosen-call" {
					out, _ := json.Marshal(item["output"])
					mu.Lock()
					toolSeen = strings.Contains(string(out), "REFLOW_TOOL_OK")
					if nativeWrite {
						toolDiagnostics.observe(out)
					}
					mu.Unlock()
				}
			}
			finalID, marker := "finish", "REFLOW_NATIVE_OK"
			if mode.appServer && n == 4 {
				finalID, marker = "resumed", "REFLOW_NATIVE_RESUMED"
			}
			events = testfixture.Round(finalID, 20, false)
			for _, ev := range events {
				if item, ok := ev["item"].(map[string]any); ok && item["type"] == "message" {
					item["content"] = []any{core.Object{"type": "output_text", "text": marker, "annotations": []any{}}}
				}
			}
		}
		return events
	}
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		mu.Lock()
		paths = append(paths, r.Method+" "+r.URL.Path)
		mu.Unlock()
		if strings.HasSuffix(r.URL.Path, "/models") {
			w.Header().Set("Content-Type", "application/json")
			fmt.Fprint(w, "{\"models\":[]}")
			return
		}
		if !strings.HasSuffix(r.URL.Path, "/responses") {
			http.Error(w, "synthetic endpoint", 404)
			return
		}
		if strings.EqualFold(r.Header.Get("Upgrade"), "websocket") {
			conn, err := websocket.Accept(w, r, nil)
			if err != nil {
				return
			}
			defer conn.CloseNow()
			conn.SetReadLimit(proxy.MaxRequestBytes)
			ctx, cancel := context.WithTimeout(context.Background(), 35*time.Second)
			defer cancel()
			for {
				_, raw, err := conn.Read(ctx)
				if err != nil {
					return
				}
				var body core.Object
				if json.Unmarshal(raw, &body) != nil {
					return
				}
				mu.Lock()
				wsCalls++
				mu.Unlock()
				for _, ev := range respond(body, r.Header) {
					if id, ok := body["stream_id"]; ok {
						ev["stream_id"] = id
					}
					data, _ := json.Marshal(ev)
					if conn.Write(ctx, websocket.MessageText, data) != nil {
						return
					}
				}
			}
		}
		if r.Method != "POST" {
			http.Error(w, "method", 405)
			return
		}
		var body core.Object
		if json.NewDecoder(r.Body).Decode(&body) != nil {
			http.Error(w, "invalid JSON", 400)
			return
		}
		mu.Lock()
		httpCalls++
		mu.Unlock()
		testfixture.WriteSSE(w, respond(body, r.Header))
	}))
	defer upstream.Close()
	proxyURL := upstream.URL + "/backend-api/codex"
	if !mode.direct {
		proxyURL = startProxy(t, proxyURL)
	}
	chatgptURL, caPath := upstream.URL, ""
	if mode.direct || mode.appServer {
		cloud, certificate := testfixture.LocalTLS(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			w.Header().Set("Content-Type", "application/json")
			if strings.Contains(r.URL.Path, "/accounts/check") {
				fmt.Fprint(w, `{"accounts":[{"id":"synthetic-account","plan_type":"pro","workspace_backend_origin":"NO_CONSTRAINT","account_routing_override":"NO_CONSTRAINT"}]}`)
				return
			}
			http.Error(w, "synthetic cloud endpoint", 404)
		}))
		defer cloud.Close()
		chatgptURL, caPath = cloud.URL, certificate
	}
	ctx, cancel := context.WithTimeout(context.Background(), 35*time.Second)
	defer cancel()
	prompt := "Synthetic local protocol test. Use the read-only fixture tool and report its final marker."
	if nativeWrite {
		prompt = "Synthetic local protocol test. You may modify only probe.txt and discarded.txt in this temporary workspace. Use the read-only fixture tool to read the retained marker, then finish."
	}
	effort := "low"
	if mode.reasoningEffort != "" {
		effort = mode.reasoningEffort
	}
	args := []string{"-a", "never", "exec", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check", "--ephemeral", "--json", "-C", work, "-m", "gpt-6.1-sol",
		"-c", "cli_auth_credentials_store=\"file\"", "-c", "openai_base_url=\"" + proxyURL + "\"", "-c", "chatgpt_base_url=\"" + chatgptURL + "\"",
		"-c", "features.memories=false", "-c", "features.apps=false", "-c", fmt.Sprintf("features.code_mode=%t", codeMode), "-c", "features.multi_agent=false", "-c", "features.multi_agent_v2=false", "-c", fmt.Sprintf("model_reasoning_effort=%q", effort),
		"-c", "mcp_servers.reflow_fixture.url=\"" + mcp.URL + "\"",
		"-c", "mcp_servers.reflow_fixture.tools.probe.approval_mode=\"approve\""}
	if nativeWrite {
		args = append(args, "-c", "default_permissions=\":workspace\"")
	} else {
		args = append(args, "-s", "read-only")
	}
	if nativeWrite && runtime.GOOS == "windows" {
		args = append(args, "-c", "windows.sandbox=\"mxc\"")
	}
	args = append(args, prompt)
	if mode.noDaemon {
		args = append([]string{"--no-daemon"}, args...)
	}
	cmd := exec.CommandContext(ctx, bin, args...)
	cmd.Dir = work
	for _, name := range []string{"PATH", "SystemRoot", "SystemDrive", "WINDIR", "COMSPEC", "PATHEXT", "ProgramData"} {
		if value := os.Getenv(name); value != "" {
			cmd.Env = append(cmd.Env, name+"="+value)
		}
	}
	cmd.Env = append(cmd.Env, "CODEX_HOME="+home, "HOME="+base, "USERPROFILE="+base, "APPDATA="+filepath.Join(base, "appdata"), "LOCALAPPDATA="+filepath.Join(base, "localappdata"), "TEMP="+filepath.Join(base, "temp"), "TMP="+filepath.Join(base, "temp"), "TMPDIR="+filepath.Join(base, "temp"), "NO_PROXY=127.0.0.1,localhost", "RUST_LOG=warn")
	if caPath != "" {
		cmd.Env = append(cmd.Env, "CODEX_CA_CERTIFICATE="+caPath)
	}
	var out []byte
	var err error
	if mode.appServer {
		out, err = runAppServerLifecycle(t, ctx, cmd, home, work, proxyURL, prompt, mode.paginated)
	} else {
		out, err = cmd.CombinedOutput()
	}
	if mode.observeOutput != nil {
		mode.observeOutput(t, out)
	}
	if nativeWrite {
		contents, readErr := os.ReadFile(filepath.Join(work, "probe.txt"))
		if readErr != nil || strings.TrimSpace(string(contents)) != "REFLOW_TOOL_OK" {
			t.Errorf("native tool did not update its permitted workspace file: %v", readErr)
		}
		if _, statErr := os.Stat(filepath.Join(work, "discarded.txt")); !os.IsNotExist(statErr) {
			t.Errorf("discarded native patch was executed: %v", statErr)
		}
	}
	mu.Lock()
	defer mu.Unlock()
	if nativeWrite {
		encoded, _ := json.Marshal(toolDiagnostics)
		t.Logf("REFLOW_NATIVE_TOOL_DIAGNOSTICS %s", encoded)
	}
	expectedCalls := 3
	if mode.direct {
		expectedCalls = 2
	} else if mode.appServer {
		expectedCalls = 4
	}
	if err != nil || calls != expectedCalls || !authSeen || !toolSeen || chosenTools != 1 || discardedTools != 0 || wsCalls < expectedCalls || httpCalls != 0 || !strings.Contains(string(out), "REFLOW_NATIVE_OK") || strings.Contains(string(out), "falling back to HTTP") {
		text := strings.ReplaceAll(string(out), jwt, "[synthetic token]")
		if len(text) > 7000 {
			text = text[len(text)-7000:]
		}
		t.Fatalf("native CLI err=%v calls=%d WS=%d HTTP=%d auth=%t tool=%t chosen=%d discarded=%d paths=%v output=%s", err, calls, wsCalls, httpCalls, authSeen, toolSeen, chosenTools, discardedTools, paths, text)
	}
	if mode.appServer && !resumeSeen {
		t.Fatal("app-server resume did not return retained tool history and the prior final message")
	}
	if mode.reasoningEffort != "" {
		if effortMatches != expectedCalls {
			t.Fatalf("reasoning effort preserved in %d of %d synthetic requests", effortMatches, expectedCalls)
		}
		t.Logf("REFLOW_NATIVE_EFFORT matched=%d expected=%d effort=%s", effortMatches, expectedCalls, mode.reasoningEffort)
	}
	t.Logf("installed CLI: %d synthetic inference calls via WebSocket, 1 real read-only MCP invocation, discarded call not executed, result returned; no HTTP fallback", calls)
	if mode.direct {
		return
	}
	stats := proxyMetrics(t, proxyURL)
	if stats.Requests != int64(expectedCalls) || stats.Continuations != 1 || stats.InputTokens != int64(expectedCalls*100) || stats.OutputTokens != int64(526+(expectedCalls-1)*30) || !stats.UsageComplete {
		t.Fatalf("native CLI upstream accounting mismatch: %+v", stats)
	}
	if stats.ContinuedToolResponses != 1 || stats.ContinuedToolCalls != 1 || stats.ContinuedToolResults != 1 || stats.ToolTrackingDrops != 0 {
		t.Fatalf("native CLI continuation/tool correlation mismatch: %+v", stats)
	}
}
