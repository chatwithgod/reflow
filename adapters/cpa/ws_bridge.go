package main

import (
	"crypto/sha256"
	"encoding/json"
	"sync"
	"time"

	"github.com/router-for-me/CLIProxyAPI/v8/sdk/pluginapi"
)

// Bridge only identities, not prompts or encrypted reasoning. The host-owned
// execution session is tied to one downstream socket; client session headers
// must never substitute for it. Misses preserve the native recovery behavior.
const wsAliasTTL = time.Hour
const wsAliasCapacity = 4096
const wsAliasMaxField = 512

// JSON metadata names from the pinned CPA 8.0.13 executor types. Importing its
// executor package would unnecessarily pull all built-in translators into this DLL.
const cpaExecutionSessionMetadataKey = "execution_session_id"
const cpaRequestedModelMetadataKey = "requested_model"

type wsAliasScope struct {
	Session [32]byte
	Model   string
	Lane    string
}

type wsAliasKey struct {
	Scope   wsAliasScope
	Visible string
}

type wsAliasEntry struct {
	Upstream string
	RunID    string
	Expires  time.Time
	Used     uint64
	Revision uint64
}

type wsAliasLease struct {
	Key      wsAliasKey
	Revision uint64
}

type wsAliasCache struct {
	mu       sync.Mutex
	entries  map[wsAliasKey]wsAliasEntry
	capacity int
	ttl      time.Duration
	now      func() time.Time
	clock    uint64
}

func newWSAliasCache(capacity int, ttl time.Duration, now func() time.Time) *wsAliasCache {
	return &wsAliasCache{entries: make(map[wsAliasKey]wsAliasEntry), capacity: capacity, ttl: ttl, now: now}
}

var foldedWSAliases = newWSAliasCache(wsAliasCapacity, wsAliasTTL, time.Now)

func wsScope(metadata map[string]any, model, lane string) (wsAliasScope, bool) {
	session, _ := metadata[cpaExecutionSessionMetadataKey].(string)
	requested, _ := metadata[cpaRequestedModelMetadataKey].(string)
	if requested != "" {
		model = requested
	}
	if session == "" || model == "" || len(session) > wsAliasMaxField || len(model) > wsAliasMaxField || len(lane) > wsAliasMaxField {
		return wsAliasScope{}, false
	}
	return wsAliasScope{Session: sha256.Sum256([]byte(session)), Model: model, Lane: lane}, true
}

func (c *wsAliasCache) prune(now time.Time) {
	for key, value := range c.entries {
		if !now.Before(value.Expires) {
			delete(c.entries, key)
		}
	}
}

func (c *wsAliasCache) put(scope wsAliasScope, visible, upstream, runID string) (wsAliasLease, bool) {
	if c.capacity <= 0 || c.ttl <= 0 || visible == "" || upstream == "" || visible == upstream ||
		len(visible) > wsAliasMaxField || len(upstream) > wsAliasMaxField || len(runID) > wsAliasMaxField {
		return wsAliasLease{}, false
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	now := c.now()
	c.prune(now)
	key := wsAliasKey{Scope: scope, Visible: visible}
	if _, exists := c.entries[key]; !exists && len(c.entries) >= c.capacity {
		var oldest wsAliasKey
		var age uint64 = ^uint64(0)
		for candidate, value := range c.entries {
			if value.Used < age {
				oldest, age = candidate, value.Used
			}
		}
		delete(c.entries, oldest)
	}
	c.clock++
	c.entries[key] = wsAliasEntry{Upstream: upstream, RunID: runID, Expires: now.Add(c.ttl), Used: c.clock, Revision: c.clock}
	return wsAliasLease{Key: key, Revision: c.clock}, true
}

func (c *wsAliasCache) get(scope wsAliasScope, visible string) (wsAliasEntry, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	key := wsAliasKey{Scope: scope, Visible: visible}
	entry, ok := c.entries[key]
	if !ok {
		return wsAliasEntry{}, false
	}
	if !c.now().Before(entry.Expires) {
		delete(c.entries, key)
		return wsAliasEntry{}, false
	}
	c.clock++
	entry.Used = c.clock
	c.entries[key] = entry
	return entry, true
}

func (c *wsAliasCache) revoke(lease wsAliasLease) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if entry, exists := c.entries[lease.Key]; exists && entry.Revision == lease.Revision {
		delete(c.entries, lease.Key)
	}
}

