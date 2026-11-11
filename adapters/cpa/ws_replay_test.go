package main

import (
	"sync"
	"testing"
	"time"
)

func TestWSReplayCacheIsolationBoundsAndExpiry(t *testing.T) {
	now := time.Unix(100, 0)
	cache := newWSReplayCache(2, 128, 200, time.Minute, func() time.Time { return now })
	scope := wsAliasScope{Model: "fixture", Lane: "one"}
	input := []any{map[string]any{"type": "message", "content": "private fixture"}}
	lease, status := cache.put(scope, "visible", "upstream", input)
	if status != "available" {
		t.Fatal(status)
	}
	input[0].(map[string]any)["content"] = "mutation"
	for _, parent := range []string{"visible", "upstream"} {
		got, status := cache.get(scope, parent, []any{map[string]any{"content": "delta"}})
		if status != "available" || len(got) != 2 || got[0].(map[string]any)["content"] != "private fixture" {
			t.Fatal(got, status)
		}
		got[0].(map[string]any)["content"] = "caller mutation"
	}
	for _, other := range []wsAliasScope{{Model: "other", Lane: "one"}, {Model: "fixture", Lane: "two"}, {Session: [32]byte{1}, Model: "fixture", Lane: "one"}} {
		if _, reason := cache.get(other, "visible", nil); reason != "replay_context_miss" {
			t.Fatal("context crossed scope", reason)
		}
	}
	if _, reason := cache.get(scope, "unrelated", nil); reason != "replay_context_miss" {
		t.Fatal(reason)
	}
	newLease, _ := cache.put(scope, "new", "new-upstream", nil)
	cache.revoke(lease)
	if _, reason := cache.get(scope, "new", nil); reason != "available" {
		t.Fatal("old revocation removed new context")
	}
	cache.revoke(newLease)
	cache.put(scope, "visible", "upstream", nil)
	now = now.Add(time.Minute)
	if _, status := cache.get(scope, "visible", nil); status != "replay_context_miss" || cache.size != 0 {
		t.Fatal("expired context retained", status, cache.size)
	}
	cache.put(scope, "visible", "upstream", nil)
	if _, reason := cache.put(scope, "large", "large", []any{string(make([]byte, 200))}); reason != "replay_size_limit" {
		t.Fatal(reason)
	}
	if _, reason := cache.get(scope, "visible", nil); reason != "replay_context_miss" {
		t.Fatal("oversized new response retained stale context")
	}
	for _, model := range []string{"a", "b", "c"} {
		cache.put(wsAliasScope{Model: model}, model, model, []any{"fixture"})
	}
	if len(cache.entries) != 2 || cache.size > cache.maxSize {
		t.Fatal("unbounded cache", len(cache.entries), cache.size)
	}
	if _, reason := cache.get(wsAliasScope{Model: "a"}, "a", nil); reason != "replay_context_miss" {
		t.Fatal("oldest scope not evicted")
	}
	cache.clear()
	if cache.size != 0 || len(cache.entries) != 0 {
		t.Fatal("shutdown retained private context")
	}
}

func TestWSReplayCacheConcurrent(t *testing.T) {
	cache := newWSReplayCache(8, 1024, 8192, time.Minute, time.Now)
	var group sync.WaitGroup
	for n := 0; n < 8; n++ {
		group.Add(1)
		go func(n int) {
			defer group.Done()
			scope := wsAliasScope{Session: [32]byte{byte(n)}, Model: "fixture"}
			for k := 0; k < 100; k++ {
				lease, _ := cache.put(scope, "visible", "upstream", []any{"fixture"})
				cache.get(scope, "visible", nil)
				cache.revoke(lease)
			}
		}(n)
	}
	group.Wait()
}

func TestWSReplaySettingsPrivateSnapshot(t *testing.T) {
	cache := newWSReplayCache(2, 4096, 8192, time.Minute, time.Now)
	scope := wsAliasScope{Model: "fixture"}
	settings := map[string]any{"input": []any{"do not duplicate"}, "previous_response_id": "old",
		"instructions": "fixture instructions", "tools": []any{map[string]any{"name": "fixture-tool"}}}
	cache.putWithSettings(scope, "visible", "upstream", []any{"fixture context"}, settings)
	settings["instructions"] = "changed"
	_, stored, reason := cache.getWithSettings(scope, "visible", nil)
	if reason != "available" || stored["instructions"] != "fixture instructions" || stored["input"] != nil || stored["previous_response_id"] != nil {
		t.Fatal("canonical settings snapshot is inconsistent")
	}
	stored["tools"].([]any)[0].(map[string]any)["name"] = "mutation"
	_, next, _ := cache.getWithSettings(scope, "visible", nil)
	if next["tools"].([]any)[0].(map[string]any)["name"] != "fixture-tool" {
		t.Fatal("caller mutated cached tool definitions")
	}
}
