package proxy

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
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

func continuedTool(id, kind string) (core.Result, []core.Object, core.Object) {
	item := core.Object{"type": kind, "id": "item-" + id, "call_id": id, "name": "private-tool", "arguments": "PRIVATE_PAYLOAD"}
	events := []core.Object{{"type": "response.completed", "response": core.Object{"output": []core.Object{item}}}}
	result := core.Result{VisibleID: "private-parent", Status: "completed", Rounds: 2}
	return result, events, item
}

func toolReply(parent, kind, id string) core.Object {
	return core.Object{"model": "private-model", "previous_response_id": parent,
		"input": []any{core.Object{"type": kind + "_output", "call_id": id, "output": "PRIVATE_RESULT"}}}
}

func TestToolMetricsCorrelateScopeParentAndDelivery(t *testing.T) {
	for _, kind := range []string{"function_call", "custom_tool_call"} {
		t.Run(kind, func(t *testing.T) {
			store := &metricsStore{}
			result, events, _ := continuedTool("private-call", kind)
			finish := store.prepareTools("private-scope", "private-model", result, events)
			reply := toolReply("private-parent", kind, "private-call")
			store.toolResults("other-scope", reply)
			wrongModel, _ := core.Clone(reply)
			wrongModel["model"] = "other-model"
			store.toolResults("private-scope", wrongModel)
			store.toolResults("private-scope", toolReply("wrong-parent", kind, "private-call"))
			warmup, _ := core.Clone(reply)
			warmup["generate"] = false
			store.toolResults("private-scope", warmup)
			missingOutput, _ := core.Clone(reply)
			delete(missingOutput["input"].([]any)[0].(map[string]any), "output")
			store.toolResults("private-scope", missingOutput)
			if len(store.tools) != 1 || store.tools[toolDigest("private-scope", "private-model", kind, "private-call")].seen {
				t.Fatal("an unrelated request acknowledged the call")
			}
			store.toolResults("private-scope", reply)
			if m := store.snapshot(); m.ContinuedToolResponses != 0 || m.ContinuedToolResults != 0 {
				t.Fatal("provisional delivery was counted")
			}
			finish(true)
			finish(true)
			store.toolResults("private-scope", reply)
			m := store.snapshot()
			if m.ContinuedToolResponses != 1 || m.ContinuedToolCalls != 1 || m.ContinuedToolResults != 1 || m.ToolTrackingDrops != 0 || len(store.tools) != 0 {
				t.Fatalf("correlation or deduplication failed: %+v", m)
			}
			raw, _ := json.Marshal(m)
			for _, secret := range []string{"private-", "PRIVATE_PAYLOAD", "PRIVATE_RESULT"} {
				if strings.Contains(string(raw), secret) {
					t.Fatal("metric output retained private data")
				}
			}
		})
	}
}

func TestToolMetricsFullHistoryRollbackAndOrdinaryReplies(t *testing.T) {
	store := &metricsStore{}
	result, events, item := continuedTool("chosen-call", "function_call")
	finish := store.prepareTools("scope", "private-model", result, events)
	finish(false)
	store.toolResults("scope", toolReply("private-parent", "function_call", "chosen-call"))
	if m := store.snapshot(); m.ContinuedToolResults != 0 || m.ContinuedToolCalls != 0 || len(store.tools) != 0 {
		t.Fatal("failed delivery left successful observations")
	}
	result.Rounds = 1
	store.prepareTools("scope", "private-model", result, events)(true)
	result.Rounds, result.Status = 2, "incomplete"
	store.prepareTools("scope", "private-model", result, events)(true)
	if store.snapshot().ContinuedToolCalls != 0 {
		t.Fatal("ordinary or incomplete response counted as continued tools")
	}
	result.Status = "completed"
	store.prepareTools("scope", "private-model", result, events)(true)
	reply := toolReply("", "function_call", "chosen-call")
	store.toolResults("scope", reply)
	wrong, _ := core.Clone(item)
	wrong["id"] = "unrelated-item"
	output := reply["input"].([]any)[0]
	reply["input"] = []any{wrong, output}
	store.toolResults("scope", reply)
	reply["input"] = []any{output, item}
	store.toolResults("scope", reply)
	missingID, _ := core.Clone(item)
	delete(missingID, "id")
	reply["input"] = []any{item, missingID, output}
	store.toolResults("scope", reply)
	if store.snapshot().ContinuedToolResults != 0 {
		t.Fatal("ambiguous or out-of-order history was accepted")
	}
	reply["input"] = []any{item, output, output}
	store.toolResults("scope", reply)
	store.toolResults("scope", reply)
	if store.snapshot().ContinuedToolResults != 1 {
		t.Fatal("retained full-history item was not correlated exactly once")
	}
}

func TestToolMetricsBoundedRetentionAndExpiry(t *testing.T) {
	store := &metricsStore{}
	for i := 0; i <= maxPendingTools; i++ {
		result, events, _ := continuedTool(fmt.Sprintf("call-%d", i), "function_call")
		store.prepareTools("scope", "private-model", result, events)(true)
	}
	if len(store.tools) != maxPendingTools || store.snapshot().ToolTrackingDrops != 1 {
		t.Fatal("pending observations exceeded their bound")
	}
	for _, entry := range store.tools {
		entry.expires = time.Now().Add(-time.Second)
	}
	store.toolResults("scope", toolReply("private-parent", "function_call", "call-0"))
	if len(store.tools) != 0 || store.snapshot().ContinuedToolResults != 0 || store.snapshot().ToolTrackingDrops != maxPendingTools+1 {
		t.Fatal("expired tool IDs remained eligible")
	}
	var disabled *metricsStore
	result, events, _ := continuedTool("call", "function_call")
	disabled.prepareTools("scope", "private-model", result, events)(true)
	disabled.toolResults("scope", toolReply("private-parent", "function_call", "call"))
}

