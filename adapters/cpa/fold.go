package main

import (
	"github.com/chatwithgod/reflow/core"
	"net/http"
	"net/url"
)

const encInclude = core.EncryptedReasoningInclude

// Compatibility names for the adapter and its inherited regression suite.
// All algorithms are implemented in the shared, SDK-free core.
var (
	reasoningTokens  = core.ReasoningTokens
	tierN            = core.TierN
	inContinueWindow = core.InContinueWindow
	commentaryNudge  = core.CommentaryNudge
	nextRoundBody    = core.NextRoundBody
	sumUsage         = core.SumUsage
	agentUsage       = core.AgentUsage
	terminalEvent    = core.TerminalEvent
	failedEvent      = core.FailedEvent
	toFloat          = core.ToFloat
	cloneUsage       = core.CloneUsage
)

var terminalTypes = map[string]bool{"response.completed": true, "response.failed": true, "response.incomplete": true}

// hostModelExecRequest is the request sent to host.model.execute_stream.
type hostModelExecRequest struct {
	EntryProtocol  string      `json:"entry_protocol"`
	ExitProtocol   string      `json:"exit_protocol"`
	Model          string      `json:"model"`
	Stream         bool        `json:"stream"`
	Body           []byte      `json:"body"`
	Headers        http.Header `json:"headers,omitempty"`
	Query          url.Values  `json:"query,omitempty"`
	Alt            string      `json:"alt,omitempty"`
	HostCallbackID string      `json:"host_callback_id,omitempty"`
}
