package integration

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/chatwithgod/reflow/core"
	"github.com/chatwithgod/reflow/internal/testfixture"
	"github.com/coder/websocket"
)

func isolatedCLIEnv(base, home string) []string {
	var env []string
	for _, key := range []string{"PATH", "SystemRoot", "SystemDrive", "WINDIR", "COMSPEC", "PATHEXT", "ProgramData"} {
		if value := os.Getenv(key); value != "" {
			env = append(env, key+"="+value)
		}
	}
	return append(env, "CODEX_HOME="+home, "REFLOW_CODEX_HOME="+home, "HOME="+base, "USERPROFILE="+base, "APPDATA="+filepath.Join(base, "appdata"), "LOCALAPPDATA="+filepath.Join(base, "localappdata"), "TEMP="+filepath.Join(base, "temp"), "TMP="+filepath.Join(base, "temp"), "TMPDIR="+filepath.Join(base, "temp"), "NO_PROXY=127.0.0.1,localhost", "RUST_LOG=error")
}

func TestCodexPluginInstallAndStdioOffline(t *testing.T) {
	cli, market := os.Getenv("REFLOW_CODEX_BIN"), os.Getenv("REFLOW_PLUGIN_MARKETPLACE")
	if cli == "" || market == "" {
		t.Skip("set REFLOW_CODEX_BIN and REFLOW_PLUGIN_MARKETPLACE for isolated plugin installation")
	}
	base := t.TempDir()
	home := filepath.Join(base, "codex-home")
	work := filepath.Join(base, "workspace")
	for _, dir := range []string{home, work, filepath.Join(base, "appdata"), filepath.Join(base, "localappdata"), filepath.Join(base, "temp")} {
		if err := os.MkdirAll(dir, 0700); err != nil {
			t.Fatal(err)
		}
	}
	env := isolatedCLIEnv(base, home)
	cloud := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.Error(w, "synthetic cloud", 404) }))
	defer cloud.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()
	run := func(args ...string) []byte {
		t.Helper()
		all := append([]string{"-c", "cli_auth_credentials_store=\"file\"", "-c", "chatgpt_base_url=\"" + cloud.URL + "\""}, args...)
		cmd := exec.CommandContext(ctx, cli, all...)
		cmd.Env = env
		cmd.Dir = work
		out, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("plugin command %v: %v\n%s", args, err, out)
		}
		return out
	}
	run("plugin", "marketplace", "add", market, "--json")
	out := run("plugin", "add", "reflow@reflow-local", "--json")
	if !bytes.Contains(out, []byte("reflow")) {
		t.Fatal("install did not identify Reflow")
	}
	listed := run("plugin", "list", "--json")
	if !bytes.Contains(listed, []byte("reflow-local")) {
		t.Fatal("plugin not listed after install")
	}
	var installed string
	_ = filepath.WalkDir(filepath.Join(home, "plugins", "cache"), func(path string, entry os.DirEntry, err error) error {
		if err != nil {
			return err
		}
		if entry.Name() == "plugin.json" {
			b, _ := os.ReadFile(path)
			var metadata map[string]any
			if json.Unmarshal(b, &metadata) == nil && metadata["name"] == "reflow" {
				installed = filepath.Dir(path)
			}
		}
		return nil
	})
	if installed == "" {
		t.Fatalf("native install did not create an isolated cache copy: %s", out)
	}
	b, err := os.ReadFile(filepath.Join(installed, "mcp.json"))
	if err != nil {
		t.Fatal(err)
	}
	var definition struct {
		Servers map[string]struct {
			Command string   `json:"command"`
			Args    []string `json:"args"`
		} `json:"mcpServers"`
	}
	if json.Unmarshal(b, &definition) != nil {
		t.Fatal("invalid installed MCP definition")
	}
	server := definition.Servers["reflow"]
	binary := strings.ReplaceAll(server.Command, "${PLUGIN_ROOT}", installed)
	if strings.HasPrefix(binary, "./") {
		binary = filepath.Join(installed, filepath.FromSlash(strings.TrimPrefix(binary, "./")))
	}
	if _, err := os.Stat(binary); err != nil {
		t.Fatal("installed binary is missing")
	}
	var healthRequests atomic.Int32
	service := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		healthRequests.Add(1)
		if r.URL.Path != "/healthz" {
			t.Error("MCP requested a model")
		}
		io.WriteString(w, `{"service":"reflow","status":"ready","version":"synthetic-plugin-target"}`)
	}))
	defer service.Close()
	before, err := os.ReadFile(filepath.Join(home, "config.toml"))
	if err != nil {
		t.Fatal(err)
	}
	var input bytes.Buffer
	for i, name := range []string{"status", "preview_codex_config", "connect_codex", "restore_codex_config"} {
		json.NewEncoder(&input).Encode(map[string]any{"jsonrpc": "2.0", "id": i + 1, "method": "tools/call", "params": map[string]any{"name": name, "arguments": map[string]any{}}})
	}
	args := append(append([]string{}, server.Args...), "--codex-home", home, "--endpoint", service.URL)
	cmd := exec.CommandContext(ctx, binary, args...)
	cmd.Env = env
	cmd.Dir = work
	cmd.Stdin = &input
	out, err = cmd.Output()
	if err != nil {
		t.Fatalf("installed stdio command: %v", err)
	}
	decoder := json.NewDecoder(bytes.NewReader(out))
	count := 0
	for decoder.More() {
		var response map[string]any
		if decoder.Decode(&response) != nil {
			t.Fatal("invalid JSON-RPC output")
		}
		result, ok := response["result"].(map[string]any)
		if !ok || result["isError"] == true {
			t.Fatalf("installed tool failed: %v", response)
		}
		count++
	}
	if count != 4 {
		t.Fatalf("tool response count=%d", count)
	}
	after, _ := os.ReadFile(filepath.Join(home, "config.toml"))
	if !bytes.Equal(before, after) {
		t.Fatal("configuration restore changed native plugin settings")
	}
	verifyNativePluginInvocation(t, cli, home, work, env, service.URL)
	if n := healthRequests.Load(); n != 3 {
		t.Fatalf("expected two direct health reads and one native plugin read; got %d", n)
	}
	t.Log("native plugin install/cache/stdio, four tools and actual Codex plugin invocation passed")
}

