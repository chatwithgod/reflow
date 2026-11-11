package main

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"math"
	"sync/atomic"
	"time"
)

var fallbackRunSequence atomic.Uint64

const diagnosticSchema = 1

func newReflowRunID() string {
	var random [12]byte
	if _, err := rand.Read(random[:]); err == nil {
		return hex.EncodeToString(random[:])
	}
	return fmt.Sprintf("local-%x-%x", time.Now().UnixNano(), fallbackRunSequence.Add(1))
}

func logReflowEvent(fields map[string]any) {
	// Fixed fields only: never include requests, headers, auth IDs, upstream
	// response IDs, output text or encrypted_content in these diagnostics.
	fields["plugin"] = pluginIdentifier
	fields["version"] = pluginVersion
	if raw, err := json.Marshal(fields); err == nil {
		pluginLog("info", string(raw))
	}
}

func nonNegative(value int) int {
	if value < 0 {
		return 0
	}
	return value
}

func (fs *foldState) diagnosticEvent(event string) map[string]any {
	path := "executor"
	if fs.nativeWS {
		path = "ws_incremental"
	}
	return map[string]any{
		"event": event, "diagnostic_schema": diagnosticSchema,
		"run_id": fs.runID, "path": path,
	}
}

// Counters are provider-reported, not billing measurements. Unknown/invalid
// values remain null, never a fabricated zero. Do not serialize arbitrary
// provider usage maps: they can contain text or nested private data.
func diagnosticToken(value any) any {
	var n float64
	switch v := value.(type) {
	case float64:
		n = v
	case int:
		n = float64(v)
	default:
		return nil
	}
	if math.IsNaN(n) || math.IsInf(n, 0) || n < 0 || n > (1<<53)-1 || math.Trunc(n) != n {
		return nil
	}
	return int64(n)
}

func (fs *foldState) roundTelemetry() map[string]any {
	fields := fs.diagnosticEvent("round_finished")
	fields["round"] = fs.roundNo
	kind, _ := fs.terminal["type"].(string)
	switch kind {
	case "response.completed", "response.incomplete", "response.failed":
		fields["terminal"] = kind
	default:
		fields["terminal"] = "unknown"
	}
	inputDetails, _ := fs.usage["input_tokens_details"].(map[string]any)
	outputDetails, _ := fs.usage["output_tokens_details"].(map[string]any)
	fields["reported_usage"] = map[string]any{
		"input_tokens":     diagnosticToken(fs.usage["input_tokens"]),
		"output_tokens":    diagnosticToken(fs.usage["output_tokens"]),
		"total_tokens":     diagnosticToken(fs.usage["total_tokens"]),
		"cached_tokens":    diagnosticToken(inputDetails["cached_tokens"]),
		"reasoning_tokens": diagnosticToken(outputDetails["reasoning_tokens"]),
	}
	return fields
}

func (fs *foldState) telemetry(stopReason string) map[string]any {
	if stopReason == "" {
		stopReason = "normal"
	}
	bridge := fs.bridgeStatus
	if bridge == "" {
		bridge = "not_needed"
	}
	fields := map[string]any{
		"plugin": pluginIdentifier, "version": pluginVersion, "run_id": fs.runID,
		"diagnostic_schema": diagnosticSchema,
		// CPA UsageRecord.RequestID (queue execution_id) is not exposed to the
		// executor/stream hooks. A lifecycle ID or WS trace is NOT that join key.
		"usage_join": "unavailable",
		"handled":    true, "rounds_started": fs.roundNo, "rounds_completed": len(fs.roundsInfo),
		"continuations_started":   nonNegative(fs.roundNo - 1),
		"continuations_completed": nonNegative(len(fs.roundsInfo) - 1),
		"stop_reason":             stopReason, "ws_context_bridge": bridge,
	}
	if fs.nativeWS {
		fields["path"] = "ws_incremental"
	}
	return fields
}

func (fs *foldState) annotateEvent(event map[string]any, stopReason string) map[string]any {
	response, ok := event["response"].(map[string]any)
	if !ok {
		return event
	}
	metadata, _ := response["metadata"].(map[string]any)
	if metadata == nil {
		metadata = make(map[string]any)
		response["metadata"] = metadata
	}
	metadata["proxy_reflow"] = fs.telemetry(stopReason)
	return event
}

func (fs *foldState) terminalStopReason() string {
	switch fs.terminal["type"] {
	case "response.failed":
		return "upstream_failed"
	case "response.incomplete":
		return "upstream_incomplete"
	default:
		return fs.stoppedReason()
	}
}

func (fs *foldState) resultTelemetry(result, emission, stopReason string) map[string]any {
	fields := fs.telemetry(stopReason)
	fields["event"], fields["result"], fields["emission"] = "fold_finished", result, emission
	return fields
}

func (fs *foldState) logResult(result, emission, stopReason string) {
	logReflowEvent(fs.resultTelemetry(result, emission, stopReason))
}
