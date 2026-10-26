package proxy

import (
	"crypto/sha256"
	"encoding/binary"
	"sync"
	"time"

	"github.com/chatwithgod/reflow/core"
)

const maxPendingTools = 256

// Tool observations retain bounded digests only, never identifiers or payloads.
// A returned result proves API correlation, not successful tool execution.
type toolBatch struct {
	parent    [32]byte
	committed bool
}

type pendingTool struct {
	batch   *toolBatch
	item    [32]byte
	expires time.Time
	seen    bool
}

func toolDigest(parts ...string) [32]byte {
	h := sha256.New()
	var length [8]byte
	for _, part := range parts {
		binary.BigEndian.PutUint64(length[:], uint64(len(part)))
		h.Write(length[:])
		h.Write([]byte(part))
	}
	var result [32]byte
	copy(result[:], h.Sum(nil))
	return result
}

func toolID(value any) string {
	id, _ := value.(string)
	if len(id) > 1024 {
		return ""
	}
	return id
}

func toolItems(value any) []core.Object {
	switch items := value.(type) {
	case []core.Object:
		return items
	case []any:
		out := make([]core.Object, 0, len(items))
		for _, value := range items {
			if item, ok := value.(map[string]any); ok {
				out = append(out, item)
			}
		}
		return out
	}
	return nil
}

func (s *metricsStore) pruneTools(now time.Time) {
	for key, item := range s.tools {
		if !now.Before(item.expires) {
			delete(s.tools, key)
			s.value.ToolTrackingDrops++
		}
	}
}

// prepareTools registers only the retained final response of a continued fold.
// The callback commits after all visible events are written, or rolls back.
// A concurrent result received before commit stays provisional until delivery.
func (s *metricsStore) prepareTools(scope, model string, result core.Result, events []core.Object) func(bool) {
	noop := func(bool) {}
	if s == nil || result.Rounds <= 1 || result.Status != "completed" || toolID(result.VisibleID) == "" || toolID(model) == "" {
		return noop
	}
	var output []core.Object
	for _, event := range events {
		if event["type"] == "response.completed" {
			response, _ := event["response"].(map[string]any)
			output = toolItems(response["output"])
		}
	}
	batch := &toolBatch{parent: toolDigest(scope, model, result.VisibleID)}
	now := time.Now()
	entries := make(map[[32]byte]*pendingTool)
	var calls int64
	ambiguous := false
	for _, item := range output {
		kind := toolID(item["type"])
		if kind != "function_call" && kind != "custom_tool_call" {
			continue
		}
		calls++
		id := toolID(item["call_id"])
		if id == "" {
			ambiguous = true
			continue
		}
		key := toolDigest(scope, model, kind, id)
		if entries[key] != nil || len(entries) >= maxPendingTools {
			ambiguous = true
			continue
		}
		entry := &pendingTool{batch: batch, expires: now.Add(30 * time.Minute)}
		if itemID := toolID(item["id"]); itemID != "" {
			entry.item = toolDigest(itemID)
		}
		entries[key] = entry
	}
	if calls == 0 {
		return noop
	}
	s.mu.Lock()
	s.pruneTools(now)
	track := !ambiguous && len(entries)+len(s.tools) <= maxPendingTools
	for key := range entries {
		if s.tools[key] != nil {
			track = false
		}
	}
	if track {
		if s.tools == nil {
			s.tools = make(map[[32]byte]*pendingTool)
		}
		for key, entry := range entries {
			s.tools[key] = entry
		}
	}
	s.mu.Unlock()
	var once sync.Once
	return func(delivered bool) {
		once.Do(func() {
			s.mu.Lock()
			defer s.mu.Unlock()
			if delivered {
				s.value.ContinuedToolResponses++
				s.value.ContinuedToolCalls += calls
				batch.committed = true
				if !track {
					s.value.ToolTrackingDrops += calls
				}
			}
			for key, expected := range entries {
				if s.tools[key] != expected {
					continue
				}
				if !delivered || expected.seen {
					delete(s.tools, key)
					if delivered && expected.seen {
						s.value.ContinuedToolResults++
					}
				}
			}
		})
	}
}

// toolResults observes the original client request, before parent-ID rewriting.
// It requires either the visible parent ID, or the exact retained item ID in
// full history before its result. Ambiguous/ID-stripped histories are not proof.
func (s *metricsStore) toolResults(scope string, request core.Object) {
	if s == nil || request["generate"] == false {
		return
	}
	model := toolID(request["model"])
	if model == "" {
		return
	}
	parent := toolID(request["previous_response_id"])
	parentDigest := toolDigest(scope, model, parent)
	s.mu.Lock()
	defer s.mu.Unlock()
	s.pruneTools(time.Now())
	seenCalls := make(map[[32]byte][32]byte)
	for _, item := range toolItems(request["input"]) {
		kind, id := toolID(item["type"]), toolID(item["call_id"])
		if id == "" {
			continue
		}
		if kind == "function_call" || kind == "custom_tool_call" {
			key := toolDigest(scope, model, kind, id)
			delete(seenCalls, key)
			if itemID := toolID(item["id"]); itemID != "" && s.tools[key] != nil {
				seenCalls[key] = toolDigest(itemID)
			}
			continue
		}
		switch kind {
		case "function_call_output":
			kind = "function_call"
		case "custom_tool_call_output":
			kind = "custom_tool_call"
		default:
			continue
		}
		if _, present := item["output"]; !present {
			continue
		}
		key := toolDigest(scope, model, kind, id)
		entry := s.tools[key]
		if entry == nil {
			continue
		}
		if parent != "" {
			if parentDigest != entry.batch.parent {
				continue
			}
		} else if entry.item == ([32]byte{}) || seenCalls[key] != entry.item {
			continue
		}
		if entry.batch.committed {
			s.value.ContinuedToolResults++
			delete(s.tools, key)
		} else {
			entry.seen = true
		}
	}
}