// The direct stdio check alone does not prove Codex discovered the plugin. This
// sends a tool call through the actual CLI and verifies its returned data.
func verifyNativePluginInvocation(t *testing.T, cli, home, work string, env []string, serviceURL string) {
	t.Helper()
	jwt := syntheticJWT(core.Object{"exp": time.Now().Add(time.Hour).Unix(), "email": "synthetic@example.invalid", "https://api.openai.com/auth": core.Object{"chatgpt_account_id": "synthetic-plugin-account", "chatgpt_user_id": "synthetic-user", "chatgpt_plan_type": "pro"}})
	auth, _ := json.Marshal(core.Object{"auth_mode": "chatgpt", "tokens": core.Object{"id_token": jwt, "access_token": jwt, "refresh_token": "synthetic-refresh", "account_id": "synthetic-plugin-account"}, "last_refresh": time.Now().UTC().Format(time.RFC3339)})
	if err := os.WriteFile(filepath.Join(home, "auth.json"), auth, 0600); err != nil {
		t.Fatal(err)
	}
	// App-server-backed exec discovers workspace routing before permitting an
	// independent ChatGPT-auth provider URL. Use its real contract on local TLS.
	cloud, caPath := testfixture.LocalTLS(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		if strings.Contains(r.URL.Path, "/accounts/check") {
			io.WriteString(w, `{"accounts":[{"id":"synthetic-plugin-account","plan_type":"pro","workspace_backend_origin":"NO_CONSTRAINT","account_routing_override":"NO_CONSTRAINT"}]}`)
			return
		}
		http.Error(w, "synthetic cloud endpoint", 404)
	}))
	defer cloud.Close()
	env = append(append([]string{}, env...), "CODEX_CA_CERTIFICATE="+caPath)
	for i, value := range env {
		if strings.HasPrefix(value, "RUST_LOG=") {
			env[i] = "RUST_LOG=warn,codex_core_plugins=debug,codex_mcp=debug,codex_rmcp_client=debug"
		}
	}
	var mu sync.Mutex
	var calls int
	var returned bool
	respond := func(body core.Object) []core.Object {
		if body["generate"] == false {
			return []core.Object{{"type": "response.completed", "response": core.Object{"id": "warmup", "status": "completed", "output": []any{}}}}
		}
		mu.Lock()
		defer mu.Unlock()
		calls++
		if calls == 1 {
			events := testfixture.Round("plugin-status", 20, true)
			args, _ := json.Marshal(core.Object{"endpoint": serviceURL})
			for _, event := range events {
				if item, ok := event["item"].(map[string]any); ok && item["type"] == "function_call" {
					item["type"], item["name"], item["namespace"], item["input"] = "custom_tool_call", "exec", "functions", "const spec=ALL_TOOLS.find(x=>x.name.includes('reflow')&&x.name.endsWith('status')); if(!spec) throw new Error('Reflow status unavailable; tools='+ALL_TOOLS.map(x=>x.name).join(',')); text(await tools[spec.name]("+string(args)+"));"
					delete(item, "arguments")
				}
			}
			return events
		}
		if input, ok := body["input"].([]any); ok {
			for _, value := range input {
				item, ok := value.(map[string]any)
				if !ok || (item["type"] != "function_call_output" && item["type"] != "custom_tool_call_output") || item["call_id"] != "plugin-status-call" {
					continue
				}
				status := findNativePluginStatus(item["output"])
				routing, _ := status["routing"].(map[string]any)
				returned = status["ready"] == true && status["version"] == "synthetic-plugin-target" && routing["config_path"] == filepath.Join(home, "config.toml")
				if !returned {
					raw, _ := json.Marshal(item["output"])
					t.Logf("native plugin status did not return expected health: %.1500s", raw)
				}
			}
		}
		events := testfixture.Round("plugin-finish", 20, false)
		for _, event := range events {
			if item, ok := event["item"].(map[string]any); ok && item["type"] == "message" {
				item["content"] = []any{core.Object{"type": "output_text", "text": "REFLOW_PLUGIN_NATIVE_OK", "annotations": []any{}}}
			}
		}
		return events
	}
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if strings.HasSuffix(r.URL.Path, "/models") {
			w.Header().Set("Content-Type", "application/json")
			io.WriteString(w, `{"models":[]}`)
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
			conn.SetReadLimit(16 << 20)
			ctx, cancel := context.WithTimeout(context.Background(), 25*time.Second)
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
				for _, ev := range respond(body) {
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
		var body core.Object
		if json.NewDecoder(r.Body).Decode(&body) != nil {
			http.Error(w, "invalid synthetic JSON", 400)
			return
		}
		testfixture.WriteSSE(w, respond(body))
	}))
	defer upstream.Close()
	ctx, cancel := context.WithTimeout(context.Background(), 25*time.Second)
	defer cancel()
	args := []string{"exec", "--ignore-rules", "--skip-git-repo-check", "--ephemeral", "--json", "-s", "read-only", "-C", work, "-m", "gpt-6.1-sol",
		"-c", "cli_auth_credentials_store=\"file\"", "-c", "openai_base_url=\"" + upstream.URL + "/backend-api/codex\"", "-c", "chatgpt_base_url=\"" + cloud.URL + "\"",
		"-c", "features.memories=false", "-c", "features.apps=false", "-c", "features.code_mode=false", "-c", "model_reasoning_effort=\"low\"",
		"-c", "features.multi_agent=false", "-c", "features.multi_agent_v2=false",
		"-c", "features.plugins=true",
		"Use the installed Reflow plugin to check the supplied local fixture status, without changing any configuration."}
	cmd := exec.CommandContext(ctx, cli, args...)
	cmd.Env = env
	cmd.Dir = work
	out, err := cmd.CombinedOutput()
	mu.Lock()
	defer mu.Unlock()
	if err != nil || calls != 2 || !returned || !strings.Contains(string(out), "REFLOW_PLUGIN_NATIVE_OK") {
		if len(out) > 5000 {
			out = out[len(out)-5000:]
		}
		t.Fatalf("native plugin invocation err=%v calls=%d returned=%t output=%s", err, calls, returned, out)
	}
}

func findNativePluginStatus(value any) map[string]any {
	switch value := value.(type) {
	case map[string]any:
		if _, ok := value["ready"].(bool); ok {
			return value
		}
		for _, child := range value {
			if status := findNativePluginStatus(child); status != nil {
				return status
			}
		}
	case []any:
		for _, child := range value {
			if status := findNativePluginStatus(child); status != nil {
				return status
			}
		}
	case string:
		var decoded any
		if json.Unmarshal([]byte(value), &decoded) == nil {
			if _, same := decoded.(string); !same {
				return findNativePluginStatus(decoded)
			}
		}
	}
	return nil
}
