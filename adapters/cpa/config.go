package main

import (
	"encoding/json"
	"fmt"
	"strings"
	"sync/atomic"

	"gopkg.in/yaml.v3"
)

const defaultMarkerText = "Continue thinking..."

const (
	defaultTruncationStep = 518
	defaultMaxTierN       = 6
	defaultMaxContinue    = 3
)

// foldConfig mirrors cpa-model-fallback-router's pluginConfig pattern:
// yaml-tagged struct, decoded by yaml.Unmarshal, normalized and validated.
type foldConfig struct {
	MarkerText         string         `yaml:"marker_text"`
	MaxTierN           int            `yaml:"max_tier_n"`
	MaxContinue        int            `yaml:"max_continue"`
	DebugLog           bool           `yaml:"debug_log"`
	ModelMode          string         `yaml:"model_mode"`
	Models             []string       `yaml:"models"`
	ExcludeModels      []string       `yaml:"exclude_models"`
	MinReasoningTokens map[string]int `yaml:"min_reasoning_tokens"`
}

var globalFoldConfig atomic.Value

type lifecycleRequest struct {
	ConfigYAML []byte `json:"config_yaml"`
}

func applyLifecycleConfig(raw []byte) error {
	if len(raw) == 0 {
		setFoldConfig(defaultFoldConfig())
		return nil
	}

	var req lifecycleRequest
	if err := json.Unmarshal(raw, &req); err != nil {
		return fmt.Errorf("decode lifecycle request: %w", err)
	}

	cfg, err := decodeFoldConfig(req.ConfigYAML)
	if err != nil {
		return err
	}
	setFoldConfig(cfg)
	if cfg.DebugLog {
		pluginLog("debug", fmt.Sprintf("config applied: model_mode=%s models=%d exclusions=%d max_tier_n=%d max_continue=%d marker_text_len=%d", cfg.ModelMode, len(cfg.Models), len(cfg.ExcludeModels), cfg.MaxTierN, cfg.MaxContinue, len(cfg.MarkerText)))
	}
	return nil
}

func defaultFoldConfig() foldConfig {
	return foldConfig{
		MarkerText:  defaultMarkerText,
		MaxTierN:    defaultMaxTierN,
		MaxContinue: defaultMaxContinue,
		ModelMode:   modelModeAuto,
	}
}

// Only legacy configurations with an explicitly empty models field use this
// historical fallback. Fresh configurations no longer ship a fixed allowlist.
func legacyDefaultModels() []string {
	return []string{"gpt-5.5", "gpt-5.6-luna", "gpt-5.6-terra"}
}

func currentFoldConfig() foldConfig {
	if raw, ok := globalFoldConfig.Load().(foldConfig); ok {
		return raw
	}
	return defaultFoldConfig()
}

func setFoldConfig(cfg foldConfig) {
	globalFoldConfig.Store(cfg)
}

// decodeFoldConfig follows the fallback-router pattern: start from defaults,
// unmarshal on top, normalize, validate.
func decodeFoldConfig(raw []byte) (foldConfig, error) {
	cfg := defaultFoldConfig()
	if strings.TrimSpace(string(raw)) != "" {
		if err := yaml.Unmarshal(raw, &cfg); err != nil {
			return foldConfig{}, fmt.Errorf("invalid %s config: %w", pluginIdentifier, err)
		}
		var fields map[string]yaml.Node
		if err := yaml.Unmarshal(raw, &fields); err != nil {
			return foldConfig{}, fmt.Errorf("invalid %s config mapping: %w", pluginIdentifier, err)
		}
		mode, hasMode := fields["model_mode"]
		_, hasModels := fields["models"]
		// Preserve every old explicit whitelist, including the old empty-list
		// fallback. Merely upgrading the DLL must not widen interception.
		if hasModels && (!hasMode || mode.Tag == "!!null" || strings.TrimSpace(cfg.ModelMode) == "") {
			cfg.ModelMode = modelModeManual
			cfg.Models = normalizeModelIDs(cfg.Models)
			if len(cfg.Models) == 0 {
				cfg.Models = legacyDefaultModels()
			}
		}
	}
	normalizeFoldConfig(&cfg)
	if err := validateFoldConfig(cfg); err != nil {
		return foldConfig{}, err
	}
	return cfg, nil
}

func normalizeFoldConfig(cfg *foldConfig) {
	if cfg == nil {
		return
	}
	cfg.MarkerText = strings.TrimSpace(cfg.MarkerText)
	if cfg.MarkerText == "" {
		cfg.MarkerText = defaultMarkerText
	}
	cfg.Models = normalizeModelIDs(cfg.Models)
	cfg.ExcludeModels = normalizeModelIDs(cfg.ExcludeModels)
	cfg.ModelMode = strings.ToLower(strings.TrimSpace(cfg.ModelMode))
	if cfg.ModelMode == "" {
		cfg.ModelMode = modelModeAuto
		if len(cfg.Models) > 0 {
			cfg.ModelMode = modelModeManual
		}
	}
	// Normalize MinReasoningTokens: trim model keys, drop empty keys
	if cfg.MinReasoningTokens != nil {
		normalizedMap := make(map[string]int, len(cfg.MinReasoningTokens))
		for model, threshold := range cfg.MinReasoningTokens {
			trimmedModel := strings.TrimSpace(model)
			if trimmedModel != "" {
				normalizedMap[trimmedModel] = threshold
			}
		}
		if len(normalizedMap) == 0 {
			cfg.MinReasoningTokens = nil
		} else {
			cfg.MinReasoningTokens = normalizedMap
		}
	}
}

func validateFoldConfig(cfg foldConfig) error {
	if cfg.ModelMode != modelModeAuto && cfg.ModelMode != modelModeManual {
		return fmt.Errorf("model_mode must be auto or manual")
	}
	if cfg.MaxTierN < 0 {
		return fmt.Errorf("max_tier_n must be a non-negative integer")
	}
	if cfg.MaxContinue < 0 {
		return fmt.Errorf("max_continue must be a non-negative integer")
	}
	for model, threshold := range cfg.MinReasoningTokens {
		if threshold < 0 {
			return fmt.Errorf("min_reasoning_tokens[%s] must be non-negative, got %d", model, threshold)
		}
	}
	return nil
}
