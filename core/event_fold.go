package core

import (
	"encoding/json"
	"errors"
)

// EventPolicy selects protocol-boundary behavior, not a transport or host SDK.
// Strict callers own cloned events and normalize response IDs. Legacy hosts
// may retain their existing event ownership and permissive framing contract.
type EventPolicy struct {
	Strict           bool
	MaxBufferedBytes int
}

type BufferedItem struct {
	Index  int
	Item   Object
	Events []Object
}

// FoldState is the transport-independent accumulator shared by Session and
// host adapters. A single request owns it; callers must serialize access.
// State can contain private input/output and must never be logged wholesale.
type FoldState struct {
	RoundNo        int
	OutputIndex    int
	Sequence       int
	BaseResponse   Object
	FinalOutput    []Object
	RoundReasoning []Object
	Kinds          map[int]string
	Indexes        map[int]int
	Buffered       []BufferedItem
	BufferedBytes  int
	Terminal       Object
	Usage          Object
	SummedUsage    Object
	FirstUsage     Object
	RoundsInfo     []Object
}

func (f *FoldState) ResetRound() {
	f.RoundReasoning, f.Buffered, f.Terminal, f.Usage = nil, nil, nil, nil
	f.Kinds, f.Indexes = map[int]string{}, map[int]int{}
	f.BufferedBytes = 0
}

func (f *FoldState) Stamp(ev Object, normalizeID bool) Object {
	ev["sequence_number"] = f.Sequence
	f.Sequence++
	if id, _ := f.BaseResponse["id"].(string); normalizeID && id != "" {
		if _, ok := ev["response_id"]; ok {
			ev["response_id"] = id
		}
	}
	return ev
}

// Process forwards reasoning and buffers final text/client tools until a
// continuation decision is known. The emitter must not retain mutable events.
func (f *FoldState) Process(ev Object, policy EventPolicy, emit func(Object) error) error {
	if policy.Strict {
		if f.Terminal != nil {
			return errors.New("event after terminal")
		}
		var err error
		ev, err = Clone(ev)
		if err != nil {
			return err
		}
	}
	typ, _ := ev["type"].(string)
	if policy.Strict && typ == "" {
		return errors.New("event type is missing")
	}
	if typ == "error" {
		return errors.New("upstream error event")
	}
	if typ == "response.done" {
		typ = "response.completed"
		if response, ok := ev["response"].(map[string]any); ok {
			switch response["status"] {
			case "failed":
				typ = "response.failed"
			case "incomplete":
				typ = "response.incomplete"
			}
		}
		ev["type"] = typ
	}
	if terminalTypes[typ] {
		f.Terminal = ev
		if response, ok := ev["response"].(map[string]any); ok {
			if usage, ok := response["usage"].(map[string]any); ok {
				f.Usage = cloneUsage(usage)
			}
			if policy.Strict && f.BaseResponse == nil {
				f.BaseResponse, _ = Clone(response)
			}
		}
		return nil
	}
	if typ == "response.created" || typ == "response.in_progress" {
		if f.RoundNo != 1 {
			return nil
		}
		if response, ok := ev["response"].(map[string]any); ok {
			if policy.Strict && f.BaseResponse == nil {
				f.BaseResponse, _ = Clone(response)
			}
			if !policy.Strict && typ == "response.created" {
				f.BaseResponse = response
			}
		}
		return emit(f.Stamp(ev, policy.Strict))
	}
	index := -1
	if value, ok := ev["output_index"].(float64); ok {
		index = int(value)
	}
	if typ == "response.output_item.added" {
		item, ok := ev["item"].(map[string]any)
		if policy.Strict && (!ok || index < 0) {
			return errors.New("invalid output item event")
		}
		if item == nil {
			item = Object{}
		}
		if _, exists := f.Kinds[index]; policy.Strict && exists {
			return errors.New("duplicate output item index")
		}
		if f.Kinds == nil {
			f.Kinds = map[int]string{}
		}
		if f.Indexes == nil {
			f.Indexes = map[int]int{}
		}
		if item["type"] == "reasoning" {
			f.Kinds[index], f.Indexes[index] = "reasoning", f.OutputIndex
			ev["output_index"] = f.OutputIndex
			f.OutputIndex++
			return emit(f.Stamp(ev, policy.Strict))
		}
		f.Kinds[index] = "buffered"
		f.Buffered = append(f.Buffered, BufferedItem{Index: index, Item: item})
	}
	switch f.Kinds[index] {
	case "reasoning":
		if outputIndex, ok := f.Indexes[index]; ok {
			ev["output_index"] = outputIndex
		}
		if typ == "response.output_item.done" {
			if item, ok := ev["item"].(map[string]any); ok {
				f.RoundReasoning = append(f.RoundReasoning, item)
				f.FinalOutput = append(f.FinalOutput, item)
			}
		}
		return emit(f.Stamp(ev, policy.Strict))
	case "buffered":
		if policy.MaxBufferedBytes > 0 {
			encoded, _ := json.Marshal(ev)
			f.BufferedBytes += len(encoded)
			if f.BufferedBytes > policy.MaxBufferedBytes {
				return errors.New("output buffer limit exceeded")
			}
		}
		for i := range f.Buffered {
			if f.Buffered[i].Index != index {
				continue
			}
			f.Buffered[i].Events = append(f.Buffered[i].Events, ev)
			if typ == "response.output_item.done" {
				if item, ok := ev["item"].(map[string]any); ok {
					f.Buffered[i].Item = item
				}
			}
			break
		}
		return nil
	default:
		if policy.Strict && index >= 0 {
			return errors.New("output event without an item")
		}
		return emit(f.Stamp(ev, policy.Strict))
	}
}

