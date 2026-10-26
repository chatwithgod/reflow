package proxy

import (
	"io"
	"math"
	"sync"
	"sync/atomic"

	"github.com/chatwithgod/reflow/core"
)

// Metrics contains process totals only: no models, accounts, identifiers or
// payloads. Usage is what observed streaming Responses replies reported, not
// a monetary charge or an estimate of unreported canceled work.
type Metrics struct {
	Enabled                bool   `json:"enabled"`
	Scope                  string `json:"scope"`
	Requests               int64  `json:"requests"`
	Continuations          int64  `json:"continuations"`
	ContinuedToolResponses int64  `json:"continued_tool_responses"`
	ContinuedToolCalls     int64  `json:"continued_tool_calls"`
	ContinuedToolResults   int64  `json:"continued_tool_results"`
	ToolTrackingDrops      int64  `json:"tool_tracking_drops"`
	Warmups                int64  `json:"warmups"`
	Completed              int64  `json:"completed"`
	Failed                 int64  `json:"failed"`
	UsageReports           int64  `json:"usage_reports"`
	ParseErrors            int64  `json:"parse_errors"`
	UnsupportedResponses   int64  `json:"unsupported_responses"`
	InputTokens            int64  `json:"input_tokens"`
	OutputTokens           int64  `json:"output_tokens"`
	CachedTokens           int64  `json:"cached_tokens"`
	CacheWriteTokens       int64  `json:"cache_write_tokens"`
	ReasoningTokens        int64  `json:"reasoning_tokens"`
	UsageComplete          bool   `json:"usage_complete"`
}

type metricsStore struct {
	mu    sync.Mutex
	value Metrics
	tools map[[32]byte]*pendingTool
}
type metricRound struct {
	store    *metricsStore
	warmup   bool
	finished atomic.Bool
}

func (s *metricsStore) begin(continuation, warmup bool) *metricRound {
	if s == nil {
		return nil
	}
	s.mu.Lock()
	if warmup {
		s.value.Warmups++
	} else {
		s.value.Requests++
		if continuation {
			s.value.Continuations++
		}
	}
	s.mu.Unlock()
	return &metricRound{store: s, warmup: warmup}
}

func (s *metricsStore) snapshot() Metrics {
	if s == nil {
		return Metrics{Scope: "streaming_responses"}
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	v := s.value
	v.Enabled = true
	v.Scope = "streaming_responses"
	v.UsageComplete = v.UsageReports == v.Requests && v.Failed == 0 && v.ParseErrors == 0 && v.UnsupportedResponses == 0
	return v
}

func (r *metricRound) failed() {
	if r == nil || r.warmup || !r.finished.CompareAndSwap(false, true) {
		return
	}
	r.store.mu.Lock()
	r.store.value.Failed++
	r.store.mu.Unlock()
}

func (r *metricRound) parseError() {
	if r != nil && !r.warmup {
		r.store.mu.Lock()
		r.store.value.ParseErrors++
		r.store.mu.Unlock()
	}
}
func (r *metricRound) unsupported() {
	if r != nil && !r.warmup {
		r.store.mu.Lock()
		r.store.value.UnsupportedResponses++
		r.store.mu.Unlock()
	}
}

func metricNumber(m core.Object, key string, required bool) (int64, bool) {
	v, ok := m[key]
	if !ok {
		return 0, !required
	}
	f, ok := v.(float64)
	if !ok || f < 0 || f > 1e12 || math.Trunc(f) != f {
		return 0, false
	}
	return int64(f), true
}

func (r *metricRound) event(event core.Object) {
	if r == nil || r.warmup {
		return
	}
	typ, _ := event["type"].(string)
	complete := typ == "response.completed" || typ == "response.done"
	if !complete && typ != "response.failed" && typ != "response.incomplete" && typ != "error" {
		return
	}
	if !r.finished.CompareAndSwap(false, true) {
		return
	}
	response, _ := event["response"].(map[string]any)
	usage, _ := response["usage"].(map[string]any)
	input, validIn := metricNumber(usage, "input_tokens", true)
	output, validOut := metricNumber(usage, "output_tokens", true)
	details, _ := usage["input_tokens_details"].(map[string]any)
	cached, validCache := metricNumber(details, "cached_tokens", false)
	written, validWrite := metricNumber(details, "cache_write_tokens", false)
	reasoning, _ := usage["output_tokens_details"].(map[string]any)
	reason, validReason := metricNumber(reasoning, "reasoning_tokens", false)
	r.store.mu.Lock()
	defer r.store.mu.Unlock()
	if complete {
		r.store.value.Completed++
	} else {
		r.store.value.Failed++
	}
	if usage == nil {
		return
	}
	if !validIn || !validOut || !validCache || !validWrite || !validReason || cached+written > input || reason > output {
		r.store.value.ParseErrors++
		return
	}
	r.store.value.UsageReports++
	r.store.value.InputTokens += input
	r.store.value.OutputTokens += output
	r.store.value.CachedTokens += cached
	r.store.value.CacheWriteTokens += written
	r.store.value.ReasoningTokens += reason
}

type meteredBody struct {
	io.ReadCloser
	round    *metricRound
	decoder  core.Decoder
	invalid  bool
	once     sync.Once
	closeErr error
}

func (b *meteredBody) Read(p []byte) (int, error) {
	n, err := b.ReadCloser.Read(p)
	if n > 0 && !b.invalid {
		events, e := b.decoder.Push(p[:n])
		for _, event := range events {
			b.round.event(event)
		}
		if e != nil {
			b.invalid = true
			b.round.parseError()
		}
	}
	if err == io.EOF && !b.invalid {
		if b.decoder.Finish() != nil {
			b.invalid = true
			b.round.parseError()
		}
	}
	return n, err
}
func (b *meteredBody) Close() error {
	b.once.Do(func() { b.closeErr = b.ReadCloser.Close(); b.round.failed() })
	return b.closeErr
}
