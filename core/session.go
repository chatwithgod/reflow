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

type itemBuffer struct {
	index  int
	item   Object
	events []Object
}

type Session struct {
	config       Config
	base         Object
	input        []any
	tail         []any
	roundInput   Object
	replayable   bool
	round        int
	seq          int
	outputIndex  int
	baseResponse Object
	terminal     Object
	usage        Object
	firstUsage   Object
	summed       Object
	rounds       []Object
	output       []Object
	reasoning    []Object
	kinds        map[int]string
	indexes      map[int]int
	buffer       []itemBuffer
	bufferBytes  int
	finished     bool
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
	s := &Session{config: config, base: base, input: input, replayable: replayable, summed: Object{}}
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
	s.round++
	s.roundInput = body
	s.terminal, s.usage, s.reasoning, s.buffer = nil, nil, nil, nil
	s.kinds, s.indexes = map[int]string{}, map[int]int{}
	s.bufferBytes = 0
}

func (s *Session) stamp(ev Object) Object {
	ev["sequence_number"] = s.seq
	s.seq++
	if id, _ := s.baseResponse["id"].(string); id != "" {
		if _, ok := ev["response_id"]; ok {
			ev["response_id"] = id
		}
	}
	return ev
}

// Push owns a clone of ev. Only reasoning is forwarded until the continuation
// decision is known; client tool calls from discarded rounds stay invisible.
func (s *Session) Push(ev Object) ([]Object, error) {
	if s.finished || s.terminal != nil {
		return nil, errors.New("event after terminal")
	}
	ev, err := Clone(ev)
	if err != nil {
		return nil, err
	}
	typ, _ := ev["type"].(string)
	if typ == "" {
		return nil, errors.New("event type is missing")
	}
	if typ == "error" {
		return nil, errors.New("upstream error event")
	}
	if typ == "response.done" {
		typ = "response.completed"
		if response, ok := ev["response"].(map[string]any); ok {
			if response["status"] == "failed" {
				typ = "response.failed"
			}
			if response["status"] == "incomplete" {
				typ = "response.incomplete"
			}
		}
		ev["type"] = typ
	}
	if terminalTypes[typ] {
		s.terminal = ev
		if response, ok := ev["response"].(map[string]any); ok {
			if usage, ok := response["usage"].(map[string]any); ok {
				s.usage = cloneUsage(usage)
			}
			if s.baseResponse == nil {
				s.baseResponse, _ = Clone(response)
			}
		}
		return nil, nil
	}
	if typ == "response.created" || typ == "response.in_progress" {
		if s.round != 1 {
			return nil, nil
		}
		if response, ok := ev["response"].(map[string]any); ok && s.baseResponse == nil {
			s.baseResponse, _ = Clone(response)
		}
		return []Object{s.stamp(ev)}, nil
	}
	index := -1
	if value, ok := ev["output_index"].(float64); ok {
		index = int(value)
	}
	if typ == "response.output_item.added" {
		item, ok := ev["item"].(map[string]any)
		if !ok || index < 0 {
			return nil, errors.New("invalid output item event")
		}
		if _, exists := s.kinds[index]; exists {
			return nil, errors.New("duplicate output item index")
		}
		if item["type"] == "reasoning" {
			s.kinds[index], s.indexes[index] = "reasoning", s.outputIndex
			ev["output_index"] = s.outputIndex
			s.outputIndex++
			return []Object{s.stamp(ev)}, nil
		}
		s.kinds[index] = "buffered"
		s.buffer = append(s.buffer, itemBuffer{index: index, item: item})
	}
	switch s.kinds[index] {
	case "reasoning":
		ev["output_index"] = s.indexes[index]
		if typ == "response.output_item.done" {
			if item, ok := ev["item"].(map[string]any); ok {
				s.reasoning = append(s.reasoning, item)
				s.output = append(s.output, item)
			}
		}
		return []Object{s.stamp(ev)}, nil
	case "buffered":
		encoded, _ := json.Marshal(ev)
		s.bufferBytes += len(encoded)
		if s.bufferBytes > s.config.MaxBufferedBytes {
			return nil, errors.New("output buffer limit exceeded")
		}
		for i := range s.buffer {
			if s.buffer[i].index != index {
				continue
			}
			s.buffer[i].events = append(s.buffer[i].events, ev)
			if typ == "response.output_item.done" {
				if item, ok := ev["item"].(map[string]any); ok {
					s.buffer[i].item = item
				}
			}
			break
		}
		return nil, nil
	default:
		if index >= 0 {
			return nil, errors.New("output event without an item")
		}
		return []Object{s.stamp(ev)}, nil
	}
}

