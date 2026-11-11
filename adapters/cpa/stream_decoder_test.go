package main

import (
	"bytes"
	"encoding/json"
	"reflect"
	"strings"
	"testing"
)

func drainDecoder(d *eventDecoder) ([]map[string]any, error) {
	var events []map[string]any
	for {
		ev, ready, err := d.next()
		if err != nil || !ready {
			return events, err
		}
		events = append(events, ev)
	}
}

func TestDecoderRawJSONAndSSEHaveIdenticalEvents(t *testing.T) {
	fixture := []byte(`{"type":"response.output_text.delta","delta":"中文 {quoted} data: \\\""}`)
	var expected []map[string]any
	for _, prefix := range []string{"", "data: ", "data:"} {
		var d eventDecoder
		if err := d.feed(append([]byte(prefix), fixture...)); err != nil {
			t.Fatal(err)
		}
		got, err := drainDecoder(&d)
		if err != nil || len(got) != 1 {
			t.Fatalf("prefix=%q: events=%v err=%v", prefix, got, err)
		}
		if expected == nil {
			expected = got
		} else if !reflect.DeepEqual(expected, got) {
			t.Fatalf("prefix=%q changed event: %v", prefix, got)
		}
		if err := d.finish(); err != nil {
			t.Fatal(err)
		}
	}
}

func TestDecoderFragmentedAtEveryByteBoundary(t *testing.T) {
	for _, fixture := range []string{
		`{"type":"response.created","response":{"id":"r","nested":{"a":[{"b":"中文 \\\" } data:"}]}}}`,
		`data: {"type":"response.completed","response":{"status":"completed"}}`,
		"event: response.created\r\ndata: {\"type\":\"response.created\"}\r\n\r\ndata: [DONE]\r\n\r\n",
	} {
		for split := 0; split <= len(fixture); split++ {
			var d eventDecoder
			var events []map[string]any
			for _, part := range []string{fixture[:split], fixture[split:]} {
				if err := d.feed([]byte(part)); err != nil {
					t.Fatal(err)
				}
				batch, err := drainDecoder(&d)
				if err != nil {
					t.Fatalf("split=%d: %v", split, err)
				}
				events = append(events, batch...)
			}
			if len(events) != 1 || d.finish() != nil {
				t.Fatalf("split=%d: decoded=%d, finish=%v", split, len(events), d.finish())
			}
		}
	}
}

func TestDecoderBytewiseAndConcatenatedFrames(t *testing.T) {
	fixture := ": heartbeat\nretry: 1000\nid: 7\n" +
		`data:{"type":"response.created","response":{"id":"r"}}` +
		`{"type":"response.output_text.delta","delta":"data: is text, not framing"}` +
		`data: {"type":"response.completed"}data: [DONE]`
	var d eventDecoder
	var events []map[string]any
	for _, b := range []byte(fixture) {
		if err := d.feed([]byte{b}); err != nil {
			t.Fatal(err)
		}
		batch, err := drainDecoder(&d)
		if err != nil {
			t.Fatal(err)
		}
		events = append(events, batch...)
	}
	if len(events) != 3 || d.finish() != nil {
		t.Fatalf("events=%d finish=%v", len(events), d.finish())
	}
	if events[1]["delta"] != "data: is text, not framing" {
		t.Fatal("JSON text was treated as an SSE prefix")
	}
}

func TestDecoderCPAScannedLinesWithoutNewlines(t *testing.T) {
	// The real host scans HTTP SSE into individual lines, dropping newlines.
	// It must not concatenate event: + data: into one endless control line.
	for _, controls := range [][]string{
		{"event: response.created"},
		{": heartbeat", "retry: 1000", "id: fixture", "event: response.created"},
	} {
		var d eventDecoder
		var events []map[string]any
		chunks := append(append([]string(nil), controls...),
			`data: {"type":"response.created","response":{"id":"r"}}`,
			"", "event: response.output_text.delta",
			`data: {"type":"response.output_text.delta","delta":"data: and event: are text"}`,
			"", "event: response.completed", "data:",
			` {"type":"response.completed","response":{"status":"completed"}}`,
			"", "data: [DONE]")
		for _, chunk := range chunks {
			if err := d.feed([]byte(chunk)); err != nil {
				t.Fatal(err)
			}
			batch, err := drainDecoder(&d)
			if err != nil {
				t.Fatal(err)
			}
			events = append(events, batch...)
		}
		if len(events) != 3 || d.finish() != nil {
			t.Fatalf("CPA line chunks decoded=%d, finish=%v", len(events), d.finish())
		}
		if events[1]["delta"] != "data: and event: are text" {
			t.Fatal("JSON content was mistaken for SSE control metadata")
		}
	}
}

func TestDecoderRejectsInvalidEventsWithoutLeakingContent(t *testing.T) {
	for _, fixture := range []string{
		`secret_token_123`,
		`data: data: {"type":"response.created"}`,
		`{"type":"response.created", "secret_token_123": }`,
		`{"secret_token_123":"value"}`,
		`data: [1,2,3]`,
		`{"type":123}`,
	} {
		var d eventDecoder
		if err := d.feed([]byte(fixture)); err != nil {
			t.Fatal(err)
		}
		_, err := drainDecoder(&d)
		if err == nil {
			t.Fatalf("accepted invalid fixture: %s", fixture)
		}
		if strings.Contains(err.Error(), "secret_token_123") {
			t.Fatal("error message leaked event content")
		}
	}
}

func TestDecoderUnexpectedEOF(t *testing.T) {
	for _, fixture := range []string{`data:`, `da`, `{"type":"response.created"`, `data: [DO`} {
		var d eventDecoder
		_ = d.feed([]byte(fixture))
		_, err := drainDecoder(&d)
		if err != nil {
			t.Fatal(err)
		}
		if d.finish() == nil {
			t.Fatalf("unfinished event should fail at EOF: %q", fixture)
		}
	}
}

