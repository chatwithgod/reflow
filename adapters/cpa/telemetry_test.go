package main

import (
	"encoding/json"
	"math"
	"regexp"
	"strings"
	"testing"
)

func TestReflowRunIDUniqueness(t *testing.T) {
	seen := map[string]bool{}
	pattern := regexp.MustCompile(`^[0-9a-f]{24}$`)
	for i := 0; i < 1000; i++ {
		id := newReflowRunID()
		if !pattern.MatchString(id) || seen[id] {
			t.Fatal("invalid/duplicate per-fold run ID")
		}
		seen[id] = true
	}
}

func TestRoundDiagnosticsWhitelistAndUnknownCounters(t *testing.T) {
	fs := newFoldState(nil, nil, rpcExecutorRequest{}, "")
	fs.roundNo = 2
	fs.nativeWS = true
	fs.terminal = map[string]any{"type": "response.completed", "response": map[string]any{"id": "private_response", "output": "private_output"}}
	fs.usage = map[string]any{
		"input_tokens": float64(1000), "output_tokens": float64(526), "total_tokens": float64(1526),
		"input_tokens_details":  map[string]any{"cached_tokens": float64(800), "private": "private_prompt"},
		"output_tokens_details": map[string]any{"reasoning_tokens": float64(516), "encrypted_content": "private_encrypted"},
		"auth_id":               "private_auth",
	}
	fields := fs.roundTelemetry()
	usage := fields["reported_usage"].(map[string]any)
	if fields["run_id"] != fs.runID || fields["round"] != 2 || fields["path"] != "ws_incremental" || usage["reasoning_tokens"] != int64(516) || len(usage) != 5 {
		t.Fatalf("incorrect round diagnostics: %v", fields)
	}
	raw, _ := json.Marshal(fields)
	for _, forbidden := range []string{"private", "auth_id", "encrypted_content", "response_id"} {
		if strings.Contains(string(raw), forbidden) {
			t.Fatalf("diagnostic leaked %s", forbidden)
		}
	}
	fs.terminal = map[string]any{"type": "private_event"}
	fs.usage = nil
	fields = fs.roundTelemetry()
	if fields["terminal"] != "unknown" {
		t.Fatal("untrusted event type logged")
	}
	for _, value := range fields["reported_usage"].(map[string]any) {
		if value != nil {
			t.Fatal("unknown usage fabricated as a number")
		}
	}
}

func TestDiagnosticCounterValidation(t *testing.T) {
	for _, value := range []any{nil, "516", true, -1, float64(-1), 1.5, math.NaN(), math.Inf(1), float64(1 << 53), map[string]any{"private": "text"}} {
		if diagnosticToken(value) != nil {
			t.Fatalf("accepted invalid counter: %v", value)
		}
	}
	for _, value := range []any{0, 516, float64(0), float64(516)} {
		if diagnosticToken(value) == nil {
			t.Fatalf("rejected valid counter: %v", value)
		}
	}
}

func TestDiagnosticsDoNotInventUsageJoin(t *testing.T) {
	fs := newFoldState(nil, nil, rpcExecutorRequest{}, "")
	fields := fs.telemetry("")
	if fields["usage_join"] != "unavailable" || fields["diagnostic_schema"] != diagnosticSchema {
		t.Fatal("must not equate lifecycle / WS trace / usage execution identifiers")
	}
	if fs.diagnosticEvent("fold_started")["path"] != "executor" {
		t.Fatal("wrong root path")
	}
}

func TestReflowTelemetryDoesNotRetainPayload(t *testing.T) {
	fs := newFoldState(map[string]any{"input": "private_fixture_prompt", "encrypted_content": "private_fixture_encrypted"}, nil, rpcExecutorRequest{}, "")
	fs.roundNo = 3
	fs.roundsInfo = []map[string]any{{"round": 1}, {"round": 2}}
	fs.bridgeStatus = "response_alias"
	m := fs.telemetry("upstream_error")
	if m["rounds_started"] != 3 || m["rounds_completed"] != 2 || m["continuations_started"] != 2 || m["continuations_completed"] != 1 {
		t.Fatal("attempts and completed rounds conflated")
	}
	raw, _ := json.Marshal(m)
	for _, private := range []string{"private_fixture", "encrypted_content", "input", "auth_id", "session_id", "response_id"} {
		if strings.Contains(string(raw), private) {
			t.Fatalf("payload/identity leaked via %s", private)
		}
	}
}

func TestReflowTelemetryPreservesMetadata(t *testing.T) {
	fs := newFoldState(nil, nil, rpcExecutorRequest{}, "")
	fs.roundNo = 1
	fs.roundsInfo = []map[string]any{{"round": 1}}
	ev := map[string]any{"type": "response.completed", "response": map[string]any{"metadata": map[string]any{"fixture": "preserved", "proxy_rounds": fs.roundsInfo}}}
	fs.annotateEvent(ev, "")
	meta := ev["response"].(map[string]any)["metadata"].(map[string]any)
	info := meta["proxy_reflow"].(map[string]any)
	if meta["fixture"] != "preserved" || meta["proxy_rounds"] == nil || info["run_id"] != fs.runID || info["stop_reason"] != "normal" || info["continuations_started"] != 0 {
		t.Fatal("terminal evidence missing/corrupted")
	}
}

func TestReflowResultTelemetryDoesNotMislabelErrors(t *testing.T) {
	fs := newFoldState(nil, nil, rpcExecutorRequest{}, "")
	for _, reason := range []string{"upstream_error", "upstream_eof", "downstream_emit_error", "aborted"} {
		fields := fs.resultTelemetry("response.incomplete", "not_emitted", reason)
		if fields["stop_reason"] != reason || fields["result"] != "response.incomplete" || fields["emission"] != "not_emitted" {
			t.Fatalf("incorrect finish evidence: %v", fields)
		}
	}
	for kind, reason := range map[string]string{"response.failed": "upstream_failed", "response.incomplete": "upstream_incomplete"} {
		fs.terminal = map[string]any{"type": kind}
		event := fs.terminalEvent()
		info := event["response"].(map[string]any)["metadata"].(map[string]any)["proxy_reflow"].(map[string]any)
		if info["stop_reason"] != reason || event["type"] != kind {
			t.Fatalf("incorrect terminal evidence: %v", event)
		}
	}
}
