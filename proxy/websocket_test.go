package proxy

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/chatwithgod/reflow/core"
	"github.com/chatwithgod/reflow/internal/testfixture"
	"github.com/coder/websocket"
)

func wsSend(t *testing.T, ctx context.Context, c *websocket.Conn, event core.Object) {
	t.Helper()
	b, _ := json.Marshal(event)
	if err := c.Write(ctx, websocket.MessageText, b); err != nil {
		t.Fatal(err)
	}
}
func wsRead(t *testing.T, ctx context.Context, c *websocket.Conn) core.Object {
	t.Helper()
	_, b, err := c.Read(ctx)
	if err != nil {
		t.Fatal(err)
	}
	var ev core.Object
	if json.Unmarshal(b, &ev) != nil {
		t.Fatal("invalid JSON")
	}
	return ev
}

func TestWebSocketWarmupFoldAndFollowingToolResult(t *testing.T) {
	var mu sync.Mutex
	var requests []core.Object
	url, _ := harness(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		c, err := websocket.Accept(w, r, nil)
		if err != nil {
			return
		}
		defer c.CloseNow()
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		for {
			_, b, err := c.Read(ctx)
			if err != nil {
				return
			}
			var body core.Object
			if json.Unmarshal(b, &body) != nil {
				return
			}
			mu.Lock()
			requests = append(requests, body)
			n := len(requests)
			mu.Unlock()
			var events []core.Object
			switch n {
			case 1:
				events = []core.Object{{"type": "response.completed", "response": core.Object{"id": "warmup", "status": "completed", "output": []any{}}}}
			case 2:
				events = testfixture.Round("first", 516, true)
			case 3:
				events = testfixture.Round("last", 20, true)
			case 4:
				events = testfixture.Round("followup", 20, false)
			default:
				t.Error("unexpected upstream request")
				return
			}
			for _, ev := range events {
				b, _ := json.Marshal(ev)
				if c.Write(ctx, websocket.MessageText, b) != nil {
					return
				}
			}
		}
	}), true)
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	defer cancel()
	c, _, err := websocket.Dial(ctx, "ws"+strings.TrimPrefix(url, "http")+"/responses", &websocket.DialOptions{HTTPHeader: http.Header{"Authorization": []string{"Bearer synthetic-only"}}})
	if err != nil {
		t.Fatal(err)
	}
	defer c.CloseNow()
	wsSend(t, ctx, c, core.Object{"type": "response.create", "generate": false, "model": "gpt-6.1-sol", "input": []any{}, "tools": []any{core.Object{"type": "function", "name": "inspect"}}})
	if wsRead(t, ctx, c)["response"].(map[string]any)["id"] != "warmup" {
		t.Fatal("warmup lost")
	}
	wsSend(t, ctx, c, core.Object{"type": "response.create", "model": "gpt-6.1-sol", "previous_response_id": "warmup", "input": []any{core.Object{"role": "user", "content": "synthetic task"}}})
	var events []core.Object
	for {
		ev := wsRead(t, ctx, c)
		events = append(events, ev)
		if ev["type"] == "response.completed" {
			break
		}
	}
	all, _ := json.Marshal(events)
	if strings.Contains(string(all), "first-call") || !strings.Contains(string(all), "last-call") {
		t.Fatalf("tool visibility=%s", all)
	}
	if events[len(events)-1]["response"].(map[string]any)["id"] != "first" {
		t.Fatal("visible id changed")
	}
	wsSend(t, ctx, c, core.Object{"type": "response.create", "model": "gpt-6.1-sol", "previous_response_id": "first", "input": []any{core.Object{"type": "function_call_output", "call_id": "last-call", "output": "synthetic result"}}})
	for {
		if wsRead(t, ctx, c)["type"] == "response.completed" {
			break
		}
	}
	mu.Lock()
	defer mu.Unlock()
	if len(requests) != 4 {
		t.Fatalf("request count=%d", len(requests))
	}
	if requests[0]["generate"] != false || len(requests[0]["input"].([]any)) != 0 {
		t.Fatal("warmup changed")
	}
	if requests[2]["previous_response_id"] != nil || len(requests[2]["input"].([]any)) != 3 {
		t.Fatalf("replay=%v", requests[2])
	}
	if len(requests[2]["tools"].([]any)) != 1 {
		t.Fatal("warmup tools not inherited")
	}
	if requests[3]["previous_response_id"] != "last" {
		t.Fatal("next tool reply has stale parent")
	}
	if m := readMetrics(t, url); m.ContinuedToolResponses != 1 || m.ContinuedToolCalls != 1 || m.ContinuedToolResults != 1 || m.ToolTrackingDrops != 0 {
		t.Fatalf("WebSocket tool result was not correlated: %+v", m)
	}
}

func TestWebSocketConcurrentLanes(t *testing.T) {
	url, _ := harness(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		c, err := websocket.Accept(w, r, nil)
		if err != nil {
			return
		}
		defer c.CloseNow()
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		counts := map[string]int{}
		for {
			_, b, err := c.Read(ctx)
			if err != nil {
				return
			}
			var body core.Object
			json.Unmarshal(b, &body)
			id := body["stream_id"].(string)
			counts[id]++
			n := counts[id]
			tokens := 20
			if id == "a" && n == 1 {
				tokens = 516
			}
			for _, ev := range testfixture.Round(id+string(rune('0'+n)), tokens, true) {
				ev["stream_id"] = id
				b, _ := json.Marshal(ev)
				if c.Write(ctx, websocket.MessageText, b) != nil {
					return
				}
			}
		}
	}))
	ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
	defer cancel()
	c, _, err := websocket.Dial(ctx, "ws"+strings.TrimPrefix(url, "http")+"/responses", &websocket.DialOptions{HTTPHeader: http.Header{"Authorization": []string{"Bearer synthetic-only"}}})
	if err != nil {
		t.Fatal(err)
	}
	defer c.CloseNow()
	for _, id := range []string{"a", "b"} {
		wsSend(t, ctx, c, core.Object{"type": "response.create", "stream_id": id, "model": "gpt-6.1-sol", "input": []any{}})
	}
	final := map[string]core.Object{}
	seq := map[string]int{}
	for len(final) < 2 {
		ev := wsRead(t, ctx, c)
		id := ev["stream_id"].(string)
		if int(ev["sequence_number"].(float64)) != seq[id] {
			t.Fatal("lane sequence mixed")
		}
		seq[id]++
		if ev["type"] == "response.completed" {
			final[id] = ev
		}
	}
	for _, id := range []string{"a", "b"} {
		if final[id]["response"].(map[string]any)["id"] != id+"1" {
			t.Fatal("lane identity mixed")
		}
	}
}
