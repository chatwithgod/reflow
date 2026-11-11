package main

import (
	"encoding/json"
	"fmt"
	"reflect"
	"strings"
	"sync"
	"testing"
	"time"

	"github.com/router-for-me/CLIProxyAPI/v8/sdk/pluginapi"
)

func fixtureWSScope(t *testing.T, socket, model, lane string) wsAliasScope {
	t.Helper()
	scope, valid := wsScope(map[string]any{cpaExecutionSessionMetadataKey: socket}, model, lane)
	if !valid {
		t.Fatal("invalid fixture scope")
	}
	return scope
}

func TestWSAliasScope(t *testing.T) {
	for _, metadata := range []map[string]any{nil, {}, {cpaExecutionSessionMetadataKey: 123}, {cpaExecutionSessionMetadataKey: ""}} {
		if _, ok := wsScope(metadata, "fixture-model", ""); ok {
			t.Fatal("accepted absent/non-string host socket scope")
		}
	}
	if _, ok := wsScope(map[string]any{cpaExecutionSessionMetadataKey: strings.Repeat("x", wsAliasMaxField+1)}, "model", ""); ok {
		t.Fatal("accepted unbounded scope")
	}
	meta := map[string]any{cpaExecutionSessionMetadataKey: "fixture-socket", cpaRequestedModelMetadataKey: "lab/gpt-6-sol(high)"}
	scope, ok := wsScope(meta, "upstream-model", "main")
	if !ok || scope.Model != "lab/gpt-6-sol(high)" {
		t.Fatal("requested model was not retained")
	}
}

func TestWSAliasIsolation(t *testing.T) {
	c := newWSAliasCache(8, time.Hour, time.Now)
	scope := fixtureWSScope(t, "socket-A", "model-A", "main")
	if _, ok := c.put(scope, "resp_visible", "resp_latest_A", "fixture-run"); !ok {
		t.Fatal("put failed")
	}
	for _, other := range []wsAliasScope{
		fixtureWSScope(t, "socket-B", "model-A", "main"),
		fixtureWSScope(t, "socket-A", "model-B", "main"),
		fixtureWSScope(t, "socket-A", "model-A", "fork"),
	} {
		if _, ok := c.get(other, "resp_visible"); ok {
			t.Fatal("alias escaped socket/model/lane scope")
		}
	}
	if _, ok := c.get(scope, "unknown_parent"); ok {
		t.Fatal("unknown parent was remapped")
	}
	if entry, ok := c.get(scope, "resp_visible"); !ok || entry.Upstream != "resp_latest_A" {
		t.Fatal("known alias was lost")
	}
}

func TestWSAliasExpiryEvictionAndRevision(t *testing.T) {
	now := time.Unix(100, 0)
	c := newWSAliasCache(2, time.Minute, func() time.Time { return now })
	scope := fixtureWSScope(t, "socket", "model", "")
	old, _ := c.put(scope, "visible-A", "upstream-A", "run")
	c.put(scope, "visible-B", "upstream-B", "run")
	c.get(scope, "visible-A")
	c.put(scope, "visible-C", "upstream-C", "run")
	if _, ok := c.get(scope, "visible-B"); ok {
		t.Fatal("LRU bound was not enforced")
	}
	latest, _ := c.put(scope, "visible-A", "upstream-A2", "run")
	c.revoke(old)
	if entry, ok := c.get(scope, "visible-A"); !ok || entry.Upstream != "upstream-A2" {
		t.Fatal("old revocation removed newer alias")
	}
	c.revoke(latest)
	if _, ok := c.get(scope, "visible-A"); ok {
		t.Fatal("failed emission lease not revoked")
	}
	now = now.Add(time.Minute)
	if _, ok := c.get(scope, "visible-C"); ok {
		t.Fatal("expired alias still accessible")
	}
	c.put(scope, "visible-D", "upstream-D", "run")
	if len(c.entries) != 1 {
		t.Fatal("expired entries were not pruned")
	}
	c.clear()
	if len(c.entries) != 0 {
		t.Fatal("shutdown cache clear failed")
	}
}

func TestWSAliasRejectsUnboundedIDs(t *testing.T) {
	c := newWSAliasCache(2, time.Hour, time.Now)
	scope := fixtureWSScope(t, "socket", "model", "")
	for _, pair := range [][2]string{{"", "b"}, {"a", ""}, {"same", "same"}, {strings.Repeat("x", wsAliasMaxField+1), "b"}, {"a", strings.Repeat("x", wsAliasMaxField+1)}} {
		if _, ok := c.put(scope, pair[0], pair[1], "run"); ok {
			t.Fatal("accepted invalid alias")
		}
	}
}

func TestWSAliasConcurrentSockets(t *testing.T) {
	c := newWSAliasCache(128, time.Hour, time.Now)
	var wg sync.WaitGroup
	for i := 0; i < 32; i++ {
		scope := fixtureWSScope(t, fmt.Sprintf("fixture-socket-%d", i), "model", "")
		wg.Add(1)
		go func(i int, scope wsAliasScope) {
			defer wg.Done()
			id := fmt.Sprintf("latest-%d", i)
			for j := 0; j < 100; j++ {
				c.put(scope, "shared-visible-id", id, "run")
				if entry, ok := c.get(scope, "shared-visible-id"); !ok || entry.Upstream != id {
					t.Error("concurrent socket aliases collided")
					return
				}
			}
		}(i, scope)
	}
	wg.Wait()
}

