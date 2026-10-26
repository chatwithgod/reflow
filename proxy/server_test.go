package proxy

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/chatwithgod/reflow/core"
	"github.com/chatwithgod/reflow/internal/testfixture"
)

func harness(t *testing.T, up http.Handler, metrics ...bool) (string, *Server) {
	t.Helper()
	upstream := httptest.NewServer(up)
	t.Cleanup(upstream.Close)
	s, err := New(Config{Upstream: upstream.URL + "/backend-api/codex", Fold: core.DefaultConfig(), EnableMetrics: len(metrics) > 0 && metrics[0]})
	if err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(s)
	t.Cleanup(server.Close)
	return server.URL, s
}

func request(t *testing.T, ctx context.Context, url string, body core.Object) *http.Response {
	t.Helper()
	b, _ := json.Marshal(body)
	req, err := http.NewRequestWithContext(ctx, "POST", url, bytes.NewReader(b))
	if err != nil {
		t.Fatal(err)
	}
	req.Header.Set("Authorization", "Bearer synthetic-only")
	req.Header.Set("ChatGPT-Account-ID", "synthetic-account")
	req.Header.Set("Content-Type", "application/json")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	return resp
}

func drain(t *testing.T, resp *http.Response) []core.Object {
	t.Helper()
	defer resp.Body.Close()
	r := core.NewReader(resp.Body)
	var out []core.Object
	for {
		ev, err := r.Next()
		if err == io.EOF {
			return out
		}
		if err != nil {
			t.Fatal(err)
		}
		out = append(out, ev)
	}
}

func TestHTTPFoldAndFollowingToolResult(t *testing.T) {
	var mu sync.Mutex
	var bodies []core.Object
	url, _ := harness(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/backend-api/codex/responses" || r.URL.Query().Get("client_version") != "synthetic" {
			t.Error("route lost")
		}
		if r.Header.Get("Authorization") != "Bearer synthetic-only" || r.Header.Get("ChatGPT-Account-ID") != "synthetic-account" {
			t.Error("credential path changed")
		}
		var body core.Object
		if json.NewDecoder(r.Body).Decode(&body) != nil {
			t.Error("body invalid")
			return
		}
		mu.Lock()
		bodies = append(bodies, body)
		n := len(bodies)
		mu.Unlock()
		switch n {
		case 1:
			testfixture.WriteSSE(w, testfixture.Round("first", 516, true))
		case 2:
			testfixture.WriteSSE(w, testfixture.Round("last", 20, true))
		case 3:
			testfixture.WriteSSE(w, testfixture.Round("followup", 20, false))
		default:
			t.Error("unexpected call")
		}
	}))
	body := core.Object{"model": "gpt-6.1-sol", "stream": true, "store": false, "input": []any{core.Object{"role": "user", "content": "synthetic task"}}, "tools": []any{}}
	out := drain(t, request(t, context.Background(), url+"/responses?client_version=synthetic", body))
	b, _ := json.Marshal(out)
	if strings.Contains(string(b), "first-call") || !strings.Contains(string(b), "last-call") {
		t.Fatal("tool visibility")
	}
	terminal := out[len(out)-1]["response"].(map[string]any)
	if terminal["id"] != "first" || terminal["status"] != "completed" {
		t.Fatal(terminal)
	}
	next := core.Object{"model": "gpt-6.1-sol", "stream": true, "previous_response_id": "first", "input": []any{core.Object{"type": "function_call_output", "call_id": "last-call", "output": "synthetic result"}}}
	_ = drain(t, request(t, context.Background(), url+"/responses?client_version=synthetic", next))
	mu.Lock()
	defer mu.Unlock()
	if len(bodies) != 3 || bodies[2]["previous_response_id"] != "last" {
		t.Fatalf("requests=%v", bodies)
	}
	if _, exists := bodies[1]["previous_response_id"]; exists {
		t.Fatal("continuation inherited wrong parent")
	}
	if len(bodies[1]["input"].([]any)) != 3 {
		t.Fatal("continuation replay missing reasoning/nudge")
	}
}

