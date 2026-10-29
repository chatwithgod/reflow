"""Whitelist optional numeric decision observations, retaining dev.4 compatibility."""
REASONS = ("continue", "rule_not_matched", "no_encrypted_content", "max_continue",
           "unresolved_parent", "upstream_tool_already_executed", "upstream_terminal", "other")


def extract(raw):
    if "diagnostics_version" not in raw:
        return {}
    invalid = {"fold_diagnostics_valid": False}
    if type(raw.get("diagnostics_version")) is not int or raw["diagnostics_version"] != 1:
        return invalid
    reasons = raw.get("fold_decisions")
    samples = raw.get("reasoning_token_samples", [])
    counts = (raw.get("reasoning_sample_drops"), raw.get("reasoning_missing_reports"))
    number = lambda value: type(value) is int and 0 <= value <= 1_000_000_000_000
    if not isinstance(reasons, dict) or not all(number(reasons.get(key)) for key in REASONS):
        return invalid
    if not isinstance(samples, list) or len(samples) > 64 or not all(number(value) for value in samples):
        return invalid
    if not all(number(value) for value in counts):
        return invalid
    return {"fold_diagnostics_valid": True, "diagnostics_version": 1,
            "fold_decisions": {key: reasons[key] for key in REASONS},
            "reasoning_token_samples": list(samples), "reasoning_sample_drops": counts[0],
            "reasoning_missing_reports": counts[1]}
