package control

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"io"

	"github.com/chatwithgod/reflow/internal/version"
)

type rpcRequest struct {
	JSONRPC string          `json:"jsonrpc"`
	ID      json.RawMessage `json:"id"`
	Method  string          `json:"method"`
	Params  json.RawMessage `json:"params"`
}

func toolSpec(name, description string, readOnly bool, endpoint bool) map[string]any {
	properties := map[string]any{}
	if endpoint {
		properties["endpoint"] = map[string]any{"type": "string", "description": "Optional local Reflow HTTP origin; defaults to http://127.0.0.1:18516."}
	}
	return map[string]any{"name": name, "description": description, "inputSchema": map[string]any{"type": "object", "properties": properties, "additionalProperties": false}, "annotations": map[string]any{"readOnlyHint": readOnly, "destructiveHint": false, "openWorldHint": false}}
}

func Tools() []map[string]any {
	return []map[string]any{
		toolSpec("status", "Check the local Reflow service and user-level Codex routing; does not call a model.", true, true),
		toolSpec("preview_codex_config", "Preview the single openai_base_url change without writing files or reading login credentials.", true, true),
		toolSpec("connect_codex", "On the user's explicit request, connect native Codex to a running local Reflow service. Saves only the prior URL setting for restore. Restart Codex only when restart_required is true.", false, true),
		toolSpec("restore_codex_config", "On the user's explicit request, restore the prior URL setting while keeping unrelated later edits. Refuses to overwrite a newer routing choice. Restart Codex only when restart_required is true.", false, false),
	}
}

func (c Controller) call(ctx context.Context, name string, arguments json.RawMessage) (any, error) {
	var args map[string]json.RawMessage
	if len(arguments) > 0 && json.Unmarshal(arguments, &args) != nil {
		return nil, errors.New("invalid tool arguments")
	}
	var endpoint string
	for key, value := range args {
		if key != "endpoint" || name == "restore_codex_config" {
			return nil, errors.New("unsupported tool argument")
		}
		if json.Unmarshal(value, &endpoint) != nil {
			return nil, errors.New("endpoint must be a string")
		}
	}
	switch name {
	case "status":
		return c.Status(ctx, endpoint)
	case "preview_codex_config":
		return c.Preview(endpoint)
	case "connect_codex":
		return c.Connect(ctx, endpoint)
	case "restore_codex_config":
		changed, err := c.Restore()
		if err != nil {
			return nil, err
		}
		return map[string]any{"restored": true, "changed": changed, "restart_required": changed}, nil
	default:
		return nil, errors.New("unknown Reflow tool")
	}
}

// ServeMCP uses newline-delimited stdio JSON-RPC. Stdout contains protocol only;
// it never prints requests, authorization data, configuration bodies or prompts.
func (c Controller) ServeMCP(ctx context.Context, input io.Reader, output io.Writer) error {
	scanner := bufio.NewScanner(input)
	scanner.Buffer(make([]byte, 4096), 1<<20)
	encoder := json.NewEncoder(output)
	for scanner.Scan() {
		if ctx.Err() != nil {
			return ctx.Err()
		}
		var req rpcRequest
		if json.Unmarshal(scanner.Bytes(), &req) != nil {
			return errors.New("invalid MCP JSON-RPC input")
		}
		if len(req.ID) == 0 {
			continue
		}
		response := map[string]any{"jsonrpc": "2.0", "id": req.ID}
		var result any
		switch req.Method {
		case "initialize":
			var args struct {
				ProtocolVersion string `json:"protocolVersion"`
			}
			_ = json.Unmarshal(req.Params, &args)
			protocol := "2025-06-18"
			if args.ProtocolVersion == "2024-11-05" || args.ProtocolVersion == "2025-03-26" {
				protocol = args.ProtocolVersion
			}
			result = map[string]any{"protocolVersion": protocol, "capabilities": map[string]any{"tools": map[string]any{}}, "serverInfo": map[string]any{"name": "reflow", "version": version.String}, "instructions": "Local Reflow diagnostics and reversible Codex routing. Installing this plugin does not start the proxy. Start the bundled reflow service first. Never change routing without the user's request."}
		case "ping":
			result = map[string]any{}
		case "tools/list":
			result = map[string]any{"tools": Tools()}
		case "tools/call":
			var args struct {
				Name      string          `json:"name"`
				Arguments json.RawMessage `json:"arguments"`
			}
			if json.Unmarshal(req.Params, &args) != nil {
				return errors.New("invalid MCP call parameters")
			}
			value, err := c.call(ctx, args.Name, args.Arguments)
			if err != nil {
				result = map[string]any{"isError": true, "content": []any{map[string]any{"type": "text", "text": err.Error()}}}
			} else {
				b, _ := json.Marshal(value)
				result = map[string]any{"isError": false, "content": []any{map[string]any{"type": "text", "text": string(b)}}, "structuredContent": value}
			}
		default:
			response["error"] = map[string]any{"code": -32601, "message": "Method not found"}
		}
		if result != nil {
			response["result"] = result
		}
		if err := encoder.Encode(response); err != nil {
			return err
		}
	}
	if scanner.Err() != nil {
		return errors.New("MCP input ended unexpectedly or exceeded its size limit")
	}
	return nil
}
