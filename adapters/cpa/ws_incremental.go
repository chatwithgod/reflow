package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"sync"
	"time"

	"github.com/router-for-me/CLIProxyAPI/v8/sdk/pluginapi"
)

const nativeWSCapacity = 64
const nativeWSMaxRequestBytes = 16 << 20
const nativeWSMaxChunkBytes = 8 << 20
const nativeWSMaxStreamBytes = 16 << 20
const nativeWSMaxBytes = 64 << 20
const nativeWSTTL = 20 * time.Minute

type rpcNativeWSChunk struct {
	pluginapi.StreamChunkInterceptRequest
	HostCallbackID string `json:"host_callback_id,omitempty"`
}

type nativeWSFold struct {
	mu           sync.Mutex
	fs           *foldState
	scope        wsAliasScope
	context      string
	expires      time.Time
	requestSize  int
	reservedSize int
	streamSize   int
	limited      bool
	closed       bool
}

type nativeWSRegistry struct {
	mu      sync.Mutex
	entries map[string]*nativeWSFold
	size    int
}

var incrementalWS = nativeWSRegistry{entries: make(map[string]*nativeWSFold)}

func (c *nativeWSRegistry) put(id string, state *nativeWSFold) bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	now := time.Now()
	for key, value := range c.entries {
		if !now.Before(value.expires) {
			c.size -= value.requestSize + value.reservedSize
			delete(c.entries, key)
		}
	}
	if old, exists := c.entries[id]; exists {
		c.size -= old.requestSize + old.reservedSize
		delete(c.entries, id)
	}
	if len(c.entries) >= nativeWSCapacity || c.size+state.requestSize > nativeWSMaxBytes {
		return false
	}
	c.entries[id] = state
	c.size += state.requestSize
	return true
}

func (c *nativeWSRegistry) get(id string) *nativeWSFold {
	c.mu.Lock()
	defer c.mu.Unlock()
	state := c.entries[id]
	if state != nil && !time.Now().Before(state.expires) {
		delete(c.entries, id)
		c.size -= state.requestSize + state.reservedSize
		return nil
	}
	return state
}

func (c *nativeWSRegistry) remove(id string, expected *nativeWSFold) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if state := c.entries[id]; state != nil && (expected == nil || state == expected) {
		delete(c.entries, id)
		c.size -= state.requestSize + state.reservedSize
	}
}

func (c *nativeWSRegistry) reserve(id string, state *nativeWSFold, size int) bool {
	c.mu.Lock()
	defer c.mu.Unlock()
	if c.entries[id] != state || c.size+size > nativeWSMaxBytes {
		return false
	}
	state.reservedSize += size
	c.size += size
	return true
}

func (c *nativeWSRegistry) clear() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.entries = make(map[string]*nativeWSFold)
	c.size = 0
}

// Leave model routing native: selecting the self executor for an incremental
// create can force CPA 8.0.13's HTTP-replay-required close before execution.
// The response hook runs after the native upstream stream releases its lock.
func prepareNativeWSFold(req pluginapi.StreamChunkInterceptRequest) (*nativeWSFold, string) {
	model := req.RequestedModel
	if model == "" {
		model = req.Model
	}
	if req.RequestID == "" || req.SourceFormat != "openai-response" || !modelInAllowlist(model) {
		return nil, ""
	}
	if len(req.RequestBody)+len(req.OriginalRequest) > nativeWSMaxRequestBytes {
		return nil, "request_size_limit"
	}
	var body, original map[string]any
	if json.Unmarshal(req.RequestBody, &body) != nil || json.Unmarshal(req.OriginalRequest, &original) != nil {
		return nil, ""
	}
	parent, _ := original["previous_response_id"].(string)
	if parent == "" {
		parent, _ = body["previous_response_id"].(string)
	}
	if parent == "" || len(parent) > wsAliasMaxField || body["generate"] == false {
		return nil, ""
	}
	lane, _ := body["stream_id"].(string)
	scope, valid := wsScope(req.Metadata, model, lane)
	if !valid {
		return nil, ""
	}
	restoreCollaborationToolSchemaTypes(body, req.OriginalRequest)
	delta, valid := body["input"].([]any)
	if !valid {
		return nil, ""
	}
	input, settings, context := foldedWSReplays.getWithSettings(scope, parent, delta)
	if context == "available" {
		// Native deltas may omit tools/instructions/reasoning settings that the
		// upstream connection inherits. Full hidden replays must inherit them
		// too, while explicit client replacements (including null) take priority.
		for key, value := range settings {
			if _, explicit := original[key]; !explicit && key != "model" && key != "stream_id" {
				body[key] = value
			}
		}
	}
	inputBytes, err := json.Marshal(input)
	if err != nil || len(inputBytes)+len(req.RequestBody) > nativeWSMaxRequestBytes {
		return nil, "request_size_limit"
	}
	fs := newFoldState(body, input, rpcExecutorRequest{ExecutorRequest: pluginapi.ExecutorRequest{
		Model: model, SourceFormat: "openai-response", Stream: true,
		Headers: cloneHeader(req.RequestHeaders), Metadata: req.Metadata,
	}}, "")
	fs.nativeWS = true
	fs.RoundNo = 1 // Round one is already executing on CPA's native path.
	return &nativeWSFold{fs: fs, scope: scope, context: context,
		expires: time.Now().Add(nativeWSTTL), requestSize: len(req.RequestBody) + len(inputBytes)}, ""
}