func TestToolMetricsAmbiguousBatchAndConcurrentResults(t *testing.T) {
	t.Run("oversized batch", func(t *testing.T) {
		store := &metricsStore{}
		result, events, _ := continuedTool("first", "function_call")
		output := make([]core.Object, maxPendingTools+1)
		for i := range output {
			_, _, output[i] = continuedTool(fmt.Sprintf("call-%d", i), "function_call")
		}
		events[0]["response"].(map[string]any)["output"] = output
		store.prepareTools("scope", "private-model", result, events)(true)
		if m := store.snapshot(); len(store.tools) != 0 || m.ContinuedToolCalls != maxPendingTools+1 || m.ToolTrackingDrops != maxPendingTools+1 {
			t.Fatalf("oversized batch was partially accepted: %+v", m)
		}
	})
	t.Run("call id collision", func(t *testing.T) {
		store := &metricsStore{}
		result, events, _ := continuedTool("call", "function_call")
		store.prepareTools("scope", "private-model", result, events)(true)
		result.VisibleID = "other-parent"
		store.prepareTools("scope", "private-model", result, events)(true)
		store.toolResults("scope", toolReply("other-parent", "function_call", "call"))
		if store.snapshot().ContinuedToolResults != 0 {
			t.Fatal("colliding parent acknowledged the original tool")
		}
		store.toolResults("scope", toolReply("private-parent", "function_call", "call"))
		if m := store.snapshot(); m.ContinuedToolCalls != 2 || m.ContinuedToolResults != 1 || m.ToolTrackingDrops != 1 || len(store.tools) != 0 {
			t.Fatalf("collision replaced the original pending call: %+v", m)
		}
	})
	t.Run("concurrent commit and result", func(t *testing.T) {
		store := &metricsStore{}
		var workers sync.WaitGroup
		for i := 0; i < 24; i++ {
			id := fmt.Sprintf("call-%d", i)
			result, events, _ := continuedTool(id, "function_call")
			finish := store.prepareTools("scope", "private-model", result, events)
			workers.Go(func() { finish(true); finish(true) })
			workers.Go(func() {
				reply := toolReply("private-parent", "function_call", id)
				store.toolResults("scope", reply)
				store.toolResults("scope", reply)
			})
		}
		workers.Wait()
		if m := store.snapshot(); m.ContinuedToolCalls != 24 || m.ContinuedToolResults != 24 || m.ToolTrackingDrops != 0 || len(store.tools) != 0 {
			t.Fatalf("concurrent results were lost or counted twice: %+v", m)
		}
	})
}

func TestHTTPContinuedToolResultMetrics(t *testing.T) {
	var calls atomic.Int32
	endpoint := metricHarness(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		n := calls.Add(1)
		id, tokens, tool := "first", 516, true
		if n == 2 {
			id, tokens = "chosen", 20
		} else if n > 2 {
			id, tokens, tool = "finish", 20, false
		}
		testfixture.WriteSSE(w, testfixture.Round(id, tokens, tool))
	}), 1, true)
	drain(t, request(t, context.Background(), endpoint+"/responses", core.Object{"model": "gpt-6", "stream": true, "input": []any{}}))
	reply := toolReply("first", "function_call", "chosen-call")
	reply["model"] = "gpt-6"
	reply["stream"] = true
	drain(t, request(t, context.Background(), endpoint+"/responses", reply))
	m := readMetrics(t, endpoint)
	if m.Continuations != 1 || m.ContinuedToolResponses != 1 || m.ContinuedToolCalls != 1 || m.ContinuedToolResults != 1 || m.ToolTrackingDrops != 0 {
		t.Fatalf("HTTP did not correlate retained tool results: %+v", m)
	}
}

type toolWriteFailure struct {
	*httptest.ResponseRecorder
	rejected bool
}

func (w *toolWriteFailure) Write(data []byte) (int, error) {
	if bytes.Contains(data, []byte("chosen-call")) {
		w.rejected = true
		return 0, errors.New("synthetic downstream failure")
	}
	return w.ResponseRecorder.Write(data)
}

func TestHTTPToolMetricsRollbackOnDeliveryFailure(t *testing.T) {
	var calls atomic.Int32
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		id, tokens := "first", 516
		if calls.Add(1) > 1 {
			id, tokens = "chosen", 20
		}
		testfixture.WriteSSE(w, testfixture.Round(id, tokens, true))
	}))
	defer upstream.Close()
	config := core.DefaultConfig()
	config.MaxContinue = 1
	server, err := New(Config{Upstream: upstream.URL, Fold: config, EnableMetrics: true})
	if err != nil {
		t.Fatal(err)
	}
	req := httptest.NewRequest(http.MethodPost, "/responses", strings.NewReader(`{"model":"gpt-6","stream":true,"input":[]}`))
	req.RemoteAddr = "127.0.0.1:1234"
	req.Header.Set("Authorization", "Bearer synthetic-only")
	writer := &toolWriteFailure{ResponseRecorder: httptest.NewRecorder()}
	server.ServeHTTP(writer, req)
	if calls.Load() != 2 || !writer.rejected {
		t.Fatal("test did not reach retained-tool delivery failure")
	}
	if m := server.metrics.snapshot(); m.ContinuedToolCalls != 0 || m.ContinuedToolResults != 0 || len(server.metrics.tools) != 0 {
		t.Fatalf("delivery failure counted a tool roundtrip: %+v", m)
	}
}