func (s *Session) HasTerminal() bool { return s.terminal != nil }

func (s *Session) reason() string {
	if s.terminal["type"] != "response.completed" {
		return "upstream_terminal"
	}
	if !s.replayable {
		return "unresolved_parent"
	}
	if !inContinueWindow(tierN(reasoningTokens(s.usage)), s.config.MaxTierN) {
		return "rule_not_matched"
	}
	if len(s.reasoning) == 0 {
		return "no_encrypted_content"
	}
	if enc, _ := s.reasoning[len(s.reasoning)-1]["encrypted_content"].(string); enc == "" {
		return "no_encrypted_content"
	}
	if s.round > s.config.MaxContinue {
		return "max_continue"
	}
	return "continue"
}

// Finish returns the next upstream body or the one final downstream result.
func (s *Session) Finish() (Decision, error) {
	if s.finished || s.terminal == nil {
		return Decision{}, errors.New("response terminal required")
	}
	sumUsage(s.summed, s.usage)
	if s.round == 1 {
		s.firstUsage = cloneUsage(s.usage)
	}
	rt := reasoningTokens(s.usage)
	s.rounds = append(s.rounds, Object{"round": s.round, "reasoning_tokens": rt})
	reason := s.reason()
	if reason == "continue" {
		for _, item := range s.reasoning {
			s.tail = append(s.tail, item)
		}
		s.tail = append(s.tail, commentaryNudge(s.config.MarkerText))
		items := append(append([]any{}, s.input...), s.tail...)
		next := nextRoundBody(s.base, items)
		delete(next, "generate")
		s.start(next)
		return Decision{Next: next}, nil
	}
	var events []Object
	completed := s.terminal["type"] == "response.completed"
	if completed {
		for _, entry := range s.buffer {
			for _, ev := range entry.events {
				ev["output_index"] = s.outputIndex
				events = append(events, s.stamp(ev))
			}
			s.outputIndex++
			s.output = append(s.output, entry.item)
		}
	}
	ev := terminalEvent(s.terminal, s.baseResponse, s.output, agentUsage(s.firstUsage, s.summed, s.usage, completed), s.rounds, s.summed, reason, "")
	// Retain the final upstream error and completion fields, not the initial
	// in-progress values. Identity, visible output and usage belong to the fold.
	response, _ := ev["response"].(map[string]any)
	final, _ := s.terminal["response"].(map[string]any)
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
	visible, _ := s.baseResponse["id"].(string)
	final, _ := s.terminal["response"].(map[string]any)
	upstream, _ := final["id"].(string)
	status, _ := final["status"].(string)
	return Result{VisibleID: visible, UpstreamID: upstream, Status: status, Rounds: s.round, StopReason: reason, BilledUsage: cloneUsage(s.summed)}
}

// Abort emits an incomplete result. Reasons are fixed codes, not upstream bodies.
func (s *Session) Abort(reason string) Object {
	s.finished = true
	switch reason {
	case "upstream_error", "upstream_eof", "buffer_limit", "canceled":
	default:
		reason = "upstream_error"
	}
	ev := terminalEvent(nil, s.baseResponse, s.output, agentUsage(s.firstUsage, s.summed, s.usage, false), s.rounds, s.summed, reason, reason)
	return s.stamp(ev)
}

func (s *Session) String() string {
	return fmt.Sprintf("Reflow session rounds=%d finished=%t", s.round, s.finished)
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
