"""Public synthetic schemas only; no accounts, model calls or private payloads."""
from copy import deepcopy


def namespace(label="root", timeout_type="number"):
    return {"type": "namespace", "name": "collaboration", "description": label, "tools": [
        {"type": "function", "name": "wait_agent", "description": "synthetic wait tool",
         "parameters": {"type": "object", "additionalProperties": False,
                        "properties": {"timeout_ms": {"type": timeout_type, "minimum": 0},
                                       "poll_count": {"type": "integer"},
                                       "optional_timeout": {"type": [timeout_type, "null"]}},
                        "required": ["timeout_ms"]}}]}


def request(model="fixture-model", *, dynamic=False, root=True):
    body = {"model": model, "stream": True, "store": False,
            "instructions": "synthetic schema compatibility fixture",
            "input": [{"role": "user", "content": "synthetic original context"}]}
    if root:
        body["tools"] = [namespace(), {"type": "function", "name": "ordinary_tool",
                                      "parameters": {"type": "object", "properties": {"count": {"type": "number"}}}}]
    if dynamic:
        body["input"][:0] = [
            {"type": "additional_tools", "tools": [namespace("dynamic-number")]},
            {"type": "additional_tools", "tools": [namespace("dynamic-integer", "integer")]},
        ]
    return body


def declarations(body):
    """Keep separate same-named tools in root and dynamic declaration scopes."""
    groups = [body.get("tools", [])]
    groups += [i.get("tools", []) for i in body.get("input", []) if i.get("type") == "additional_tools"]
    result = {}
    for tools in groups:
        for tool in tools:
            if tool.get("type") == "namespace" and tool.get("name") == "collaboration":
                label = tool["description"]
                assert label not in result, "duplicate synthetic declaration label"
                result[label] = deepcopy(tool)
    return result


def normalized_request(original):
    """Model only the known host mutation, not the repair being tested."""
    body = deepcopy(original)
    def visit(value):
        if isinstance(value, dict):
            if value.get("type") == "number":
                value["type"] = "integer"
            elif isinstance(value.get("type"), list):
                value["type"] = list(dict.fromkeys("integer" if v == "number" else v for v in value["type"]))
            for child in value.values():
                visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)
    visit(body.get("tools", []))
    for item in body.get("input", []):
        if item.get("type") == "additional_tools":
            visit(item.get("tools", []))
    return body
