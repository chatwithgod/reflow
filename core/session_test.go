package core

import (
	"encoding/json"
	"reflect"
	"strings"
	"testing"
)

func fixtureRound(id string, tokens int, encrypted bool, tool bool) []Object {
	item := Object{"id": id + "-r", "type": "reasoning", "summary": []any{}}
	if encrypted {
		item["encrypted_content"] = "synthetic-" + id
	}
	answer := Object{"id": id + "-a", "type": "message", "role": "assistant", "status": "completed", "phase": "final_answer", "content": []any{Object{"type": "output_text", "text": id}}}
	if tool {
		answer = Object{"type": "function_call", "id": id + "-f", "call_id": id + "-call", "name": "inspect", "arguments": "{}", "status": "completed"}
	}
	usage := Object{"input_tokens": 100, "output_tokens": tokens + 10, "total_tokens": 110 + tokens, "input_tokens_details": Object{"cached_tokens": 20}, "output_tokens_details": Object{"reasoning_tokens": tokens}}
	return []Object{
		{"type": "response.created", "response": Object{"id": id, "status": "in_progress", "output": []any{}, "error": nil}},
		{"type": "response.output_item.added", "output_index": 0, "item": Object{"id": id + "-r", "type": "reasoning", "summary": []any{}}},
		{"type": "response.output_item.done", "output_index": 0, "item": item},
		{"type": "response.output_item.added", "output_index": 1, "item": answer},
		{"type": "response.output_item.done", "output_index": 1, "item": answer},
		{"type": "response.completed", "response": Object{"id": id, "status": "completed", "output": []any{item, answer}, "usage": usage, "error": nil}},
	}
}

func feed(t *testing.T, s *Session, events []Object) []Object {
	t.Helper()
	var out []Object
	for _, ev := range events {
		es, err := s.Push(ev)
		if err != nil {
			t.Fatal(err)
		}
		out = append(out, es...)
	}
	return out
}

func newSession(t *testing.T, c Config) *Session {
	t.Helper()
	s, err := New(c, Object{"model": "gpt-6.1-sol", "input": []any{Object{"role": "user", "content": "synthetic task"}}, "tools": []any{}}, nil)
	if err != nil {
		t.Fatal(err)
	}
	return s
}

func TestFoldHoldsDiscardedToolsAndPreservesNextTurnState(t *testing.T) {
	s := newSession(t, DefaultConfig())
	events := feed(t, s, fixtureRound("first", 516, true, true))
	d, err := s.Finish()
	if err != nil || d.Next == nil {
		t.Fatalf("decision=%v err=%v", d, err)
	}
	encoded, _ := json.Marshal(events)
	if strings.Contains(string(encoded), "first-call") {
		t.Fatal("discarded tool escaped")
	}
	input := d.Next["input"].([]any)
	if len(input) != 3 {
		t.Fatalf("continuation input=%v", input)
	}
	if input[1].(map[string]any)["encrypted_content"] != "synthetic-first" {
		t.Fatal("reasoning state lost")
	}
	events = append(events, feed(t, s, fixtureRound("last", 23, true, true))...)
	d, err = s.Finish()
	if err != nil || d.Next != nil {
		t.Fatalf("finish=%v err=%v", d, err)
	}
	events = append(events, d.Events...)
	encoded, _ = json.Marshal(events)
	if strings.Contains(string(encoded), "first-call") || !strings.Contains(string(encoded), "last-call") {
		t.Fatal("incorrect tool visibility")
	}
	if d.Result.VisibleID != "first" || d.Result.UpstreamID != "last" || d.Result.Rounds != 2 {
		t.Fatalf("result=%+v", d.Result)
	}
	terminal := events[len(events)-1]["response"].(map[string]any)
	if len(terminal["output"].([]map[string]any)) != 3 {
		t.Fatal("fold output lost items")
	}
	usage := terminal["usage"].(map[string]any)
	if usage["input_tokens"] != float64(100) || usage["output_tokens"] != float64(549) {
		t.Fatalf("client usage=%v", usage)
	}
	if d.Result.BilledUsage["input_tokens"] != float64(200) {
		t.Fatal("billed usage lost second input")
	}
	replay := d.Result.ReplayRequest["input"].([]any)
	if len(replay) != 5 || replay[4].(map[string]any)["call_id"] != "last-call" {
		t.Fatalf("next turn replay=%v", replay)
	}
	for i, ev := range events {
		if ev["sequence_number"] != i {
			t.Fatalf("sequence %d=%v", i, ev["sequence_number"])
		}
	}
}