func TestDecoderChecksLimitBeforeAllocating(t *testing.T) {
	var d eventDecoder
	if err := d.feed(make([]byte, maxStreamBufferSize+1)); err == nil {
		t.Fatal("oversized input accepted")
	}
	if len(d.buffer) != 0 {
		t.Fatal("oversized data allocated before validation")
	}
}

func TestWebSocketRawEventsKeepEncryptedReasoningAndToolCall(t *testing.T) {
	fs := newFoldState(map[string]any{}, nil, rpcExecutorRequest{}, "")
	fs.roundNo = 1
	fixtures := []string{
		`{"type":"response.created","response":{"id":"r"}}`,
		`{"type":"response.output_item.added","output_index":0,"item":{"type":"reasoning","id":"rs"}}`,
		`{"type":"response.output_item.done","output_index":0,"item":{"type":"reasoning","id":"rs","encrypted_content":"opaque-test-only"}}`,
		`{"type":"response.output_item.added","output_index":1,"item":{"type":"function_call","id":"fc","call_id":"call_1","name":"lookup","arguments":""}}`,
		`{"type":"response.function_call_arguments.delta","output_index":1,"delta":"{\"q\":\"中文\"}"}`,
		`{"type":"response.output_item.done","output_index":1,"item":{"type":"function_call","id":"fc","call_id":"call_1","name":"lookup","arguments":"{\"q\":\"中文\"}"}}`,
		`{"type":"response.completed","response":{"id":"r","status":"completed","usage":{"output_tokens":59,"output_tokens_details":{"reasoning_tokens":40}}}}`,
	}
	var terminal map[string]any
	for _, fixture := range fixtures {
		var err error
		terminal, err = fs.processAndEmit([]byte(fixture), "")
		if err != nil {
			t.Fatal(err)
		}
	}
	if terminal == nil || !fs.hasEncryptedContent() {
		t.Fatal("raw JSON was not processed as a completed reasoning round")
	}
	fs.endRound(terminal, fs.usage)
	if fs.shouldContinue() {
		t.Fatal("a normal 40-token round must not trigger continuation")
	}
	if err := fs.flushCleanStop(""); err != nil {
		t.Fatal(err)
	}
	if len(fs.finalOutput) != 2 || fs.finalOutput[1]["call_id"] != "call_1" ||
		fs.finalOutput[0]["encrypted_content"] != "opaque-test-only" {
		t.Fatalf("reasoning or tool call lost: %v", fs.finalOutput)
	}
}

func TestResponseDoneAliasPreservesFailureAndIncomplete(t *testing.T) {
	for _, status := range []string{"completed", "failed", "incomplete"} {
		fs := newFoldState(nil, nil, rpcExecutorRequest{}, "")
		ev := map[string]any{"type": "response.done", "response": map[string]any{"status": status}}
		term, err := fs.processEvent(ev, "")
		if err != nil || term == nil || term["type"] != "response."+status {
			t.Fatalf("status=%s term=%v err=%v", status, term, err)
		}
	}
}

func TestPluginRegistrationUsesIndependentIDAndDirectResponses(t *testing.T) {
	reg := pluginRegistration()
	for field, value := range map[string]string{
		"name": reg.Metadata.Name, "version": reg.Metadata.Version,
		"author": reg.Metadata.Author, "source": reg.Metadata.GitHubRepository,
	} {
		if strings.TrimSpace(value) == "" {
			t.Fatalf("CPA requires nonempty registration metadata: %s", field)
		}
	}
	if pluginIdentifier != "codexreflow" || reg.Metadata.Name != pluginIdentifier {
		t.Fatal("fork must not reuse the codexcomp plugin ID")
	}
	if !reflect.DeepEqual(reg.Capabilities.ExecutorInputFormats, []string{"codex"}) ||
		!reflect.DeepEqual(reg.Capabilities.ExecutorOutputFormats, []string{"codex", "openai-response"}) {
		t.Fatal("Responses must bypass host identity translation; other protocols must retain codex translation")
	}
	if reg.Metadata.GitHubRepository == "https://github.com/uf-hy/cpa-plugin-codexcomp" {
		t.Fatal("fork must not advertise the upstream repository as its own release source")
	}
}

func FuzzDecoderChunkBoundaries(f *testing.F) {
	f.Add("中文 } data: \\", uint8(1))
	f.Add("plain text", uint8(7))
	f.Fuzz(func(t *testing.T, delta string, width uint8) {
		if len(delta) > 4096 {
			t.Skip()
		}
		fixture, _ := json.Marshal(map[string]any{"type": "response.output_text.delta", "delta": delta})
		// Marshal may replace invalid UTF-8. Compare to the canonical parsed value.
		var expected map[string]any
		_ = json.Unmarshal(fixture, &expected)
		wire := append([]byte("data: "), fixture...)
		wire = append(wire, '\n', '\n')
		step := int(width)%31 + 1
		var d eventDecoder
		var events []map[string]any
		for offset := 0; offset < len(wire); offset += step {
			end := min(offset+step, len(wire))
			if err := d.feed(wire[offset:end]); err != nil {
				t.Fatal(err)
			}
			batch, err := drainDecoder(&d)
			if err != nil {
				t.Fatal(err)
			}
			events = append(events, batch...)
		}
		if len(events) != 1 || !reflect.DeepEqual(events[0], expected) || d.finish() != nil {
			t.Fatalf("fragmentation changed event; wire=%q", bytes.TrimSpace(wire))
		}
	})
}
