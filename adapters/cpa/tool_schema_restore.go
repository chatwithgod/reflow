package main

import (
	"bytes"
	"encoding/json"
	"reflect"
)

// CPA's plugin adapter may normalize number to integer before invoking us,
// even when the eventual upstream is native Codex. Restore only that exact
// mutation in matching collaboration tool schemas, using the client's own
// declarations. Keep all other host payload edits and tool membership intact.
const toolSchemaRestoreMaxDepth = 64
const toolSchemaRestoreMaxNodes = 16384

type additionalToolDeclaration struct {
	ID    string `json:"id"`
	Type  string `json:"type"`
	Tools []any  `json:"tools"`
}

type additionalToolDeclarations []additionalToolDeclaration

func (d *additionalToolDeclarations) UnmarshalJSON(raw []byte) error {
	// Responses also allows a string input. Its contents are not tool
	// declarations, and must not prevent restoring valid top-level tools.
	raw = bytes.TrimSpace(raw)
	if len(raw) == 0 || raw[0] != '[' {
		return nil
	}
	var items []additionalToolDeclaration
	if err := json.Unmarshal(raw, &items); err != nil {
		return err
	}
	for _, item := range items {
		if item.Type == "additional_tools" {
			*d = append(*d, item)
		}
	}
	return nil
}

type toolSchemaTypeEdit struct {
	schema map[string]any
	value  any
}

type toolSchemaRestorePlan struct {
	edits     []toolSchemaTypeEdit
	nodes     int
	exhausted bool
}

func restoreCollaborationToolSchemaTypes(body map[string]any, original []byte) int {
	if body == nil || len(original) == 0 {
		return 0
	}
	// Decode declarations only: never retain an additional copy of messages,
	// encrypted reasoning, tool results or other conversation data.
	var source struct {
		Tools []any                      `json:"tools"`
		Input additionalToolDeclarations `json:"input"`
	}
	if json.Unmarshal(original, &source) != nil {
		return 0
	}
	plan := &toolSchemaRestorePlan{}
	tools, _ := body["tools"].([]any)
	plan.toolList(tools, source.Tools)
	var target []additionalToolDeclaration
	input, _ := body["input"].([]any)
	for _, raw := range input {
		item, _ := raw.(map[string]any)
		if item["type"] != "additional_tools" {
			continue
		}
		id, _ := item["id"].(string)
		items, _ := item["tools"].([]any)
		target = append(target, additionalToolDeclaration{ID: id, Tools: items})
	}
	sourceIDs := uniqueAdditionalToolIDs(source.Input)
	targetIDs := uniqueAdditionalToolIDs(target)
	for i, item := range target {
		if item.ID != "" {
			// Both sides must have a unique identity; never repair an
			// ambiguous duplicate using whichever declaration came first.
			if matched := sourceIDs[item.ID]; matched != nil && targetIDs[item.ID] != nil {
				plan.toolList(item.Tools, matched.Tools)
			}
		} else if len(target) == len(source.Input) && source.Input[i].ID == "" {
			// Match anonymous declaration blocks by ordinal, not input index:
			// translations may remove preceding system messages. A changed block
			// count is ambiguous, so leave those declarations untouched.
			plan.toolList(item.Tools, source.Input[i].Tools)
		}
	}
	if plan.exhausted {
		return 0 // Never leave a partly restored schema when limits are hit.
	}
	for _, edit := range plan.edits {
		edit.schema["type"] = edit.value
	}
	return len(plan.edits)
}

func uniqueAdditionalToolIDs(items []additionalToolDeclaration) map[string]*additionalToolDeclaration {
	index := make(map[string]*additionalToolDeclaration)
	for i := range items {
		id := items[i].ID
		if id == "" {
			continue
		}
		if _, duplicate := index[id]; duplicate {
			index[id] = nil
		} else {
			index[id] = &items[i]
		}
	}
	return index
}

func collaborationToolSchemas(tools []any) map[string]map[string]any {
	index := make(map[string]map[string]any)
	for _, raw := range tools {
		namespace, _ := raw.(map[string]any)
		if namespace["type"] != "namespace" || namespace["name"] != "collaboration" {
			continue
		}
		children, _ := namespace["tools"].([]any)
		for _, rawChild := range children {
			child, _ := rawChild.(map[string]any)
			if child["type"] != "function" {
				continue
			}
			name, _ := child["name"].(string)
			schema, _ := child["parameters"].(map[string]any)
			if name == "" || schema == nil {
				continue
			}
			if _, duplicate := index[name]; duplicate {
				index[name] = nil
			} else {
				index[name] = schema
			}
		}
	}
	return index
}

func (p *toolSchemaRestorePlan) toolList(target, original []any) {
	source := collaborationToolSchemas(original)
	for name, schema := range collaborationToolSchemas(target) {
		if schema != nil && source[name] != nil {
			p.schema(schema, source[name], 0)
		}
	}
}

func (p *toolSchemaRestorePlan) schema(target, original map[string]any, depth int) {
	if p.exhausted || target == nil || original == nil {
		return
	}
	p.nodes++
	if depth > toolSchemaRestoreMaxDepth || p.nodes > toolSchemaRestoreMaxNodes {
		p.exhausted = true
		return
	}
	if normalized, changed := normalizedNumberSchemaType(original["type"]); changed && reflect.DeepEqual(target["type"], normalized) {
		value := original["type"]
		if values, ok := value.([]any); ok {
			value = append([]any(nil), values...)
		}
		p.edits = append(p.edits, toolSchemaTypeEdit{schema: target, value: value})
	}
	// Traverse schema locations only; literals in defaults/examples/enums are
	// data and must never be interpreted as schema types.
	for _, key := range []string{"properties", "patternProperties", "$defs", "definitions", "dependentSchemas"} {
		left, _ := target[key].(map[string]any)
		right, _ := original[key].(map[string]any)
		for name, raw := range left {
			child, _ := raw.(map[string]any)
			source, _ := right[name].(map[string]any)
			p.schema(child, source, depth+1)
		}
	}
	for _, key := range []string{"items", "additionalItems", "contains", "additionalProperties", "unevaluatedProperties", "unevaluatedItems", "propertyNames", "not", "if", "then", "else", "contentSchema"} {
		left, _ := target[key].(map[string]any)
		right, _ := original[key].(map[string]any)
		p.schema(left, right, depth+1)
	}
	for _, key := range []string{"allOf", "anyOf", "oneOf", "prefixItems"} {
		left, _ := target[key].([]any)
		right, _ := original[key].([]any)
		if len(left) != len(right) {
			continue
		}
		for i, raw := range left {
			child, _ := raw.(map[string]any)
			source, _ := right[i].(map[string]any)
			p.schema(child, source, depth+1)
		}
	}
}

func normalizedNumberSchemaType(value any) (any, bool) {
	if value == "number" {
		return "integer", true
	}
	values, ok := value.([]any)
	if !ok {
		return nil, false
	}
	result := make([]any, 0, len(values))
	seen := make(map[string]bool, len(values))
	changed := false
	for _, raw := range values {
		typ, ok := raw.(string)
		if !ok {
			return nil, false
		}
		if typ == "number" {
			typ, changed = "integer", true
		}
		if !seen[typ] {
			seen[typ] = true
			result = append(result, typ)
		}
	}
	return result, changed
}
