package proxy

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"
	"sync/atomic"
	"testing"
	"time"

	"github.com/chatwithgod/reflow/core"
	"github.com/chatwithgod/reflow/internal/testfixture"
	"github.com/coder/websocket"
)

func TestWebSocketDisconnectCancelsUpstream(t *testing.T) {
	disconnected := make(chan struct{})
	url, _ := harness(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		up, err := websocket.Accept(w, r, nil)
		if err != nil {
			return
		}
		defer up.CloseNow()
		ctx, cancel := context.WithTimeout(context.Background(), 4*time.Second)
		defer cancel()
		if _, _, err := up.Read(ctx); err != nil {
			return
		}
		b, _ := json.Marshal(core.Object{"type": "response.created", "response": core.Object{"id": "pending"}})
		if up.Write(ctx, websocket.MessageText, b) != nil {
			return
		}
		if _, _, err := up.Read(ctx); err != nil {
			close(disconnected)
		}
	}))
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	down, _, err := websocket.Dial(ctx, "ws"+strings.TrimPrefix(url, "http")+"/responses", &websocket.DialOptions{HTTPHeader: http.Header{"Authorization": []string{"Bearer synthetic"}}})
	if err != nil {
		t.Fatal(err)
	}
	wsSend(t, ctx, down, core.Object{"type": "response.create", "model": "gpt-6.1-sol", "input": []any{}})
	_ = wsRead(t, ctx, down)
	down.CloseNow()
	select {
	case <-disconnected:
	case <-ctx.Done():
		t.Fatal("upstream survived client disconnect")
	}
}

func TestWebSocketCancelHiddenRoundAndContinueSameSocket(t *testing.T) {
	for _, kind := range []string{"response.cancel", "response.interrupt", "interrupt_rejected"} {
		t.Run(kind, func(t *testing.T) { testWebSocketCancellation(t, kind) })
	}
}

func testWebSocketCancellation(t *testing.T, kind string) {
	rejected := kind == "interrupt_rejected"
	if rejected {
		kind = "response.interrupt"
	}
	var requests atomic.Int32
	cancelID := make(chan string, 1)
	url, _ := harness(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		up, err := websocket.Accept(w, r, nil)
		if err != nil {
			return
		}
		defer up.CloseNow()
		ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
		defer cancel()
		for {
			_, b, err := up.Read(ctx)
			if err != nil {
				return
			}
			var body core.Object
			json.Unmarshal(b, &body)
			var events []core.Object
			if body["type"] == kind {
				id, _ := body["response_id"].(string)
				cancelID <- id
				events = []core.Object{{"type": "response.incomplete", "response": core.Object{"id": "hidden", "status": "incomplete", "output": []any{}}}}
				if kind == "response.interrupt" {
					if body["mode"] != "discard_partial_items" {
						t.Error("interrupt mode changed")
					}
					ack := "response.interrupt.accepted"
					if rejected {
						ack = "response.interrupt.failed"
						events = testfixture.Round("hidden", 20, true)[2:]
					}
					events = append([]core.Object{{"type": ack, "response_id": id}}, events...)
				}
			} else {
				switch requests.Add(1) {
				case 1:
					events = testfixture.Round("visible", 516, true)
				case 2:
					events = testfixture.Round("hidden", 20, true)[:2]
				case 3:
					events = testfixture.Round("after", 20, false)
				default:
					t.Error("extra generation after cancel")
					return
				}
			}
			for _, ev := range events {
				data, _ := json.Marshal(ev)
				if up.Write(ctx, websocket.MessageText, data) != nil {
					return
				}
			}
		}
	}), true)
	ctx, cancel := context.WithTimeout(context.Background(), 4*time.Second)
	defer cancel()
	down, _, err := websocket.Dial(ctx, "ws"+strings.TrimPrefix(url, "http")+"/responses", &websocket.DialOptions{HTTPHeader: http.Header{"Authorization": []string{"Bearer synthetic"}}})
	if err != nil {
		t.Fatal(err)
	}
	defer down.CloseNow()
	wsSend(t, ctx, down, core.Object{"type": "response.create", "model": "gpt-6.1-sol", "input": []any{}})
	for {
		ev := wsRead(t, ctx, down)
		if item, ok := ev["item"].(map[string]any); ok && item["id"] == "hidden-reason" {
			break
		}
	}
	wsSend(t, ctx, down, core.Object{"type": kind, "response_id": "visible", "mode": "discard_partial_items"})
	ev := wsRead(t, ctx, down)
	if kind == "response.interrupt" {
		ack := "response.interrupt.accepted"
		if rejected {
			ack = "response.interrupt.failed"
		}
		if ev["type"] != ack || ev["response_id"] != "visible" {
			t.Fatal("interrupt acknowledgement lost visible identity")
		}
		ev = wsRead(t, ctx, down)
	}
	if rejected {
		for ev["type"] != "response.completed" && ev["type"] != "response.incomplete" {
			ev = wsRead(t, ctx, down)
		}
		if ev["type"] != "response.completed" {
			t.Fatal("rejected interrupt canceled the active turn")
		}
	} else if ev["type"] != "response.incomplete" || ev["response"].(map[string]any)["id"] != "visible" {
		t.Fatal("cancel terminal identity lost")
	}
	if kind == "response.interrupt" && !rejected {
		response := ev["response"].(map[string]any)
		details, _ := response["incomplete_details"].(map[string]any)
		if details["reason"] != "interrupted" || len(response["output"].([]any)) != 0 {
			t.Fatal("interrupt did not discard partial output with the native reason")
		}
	}
	if id := <-cancelID; id != "hidden" {
		t.Fatal("cancel did not target active upstream attempt")
	}
	wsSend(t, ctx, down, core.Object{"type": "response.create", "model": "gpt-6.1-sol", "input": []any{}})
	for {
		ev := wsRead(t, ctx, down)
		if ev["type"] == "response.completed" {
			if ev["response"].(map[string]any)["id"] != "after" {
				t.Fatal("socket did not recover")
			}
			break
		}
	}
	if requests.Load() != 3 {
		t.Fatal("unexpected request count")
	}
	expectedTools := int64(0)
	if rejected {
		expectedTools = 1
	}
	if m := readMetrics(t, url); m.Continuations != 1 || m.ContinuedToolResponses != expectedTools || m.ContinuedToolResults != 0 {
		t.Fatalf("canceled continuation counted as a tool return: %+v", m)
	}
}

