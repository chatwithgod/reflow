package main

import (
	"encoding/json"
	"reflect"
	"testing"

	"github.com/router-for-me/CLIProxyAPI/v8/sdk/pluginapi"
)

func TestModelSelectionConfigModes(t *testing.T) {
	for _, test := range []struct {
		name, raw, mode string
		models          []string
	}{
		{"fresh", "", modelModeAuto, nil},
		{"host enabled only", "enabled: true\npriority: 1", modelModeAuto, nil},
		{"explicit auto", "model_mode: auto", modelModeAuto, nil},
		{"normalized auto", "model_mode: ' AUTO '", modelModeAuto, nil},
		{"legacy whitelist", "models: [gpt-5.6-sol]", modelModeManual, []string{"gpt-5.6-sol"}},
		{"legacy JSON", `{"models":["gpt-6-sol"]}`, modelModeManual, []string{"gpt-6-sol"}},
		{"legacy empty", "models: []", modelModeManual, legacyDefaultModels()},
		{"legacy null", "models: null", modelModeManual, legacyDefaultModels()},
		{"legacy blank", "models: [' ', '']", modelModeManual, legacyDefaultModels()},
		{"blank mode legacy", "model_mode: ''\nmodels: [gpt-6-sol]", modelModeManual, []string{"gpt-6-sol"}},
		{"null mode legacy", "model_mode: null\nmodels: [gpt-6-sol]", modelModeManual, []string{"gpt-6-sol"}},
		{"manual empty", "model_mode: manual\nmodels: []", modelModeManual, nil},
		{"manual omitted", "model_mode: manual", modelModeManual, nil},
		{"auto retained list", "model_mode: auto\nmodels: [fixture-alias]", modelModeAuto, []string{"fixture-alias"}},
		{"deduped manual", "models: [' gpt-6-sol ', gpt-6-sol, '']", modelModeManual, []string{"gpt-6-sol"}},
	} {
		t.Run(test.name, func(t *testing.T) {
			cfg, err := decodeFoldConfig([]byte(test.raw))
			if err != nil {
				t.Fatal(err)
			}
			if cfg.ModelMode != test.mode || !reflect.DeepEqual(cfg.Models, test.models) {
				t.Fatalf("mode=%s models=%v; want %s %v", cfg.ModelMode, cfg.Models, test.mode, test.models)
			}
		})
	}
}

func TestModelSelectionInvalidModeDoesNotReplaceLiveConfig(t *testing.T) {
	previous := currentFoldConfig()
	defer setFoldConfig(previous)
	setFoldConfig(defaultFoldConfig())
	for _, mode := range []string{"all", "automatic", "manual*", "123"} {
		raw, _ := json.Marshal(lifecycleRequest{ConfigYAML: []byte("model_mode: " + mode)})
		if err := applyLifecycleConfig(raw); err == nil {
			t.Fatalf("invalid mode %s accepted", mode)
		}
		if currentFoldConfig().ModelMode != modelModeAuto {
			t.Fatal("invalid reload replaced previous config")
		}
	}
}

func TestAutoGPTModelNameSelection(t *testing.T) {
	accepted := []string{
		"gpt-5", "gpt-5.5", "gpt-5.6-luna", "gpt-5.6-sol", "gpt-5.6-terra",
		"gpt-5.3-codex-spark", "gpt-6-astra", "gpt-6-sol", "gpt-6-luna", "gpt-6.1-sol",
		"gpt-7-fixture", "gpt-12.3-fixture", // synthetic future names, not real models
		"gpt-6-sol(high)", "gpt-6-sol(8192)", "gpt-6-sol(-1)",
		"team/gpt-6-sol", "team/gpt-6-sol(max)", "org/team/gpt-6-sol",
	}
	declined := []string{
		"", "gpt-4o", "gpt-4.1", "gpt-3.5-turbo", "claude-fixture", "gemini-fixture",
		"fixture-alias", "not-gpt-6", "gptish-6", "gpt-06", "gpt-0", "gpt-6x", "gpt-6.1.2",
		"gpt-6_vision", "gpt-6-", "gpt-6--sol", "gpt-6 ", " gpt-6", "GPT-6", "gpt-6-中文",
		"gpt-18446744073709551616-fixture", "/gpt-6", "team//gpt-6", "http://fixture/gpt-6",
		"gpt-6-sol(high", "gpt-6-sol(low)(high)",
		"gpt-6-image", "gpt-6-mini-image", "gpt-6-audio-preview", "gpt-6-realtime",
		"gpt-6-transcribe", "gpt-6-transcription", "gpt-6-tts", "gpt-6-video", "gpt-6-embeddings", "gpt-6-moderation",
	}
	for _, model := range accepted {
		if !isAutoGPTModel(model) {
			t.Errorf("should match %s", model)
		}
	}
	for _, model := range declined {
		if isAutoGPTModel(model) {
			t.Errorf("must decline %s", model)
		}
	}
}

