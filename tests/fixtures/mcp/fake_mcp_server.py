from __future__ import annotations

import json
import sys


TOOLS = [
    {
        "name": "echo",
        "description": "Echo a message.",
        "inputSchema": {
            "type": "object",
            "properties": {"message": {"type": "string"}},
            "required": ["message"],
        },
    }
]

RESOURCES = [{"uri": "fake://resource", "name": "fake-resource", "mimeType": "text/plain"}]
PROMPTS = [{"name": "fake-prompt", "description": "A fake prompt"}]


def send(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if "id" not in request:
        continue
    if method == "initialize":
        send(
            {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
                    "serverInfo": {"name": "fake-mcp", "version": "0.1"},
                },
            }
        )
    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": request["id"], "result": {"tools": TOOLS}})
    elif method == "resources/list":
        send({"jsonrpc": "2.0", "id": request["id"], "result": {"resources": RESOURCES}})
    elif method == "prompts/list":
        send({"jsonrpc": "2.0", "id": request["id"], "result": {"prompts": PROMPTS}})
    elif method == "resources/read":
        send(
            {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {"contents": [{"uri": "fake://resource", "mimeType": "text/plain", "text": "fake resource"}]},
            }
        )
    elif method == "prompts/get":
        send(
            {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {"messages": [{"role": "user", "content": {"type": "text", "text": "fake prompt"}}]},
            }
        )
    elif method == "tools/call":
        args = request.get("params", {}).get("arguments") or {}
        send(
            {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {"content": [{"type": "text", "text": "echo:" + str(args.get("message", ""))}]},
            }
        )
    else:
        send({"jsonrpc": "2.0", "id": request["id"], "error": {"message": f"unknown method: {method}"}})