func interceptNativeWSChunk(raw []byte) ([]byte, error) {
	var req rpcNativeWSChunk
	if err := json.Unmarshal(raw, &req); err != nil {
		return nil, err
	}
	if req.ChunkIndex == pluginapi.StreamChunkHeaderInitIndex {
		state, reason := prepareNativeWSFold(req.StreamChunkInterceptRequest)
		if state != nil {
			if incrementalWS.put(req.RequestID, state) {
				logReflowEvent(state.fs.diagnosticEvent("fold_started"))
			} else {
				reason = "active_request_limit"
			}
		}
		if reason != "" {
			logReflowEvent(map[string]any{"event": "ws_incremental_bypassed", "reason": reason})
		}
		return okEnvelope(pluginapi.StreamChunkInterceptResponse{})
	}
	state := incrementalWS.get(req.RequestID)
	if state == nil {
		return okEnvelope(pluginapi.StreamChunkInterceptResponse{})
	}
	state.mu.Lock()
	defer state.mu.Unlock()
	if state.closed {
		return okEnvelope(pluginapi.StreamChunkInterceptResponse{DropChunk: true})
	}
	fs := state.fs
	var emitted bytes.Buffer
	fs.emitter = func(payload []byte) error { _, err := emitted.Write(payload); return err }
	defer func() { fs.emitter, fs.beforeChunk = nil, nil }()
	fs.hostCallbackID = req.HostCallbackID
	fs.beforeChunk = func(payload []byte) error {
		if fs.RoundNo == 1 {
			return nil // Native first-round bytes are reserved below.
		}
		state.streamSize += len(payload)
		if len(payload) > nativeWSMaxChunkBytes || state.streamSize > nativeWSMaxStreamBytes ||
			!incrementalWS.reserve(req.RequestID, state, len(payload)) {
			state.limited = true
			return fmt.Errorf("native WS fold resource limit")
		}
		return nil
	}
	state.streamSize += len(req.Body)
	if len(req.Body) > nativeWSMaxChunkBytes || state.streamSize > nativeWSMaxStreamBytes ||
		!incrementalWS.reserve(req.RequestID, state, len(req.Body)) {
		// Resource exhaustion is explicit and recoverable by a full replay.
		// Never silently drop a parent/history or forward half-buffered tools.
		state.finishError(&emitted, "stream_size_limit")
		state.fs.baseBody, state.fs.origInput, state.fs.Buffered = nil, nil, nil
		return okEnvelope(pluginapi.StreamChunkInterceptResponse{Body: emitted.Bytes()})
	}
	terminal, err := fs.processAndEmit(req.Body, "")
	if err != nil {
		state.finishError(&emitted, "upstream_error")
	} else if terminal != nil {
		fs.endRound(fs.Terminal, fs.Usage)
		for !state.limited && state.context == "available" && fs.shouldContinue() {
			fs.prepareNextRound()
			terminal, usage, _, roundErr := fs.openRound("")
			if roundErr != nil || terminal == nil {
				reason := "upstream_error"
				if roundErr == nil {
					reason = "upstream_eof"
				}
				if state.limited {
					reason = "stream_size_limit"
				}
				state.finishError(&emitted, reason)
				break
			}
			fs.endRound(terminal, usage)
		}
		if !state.closed {
			_ = fs.flushCleanStop("")
			lease, bridge := fs.registerWSAlias()
			fs.bridgeStatus = bridge
			stop := fs.terminalStopReason()
			if fs.continueReason() != "" && state.context != "available" {
				stop = state.context
			}
			if state.limited {
				stop = "stream_size_limit"
			}
			if state.context == "available" && !state.limited {
				fs.commitWSReplay()
			} else {
				foldedWSReplays.invalidate(state.scope)
			}
			event := fs.terminalEvent()
			fs.annotateEvent(event, stop)
			fs.stamp(event)
			if _, err := emitted.Write(sseEvent(event)); err != nil {
				foldedWSAliases.revoke(lease)
			}
			fs.logResult(event["type"].(string), "interceptor_returned", stop)
			state.closed = true
		}
		incrementalWS.remove(req.RequestID, state)
	}
	if emitted.Len() == 0 {
		return okEnvelope(pluginapi.StreamChunkInterceptResponse{DropChunk: true})
	}
	return okEnvelope(pluginapi.StreamChunkInterceptResponse{Body: emitted.Bytes()})
}

func (s *nativeWSFold) finishError(emitted *bytes.Buffer, reason string) {
	fs := s.fs
	event := fs.incompleteEvent(reason)
	fs.stamp(event)
	emitted.Write(sseEvent(event))
	foldedWSReplays.invalidate(s.scope)
	fs.logResult("response.incomplete", "interceptor_returned", reason)
	s.closed = true
}

func completeNativeWSRequest(raw []byte) ([]byte, error) {
	var req pluginapi.RequestCompletion
	if err := json.Unmarshal(raw, &req); err != nil {
		return nil, fmt.Errorf("decode native request completion: %w", err)
	}
	if state := incrementalWS.get(req.RequestID); state != nil && req.Outcome != pluginapi.RequestCompletionSucceeded {
		foldedWSReplays.invalidate(state.scope)
		// A native failure can be preempted by the host before its terminal
		// chunk reaches us. Record only lifecycle evidence, never a delivery
		// claim or the host's free-form Error (which may contain private data).
		state.mu.Lock()
		if !state.closed {
			result := "host_lifecycle_unknown"
			switch req.Outcome {
			case pluginapi.RequestCompletionFailed:
				result = "host_lifecycle_failed"
			case pluginapi.RequestCompletionCanceled:
				result = "host_lifecycle_canceled"
			case pluginapi.RequestCompletionRejected:
				result = "host_lifecycle_rejected"
			}
			state.fs.logResult(result, "not_confirmed", result)
		}
		state.mu.Unlock()
	}
	incrementalWS.remove(req.RequestID, nil)
	return okEnvelope(map[string]any{})
}
