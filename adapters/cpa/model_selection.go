package main

import (
	"regexp"
	"strconv"
	"strings"
)

const (
	modelModeAuto   = "auto"
	modelModeManual = "manual"
)

var (
	autoGPTName = regexp.MustCompile(`^gpt-([1-9][0-9]*)(\.[0-9]+)?(-[a-z0-9]+)*$`)
	modelPrefix = regexp.MustCompile(`^[A-Za-z0-9_.-]+(/[A-Za-z0-9_.-]+)*$`)
)

func normalizeModelIDs(models []string) []string {
	var out []string
	seen := make(map[string]bool, len(models))
	for _, model := range models {
		model = strings.TrimSpace(model)
		if model != "" && !seen[model] {
			out = append(out, model)
			seen[model] = true
		}
	}
	return out
}

// selectionModelNames is only for matching. It never rewrites the requested
// model, resolves an alias, selects a provider, or validates a thinking budget.
// CPA's ParseSuffix similarly extracts the final (...) without interpreting it.
func selectionModelNames(model string) (base, leaf string) {
	base = model
	if open := strings.LastIndex(base, "("); open >= 0 && strings.HasSuffix(base, ")") {
		base = base[:open]
	}
	leaf = base
	if slash := strings.LastIndexByte(base, '/'); slash >= 0 {
		leaf = base[slash+1:]
	}
	return base, leaf
}

// isAutoGPTModel is a naming heuristic, NOT CPA catalog synchronization or a
// claim of model capabilities. CPA still owns model availability and routing.
// Non-text families are excluded; runtime continuation separately requires
// usable encrypted reasoning, token usage, a matching tier and a round budget.
func isAutoGPTModel(model string) bool {
	if len(model) == 0 || len(model) > 512 || strings.TrimSpace(model) != model {
		return false
	}
	base, leaf := selectionModelNames(model)
	if slash := strings.LastIndexByte(base, '/'); slash >= 0 && !modelPrefix.MatchString(base[:slash]) {
		return false
	}
	match := autoGPTName.FindStringSubmatch(leaf)
	if match == nil {
		return false
	}
	major, err := strconv.ParseUint(match[1], 10, 64)
	if err != nil || major < 5 {
		return false
	}
	for _, token := range strings.Split(leaf, "-")[2:] {
		switch token {
		case "image", "audio", "realtime", "transcribe", "transcription", "tts", "video", "embedding", "embeddings", "moderation":
			return false
		}
	}
	return true
}

func (cfg foldConfig) matchesModel(model string) bool {
	base, leaf := selectionModelNames(model)
	for _, excluded := range cfg.ExcludeModels {
		// A base ID excludes its prefixes and effort suffixes too. A qualified
		// ID excludes only that qualified route; other prefixes remain eligible.
		if excluded == model || excluded == base || excluded == leaf {
			return false
		}
	}
	mode := cfg.ModelMode
	if mode == "" { // also support programmatic/inherited config construction
		mode = modelModeAuto
		if len(cfg.Models) > 0 {
			mode = modelModeManual
		}
	}
	switch mode {
	case modelModeAuto:
		return isAutoGPTModel(model)
	case modelModeManual:
		for _, allowed := range cfg.Models {
			if allowed == model {
				return true
			}
		}
	}
	return false
}