func (f *FoldState) RecordRound(terminal, usage Object, includeTier bool) {
	f.Terminal, f.Usage = terminal, usage
	if f.SummedUsage == nil {
		f.SummedUsage = Object{}
	}
	sumUsage(f.SummedUsage, usage)
	if f.RoundNo == 1 {
		f.FirstUsage = cloneUsage(usage)
	}
	rt := reasoningTokens(usage)
	round := Object{"round": f.RoundNo, "reasoning_tokens": rt}
	if includeTier {
		round["n"] = tierN(rt)
	}
	f.RoundsInfo = append(f.RoundsInfo, round)
}

func (f *FoldState) Flush(emit func(Object) error, normalizeID bool) error {
	for _, entry := range f.Buffered {
		for _, ev := range entry.Events {
			if _, ok := ev["output_index"]; normalizeID || ok {
				ev["output_index"] = f.OutputIndex
			}
			if err := emit(f.Stamp(ev, normalizeID)); err != nil {
				return err
			}
		}
		f.OutputIndex++
		f.FinalOutput = append(f.FinalOutput, entry.Item)
	}
	return nil
}

func (f *FoldState) HasEncryptedContent() bool {
	if len(f.RoundReasoning) == 0 {
		return false
	}
	value, _ := f.RoundReasoning[len(f.RoundReasoning)-1]["encrypted_content"].(string)
	return value != ""
}

type ContinuationPolicy struct {
	MaxContinue        int
	MaxTierN           int
	MinReasoningTokens int
	Replayable         bool
	GuardHostedTools   bool
}

type ContinuationDecision struct {
	Continue   bool
	Trigger    string
	StopReason string
}

func ContinuationTrigger(usage, summed Object, maxTier, minimum int) string {
	if inContinueWindow(tierN(reasoningTokens(usage)), maxTier) {
		return "truncation"
	}
	if total := reasoningTokens(summed); minimum > 0 && total != nil && *total < minimum {
		return "low_reasoning_tokens"
	}
	return ""
}

func (f *FoldState) DecideContinuation(policy ContinuationPolicy) ContinuationDecision {
	d := ContinuationDecision{Trigger: ContinuationTrigger(f.Usage, f.SummedUsage, policy.MaxTierN, policy.MinReasoningTokens)}
	switch {
	case f.Terminal["type"] != "response.completed":
		d.StopReason = "upstream_terminal"
	case !policy.Replayable:
		d.StopReason = "unresolved_parent"
	default:
		if policy.GuardHostedTools {
			for _, entry := range f.Buffered {
				switch entry.Item["type"] {
				case "message", "function_call", "custom_tool_call":
				default:
					d.StopReason = "upstream_tool_already_executed"
					return d
				}
			}
		}
		switch {
		case d.Trigger == "":
			d.StopReason = "rule_not_matched"
		case !f.HasEncryptedContent():
			d.StopReason = "no_encrypted_content"
		case f.RoundNo > policy.MaxContinue:
			d.StopReason = "max_continue"
		default:
			d.Continue = true
			d.StopReason = "continue"
		}
	}
	return d
}

func ContinueReplay(tail []any, reasoning []Object, marker string) []any {
	for _, item := range reasoning {
		tail = append(tail, item)
	}
	return append(tail, commentaryNudge(marker))
}
