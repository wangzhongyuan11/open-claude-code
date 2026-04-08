from __future__ import annotations

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import time


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

MODE = os.getenv("FAKE_REMOTE_MODE", "stream")
TOKEN = os.getenv("FAKE_REMOTE_TOKEN", "")


def _result_for(request: dict) -> dict:
    method = request.get("method")
    if method == "initialize":
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
            "serverInfo": {"name": "fake-remote-mcp", "version": "0.1"},
        }
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "resources/list":
        return {"resources": RESOURCES}
    if method == "prompts/list":
        return {"prompts": PROMPTS}
    if method == "resources/read":
        return {"contents": [{"uri": "fake://resource", "mimeType": "text/plain", "text": "fake resource"}]}
    if method == "prompts/get":
        return {"messages": [{"role": "user", "content": {"type": "text", "text": "fake prompt"}}]}
    if method == "tools/call":
        args = request.get("params", {}).get("arguments") or {}
        return {"content": [{"type": "text", "text": "echo:" + str(args.get("message", ""))}]}
    raise KeyError(f"unknown method: {method}")


class Handler(BaseHTTPRequestHandler):
    server_version = "FakeRemoteMCP/0.1"

    def log_message(self, format, *args):  # noqa: A003
        return

    def do_GET(self):  # noqa: N802
        if self.path != "/sse":
            self.send_response(404)
            self.end_headers()
            return
        if not self._check_auth():
            return
        if MODE == "registration":
            self.send_response(428)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        endpoint = json.dumps({"endpoint": "/messages"})
        self.wfile.write(f"event: endpoint\ndata: {endpoint}\n\n".encode("utf-8"))
        self.wfile.flush()
        while True:
            raw = self.server.queue.pop(0) if self.server.queue else None
            if raw is None:
                time.sleep(0.01)
                continue
            self.wfile.write(f"event: message\ndata: {raw}\n\n".encode("utf-8"))
            self.wfile.flush()

    def do_POST(self):  # noqa: N802
        if not self._check_auth():
            return
        if MODE == "registration":
            self.send_response(428)
            self.end_headers()
            return
        if self.path == "/mcp":
            if MODE == "sse_only":
                self.send_response(404)
                self.end_headers()
                return
            self._handle_rpc(streamable=True)
            return
        if self.path == "/messages":
            self._handle_rpc(streamable=False)
            return
        self.send_response(404)
        self.end_headers()

    def _handle_rpc(self, *, streamable: bool) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
        if "id" not in payload:
            self.send_response(202)
            self.end_headers()
            return
        response = {"jsonrpc": "2.0", "id": payload["id"]}
        try:
            response["result"] = _result_for(payload)
        except KeyError as exc:
            response["error"] = {"message": str(exc)}
        if streamable:
            body = json.dumps(response).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self.server.queue.append(json.dumps(response))
        self.send_response(202)
        self.end_headers()

    def _check_auth(self) -> bool:
        if not TOKEN:
            return True
        if self.headers.get("X-API-Key") == TOKEN:
            return True
        self.send_response(401)
        self.end_headers()
        return False


class Server(ThreadingHTTPServer):
    def __init__(self, server_address, RequestHandlerClass):  # noqa: N803
        super().__init__(server_address, RequestHandlerClass)
        self.queue: list[str] = []


def main() -> None:
    port = int(sys.argv[1])
    server = Server(("127.0.0.1", port), Handler)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
