package main

import (
	"encoding/json"
	"reflect"
	"strconv"
	"testing"
)

func schemaFixtureTool(name string, typ any) map[string]any {
	return map[string]any{"type": "function", "name": name, "description": "original description", "parameters": map[string]any{
		"type": "object", "properties": map[string]any{"timeout_ms": map[string]any{"type": typ, "minimum": float64(0)}},
	}}
}

func schemaFixtureNamespace(children ...any) map[string]any {
	return map[string]any{"type": "namespace", "name": "collaboration", "tools": children}
}

func schemaFixtureRequest(typ any) map[string]any {
	return map[string]any{"model": "gpt-6-sol", "tools": []any{schemaFixtureNamespace(schemaFixtureTool("wait_agent", typ))},
		"input": []any{map[string]any{"role": "user", "content": "synthetic schema fixture"}}}
}

func schemaFixtureJSON(t *testing.T, value any) []byte {
	t.Helper()
	raw, err := json.Marshal(value)
	if err != nil {
		t.Fatal(err)
	}
	return raw
}

func schemaFixtureClone(t *testing.T, value map[string]any) map[string]any {
	t.Helper()
	var result map[string]any
	if err := json.Unmarshal(schemaFixtureJSON(t, value), &result); err != nil {
		t.Fatal(err)
	}
	return result
}

func schemaFixtureParameter(body map[string]any) map[string]any {
	tools := body["tools"].([]any)
	child := tools[0].(map[string]any)["tools"].([]any)[0].(map[string]any)
	return child["parameters"].(map[string]any)["properties"].(map[string]any)["timeout_ms"].(map[string]any)
}

func TestRestoreCollaborationToolTypesPreservesHostEdits(t *testing.T) {
	original := schemaFixtureRequest("number")
	original["tools"] = append(original["tools"].([]any), schemaFixtureTool("exec_command", "number"))
	body := schemaFixtureClone(t, original)
	body["model"] = "host-mapped-model"
	body["reasoning"] = map[string]any{"effort": "high"}
	body["prompt_cache_key"] = "host-cache-key"
	param := schemaFixtureParameter(body)
	param["type"], param["minimum"] = "integer", float64(10)
	namespace := body["tools"].([]any)[0].(map[string]any)
	namespace["description"] = "host namespace description"
	child := namespace["tools"].([]any)[0].(map[string]any)
	child["description"] = "host function description"
	child["parameters"].(map[string]any)["additionalProperties"] = false
	other := body["tools"].([]any)[1].(map[string]any)
	other["parameters"].(map[string]any)["properties"].(map[string]any)["timeout_ms"].(map[string]any)["type"] = "integer"
	body["tools"] = append(body["tools"].([]any), schemaFixtureNamespace(schemaFixtureTool("host_added", "integer")))
	expected := schemaFixtureClone(t, body)
	schemaFixtureParameter(expected)["type"] = "number"
	originalBytes := schemaFixtureJSON(t, original)
	if got := restoreCollaborationToolSchemaTypes(body, originalBytes); got != 1 {
		t.Fatalf("restored %d fields, want 1", got)
	}
	if !reflect.DeepEqual(body, expected) {
		t.Fatalf("host edits changed: got %s, want %s", schemaFixtureJSON(t, body), schemaFixtureJSON(t, expected))
	}
	if !reflect.DeepEqual(schemaFixtureJSON(t, original), originalBytes) {
		t.Fatal("original declaration changed")
	}
	if got := restoreCollaborationToolSchemaTypes(body, originalBytes); got != 0 {
		t.Fatalf("restoration is not idempotent: %d", got)
	}
}

func TestRestoreCollaborationTypeMutationSignatures(t *testing.T) {
	for _, tc := range []struct {
		name              string
		original, current any
		want              any
		restored          int
	}{
		{"number", "number", "integer", "number", 1},
		{"already number", "number", "number", "number", 0},
		{"client integer", "integer", "integer", "integer", 0},
		{"other host rewrite", "number", "string", "string", 0},
		{"nullable", []any{"number", "null"}, []any{"integer", "null"}, []any{"number", "null"}, 1},
		{"deduplicated", []any{"integer", "number", "null"}, []any{"integer", "null"}, []any{"integer", "number", "null"}, 1},
		{"changed nullable shape", []any{"number", "null"}, "integer", "integer", 0},
		{"invalid type array", []any{"number", float64(1)}, []any{"integer", float64(1)}, []any{"integer", float64(1)}, 0},
		{"object instead of type", map[string]any{"type": "number"}, "integer", "integer", 0},
		{"missing source type", nil, "integer", "integer", 0},
	} {
		t.Run(tc.name, func(t *testing.T) {
			body := schemaFixtureRequest(tc.current)
			if got := restoreCollaborationToolSchemaTypes(body, schemaFixtureJSON(t, schemaFixtureRequest(tc.original))); got != tc.restored {
				t.Fatalf("restored=%d, want %d", got, tc.restored)
			}
			if got := schemaFixtureParameter(body)["type"]; !reflect.DeepEqual(got, tc.want) {
				t.Fatalf("type=%#v, want %#v", got, tc.want)
			}
		})
	}
}

