package control

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestMCPPreviewConnectRestoreAndNoModelRequests(t *testing.T) {
	requests := 0
	service := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		requests++
		if r.URL.Path != "/healthz" {
			t.Error("diagnostics called inference")
		}
		io.WriteString(w, `{"service":"reflow","status":"ready","version":"synthetic","max_continue":3}`)
	}))
	defer service.Close()
	home := t.TempDir()
	c := Controller{Home: home, Endpoint: service.URL}
	var in, out bytes.Buffer
	for _, req := range []map[string]any{
		{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": map[string]any{"protocolVersion": "2025-06-18"}},
		{"jsonrpc": "2.0", "method": "notifications/initialized"},
		{"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
		{"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": map[string]any{"name": "preview_codex_config", "arguments": map[string]any{}}},
		{"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": map[string]any{"name": "connect_codex", "arguments": map[string]any{}}},
		{"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": map[string]any{"name": "status", "arguments": map[string]any{}}},
		{"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": map[string]any{"name": "restore_codex_config", "arguments": map[string]any{}}},
	} {
		json.NewEncoder(&in).Encode(req)
	}
	if err := c.ServeMCP(context.Background(), &in, &out); err != nil {
		t.Fatal(err)
	}
	decoder := json.NewDecoder(&out)
	responses := 0
	for decoder.More() {
		var response map[string]any
		if err := decoder.Decode(&response); err != nil {
			t.Fatal(err)
		}
		responses++
		if result, ok := response["result"].(map[string]any); ok && result["isError"] == true {
			t.Fatalf("MCP tool failed: %v", result)
		}
	}
	if responses != 6 || requests != 2 {
		t.Fatalf("responses=%d HTTP requests=%d", responses, requests)
	}
	if _, err := os.Stat(filepath.Join(home, "config.toml")); !os.IsNotExist(err) {
		t.Fatal("restore did not remove owned empty config")
	}
}

func TestStatusRejectsRedirectAndWrongService(t *testing.T) {
	outside := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { t.Error("followed a diagnostics redirect") }))
	defer outside.Close()
	service := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.Redirect(w, r, outside.URL, 302) }))
	defer service.Close()
	c := Controller{Home: t.TempDir(), Endpoint: service.URL}
	status, err := c.Status(context.Background(), "")
	if err != nil || status.Ready {
		t.Fatal("redirect accepted as Reflow")
	}
	if _, err := c.Connect(context.Background(), ""); err == nil {
		t.Fatal("connected without a ready service")
	}
	if _, err := os.Stat(filepath.Join(c.Home, "config.toml")); !os.IsNotExist(err) {
		t.Fatal("failed health check wrote configuration")
	}
}

func TestMCPDoesNotAcceptArbitraryHomeOrRemoteEndpoints(t *testing.T) {
	c := Controller{Home: t.TempDir()}
	for _, args := range []string{`{"home":"somewhere-else"}`, `{"endpoint":"https://example.invalid"}`, `{"endpoint":"http://u:secret@localhost:1"}`} {
		_, err := c.call(context.Background(), "preview_codex_config", json.RawMessage(args))
		if err == nil {
			t.Fatal("unsafe argument accepted")
		}
		if strings.Contains(err.Error(), "secret") {
			t.Fatal("argument echoed secret")
		}
	}
}

func TestPluginHomeUsesOwningProfileAndRejectsUnknownLayout(t *testing.T) {
	t.Setenv("REFLOW_CODEX_HOME", "")
	t.Setenv("CODEX_HOME", "")
	home := t.TempDir()
	root := filepath.Join(home, "plugins", "cache", "reflow-local", "reflow", "0.1.0-test")
	if err := os.MkdirAll(root, 0700); err != nil {
		t.Fatal(err)
	}
	t.Setenv("PLUGIN_ROOT", root)
	got, err := DefaultHome()
	if err != nil {
		t.Fatal(err)
	}
	// Discovery resolves links and Windows short names; compare the owning
	// directory rather than platform-dependent spellings of that directory.
	wantInfo, err := os.Stat(home)
	if err != nil {
		t.Fatal(err)
	}
	gotInfo, err := os.Stat(got)
	if err != nil || !os.SameFile(wantInfo, gotInfo) {
		t.Fatalf("home=%q want=%q err=%v", got, home, err)
	}
	t.Setenv("PLUGIN_ROOT", t.TempDir())
	if _, err := DefaultHome(); err == nil {
		t.Fatal("unknown plugin location silently fell back to another profile")
	}
	t.Setenv("REFLOW_CODEX_HOME", home)
	if got, err := DefaultHome(); err != nil || got != home {
		t.Fatal("explicit home did not override plugin discovery")
	}
}