func TestPassthroughWarmupCompactAndModels(t *testing.T) {
	var calls atomic.Int32
	url, _ := harness(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		calls.Add(1)
		b, _ := io.ReadAll(r.Body)
		w.Header().Set("X-Synthetic", "kept")
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(201)
		if r.Method == http.MethodGet {
			io.WriteString(w, `{"models":[]}`)
		} else {
			w.Write(b)
		}
	}))
	for _, suffix := range []string{"/responses", "/responses/compact"} {
		body := core.Object{"generate": false, "stream": true, "input": []any{}, "model": "gpt-6.1-sol"}
		resp := request(t, context.Background(), url+suffix, body)
		b, _ := io.ReadAll(resp.Body)
		resp.Body.Close()
		if resp.StatusCode != 201 || resp.Header.Get("X-Synthetic") != "kept" || !strings.Contains(string(b), `"input":[]`) {
			t.Fatalf("passthrough=%s %v", b, resp.StatusCode)
		}
	}
	req, _ := http.NewRequest("GET", url+"/models?client_version=synthetic", nil)
	req.Header.Set("Authorization", "Bearer synthetic-only")
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if calls.Load() != 3 {
		t.Fatal("unexpected additional requests")
	}
}

func TestHTTPDisconnectCancelsUpstream(t *testing.T) {
	canceled := make(chan struct{})
	url, _ := harness(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		io.WriteString(w, "data: {\"type\":\"response.created\",\"response\":{\"id\":\"r\"}}\n\n")
		_ = http.NewResponseController(w).Flush()
		<-r.Context().Done()
		close(canceled)
	}))
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	resp := request(t, ctx, url+"/responses", core.Object{"model": "gpt-6.1-sol", "stream": true, "input": []any{}})
	_, err := core.NewReader(resp.Body).Next()
	if err != nil {
		t.Fatal(err)
	}
	cancel()
	resp.Body.Close()
	select {
	case <-canceled:
	case <-time.After(3 * time.Second):
		t.Fatal("upstream not canceled")
	}
}

func TestContinuationFailureIsIncomplete(t *testing.T) {
	var calls atomic.Int32
	url, _ := harness(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if calls.Add(1) == 1 {
			testfixture.WriteSSE(w, testfixture.Round("first", 516, true))
			return
		}
		http.Error(w, "synthetic private upstream error", 503)
	}))
	out := drain(t, request(t, context.Background(), url+"/responses", core.Object{"model": "gpt-6.1-sol", "stream": true, "input": []any{}}))
	b, _ := json.Marshal(out)
	if out[len(out)-1]["type"] != "response.incomplete" || strings.Contains(string(b), "first-call") || strings.Contains(string(b), "private upstream") {
		t.Fatalf("failure=%s", b)
	}
}

func TestNoCredentialRedirectAndOriginIsolation(t *testing.T) {
	var leaked atomic.Bool
	other := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { leaked.Store(true) }))
	defer other.Close()
	url, s := harness(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { http.Redirect(w, r, other.URL, 307) }))
	client := &http.Client{CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse }}
	req, _ := http.NewRequest("GET", url+"/models", nil)
	req.Header.Set("Authorization", "Bearer synthetic-only")
	resp, err := client.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	resp.Body.Close()
	if resp.StatusCode != 307 || leaked.Load() {
		t.Fatal("redirect followed with credentials")
	}
	for _, tc := range []struct{ peer, origin string }{{"198.51.100.2:22", ""}, {"127.0.0.1:22", "https://example.invalid"}} {
		req := httptest.NewRequest("GET", "http://localhost/healthz", nil)
		req.RemoteAddr = tc.peer
		req.Header.Set("Origin", tc.origin)
		w := httptest.NewRecorder()
		s.ServeHTTP(w, req)
		if w.Code != 403 {
			t.Fatal("untrusted client accepted")
		}
	}
}

func TestReplayCacheDoesNotMixCredentialsModelsOrLanes(t *testing.T) {
	c := NewReplayCache()
	c.Remember("A", core.Result{VisibleID: "visible", UpstreamID: "actual", ReplayRequest: core.Object{"model": "gpt-6.1-sol", "input": []any{"private-synthetic"}, "stream_id": "old", "generate": false}})
	body := core.Object{"model": "gpt-6.1-sol", "previous_response_id": "visible", "input": []any{}}
	wire, full := c.Resolve("B", body)
	if full != nil || wire["previous_response_id"] != "visible" {
		t.Fatal("cross-account replay")
	}
	body["model"] = "gpt-6-astra"
	_, full = c.Resolve("A", body)
	if full != nil {
		t.Fatal("cross-model replay")
	}
	body["model"] = "gpt-6.1-sol"
	_, full = c.Resolve("A", body)
	if full["stream_id"] != nil || full["generate"] != nil {
		t.Fatal("transport settings leaked from parent")
	}
}