func TestRestoreCollaborationToolMembershipAndIdentity(t *testing.T) {
	for _, name := range []string{"removed tool", "renamed tool", "other namespace", "duplicate original", "duplicate target"} {
		t.Run(name, func(t *testing.T) {
			original := schemaFixtureRequest("number")
			body := schemaFixtureRequest("integer")
			switch name {
			case "removed tool":
				delete(body, "tools")
			case "renamed tool":
				body["tools"].([]any)[0].(map[string]any)["tools"].([]any)[0].(map[string]any)["name"] = "host_renamed"
			case "other namespace":
				body["tools"].([]any)[0].(map[string]any)["name"] = "functions"
			case "duplicate original":
				original["tools"] = append(original["tools"].([]any), schemaFixtureNamespace(schemaFixtureTool("wait_agent", "integer")))
			case "duplicate target":
				body["tools"] = append(body["tools"].([]any), schemaFixtureNamespace(schemaFixtureTool("wait_agent", "integer")))
			}
			before := schemaFixtureJSON(t, body)
			if restoreCollaborationToolSchemaTypes(body, schemaFixtureJSON(t, original)) != 0 || !reflect.DeepEqual(before, schemaFixtureJSON(t, body)) {
				t.Fatal("absent, renamed or ambiguous tool was modified")
			}
		})
	}
}

func TestRestoreCollaborationMissingOriginalAndMalformedInput(t *testing.T) {
	for _, raw := range [][]byte{nil, {}, []byte("null"), []byte("[]"), []byte("{"), []byte(`{"tools":{}}`), []byte(`{"tools":[],"input":[{"type":"additional_tools","tools":{}}]}`)} {
		body := schemaFixtureRequest("integer")
		before := schemaFixtureJSON(t, body)
		if restoreCollaborationToolSchemaTypes(body, raw) != 0 || !reflect.DeepEqual(before, schemaFixtureJSON(t, body)) {
			t.Fatalf("changed payload without valid originals: %q", raw)
		}
	}
	original := schemaFixtureRequest("number")
	original["input"] = "valid Responses string input"
	body := schemaFixtureRequest("integer")
	if restoreCollaborationToolSchemaTypes(body, schemaFixtureJSON(t, original)) != 1 {
		t.Fatal("string input blocked valid top-level restoration")
	}
}

func TestRestoreCollaborationAdditionalToolDeclarations(t *testing.T) {
	additional := func(id, typ string) map[string]any {
		item := map[string]any{"type": "additional_tools", "tools": []any{schemaFixtureNamespace(schemaFixtureTool("wait_agent", typ))}}
		if id != "" {
			item["id"] = id
		}
		return item
	}
	readType := func(item any) any {
		return schemaFixtureParameter(item.(map[string]any))["type"]
	}
	t.Run("top and dynamic keep separate originals", func(t *testing.T) {
		original := schemaFixtureRequest("number")
		original["input"] = []any{map[string]any{"role": "system", "content": "moved to instructions"}, additional("", "integer"), additional("", "number")}
		body := schemaFixtureRequest("integer")
		body["input"] = []any{additional("", "integer"), additional("", "integer")}
		if got := restoreCollaborationToolSchemaTypes(body, schemaFixtureJSON(t, original)); got != 2 {
			t.Fatalf("restored=%d, want 2", got)
		}
		input := body["input"].([]any)
		if schemaFixtureParameter(body)["type"] != "number" || readType(input[0]) != "integer" || readType(input[1]) != "number" {
			t.Fatal("declarations were conflated or input indexes were used")
		}
	})
	t.Run("identified declarations can be reordered", func(t *testing.T) {
		original := map[string]any{"input": []any{additional("a", "number"), additional("b", "integer")}}
		body := map[string]any{"input": []any{additional("b", "integer"), additional("a", "integer")}}
		if restoreCollaborationToolSchemaTypes(body, schemaFixtureJSON(t, original)) != 1 {
			t.Fatal("identified dynamic declaration not restored")
		}
		input := body["input"].([]any)
		if readType(input[0]) != "integer" || readType(input[1]) != "number" {
			t.Fatal("incorrect declaration identity")
		}
	})
	t.Run("ambiguous anonymous blocks are preserved", func(t *testing.T) {
		original := map[string]any{"input": []any{additional("", "number"), additional("", "integer")}}
		body := map[string]any{"input": []any{additional("", "integer")}}
		before := schemaFixtureJSON(t, body)
		if restoreCollaborationToolSchemaTypes(body, schemaFixtureJSON(t, original)) != 0 || !reflect.DeepEqual(before, schemaFixtureJSON(t, body)) {
			t.Fatal("guessed a removed anonymous declaration")
		}
	})
	t.Run("duplicate original IDs are preserved", func(t *testing.T) {
		original := map[string]any{"input": []any{additional("a", "number"), additional("a", "integer")}}
		body := map[string]any{"input": []any{additional("a", "integer")}}
		if restoreCollaborationToolSchemaTypes(body, schemaFixtureJSON(t, original)) != 0 {
			t.Fatal("ambiguous original ID was used")
		}
	})
	t.Run("duplicate target IDs are preserved", func(t *testing.T) {
		original := map[string]any{"input": []any{additional("a", "number")}}
		body := map[string]any{"input": []any{additional("a", "integer"), additional("a", "integer")}}
		if restoreCollaborationToolSchemaTypes(body, schemaFixtureJSON(t, original)) != 0 {
			t.Fatal("ambiguous target ID was used")
		}
	})
}

