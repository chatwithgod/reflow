package proxy

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/chatwithgod/reflow/core"
	"github.com/chatwithgod/reflow/internal/testfixture"
	"github.com/coder/websocket"
)

func metricHarness(t *testing.T, up http.Handler, maximum int, enabled bool) string {
	t.Helper()
	upstream := httptest.NewServer(up)
	t.Cleanup(upstream.Close)
	config := core.DefaultConfig()
	config.MaxContinue = maximum
	handler, err := New(Config{Upstream: upstream.URL + "/backend-api/codex", Fold: config, EnableMetrics: enabled})
	if err != nil {
		t.Fatal(err)
	}
	server := httptest.NewServer(handler)
	t.Cleanup(server.Close)
	return server.URL
}

func readMetrics(t *testing.T, url string) Metrics {
	t.Helper()
	res, err := http.Get(url + "/metrics")
	if err != nil {
		t.Fatal(err)
	}
	defer res.Body.Close()
	raw, err := io.ReadAll(res.Body)
	if err != nil {
		t.Fatal(err)
	}
	for _, private := range []string{"synthetic-only", "synthetic-account", "private-first", "synthetic answer"} {
		if strings.Contains(string(raw), private) {
			t.Fatal("metrics retained a payload or credential")
		}
	}
	var stats Metrics
	if json.Unmarshal(raw, &stats) != nil {
		t.Fatal("invalid metrics JSON")
	}
	return stats
}

func TestHTTPMetricsCountUpstreamWhenFoldingOnAndOff(t *testing.T) {
	for _, maximum := range []int{0, 1} {
		t.Run(string(rune('0'+maximum)), func(t *testing.T) {
			var calls atomic.Int32
			url := metricHarness(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				tokens, id := 516, "private-first"
				if calls.Add(1) > 1 {
					tokens, id = 20, "private-last"
				}
				testfixture.WriteSSE(w, testfixture.Round(id, tokens, false))
			}), maximum, true)
			drain(t, request(t, context.Background(), url+"/responses", core.Object{"model": "gpt-6", "stream": true, "input": []any{}}))
			stats := readMetrics(t, url)
			want := int64(maximum + 1)
			if stats.Requests != want || stats.Continuations != int64(maximum) || stats.Completed != want || stats.InputTokens != 100*want || stats.OutputTokens != 526+30*int64(maximum) || !stats.UsageComplete {
				t.Fatalf("incorrect upstream totals: %+v", stats)
			}
		})
	}
}

func TestMetricsDisabledUnsupportedAndDuplicateTerminal(t *testing.T) {
	url := metricHarness(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		io.WriteString(w, `{"unsupported":true}`)
	}), 0, false)
	if readMetrics(t, url).Enabled {
		t.Fatal("metrics enabled without opting in")
	}
	url = metricHarness(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		io.WriteString(w, `{"unsupported":true}`)
	}), 0, true)
	res := request(t, context.Background(), url+"/responses", core.Object{"model": "gpt-6", "stream": true})
	io.Copy(io.Discard, res.Body)
	res.Body.Close()
	if m := readMetrics(t, url); m.UnsupportedResponses != 1 || m.UsageComplete {
		t.Fatal("unobserved usage reported as complete")
	}
	url = metricHarness(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		events := testfixture.Round("private-first", 20, false)
		testfixture.WriteSSE(w, append(events, events[len(events)-1]))
	}), 0, true)
	drain(t, request(t, context.Background(), url+"/responses", core.Object{"model": "gpt-6", "stream": true}))
	if m := readMetrics(t, url); m.UsageReports != 1 || m.InputTokens != 100 || !m.UsageComplete {
		t.Fatalf("duplicate terminal counted twice: %+v", m)
	}
}

func TestWebSocketMetricsExcludeWarmupAndCountHiddenRound(t *testing.T) {
	var calls atomic.Int32
	url := metricHarness(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := websocket.Accept(w, r, nil)
		if err != nil {
			return
		}
		defer conn.CloseNow()
		ctx, cancel := context.WithTimeout(r.Context(), 10*time.Second)
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
			var events []core.Object
			if body["generate"] == false {
				events = testfixture.Round("warmup", 999, false)
			} else {
				tokens, id := 516, "private-first"
				if calls.Add(1) > 1 {
					tokens, id = 20, "last"
				}
				events = testfixture.Round(id, tokens, false)
			}
			for _, event := range events {
				raw, _ := json.Marshal(event)
				if conn.Write(ctx, websocket.MessageText, raw) != nil {
					return
				}
			}
		}
	}), 1, true)
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	conn, _, err := websocket.Dial(ctx, "ws"+strings.TrimPrefix(url, "http")+"/responses", &websocket.DialOptions{HTTPHeader: http.Header{"Authorization": {"Bearer synthetic-only"}}})
	if err != nil {
		t.Fatal(err)
	}
	defer conn.CloseNow()
	for _, warmup := range []bool{true, false} {
		body := core.Object{"type": "response.create", "model": "gpt-6", "input": []any{}}
		if warmup {
			body["generate"] = false
		}
		wsSend(t, ctx, conn, body)
		for {
			event := wsRead(t, ctx, conn)
			if event["type"] == "response.completed" {
				break
			}
		}
	}
	stats := readMetrics(t, url)
	if stats.Requests != 2 || stats.Warmups != 1 || stats.Continuations != 1 || stats.InputTokens != 200 || stats.OutputTokens != 556 || !stats.UsageComplete {
		t.Fatalf("WS metrics mismatch: %+v", stats)
	}
}