func (c *wsAliasCache) clear() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.entries = make(map[wsAliasKey]wsAliasEntry)
}

// Run after native auth selection. Keep the complete delta/tool payload intact
// and retain CPA's credential pinning, transport policy, and failure handling.
// This does not intercept native incremental generations for extra thinking.
func rewriteWSParent(req pluginapi.RequestInterceptRequest, cache *wsAliasCache) (pluginapi.RequestInterceptResponse, string) {
	unchanged := pluginapi.RequestInterceptResponse{}
	if !req.Stream || req.SourceFormat != "openai-response" || req.ToFormat != "codex" {
		return unchanged, ""
	}
	var body map[string]json.RawMessage
	if json.Unmarshal(req.Body, &body) != nil {
		return unchanged, ""
	}
	var parent, lane string
	if json.Unmarshal(body["previous_response_id"], &parent) != nil || parent == "" || len(parent) > wsAliasMaxField {
		return unchanged, ""
	}
	if raw, exists := body["stream_id"]; exists && json.Unmarshal(raw, &lane) != nil {
		return unchanged, ""
	}
	model := req.RequestedModel
	if model == "" {
		model = req.Model
	}
	scope, valid := wsScope(req.Metadata, model, lane)
	if !valid {
		return unchanged, ""
	}
	entry, found := cache.get(scope, parent)
	if !found {
		return unchanged, ""
	}
	body["previous_response_id"], _ = json.Marshal(entry.Upstream)
	raw, err := json.Marshal(body)
	if err != nil {
		return unchanged, ""
	}
	return pluginapi.RequestInterceptResponse{Body: raw}, entry.RunID
}

func interceptWSParentAfter(raw []byte) ([]byte, error) {
	var req pluginapi.RequestInterceptRequest
	if err := json.Unmarshal(raw, &req); err != nil {
		return nil, err
	}
	response, runID := rewriteWSParent(req, foldedWSAliases)
	if len(response.Body) > 0 {
		logReflowEvent(map[string]any{"event": "ws_parent_remapped", "run_id": runID})
	}
	return okEnvelope(response)
}

func (fs *foldState) registerWSAlias() (wsAliasLease, string) {
	if fs.roundNo <= 1 {
		return wsAliasLease{}, "not_needed"
	}
	// CPA's self-executor adapter translates Responses input to the declared
	// codex input format before invoking this DLL (SDK 8.0.13). The after-auth
	// interceptor still sees the original openai-response source on the next
	// native turn. Do not mistake that adapter conversion for a non-WS request.
	if fs.req.SourceFormat != "openai-response" && fs.req.SourceFormat != "codex" {
		return wsAliasLease{}, "not_applicable"
	}
	lane, _ := fs.baseBody["stream_id"].(string)
	scope, valid := wsScope(fs.req.Metadata, fs.req.Model, lane)
	if !valid {
		return wsAliasLease{}, "no_socket_scope"
	}
	if fs.terminal["type"] != "response.completed" {
		return wsAliasLease{}, "not_committed"
	}
	visible, _ := fs.baseResponse["id"].(string)
	response, _ := fs.terminal["response"].(map[string]any)
	upstream, _ := response["id"].(string)
	if visible != "" && visible == upstream {
		return wsAliasLease{}, "not_needed"
	}
	lease, stored := foldedWSAliases.put(scope, visible, upstream, fs.runID)
	if !stored {
		return wsAliasLease{}, "unavailable_identity"
	}
	return lease, "response_alias"
}