func TestWebSocketMissingParentPreservesNativeRecoveryCode(t *testing.T) {
	var calls atomic.Int32
	url, _ := harness(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		up, err := websocket.Accept(w, r, nil)
		if err != nil {
			return
		}
		defer up.CloseNow()
		ctx, cancel := context.WithTimeout(context.Background(), 4*time.Second)
		defer cancel()
		for {
			_, b, err := up.Read(ctx)
			if err != nil {
				return
			}
			var body core.Object
			json.Unmarshal(b, &body)
			n := calls.Add(1)
			events := testfixture.Round("recovered", 20, false)
			if n == 1 {
				events = []core.Object{{"type": "error", "error": core.Object{"code": "previous_response_not_found", "message": "synthetic missing parent"}}}
			} else if body["previous_response_id"] != nil {
				t.Error("full replay still has stale parent")
			}
			for _, ev := range events {
				data, _ := json.Marshal(ev)
				if up.Write(ctx, websocket.MessageText, data) != nil {
					return
				}
			}
		}
	}))
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	down, _, err := websocket.Dial(ctx, "ws"+strings.TrimPrefix(url, "http")+"/responses", &websocket.DialOptions{HTTPHeader: http.Header{"Authorization": []string{"Bearer synthetic"}}})
	if err != nil {
		t.Fatal(err)
	}
	defer down.CloseNow()
	wsSend(t, ctx, down, core.Object{"type": "response.create", "model": "gpt-6.1-sol", "previous_response_id": "expired", "input": []any{}})
	ev := wsRead(t, ctx, down)
	if ev["type"] != "error" || ev["error"].(map[string]any)["code"] != "previous_response_not_found" {
		t.Fatal("native recovery code hidden")
	}
	wsSend(t, ctx, down, core.Object{"type": "response.create", "model": "gpt-6.1-sol", "input": []any{core.Object{"role": "user", "content": "full synthetic history"}}})
	for {
		ev := wsRead(t, ctx, down)
		if ev["type"] == "response.completed" {
			break
		}
	}
	if calls.Load() != 2 {
		t.Fatal("unexpected recovery attempts")
	}
}

func TestHTTPMissingParentPreservesNativeRecoveryCode(t *testing.T) {
	url, _ := harness(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		testfixture.WriteSSE(w, []core.Object{{"type": "error", "code": "previous_response_not_found"}})
	}))
	out := drain(t, request(t, context.Background(), url+"/responses", core.Object{"model": "gpt-6.1-sol", "stream": true, "previous_response_id": "expired", "input": []any{}}))
	if len(out) != 1 || out[0]["code"] != "previous_response_not_found" {
		t.Fatal("HTTP recovery code hidden")
	}
}

func TestReplayExpiryAndRollbackDoNotRestoreStaleAliases(t *testing.T) {
	c := NewReplayCache()
	r := core.Result{VisibleID: "v", UpstreamID: "old", ReplayRequest: core.Object{"model": "gpt-6.1-sol", "input": []any{}}}
	undo := c.Remember("scope", r)
	r.UpstreamID = "new"
	c.Remember("scope", r)
	undo()
	body := core.Object{"model": "gpt-6.1-sol", "previous_response_id": "v", "input": []any{}}
	wire, full := c.Resolve("scope", body)
	if full == nil || wire["previous_response_id"] != "new" {
		t.Fatal("rollback removed a newer alias")
	}
	c.entries["scope/v"].expires = time.Unix(0, 0)
	wire, full = c.Resolve("scope", body)
	if full != nil || wire["previous_response_id"] != "v" || c.bytes != 0 {
		t.Fatal("expired state reused")
	}
}
