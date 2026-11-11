// Package core folds Responses events without owning credentials or transports.
// Event folding and continuation rules derive from CPA CodexReflow/CodexComp.
package core

import (
	"encoding/json"
	"errors"
	"fmt"
	"strings"
)

type Object = map[string]any

const (
	defaultTruncationStep = 518
	defaultMarkerText     = "Continue thinking..."
)

type Config struct {
	MaxContinue      int    `json:"max_continue"`
	MaxTierN         int    `json:"max_tier_n"`
	MaxBufferedBytes int    `json:"max_buffered_bytes"`
	MarkerText       string `json:"marker_text"`
}

func DefaultConfig() Config {
	return Config{MaxContinue: 3, MaxTierN: 6, MaxBufferedBytes: 8 << 20, MarkerText: defaultMarkerText}
}

func (c Config) Validate() error {
	if c.MaxContinue < 0 || c.MaxContinue > 16 || c.MaxTierN < 0 || c.MaxTierN > 4096 {
		return errors.New("invalid continuation budget")
	}
	if c.MaxBufferedBytes < 1024 || c.MaxBufferedBytes > 64<<20 {
		return errors.New("max_buffered_bytes must be between 1024 and 67108864")
	}
	return nil
}

type Result struct {
	VisibleID   string
	UpstreamID  string
	Status      string
	Rounds      int
	StopReason  string
	BilledUsage Object
	// ReplayRequest includes the last actual input and output, including hidden
	// continuation nudges. Keep in bounded memory only; never log or persist it.
	ReplayRequest Object
}

type Decision struct {
	Next   Object
	Events []Object
	Result Result
}

type Session struct {
	FoldState
	config     Config
	base       Object
	input      []any
	tail       []any
	roundInput Object
	replayable bool
	finished   bool
}

// New starts one client request. replayBase is the complete effective request,
// when an adapter has resolved previous_response_id from its scoped cache.
// An unresolved parent is passed through without an unsafe partial replay.
func New(config Config, request Object, replayBase Object) (*Session, error) {
	if err := config.Validate(); err != nil {
		return nil, err
	}
	base, err := Clone(request)
	if err != nil {
		return nil, err
	}
	replayable := true
	if parent, _ := base["previous_response_id"].(string); parent != "" {
		replayable = replayBase != nil
	}
	if replayBase != nil {
		base, err = Clone(replayBase)
		if err != nil {
			return nil, err
		}
	}
	var input []any
	switch v := base["input"].(type) {
	case []any:
		input = append([]any{}, v...)
	case string:
		input = []any{Object{"role": "user", "content": v}}
	case nil:
		input = []any{}
	default:
		return nil, errors.New("input must be an array or string")
	}
	s := &Session{config: config, base: base, input: input, replayable: replayable, FoldState: FoldState{SummedUsage: Object{}}}
	s.start(base)
	return s, nil
}

func Clone(in Object) (Object, error) {
	b, err := json.Marshal(in)
	if err != nil {
		return nil, errors.New("invalid Responses object")
	}
	var out Object
	if err := json.Unmarshal(b, &out); err != nil {
		return nil, errors.New("invalid Responses object")
	}
	return out, nil
}

func (s *Session) start(body Object) {
	s.RoundNo++
	s.roundInput = body
	s.ResetRound()
}

func (s *Session) stamp(ev Object) Object { return s.Stamp(ev, true) }

// Push owns a clone of ev and delegates event folding to the shared core.
func (s *Session) Push(ev Object) ([]Object, error) {
	if s.finished {
		return nil, errors.New("event after terminal")
	}
	var events []Object
	err := s.Process(ev, EventPolicy{Strict: true, MaxBufferedBytes: s.config.MaxBufferedBytes}, func(ev Object) error {
		events = append(events, ev)
		return nil
	})
	return events, err
}

func (s *Session) HasTerminal() bool { return s.Terminal != nil }

// Rounds is the number of upstream attempts opened for this client request.
func (s *Session) Rounds() int { return s.RoundNo }

func (s *Session) reason() string {
	return s.DecideContinuation(ContinuationPolicy{
		MaxContinue: s.config.MaxContinue, MaxTierN: s.config.MaxTierN,
		Replayable: s.replayable, GuardHostedTools: true,
	}).StopReason
}

