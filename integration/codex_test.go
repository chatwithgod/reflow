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
// actual local read-only MCP tool. No shell command or real model call is made.
func TestCodexNativeLoginOffline(t *testing.T) {
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
	jwt := syntheticJWT(core.Object{"exp": time.Now().Add(time.Hour).Unix(), "email": "synthetic@example.invalid", "https://api.openai.com/auth": core.Object{"chatgpt_account_id": "synthetic-account", "chatgpt_user_id": "synthetic-user", "chatgpt_plan_type": "pro"}})
	auth := core.Object{"auth_mode": "chatgpt", "tokens": core.Object{"id_token": jwt, "access_token": jwt, "refresh_token": "synthetic-refresh", "account_id": "synthetic-account"}, "last_refresh": time.Now().UTC().Format(time.RFC3339)}
	b, _ := json.Marshal(auth)
	if err := os.WriteFile(filepath.Join(home, "auth.json"), b, 0600); err != nil {
		t.Fatal(err)
	}
	var mu sync.Mutex
	var calls, wsCalls, httpCalls, chosenTools, discardedTools int
	var authSeen, toolSeen bool
	var paths []string

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
			result = core.Object{"content": []any{core.Object{"type": "text", "text": "REFLOW_TOOL_OK"}}, "isError": false}
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
		mu.Unlock()
		var events []core.Object
		if n <= 2 {
			tokens, id := 20, "chosen"
			if n == 1 {
				tokens, id = 516, "discarded"
			}
			events = testfixture.Round(id, tokens, true)
			args, _ := json.Marshal(core.Object{"marker": id})
			patch := func(item core.Object) {
				if item["type"] == "function_call" {
					item["name"] = "probe"
					item["namespace"] = "mcp__reflow_fixture"
					item["arguments"] = string(args)
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
		} else {
			input, _ := body["input"].([]any)
			for _, value := range input {
				item, ok := value.(map[string]any)
				if !ok {
					continue
				}
				if item["type"] == "function_call_output" && item["call_id"] == "chosen-call" {
					out, _ := json.Marshal(item["output"])
					mu.Lock()
					toolSeen = strings.Contains(string(out), "REFLOW_TOOL_OK")
					mu.Unlock()
				}
			}
			events = testfixture.Round("finish", 20, false)
			for _, ev := range events {
				if item, ok := ev["item"].(map[string]any); ok && item["type"] == "message" {
					item["content"] = []any{core.Object{"type": "output_text", "text": "REFLOW_NATIVE_OK", "annotations": []any{}}}
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
	proxyURL := startProxy(t, upstream.URL+"/backend-api/codex")
	ctx, cancel := context.WithTimeout(context.Background(), 35*time.Second)
	defer cancel()
	args := []string{"exec", "--ignore-user-config", "--ignore-rules", "--skip-git-repo-check", "--ephemeral", "--json", "-s", "read-only", "-C", work, "-m", "gpt-6.1-sol",
		"-c", "cli_auth_credentials_store=\"file\"", "-c", "openai_base_url=\"" + proxyURL + "\"", "-c", "chatgpt_base_url=\"" + upstream.URL + "\"",
		"-c", "features.memories=false", "-c", "features.apps=false", "-c", "features.code_mode=false", "-c", "model_reasoning_effort=\"low\"",
		"-c", "mcp_servers.reflow_fixture.url=\"" + mcp.URL + "\"",
		"-c", "mcp_servers.reflow_fixture.tools.probe.approval_mode=\"approve\"",
		"Synthetic local protocol test. Use the read-only fixture tool and report its final marker."}
	cmd := exec.CommandContext(ctx, bin, args...)
	cmd.Dir = work
	for _, name := range []string{"PATH", "SystemRoot", "WINDIR", "COMSPEC", "PATHEXT", "ProgramData"} {
		if value := os.Getenv(name); value != "" {
			cmd.Env = append(cmd.Env, name+"="+value)
		}
	}
	cmd.Env = append(cmd.Env, "CODEX_HOME="+home, "USERPROFILE="+base, "APPDATA="+filepath.Join(base, "appdata"), "LOCALAPPDATA="+filepath.Join(base, "localappdata"), "TEMP="+filepath.Join(base, "temp"), "TMP="+filepath.Join(base, "temp"), "NO_PROXY=127.0.0.1,localhost", "RUST_LOG=warn")
	out, err := cmd.CombinedOutput()
	mu.Lock()
	defer mu.Unlock()
	if err != nil || calls != 3 || !authSeen || !toolSeen || chosenTools != 1 || discardedTools != 0 || wsCalls < 3 || httpCalls != 0 || !strings.Contains(string(out), "REFLOW_NATIVE_OK") || strings.Contains(string(out), "falling back to HTTP") {
		text := strings.ReplaceAll(string(out), jwt, "[synthetic token]")
		if len(text) > 7000 {
			text = text[len(text)-7000:]
		}
		t.Fatalf("native CLI err=%v calls=%d WS=%d HTTP=%d auth=%t tool=%t chosen=%d discarded=%d paths=%v output=%s", err, calls, wsCalls, httpCalls, authSeen, toolSeen, chosenTools, discardedTools, paths, text)
	}
	t.Logf("installed CLI: 3 synthetic inference calls via WebSocket, 1 real read-only MCP invocation, discarded call not executed, result returned; no HTTP fallback")
	stats := proxyMetrics(t, proxyURL)
	if stats.Requests != 3 || stats.Continuations != 1 || stats.InputTokens != 300 || stats.OutputTokens != 586 || !stats.UsageComplete {
		t.Fatalf("native CLI upstream accounting mismatch: %+v", stats)
	}
}
