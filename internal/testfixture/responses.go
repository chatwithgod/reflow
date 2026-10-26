// Package testfixture contains synthetic Responses records, never live data.
package testfixture

import (
	"encoding/json"
	"fmt"
	"net/http"

	"github.com/chatwithgod/reflow/core"
)

func Round(id string, tokens int, tool bool) []core.Object {
	reason := core.Object{"type": "reasoning", "id": id + "-reason", "summary": []any{}, "encrypted_content": "synthetic-" + id}
	answer := core.Object{"type": "message", "id": id + "-answer", "role": "assistant", "status": "completed", "phase": "final_answer", "content": []any{core.Object{"type": "output_text", "text": "synthetic answer"}}}
	if tool {
		answer = core.Object{"type": "function_call", "id": id + "-tool", "call_id": id + "-call", "name": "inspect", "arguments": "{}", "status": "completed"}
	}
	usage := core.Object{"input_tokens": 100, "output_tokens": tokens + 10, "total_tokens": 110 + tokens, "output_tokens_details": core.Object{"reasoning_tokens": tokens}}
	return []core.Object{
		{"type": "response.created", "response": core.Object{"id": id, "status": "in_progress", "output": []any{}}},
		{"type": "response.output_item.added", "output_index": 0, "item": core.Object{"type": "reasoning", "id": id + "-reason", "summary": []any{}}},
		{"type": "response.output_item.done", "output_index": 0, "item": reason},
		{"type": "response.output_item.added", "output_index": 1, "item": answer},
		{"type": "response.output_item.done", "output_index": 1, "item": answer},
		{"type": "response.completed", "response": core.Object{"id": id, "status": "completed", "output": []any{reason, answer}, "usage": usage}},
	}
}

func WriteSSE(w http.ResponseWriter, events []core.Object) {
	w.Header().Set("Content-Type", "text/event-stream")
	for _, ev := range events {
		b, _ := json.Marshal(ev)
		fmt.Fprintf(w, "data: %s\n\n", b)
		_ = http.NewResponseController(w).Flush()
	}
	fmt.Fprint(w, "data: [DONE]\n\n")
}