func TestModelSelectionManualRemainsExact(t *testing.T) {
	cfg, err := decodeFoldConfig([]byte("models: [gpt-6-sol, fixture-alias]"))
	if err != nil {
		t.Fatal(err)
	}
	for _, model := range []string{"gpt-6-sol", "fixture-alias"} {
		if !cfg.matchesModel(model) {
			t.Errorf("explicit model %s lost", model)
		}
	}
	for _, model := range []string{"gpt-6-luna", "gpt-5.5", "gpt-6-sol(max)", "team/gpt-6-sol"} {
		if cfg.matchesModel(model) {
			t.Errorf("legacy whitelist widened to %s", model)
		}
	}
	for _, raw := range []string{"model_mode: manual", "model_mode: manual\nmodels: []"} {
		cfg, _ = decodeFoldConfig([]byte(raw))
		if cfg.matchesModel("gpt-5.5") || cfg.matchesModel("gpt-6-sol") {
			t.Fatal("explicit empty manual whitelist must intercept nothing")
		}
	}
}

func TestExplicitAutoIgnoresRetainedManualList(t *testing.T) {
	cfg, err := decodeFoldConfig([]byte("model_mode: auto\nmodels: [fixture-alias]"))
	if err != nil {
		t.Fatal(err)
	}
	if cfg.matchesModel("fixture-alias") || !cfg.matchesModel("gpt-6-astra") {
		t.Fatal("explicit auto did not replace the manual selector")
	}
}

func TestModelExclusionsTakePriority(t *testing.T) {
	for _, mode := range []string{modelModeAuto, modelModeManual} {
		cfg, err := decodeFoldConfig([]byte("model_mode: " + mode + "\nmodels: [gpt-6-sol, gpt-6-sol(max), team/gpt-6-sol, gpt-6-luna]\nexclude_models: [' gpt-6-sol ', gpt-6-sol, '']"))
		if err != nil {
			t.Fatal(err)
		}
		if !reflect.DeepEqual(cfg.ExcludeModels, []string{"gpt-6-sol"}) {
			t.Fatal("exclusions were not normalized")
		}
		for _, model := range []string{"gpt-6-sol", "gpt-6-sol(max)", "team/gpt-6-sol", "team/gpt-6-sol(low)"} {
			if cfg.matchesModel(model) {
				t.Errorf("%s exclusion failed for %s", mode, model)
			}
		}
		if !cfg.matchesModel("gpt-6-luna") {
			t.Fatal("unrelated model was excluded")
		}
	}
	cfg, _ := decodeFoldConfig([]byte("exclude_models: [team/gpt-6-sol]"))
	if cfg.matchesModel("team/gpt-6-sol(max)") || !cfg.matchesModel("other/gpt-6-sol(max)") {
		t.Fatal("qualified exclusion affected another route")
	}
}

func TestAutoRoutingRetainsRequestGuardsAndModelID(t *testing.T) {
	previous := currentFoldConfig()
	defer setFoldConfig(previous)
	setFoldConfig(defaultFoldConfig())
	for _, test := range []struct {
		name, model, format, body string
		stream, handled           bool
	}{
		{"new model", "gpt-6-astra", "openai-response", `{"input":[]}`, true, true},
		{"prefix and suffix", "team/gpt-6-sol(max)", "openai-response", `{"input":[]}`, true, true},
		{"empty prewarm", "gpt-6-sol", "openai-response", `{"input":[],"generate":false}`, true, false},
		{"nonempty prewarm", "gpt-6-sol", "openai-response", `{"input":[{"role":"user","content":"fixture"}],"generate":false}`, true, false},
		{"chat prewarm", "gpt-6-sol", "openai", `{"messages":[],"generate":false}`, true, false},
		{"claude prewarm", "gpt-6-sol", "claude", `{"messages":[],"generate":false}`, true, false},
		{"explicit generation", "gpt-6-sol", "openai-response", `{"input":[],"generate":true}`, true, true},
		{"string input", "gpt-6-sol", "openai-response", `{"input":"fixture"}`, true, false},
		{"incremental", "gpt-6-sol", "openai-response", `{"input":[],"previous_response_id":"fixture"}`, true, false},
		{"nonstream", "gpt-6-sol", "openai-response", `{"input":[]}`, false, false},
		{"protocol", "gpt-6-sol", "gemini", `{"input":[]}`, true, false},
		{"other family", "claude-fixture", "openai-response", `{"input":[]}`, true, false},
	} {
		t.Run(test.name, func(t *testing.T) {
			req := rpcModelRouteRequest{ModelRouteRequest: pluginapi.ModelRouteRequest{
				RequestedModel: test.model, SourceFormat: test.format, Body: []byte(test.body), Stream: test.stream,
			}}
			raw, _ := json.Marshal(req)
			result, err := routeModel(raw)
			if err != nil {
				t.Fatal(err)
			}
			var resp struct {
				Result pluginapi.ModelRouteResponse `json:"result"`
			}
			if err := json.Unmarshal(result, &resp); err != nil {
				t.Fatal(err)
			}
			if resp.Result.Handled != test.handled {
				t.Fatalf("handled=%v want=%v", resp.Result.Handled, test.handled)
			}
			if resp.Result.TargetModel != "" || string(req.Body) != test.body || req.RequestedModel != test.model {
				t.Fatal("model, route alias or request was rewritten by automatic matching")
			}
		})
	}
}

func TestModelSelectionEnumMetadata(t *testing.T) {
	reg := pluginRegistration()
	for _, field := range reg.Metadata.ConfigFields {
		if field.Name == "model_mode" {
			if field.Type != pluginapi.ConfigFieldTypeEnum || !reflect.DeepEqual(field.EnumValues, []string{modelModeAuto, modelModeManual}) {
				t.Fatal("selection must be exposed as an auto/manual dropdown")
			}
			return
		}
	}
	t.Fatal("selection mode is missing from management fields")
}
