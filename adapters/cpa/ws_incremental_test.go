package main

import (
	"encoding/json"
	"strings"
	"testing"
	"time"

	"github.com/router-for-me/CLIProxyAPI/v8/sdk/pluginapi"
)

func fixtureNativeWSRequest() pluginapi.StreamChunkInterceptRequest {
	body := []byte(`{"model":"gpt-6-sol","stream":true,"previous_response_id":"visible","input":[{"type":"function_call_output","call_id":"fixture-call","output":"fixture result"}]}`)
	return pluginapi.StreamChunkInterceptRequest{RequestID: "fixture-request", SourceFormat: "openai-response",
		Model: "fixture-upstream", RequestedModel: "gpt-6-sol", OriginalRequest: body, RequestBody: body,
		Metadata: map[string]any{cpaExecutionSessionMetadataKey: "fixture-socket"}}
}

func TestPrepareNativeWSFoldRequiresCompleteContext(t *testing.T) {
	previous := currentFoldConfig()
	setFoldConfig(defaultFoldConfig())
	t.Cleanup(func() { setFoldConfig(previous); foldedWSReplays.clear() })
	req := fixtureNativeWSRequest()
	state, reason := prepareNativeWSFold(req)
	if reason != "" || state == nil || state.context != "replay_context_miss" || len(state.fs.origInput) != 0 {
		t.Fatal("unknown delta did not fail closed", reason)
	}
	scope := fixtureWSScope(t, "fixture-socket", "gpt-6-sol", "")
	root := []any{map[string]any{"role": "user", "content": "fixture root"},
		map[string]any{"type": "function_call", "call_id": "fixture-call", "arguments": "{}"}}
	foldedWSReplays.put(scope, "visible", "upstream", root)
	state, reason = prepareNativeWSFold(req)
	if reason != "" || state.context != "available" || len(state.fs.origInput) != 3 || !state.fs.nativeWS {
		t.Fatal("complete native context unavailable", reason, state.context)
	}
	if state.fs.origInput[2].(map[string]any)["type"] != "function_call_output" {
		t.Fatal("tool result omitted from complete replay")
	}
	if state.fs.telemetry("")["path"] != "ws_incremental" {
		t.Fatal("native path lacks distinct evidence")
	}
	for _, mutate := range []func(*pluginapi.StreamChunkInterceptRequest){
		func(r *pluginapi.StreamChunkInterceptRequest) { r.SourceFormat = "codex" },
		func(r *pluginapi.StreamChunkInterceptRequest) { r.Metadata = nil },
		func(r *pluginapi.StreamChunkInterceptRequest) { r.RequestedModel = "non-gpt-fixture" },
		func(r *pluginapi.StreamChunkInterceptRequest) {
			r.RequestBody = []byte(`{"input":[],"generate":false,"previous_response_id":"visible"}`)
		},
		func(r *pluginapi.StreamChunkInterceptRequest) {
			r.RequestBody = []byte(`{"input":"bad","previous_response_id":"visible"}`)
		},
	} {
		candidate := fixtureNativeWSRequest()
		mutate(&candidate)
		if got, _ := prepareNativeWSFold(candidate); got != nil {
			t.Fatal("accepted ineligible request")
		}
	}
	req.RequestBody = []byte(strings.Repeat("x", nativeWSMaxRequestBytes+1))
	if got, reason := prepareNativeWSFold(req); got != nil || reason != "request_size_limit" {
		t.Fatal("request bound not enforced", reason)
	}
}

