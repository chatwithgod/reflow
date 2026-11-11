package core

const EncryptedReasoningInclude = encInclude

// These operations are also used by host adapters whose stream lifecycle is
// controlled externally. They share Session's algorithms without host SDKs.
func ReasoningTokens(usage Object) *int             { return reasoningTokens(usage) }
func TierN(tokens *int) *int                        { return tierN(tokens) }
func InContinueWindow(n *int, maxTier int) bool     { return inContinueWindow(n, maxTier) }
func CommentaryNudge(marker string) Object          { return commentaryNudge(marker) }
func NextRoundBody(base Object, input []any) Object { return nextRoundBody(base, input) }
func SumUsage(acc, usage Object)                    { sumUsage(acc, usage) }
func AgentUsage(first, summed, final Object, flushed bool) Object {
	return agentUsage(first, summed, final, flushed)
}
func TerminalEvent(upstream, base Object, output []Object, usage Object, rounds []Object, billed Object, stopped, incomplete string) Object {
	return terminalEvent(upstream, base, output, usage, rounds, billed, stopped, incomplete)
}
func FailedEvent(status int, detail string) Object { return failedEvent(status, detail) }
func ToFloat(value any) float64                    { return toFloat(value) }
func CloneUsage(usage Object) Object               { return cloneUsage(usage) }
