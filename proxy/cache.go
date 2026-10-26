package proxy

import (
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"net/http"
	"sync"
	"time"

	"github.com/chatwithgod/reflow/core"
)

type cachedResponse struct {
	request  core.Object
	upstream string
	size     int
	expires  time.Time
}

// ReplayCache contains only bounded in-memory state. Scopes include the
// credential and account fingerprint, never a user-supplied session id alone.
type ReplayCache struct {
	mu         sync.Mutex
	entries    map[string]*cachedResponse
	bytes      int
	maxBytes   int
	maxEntries int
	ttl        time.Duration
}

func NewReplayCache() *ReplayCache {
	return &ReplayCache{entries: map[string]*cachedResponse{}, maxBytes: 64 << 20, maxEntries: 256, ttl: 30 * time.Minute}
}

func credentialScope(h http.Header) string {
	hash := sha256.Sum256([]byte(h.Get("Authorization") + "\x00" + h.Get("ChatGPT-Account-ID")))
	return hex.EncodeToString(hash[:])
}

func inputItems(value any) []any {
	switch v := value.(type) {
	case []any:
		return append([]any{}, v...)
	case string:
		return []any{core.Object{"role": "user", "content": v}}
	default:
		return []any{}
	}
}

func (c *ReplayCache) Resolve(scope string, body core.Object) (wire, replay core.Object) {
	wire, _ = core.Clone(body)
	parent, _ := body["previous_response_id"].(string)
	if parent == "" {
		return wire, nil
	}
	c.mu.Lock()
	defer c.mu.Unlock()
	c.prune()
	entry := c.entries[scope+"/"+parent]
	if entry == nil {
		return wire, nil
	}
	model, _ := body["model"].(string)
	if model != "" && model != entry.request["model"] {
		return wire, nil
	}
	replay, _ = core.Clone(entry.request)
	items := inputItems(replay["input"])
	for k, v := range wire {
		if k != "input" && k != "previous_response_id" {
			replay[k] = v
		}
	}
	replay["input"] = append(items, inputItems(wire["input"])...)
	delete(replay, "previous_response_id")
	wire["previous_response_id"] = entry.upstream
	if model == "" {
		wire["model"] = entry.request["model"]
	}
	return wire, replay
}

func (c *ReplayCache) prune() {
	now := time.Now()
	for key, e := range c.entries {
		if now.After(e.expires) {
			c.bytes -= e.size
			delete(c.entries, key)
		}
	}
}

// Remember returns an idempotent rollback that cannot remove a newer revision.
func (c *ReplayCache) Remember(scope string, r core.Result) func() {
	if r.VisibleID == "" || r.UpstreamID == "" || r.ReplayRequest == nil {
		return func() {}
	}
	b, err := json.Marshal(r.ReplayRequest)
	if err != nil || len(b) > 8<<20 {
		return func() {}
	}
	request, _ := core.Clone(r.ReplayRequest)
	for _, key := range []string{"type", "stream_id", "stream", "generate"} {
		delete(request, key)
	}
	e := &cachedResponse{request: request, upstream: r.UpstreamID, size: len(b), expires: time.Now().Add(c.ttl)}
	key := scope + "/" + r.VisibleID
	c.mu.Lock()
	c.prune()
	if old := c.entries[key]; old != nil {
		c.bytes -= old.size
		delete(c.entries, key)
	}
	for len(c.entries) >= c.maxEntries || c.bytes+e.size > c.maxBytes {
		var oldestKey string
		var oldest *cachedResponse
		for k, v := range c.entries {
			if oldest == nil || v.expires.Before(oldest.expires) {
				oldestKey, oldest = k, v
			}
		}
		if oldest == nil {
			break
		}
		c.bytes -= oldest.size
		delete(c.entries, oldestKey)
	}
	c.entries[key] = e
	c.bytes += e.size
	c.mu.Unlock()
	return func() {
		c.mu.Lock()
		defer c.mu.Unlock()
		if c.entries[key] == e {
			delete(c.entries, key)
			c.bytes -= e.size
		}
	}
}
