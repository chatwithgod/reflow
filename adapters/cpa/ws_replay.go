package main

import (
	"encoding/json"
	"sync"
	"time"
)

// Incremental inputs are deltas, not complete prompts. Retain only the latest
// canonical input/output per host socket/model/lane so a hidden fold can replay
// the complete conversation without duplicating a tentative tool call. This is
// volatile sensitive state: no disk/log serialization, no client-header scope,
// no cross-socket recovery, no partial transcript on a miss or size overflow.
// Limits count serialized payload bytes, not Go heap/RSS.
const wsReplayTTL = 15 * time.Minute
const wsReplayCapacity = 64
const wsReplayMaxEntryBytes = 16 << 20
const wsReplayMaxBytes = 64 << 20

type wsReplayEntry struct {
	Visible, Upstream string
	Input             []byte
	Settings          []byte
	Expires           time.Time
	Revision          uint64
}

type wsReplayLease struct {
	Scope    wsAliasScope
	Revision uint64
}

type wsReplayCache struct {
	mu                          sync.Mutex
	entries                     map[wsAliasScope]wsReplayEntry
	capacity, maxEntry, maxSize int
	size                        int
	clock                       uint64
	ttl                         time.Duration
	now                         func() time.Time
}

func newWSReplayCache(capacity, maxEntry, maxSize int, ttl time.Duration, now func() time.Time) *wsReplayCache {
	return &wsReplayCache{entries: make(map[wsAliasScope]wsReplayEntry), capacity: capacity,
		maxEntry: maxEntry, maxSize: maxSize, ttl: ttl, now: now}
}

var foldedWSReplays = newWSReplayCache(wsReplayCapacity, wsReplayMaxEntryBytes, wsReplayMaxBytes, wsReplayTTL, time.Now)

func (c *wsReplayCache) remove(scope wsAliasScope) {
	if entry, exists := c.entries[scope]; exists {
		c.size -= len(entry.Input) + len(entry.Settings)
		delete(c.entries, scope)
	}
}

func (c *wsReplayCache) put(scope wsAliasScope, visible, upstream string, input []any) (wsReplayLease, string) {
	return c.putWithSettings(scope, visible, upstream, input, nil)
}

func (c *wsReplayCache) putWithSettings(scope wsAliasScope, visible, upstream string, input []any, body map[string]any) (wsReplayLease, string) {
	if visible == "" || upstream == "" || len(visible) > wsAliasMaxField || len(upstream) > wsAliasMaxField {
		return wsReplayLease{}, "unavailable_identity"
	}
	encoded, err := json.Marshal(input)
	settings := make(map[string]any, len(body))
	for key, value := range body {
		if key != "input" && key != "previous_response_id" && key != "type" && key != "generate" {
			settings[key] = value
		}
	}
	encodedSettings, settingsErr := json.Marshal(settings)
	size := len(encoded) + len(encodedSettings)
	c.mu.Lock()
	defer c.mu.Unlock()
	// Even an oversized new response advances upstream state. Never leave a
	// stale transcript eligible for a later delta on this scope.
	c.remove(scope)
	if err != nil || settingsErr != nil || c.capacity <= 0 || c.ttl <= 0 || size > c.maxEntry || size > c.maxSize {
		return wsReplayLease{}, "replay_size_limit"
	}
	now := c.now()
	for key, entry := range c.entries {
		if !now.Before(entry.Expires) {
			c.remove(key)
		}
	}
	for len(c.entries) >= c.capacity || c.size+size > c.maxSize {
		var oldest wsAliasScope
		age := ^uint64(0)
		for key, entry := range c.entries {
			if entry.Revision < age {
				oldest, age = key, entry.Revision
			}
		}
		c.remove(oldest)
	}
	c.clock++
	c.entries[scope] = wsReplayEntry{Visible: visible, Upstream: upstream, Input: encoded, Settings: encodedSettings,
		Expires: now.Add(c.ttl), Revision: c.clock}
	c.size += size
	return wsReplayLease{Scope: scope, Revision: c.clock}, "available"
}

func (c *wsReplayCache) get(scope wsAliasScope, parent string, delta []any) ([]any, string) {
	input, _, reason := c.getWithSettings(scope, parent, delta)
	return input, reason
}

func (c *wsReplayCache) getWithSettings(scope wsAliasScope, parent string, delta []any) ([]any, map[string]any, string) {
	c.mu.Lock()
	entry, exists := c.entries[scope]
	if exists && !c.now().Before(entry.Expires) {
		c.remove(scope)
		exists = false
	}
	if !exists || (parent != entry.Visible && parent != entry.Upstream) {
		c.mu.Unlock()
		return nil, nil, "replay_context_miss"
	}
	// Decode a private immutable snapshot outside the lock. Neither the caller
	// nor a simultaneous replacement can mutate the cache's byte slice.
	encoded := entry.Input
	c.mu.Unlock()
	var input []any
	var settings map[string]any
	if json.Unmarshal(encoded, &input) != nil || json.Unmarshal(entry.Settings, &settings) != nil {
		return nil, nil, "replay_context_miss"
	}
	input = append(input, delta...)
	if raw, err := json.Marshal(input); err != nil || len(raw)+len(entry.Settings) > c.maxEntry {
		return nil, nil, "replay_size_limit"
	}
	return input, settings, "available"
}

func (c *wsReplayCache) revoke(lease wsReplayLease) {
	c.mu.Lock()
	defer c.mu.Unlock()
	if entry, ok := c.entries[lease.Scope]; ok && entry.Revision == lease.Revision {
		c.remove(lease.Scope)
	}
}

func (c *wsReplayCache) invalidate(scope wsAliasScope) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.remove(scope)
}

func (c *wsReplayCache) clear() {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.entries = make(map[wsAliasScope]wsReplayEntry)
	c.size = 0
}

func (fs *foldState) commitWSReplay() wsReplayLease {
	if fs.req.SourceFormat != "codex" && fs.req.SourceFormat != "openai-response" {
		return wsReplayLease{}
	}
	lane, _ := fs.baseBody["stream_id"].(string)
	scope, valid := wsScope(fs.req.Metadata, fs.req.Model, lane)
	if !valid {
		return wsReplayLease{}
	}
	if fs.terminal["type"] != "response.completed" {
		foldedWSReplays.invalidate(scope)
		return wsReplayLease{}
	}
	visible, _ := fs.baseResponse["id"].(string)
	response, _ := fs.terminal["response"].(map[string]any)
	upstream, _ := response["id"].(string)
	input := append([]any(nil), fs.origInput...)
	for _, item := range fs.finalOutput {
		input = append(input, item)
	}
	lease, _ := foldedWSReplays.putWithSettings(scope, visible, upstream, input, fs.baseBody)
	return lease
}
