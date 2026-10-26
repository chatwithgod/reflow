package magpie

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/chatwithgod/reflow/core"
	"github.com/chatwithgod/reflow/internal/testfixture"
)

func TestEmbeddedContinuationAndAccountScopedRecovery(t *testing.T) {
	e, err := New(core.DefaultConfig())
	if err != nil {
		t.Fatal(err)
	}
	var mu sync.Mutex
	var seen []core.Object
	send := func(_ context.Context, body []byte) (*http.Response, error) {
		var request core.Object
		if err := json.Unmarshal(body, &request); err != nil {
			return nil, err
		}
		mu.Lock()
		seen = append(seen, request)
		n := len(seen)
		mu.Unlock()
		id, tokens, tool := "discarded", 516, true
		if n == 2 {
			id, tokens = "chosen", 20
		}
		if n >= 3 {
			id, tokens, tool = "final", 20, false
		}
		recorder := httptest.NewRecorder()
		testfixture.WriteSSE(recorder, testfixture.Round(id, tokens, tool))
		return recorder.Result(), nil
	}
	execute := func(scope, body string) string {
		t.Helper()
		res, err := e.Execute(context.Background(), scope, []byte(body), send)
		if err != nil {
			t.Fatal(err)
		}
		out, err := io.ReadAll(res.Body)
		res.Body.Close()
		if err != nil {
			t.Fatal(err)
		}
		if res.StatusCode != 200 {
			t.Fatalf("unexpected status=%d", res.StatusCode)
		}
		return string(out)
	}
	out := execute("account-a", `{"model":"gpt-6","stream":true,"input":[{"role":"user","content":"synthetic task"}]}`)
	if strings.Contains(out, "discarded-call") || !strings.Contains(out, "chosen-call") {
		t.Fatal("intermediate tool leaked or final tool missing")
	}
	request := `{"model":"gpt-6","stream":true,"previous_response_id":"discarded","input":[{"type":"function_call_output","call_id":"chosen-call","output":"synthetic result"}]}`
	execute("account-a", request)
	execute("account-b", request)
	mu.Lock()
	defer mu.Unlock()
	if len(seen) != 4 || seen[2]["previous_response_id"] != nil || seen[3]["previous_response_id"] != "discarded" {
		t.Fatalf("scope or replay mismatch: requests=%d", len(seen))
	}
	replayed, _ := json.Marshal(seen[2]["input"])
	if !strings.Contains(string(replayed), "chosen-call") || !strings.Contains(string(replayed), "synthetic-discarded") || !strings.Contains(string(replayed), "synthetic result") {
		t.Fatal("complete history was not replayed on the host's new connection")
	}
}

func TestEmbeddedCloseCancelsHostAndJoinsWorker(t *testing.T) {
	e, err := New(core.DefaultConfig())
	if err != nil {
		t.Fatal(err)
	}
	closed := make(chan struct{})
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "text/event-stream")
		io.WriteString(w, "data: {\"type\":\"response.created\",\"response\":{\"id\":\"pending\",\"status\":\"in_progress\"}}\n\n")
		http.NewResponseController(w).Flush()
		<-r.Context().Done()
		close(closed)
	}))
	defer upstream.Close()
	send := func(ctx context.Context, body []byte) (*http.Response, error) {
		r, _ := http.NewRequestWithContext(ctx, http.MethodPost, upstream.URL, strings.NewReader(string(body)))
		return upstream.Client().Do(r)
	}
	res, err := e.Execute(context.Background(), "account-a", []byte(`{"model":"gpt-6","stream":true,"input":[]}`), send)
	if err != nil {
		t.Fatal(err)
	}
	res.Body.Close()
	select {
	case <-closed:
	case <-time.After(3 * time.Second):
		t.Fatal("host request survived closing the folded response")
	}
}