func TestStopConditions(t *testing.T) {
	for _, tc := range []struct {
		name      string
		tokens    int
		encrypted bool
		limit     int
		parent    string
		want      string
	}{
		{"ordinary", 47, true, 3, "", "rule_not_matched"},
		{"missing encrypted", 516, false, 3, "", "no_encrypted_content"},
		{"budget zero", 516, true, 0, "", "max_continue"},
		{"unknown parent", 516, true, 3, "other", "unresolved_parent"},
	} {
		t.Run(tc.name, func(t *testing.T) {
			c := DefaultConfig()
			c.MaxContinue = tc.limit
			body := Object{"model": "gpt-6.1-sol", "input": []any{}}
			if tc.parent != "" {
				body["previous_response_id"] = tc.parent
			}
			s, err := New(c, body, nil)
			if err != nil {
				t.Fatal(err)
			}
			feed(t, s, fixtureRound("r", tc.tokens, tc.encrypted, false))
			d, err := s.Finish()
			if err != nil || d.Next != nil || d.Result.StopReason != tc.want {
				t.Fatalf("%+v %v", d, err)
			}
		})
	}
}

func TestFailedRoundDoesNotReleaseToolAndKeepsError(t *testing.T) {
	s := newSession(t, DefaultConfig())
	es := fixtureRound("r", 516, true, true)
	es[len(es)-1]["type"] = "response.failed"
	r := es[len(es)-1]["response"].(Object)
	r["status"] = "failed"
	r["error"] = Object{"code": "synthetic_failure"}
	out := feed(t, s, es)
	d, err := s.Finish()
	if err != nil {
		t.Fatal(err)
	}
	out = append(out, d.Events...)
	b, _ := json.Marshal(out)
	if strings.Contains(string(b), "r-call") || !strings.Contains(string(b), "synthetic_failure") {
		t.Fatalf("failed response=%s", b)
	}
}

func TestCoreDoesNotMutateInputs(t *testing.T) {
	body := Object{"model": "gpt-6.1-sol", "input": []any{}, "tools": []any{}}
	before, _ := json.Marshal(body)
	s, err := New(DefaultConfig(), body, nil)
	if err != nil {
		t.Fatal(err)
	}
	es := fixtureRound("r", 516, true, false)
	saved, _ := json.Marshal(es)
	feed(t, s, es)
	_, err = s.Finish()
	if err != nil {
		t.Fatal(err)
	}
	after, _ := json.Marshal(body)
	eventsAfter, _ := json.Marshal(es)
	if !reflect.DeepEqual(before, after) || !reflect.DeepEqual(saved, eventsAfter) {
		t.Fatal("caller data mutated")
	}
}

func TestBoundedBufferAndAbort(t *testing.T) {
	c := DefaultConfig()
	c.MaxBufferedBytes = 1024
	s := newSession(t, c)
	feed(t, s, fixtureRound("r", 516, true, false)[:4])
	_, err := s.Push(Object{"type": "response.output_text.delta", "output_index": 1, "delta": strings.Repeat("x", 2000)})
	if err == nil {
		t.Fatal("unbounded buffer")
	}
	ev := s.Abort("buffer_limit")
	if ev["type"] != "response.incomplete" {
		t.Fatal(ev)
	}
}

func TestEmptyInputStaysArray(t *testing.T) {
	s, err := New(DefaultConfig(), Object{"model": "gpt-6.1-sol", "input": []any{}}, nil)
	if err != nil {
		t.Fatal(err)
	}
	feed(t, s, fixtureRound("r", 516, true, false))
	d, err := s.Finish()
	if err != nil {
		t.Fatal(err)
	}
	b, _ := json.Marshal(d.Next)
	if strings.Contains(string(b), `"input":null`) {
		t.Fatal("null input")
	}
}