func TestRestoreCollaborationSchemaLocationsAndLimits(t *testing.T) {
	original := schemaFixtureRequest("number")
	param := schemaFixtureParameter(original)
	param["default"] = map[string]any{"type": "number"}
	param["examples"] = []any{map[string]any{"type": "number"}}
	param["anyOf"] = []any{map[string]any{"type": "number"}, map[string]any{"type": "null"}}
	param["items"] = map[string]any{"type": "number"}
	body := schemaFixtureClone(t, original)
	target := schemaFixtureParameter(body)
	target["type"] = "integer"
	target["default"].(map[string]any)["type"] = "integer"
	target["examples"].([]any)[0].(map[string]any)["type"] = "integer"
	target["anyOf"].([]any)[0].(map[string]any)["type"] = "integer"
	target["items"].(map[string]any)["type"] = "integer"
	if got := restoreCollaborationToolSchemaTypes(body, schemaFixtureJSON(t, original)); got != 3 {
		t.Fatalf("restored=%d, want 3 schema locations", got)
	}
	if target["default"].(map[string]any)["type"] != "integer" || target["examples"].([]any)[0].(map[string]any)["type"] != "integer" {
		t.Fatal("literal data was modified")
	}
	t.Run("depth overflow is atomic", func(t *testing.T) {
		source := schemaFixtureRequest("number")
		current := schemaFixtureParameter(source)
		for i := 0; i < toolSchemaRestoreMaxDepth+2; i++ {
			next := map[string]any{"type": "number"}
			current["items"] = next
			current = next
		}
		payload := schemaFixtureClone(t, source)
		schemaFixtureParameter(payload)["type"] = "integer"
		before := schemaFixtureJSON(t, payload)
		if restoreCollaborationToolSchemaTypes(payload, schemaFixtureJSON(t, source)) != 0 || !reflect.DeepEqual(before, schemaFixtureJSON(t, payload)) {
			t.Fatal("a partial repair escaped the depth limit")
		}
	})
	t.Run("node overflow is atomic", func(t *testing.T) {
		source := schemaFixtureRequest("number")
		properties := make(map[string]any)
		for i := 0; i < toolSchemaRestoreMaxNodes; i++ {
			properties[strconv.Itoa(i)] = map[string]any{"type": "number"}
		}
		schemaFixtureParameter(source)["properties"] = properties
		payload := schemaFixtureClone(t, source)
		schemaFixtureParameter(payload)["type"] = "integer"
		before := schemaFixtureJSON(t, payload)
		if restoreCollaborationToolSchemaTypes(payload, schemaFixtureJSON(t, source)) != 0 || !reflect.DeepEqual(before, schemaFixtureJSON(t, payload)) {
			t.Fatal("a partial repair escaped the node limit")
		}
	})
}

func FuzzRestoreCollaborationToolSchemas(f *testing.F) {
	f.Add([]byte(`{"tools":[]}`), []byte(`{"input":[]}`))
	f.Add([]byte(`{"tools":[{"type":"namespace","name":"collaboration","tools":[{"type":"function","name":"wait_agent","parameters":{"properties":{"timeout_ms":{"type":"integer"}}}}]}]}`), []byte(`{"tools":[{"type":"namespace","name":"collaboration","tools":[{"type":"function","name":"wait_agent","parameters":{"properties":{"timeout_ms":{"type":"number"}}}}]}]}`))
	f.Fuzz(func(t *testing.T, payload, original []byte) {
		if len(payload)+len(original) > 65536 {
			t.Skip()
		}
		var body map[string]any
		if json.Unmarshal(payload, &body) != nil {
			return
		}
		restoreCollaborationToolSchemaTypes(body, original)
		if _, err := json.Marshal(body); err != nil {
			t.Fatal(err)
		}
	})
}