func TestNativeWSRegistryCleanupAndBounds(t *testing.T) {
	registry := nativeWSRegistry{entries: make(map[string]*nativeWSFold)}
	state := &nativeWSFold{expires: time.Now().Add(time.Minute), requestSize: nativeWSMaxBytes}
	if !registry.put("fixture", state) || registry.put("other", &nativeWSFold{expires: state.expires, requestSize: 1}) {
		t.Fatal("active state byte limit not enforced")
	}
	registry.remove("fixture", &nativeWSFold{})
	if registry.get("fixture") == nil {
		t.Fatal("old cleanup removed replacement")
	}
	registry.remove("fixture", state)
	if registry.size != 0 {
		t.Fatal("sensitive active state retained")
	}
	state = &nativeWSFold{expires: time.Now().Add(time.Minute), requestSize: 10}
	registry.put("fixture", state)
	if !registry.reserve("fixture", state, nativeWSMaxBytes-10) || registry.reserve("fixture", state, 1) {
		t.Fatal("stream bytes escaped aggregate active limit")
	}
	registry.remove("fixture", state)
	if registry.size != 0 {
		t.Fatal("stream reservation retained after completion")
	}
	registry.put("expired", &nativeWSFold{expires: time.Now().Add(-time.Minute), requestSize: 1})
	if registry.get("expired") != nil || registry.size != 0 {
		t.Fatal("expired active state retained")
	}
	registry.put("fixture", state)
	registry.clear()
	if registry.size != 0 || len(registry.entries) != 0 {
		t.Fatal("shutdown cleanup failed")
	}
}

func TestNativeWSMissDoesNotCallModelAndPreservesTools(t *testing.T) {
	previous := currentFoldConfig()
	setFoldConfig(defaultFoldConfig())
	t.Cleanup(func() { setFoldConfig(previous); incrementalWS.clear(); foldedWSReplays.clear() })
	req := fixtureNativeWSRequest()
	state, _ := prepareNativeWSFold(req)
	if !incrementalWS.put(req.RequestID, state) {
		t.Fatal("fixture state rejected")
	}
	// A terminal containing a trigger and opaque reasoning must not cause a
	// model callback when only the delta is available. C callbacks are absent
	// in go test; any accidental extra round would become response.incomplete.
	events := []map[string]any{
		{"type": "response.created", "response": map[string]any{"id": "resp_fixture", "status": "in_progress"}},
		{"type": "response.output_item.added", "output_index": float64(0), "item": map[string]any{"type": "reasoning", "id": "rs_fixture"}},
		{"type": "response.output_item.done", "output_index": float64(0), "item": map[string]any{"type": "reasoning", "id": "rs_fixture", "encrypted_content": "opaque_fixture"}},
		{"type": "response.output_item.added", "output_index": float64(1), "item": map[string]any{"type": "function_call", "call_id": "next-fixture", "arguments": "{}"}},
		{"type": "response.output_item.done", "output_index": float64(1), "item": map[string]any{"type": "function_call", "call_id": "next-fixture", "arguments": "{}"}},
		{"type": "response.completed", "response": map[string]any{"id": "resp_fixture", "status": "completed", "usage": map[string]any{
			"input_tokens": float64(100), "output_tokens": float64(530), "output_tokens_details": map[string]any{"reasoning_tokens": float64(516)}}}},
	}
	var all []byte
	for n, event := range events {
		chunk := rpcNativeWSChunk{StreamChunkInterceptRequest: req}
		chunk.ChunkIndex, chunk.Body = n, sseEvent(event)
		raw, _ := json.Marshal(chunk)
		result, err := interceptNativeWSChunk(raw)
		if err != nil {
			t.Fatal(err)
		}
		var env envelope
		json.Unmarshal(result, &env)
		var response pluginapi.StreamChunkInterceptResponse
		json.Unmarshal(env.Result, &response)
		all = append(all, response.Body...)
	}
	decoder := eventDecoder{}
	decoder.feed(all)
	var terminal map[string]any
	for {
		event, ready, err := decoder.next()
		if err != nil || !ready {
			break
		}
		if terminalTypes[event["type"].(string)] {
			terminal = event
		}
	}
	if terminal == nil || terminal["type"] != "response.completed" || state.fs.roundNo != 1 {
		t.Fatal("context miss made a model call", terminal)
	}
	response := terminal["response"].(map[string]any)
	output := response["output"].([]any)
	if len(output) != 2 || output[1].(map[string]any)["call_id"] != "next-fixture" {
		t.Fatal("native tool output lost")
	}
	info := response["metadata"].(map[string]any)["proxy_reflow"].(map[string]any)
	if info["stop_reason"] != "replay_context_miss" || incrementalWS.get(req.RequestID) != nil {
		t.Fatal("missing bypass evidence/cleanup", info)
	}
}