func fixtureInterceptRequest() pluginapi.RequestInterceptRequest {
	return pluginapi.RequestInterceptRequest{
		SourceFormat: "openai-response", ToFormat: "codex", Stream: true,
		Model: "upstream-model", RequestedModel: "gpt-6-sol",
		Metadata: map[string]any{cpaExecutionSessionMetadataKey: "fixture-socket"},
		Body:     []byte(`{"previous_response_id":"visible-A","stream_id":"main","input":[{"type":"function_call_output","call_id":"fixture-call","output":"中文"}],"instructions":"fixture only","number":9007199254740993}`),
	}
}

func TestRewriteWSParentPreservesToolDelta(t *testing.T) {
	c := newWSAliasCache(2, time.Hour, time.Now)
	scope := fixtureWSScope(t, "fixture-socket", "gpt-6-sol", "main")
	c.put(scope, "visible-A", "latest-B", "fixture-run")
	req := fixtureInterceptRequest()
	original := append([]byte(nil), req.Body...)
	response, runID := rewriteWSParent(req, c)
	var before, after map[string]json.RawMessage
	json.Unmarshal(req.Body, &before)
	json.Unmarshal(response.Body, &after)
	if string(after["previous_response_id"]) != `"latest-B"` || runID != "fixture-run" {
		t.Fatal("known parent was not remapped")
	}
	delete(before, "previous_response_id")
	delete(after, "previous_response_id")
	if !reflect.DeepEqual(before, after) || string(req.Body) != string(original) {
		t.Fatal("delta, instructions, large integer or original body was changed")
	}
	if response.Terminate || response.Headers != nil {
		t.Fatal("bridge changed routing/auth/transport")
	}
}

func TestRewriteWSParentGuards(t *testing.T) {
	c := newWSAliasCache(2, time.Hour, time.Now)
	c.put(fixtureWSScope(t, "fixture-socket", "gpt-6-sol", "main"), "visible-A", "latest-B", "run")
	tests := []struct {
		name   string
		change func(*pluginapi.RequestInterceptRequest)
	}{
		{"nonstream", func(r *pluginapi.RequestInterceptRequest) { r.Stream = false }},
		{"other_format", func(r *pluginapi.RequestInterceptRequest) { r.SourceFormat = "claude" }},
		{"other_provider", func(r *pluginapi.RequestInterceptRequest) { r.ToFormat = "openai" }},
		{"no_socket", func(r *pluginapi.RequestInterceptRequest) { r.Metadata = nil }},
		{"reconnect", func(r *pluginapi.RequestInterceptRequest) {
			r.Metadata[cpaExecutionSessionMetadataKey] = "new-socket"
		}},
		{"other_model", func(r *pluginapi.RequestInterceptRequest) { r.RequestedModel = "gpt-6-luna" }},
		{"malformed", func(r *pluginapi.RequestInterceptRequest) { r.Body = []byte(`{"`) }},
		{"null_parent", func(r *pluginapi.RequestInterceptRequest) { r.Body = []byte(`{"previous_response_id":null}`) }},
		{"empty_parent", func(r *pluginapi.RequestInterceptRequest) { r.Body = []byte(`{"previous_response_id":""}`) }},
		{"unknown_parent", func(r *pluginapi.RequestInterceptRequest) {
			r.Body = []byte(`{"previous_response_id":"unknown","stream_id":"main"}`)
		}},
		{"fork_lane", func(r *pluginapi.RequestInterceptRequest) {
			r.Body = []byte(`{"previous_response_id":"visible-A","stream_id":"fork"}`)
		}},
		{"invalid_lane", func(r *pluginapi.RequestInterceptRequest) {
			r.Body = []byte(`{"previous_response_id":"visible-A","stream_id":123}`)
		}},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			req := fixtureInterceptRequest()
			test.change(&req)
			if response, run := rewriteWSParent(req, c); len(response.Body) != 0 || run != "" {
				t.Fatal("guarded request was rewritten")
			}
		})
	}
}

func TestFoldRegistersOnlyCompletedSocketAlias(t *testing.T) {
	original := foldedWSAliases
	foldedWSAliases = newWSAliasCache(8, time.Hour, time.Now)
	defer func() { foldedWSAliases = original }()
	req := rpcExecutorRequest{ExecutorRequest: pluginapi.ExecutorRequest{Model: "gpt-6-sol", SourceFormat: "openai-response", Metadata: map[string]any{cpaExecutionSessionMetadataKey: "fixture-socket"}}}
	fs := newFoldState(map[string]any{}, nil, req, "")
	fs.roundNo = 2
	fs.baseResponse = map[string]any{"id": "visible-A"}
	fs.terminal = map[string]any{"type": "response.completed", "response": map[string]any{"id": "latest-B"}}
	lease, status := fs.registerWSAlias()
	if status != "response_alias" {
		t.Fatalf("bridge=%s", status)
	}
	foldedWSAliases.revoke(lease)
	fs.req.SourceFormat = "codex"
	lease, status = fs.registerWSAlias()
	if status != "response_alias" {
		t.Fatalf("CPA-translated input bridge=%s", status)
	}
	foldedWSAliases.revoke(lease)
	fs.terminal["type"] = "response.failed"
	if _, status := fs.registerWSAlias(); status != "not_committed" {
		t.Fatal("failed terminal committed alias")
	}
	fs.req.Metadata = nil
	if _, status := fs.registerWSAlias(); status != "no_socket_scope" {
		t.Fatal("no-scope request retained state")
	}
	fs.roundNo = 1
	if _, status := fs.registerWSAlias(); status != "not_needed" {
		t.Fatal("single round created alias")
	}
}
