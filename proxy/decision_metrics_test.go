package proxy

import (
	"context"
	"encoding/json"
	"net/http"
	"strings"
	"sync"
	"sync/atomic"
	"testing"

	"github.com/chatwithgod/reflow/core"
	"github.com/chatwithgod/reflow/internal/testfixture"
)

func TestHTTPActualStopReasonsDoNotChangeContinuationRules(t *testing.T) {
	for _, name := range []string{"rule_not_matched", "no_encrypted_content", "max_continue", "unresolved_parent", "upstream_tool_already_executed", "upstream_terminal"} {
		t.Run(name, func(t *testing.T) {
			var calls atomic.Int32
			endpoint := metricHarness(t, http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				calls.Add(1)
				tokens := 516
				if name == "rule_not_matched" {
					tokens = 517
				}
				events := testfixture.Round("private-first", tokens, true)
				for _, event := range events {
					if item, ok := event["item"].(map[string]any); ok {
						if name == "no_encrypted_content" && item["type"] == "reasoning" {
							delete(item, "encrypted_content")
						}
						if name == "upstream_tool_already_executed" && item["type"] == "function_call" {
							item["type"] = "web_search_call"
						}
					}
				}
				if name == "upstream_terminal" {
					events[len(events)-1]["type"] = "response.failed"
					events[len(events)-1]["response"].(map[string]any)["status"] = "failed"
				}
				testfixture.WriteSSE(w, events)
			}), 1, true)
			body := core.Object{"model": "gpt-6", "stream": true, "input": []any{}}
			if name == "unresolved_parent" {
				body["previous_response_id"] = "unknown-private-parent"
			}
			drain(t, request(t, context.Background(), endpoint+"/responses", body))
			stats := readMetrics(t, endpoint)
			encoded, _ := json.Marshal(stats.FoldDecisions)
			var reasons map[string]int64
			if json.Unmarshal(encoded, &reasons) != nil || reasons[name] != 1 {
				t.Fatalf("wrong actual stop reason: %s", encoded)
			}
			want := int32(1)
			if name == "max_continue" {
				want = 2
				if stats.FoldDecisions.Continue != 1 {
					t.Fatal("continuation decision missing")
				}
			}
			if calls.Load() != want || len(stats.ReasoningTokenSamples) != int(want) {
				t.Fatal("observability changed upstream calls or lost numeric samples")
			}
		})
	}
}

func terminalUsage(t *testing.T, tokens int) core.Object {
	t.Helper()
	events := testfixture.Round("private-first", tokens, false)
	cloned, err := core.Clone(events[len(events)-1])
	if err != nil {
		t.Fatal(err)
	}
	return cloned
}

func TestDecisionMetricsBoundSamplesMissingUsageAndSnapshotOwnership(t *testing.T) {
	store := &metricsStore{}
	for i := 0; i < maxReasoningSamples+3; i++ {
		round := store.begin(false, false)
		round.event(terminalUsage(t, i))
		round.event(terminalUsage(t, 999)) // Duplicate terminal must not add a sample.
	}
	missing := terminalUsage(t, 0)
	delete(missing["response"].(map[string]any)["usage"].(map[string]any), "output_tokens_details")
	store.begin(false, false).event(missing)
	store.begin(false, true).event(terminalUsage(t, 999))
	snapshot := store.snapshot()
	if len(snapshot.ReasoningTokenSamples) != maxReasoningSamples || snapshot.ReasoningSampleDrops != 3 || snapshot.ReasoningMissingReports != 1 {
		t.Fatalf("invalid sample cap or missing-usage accounting: %+v", snapshot)
	}
	snapshot.ReasoningTokenSamples[0] = 123456
	if store.snapshot().ReasoningTokenSamples[0] != 0 {
		t.Fatal("caller changed retained metrics through snapshot alias")
	}
	store.decision(core.Decision{Result: core.Result{StopReason: "PRIVATE_PAYLOAD_SENTINEL", VisibleID: "PRIVATE_PAYLOAD_SENTINEL"}})
	store.decision(core.Decision{Next: core.Object{"private": "PRIVATE_PAYLOAD_SENTINEL"}})
	raw, _ := json.Marshal(store.snapshot())
	if strings.Contains(string(raw), "PRIVATE_PAYLOAD_SENTINEL") || store.snapshot().FoldDecisions.Other != 1 || store.snapshot().FoldDecisions.Continue != 1 {
		t.Fatal("unknown decision copied raw content or miscounted")
	}
	var disabled *metricsStore
	disabled.decision(core.Decision{Next: core.Object{}})
	if disabled.snapshot().DiagnosticsVersion != 0 {
		t.Fatal("diagnostics enabled without metrics opt-in")
	}
}

func TestConcurrentDecisionMetricsSnapshots(t *testing.T) {
	store := &metricsStore{}
	event := terminalUsage(t, 20)
	var group sync.WaitGroup
	for i := 0; i < 16; i++ {
		group.Go(func() {
			for j := 0; j < 10; j++ {
				store.begin(false, false).event(event)
				store.decision(core.Decision{Result: core.Result{StopReason: "rule_not_matched"}})
				snapshot := store.snapshot()
				if len(snapshot.ReasoningTokenSamples) > 0 {
					snapshot.ReasoningTokenSamples[0] = -1
				}
			}
		})
	}
	group.Wait()
	snapshot := store.snapshot()
	if snapshot.Requests != 160 || snapshot.FoldDecisions.RuleNotMatched != 160 || snapshot.ReasoningSampleDrops != 96 || snapshot.ReasoningTokenSamples[0] != 20 {
		t.Fatalf("concurrent diagnostics lost data or shared a snapshot: %+v", snapshot)
	}
}