// Finish returns the next upstream body or the one final downstream result.
func (s *Session) Finish() (Decision, error) {
	if s.finished || s.Terminal == nil {
		return Decision{}, errors.New("response terminal required")
	}
	s.RecordRound(s.Terminal, s.Usage, false)
	reason := s.reason()
	if reason == "continue" {
		s.tail = ContinueReplay(s.tail, s.RoundReasoning, s.config.MarkerText)
		items := append(append([]any{}, s.input...), s.tail...)
		next := nextRoundBody(s.base, items)
		delete(next, "generate")
		s.start(next)
		return Decision{Next: next}, nil
	}
	var events []Object
	completed := s.Terminal["type"] == "response.completed"
	if completed {
		_ = s.Flush(func(ev Object) error { events = append(events, ev); return nil }, true)
	}
	ev := terminalEvent(s.Terminal, s.BaseResponse, s.FinalOutput, agentUsage(s.FirstUsage, s.SummedUsage, s.Usage, completed), s.RoundsInfo, s.SummedUsage, reason, "")
	// Retain the final upstream error and completion fields, not the initial
	// in-progress values. Identity, visible output and usage belong to the fold.
	response, _ := ev["response"].(map[string]any)
	final, _ := s.Terminal["response"].(map[string]any)
	for key, value := range final {
		switch key {
		case "id", "output", "usage", "metadata":
		default:
			response[key] = value
		}
	}
	events = append(events, s.stamp(ev))
	s.finished = true
	result := s.result(reason)
	if completed && s.replayable {
		replay, _ := Clone(s.roundInput)
		items, _ := replay["input"].([]any)
		if text, ok := replay["input"].(string); ok {
			items = []any{Object{"role": "user", "content": text}}
		}
		items = append([]any{}, items...)
		if output, ok := final["output"].([]any); ok {
			items = append(items, output...)
		}
		replay["input"] = items
		delete(replay, "previous_response_id")
		result.ReplayRequest = replay
	}
	return Decision{Events: events, Result: result}, nil
}

func (s *Session) result(reason string) Result {
	visible, _ := s.BaseResponse["id"].(string)
	final, _ := s.Terminal["response"].(map[string]any)
	upstream, _ := final["id"].(string)
	status, _ := final["status"].(string)
	return Result{VisibleID: visible, UpstreamID: upstream, Status: status, Rounds: s.RoundNo, StopReason: reason, BilledUsage: cloneUsage(s.SummedUsage)}
}

// Abort emits an incomplete result. Reasons are fixed codes, not upstream bodies.
func (s *Session) Abort(reason string) Object {
	s.finished = true
	switch reason {
	case "upstream_error", "upstream_eof", "buffer_limit", "canceled", "interrupted":
	default:
		reason = "upstream_error"
	}
	output := s.FinalOutput
	if reason == "interrupted" {
		// Native response.interrupt uses discard_partial_items: the canceled
		// response must not publish partial output as reusable history.
		output = nil
	}
	ev := terminalEvent(nil, s.BaseResponse, output, agentUsage(s.FirstUsage, s.SummedUsage, s.Usage, false), s.RoundsInfo, s.SummedUsage, reason, reason)
	return s.stamp(ev)
}

func (s *Session) String() string {
	return fmt.Sprintf("Reflow session rounds=%d finished=%t", s.RoundNo, s.finished)
}

// Eligible is a conservative text-model naming rule; it does not claim a model's
// actual capabilities. Runtime decisions also require usable reasoning state.
func Eligible(body Object) bool {
	if body["generate"] == false || body["stream"] == false {
		return false
	}
	model, _ := body["model"].(string)
	if i := strings.LastIndex(model, "/"); i >= 0 {
		model = model[i+1:]
	}
	if !strings.HasPrefix(model, "gpt-") {
		return false
	}
	for _, part := range strings.Split(model, "-") {
		switch part {
		case "image", "audio", "realtime", "transcribe", "transcription", "tts", "video", "embedding", "embeddings", "moderation":
			return false
		}
	}
	return true
}
