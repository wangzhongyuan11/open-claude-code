import json

from openagent.domain.messages import Message, ToolCall
from openagent.domain.tools import ToolSpec
from openagent.providers.volcengine import VolcengineProvider


def test_volcengine_provider_builds_openai_compatible_messages():
    messages = [
        Message(role="user", content="hello"),
        Message(
            role="assistant",
            content="",
            tool_calls=[ToolCall(id="call-1", name="read_file", arguments={"path": "a.txt"})],
        ),
        Message(role="tool", content="file content", tool_call_id="call-1", name="read_file"),
    ]

    chat_messages = VolcengineProvider._to_chat_messages(messages, "system")

    assert chat_messages[0] == {"role": "system", "content": "system"}
    assert chat_messages[2]["tool_calls"][0]["function"]["name"] == "read_file"
    assert chat_messages[3]["role"] == "tool"
    assert chat_messages[3]["tool_call_id"] == "call-1"


def test_volcengine_provider_parses_tool_calls():
    payload = {
        "choices": [
            {
                "message": {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "function": {
                                "name": "write_file",
                                "arguments": json.dumps({"path": "a.txt", "content": "x"}),
                            },
                        }
                    ],
                }
            }
        ]
    }

    response = VolcengineProvider._parse_response(payload)

    assert response.tool_calls[0].name == "write_file"
    assert response.tool_calls[0].arguments["path"] == "a.txt"


def test_volcengine_provider_posts_expected_payload(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8")

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(req.header_items())
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("openagent.providers.volcengine.request.urlopen", fake_urlopen)

    provider = VolcengineProvider(
        model="ep-test",
        api_key="secret",
        base_url="https://operator.las.cn-beijing.volces.com/api/v1",
    )
    response = provider.generate(
        messages=[Message(role="user", content="hello")],
        tools=[
            ToolSpec(
                name="read_file",
                description="read file",
                input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
            )
        ],
        system_prompt="system",
    )

    assert response.text == "ok"
    assert captured["url"].endswith("/chat/completions")
    assert captured["body"]["model"] == "ep-test"
    assert captured["body"]["messages"][0]["role"] == "system"
    assert captured["headers"]["Authorization"] == "Bearer secret"


def test_volcengine_provider_stream_generate_parses_text_and_tool_calls(monkeypatch):
    provider = VolcengineProvider(
        model="ep-test",
        api_key="secret",
        base_url="https://operator.las.cn-beijing.volces.com/api/v1",
    )

    def fake_stream(path, payload):
        assert path == "/chat/completions"
        assert payload["stream"] is True
        yield {
            "model": "ep-test",
            "choices": [
                {
                    "delta": {"content": "先"},
                    "finish_reason": None,
                }
            ],
        }
        yield {
            "model": "ep-test",
            "choices": [
                {
                    "delta": {
                        "content": "读取",
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call-1",
                                "function": {"name": "read_file", "arguments": "{\"path\":\"README"},
                            }
                        ],
                    },
                    "finish_reason": None,
                }
            ],
        }
        yield {
            "model": "ep-test",
            "choices": [
                {
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "function": {"arguments": ".md\"}"},
                            }
                        ]
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 12, "completion_tokens": 5},
        }

    monkeypatch.setattr(provider, "_post_stream_json", fake_stream)

    events = list(
        provider.stream_generate(
            messages=[Message(role="user", content="hello")],
            tools=[
                ToolSpec(
                    name="read_file",
                    description="read file",
                    input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
                )
            ],
            system_prompt="system",
        )
    )

    assert events[0]["type"] == "start"
    assert events[1] == {"type": "text-delta", "text": "先"}
    assert events[2] == {"type": "text-delta", "text": "读取"}
    assert events[3]["type"] == "tool-call"
    assert events[3]["tool_call"].name == "read_file"
    assert events[3]["tool_call"].arguments == {"path": "README.md"}
    assert events[4]["type"] == "finish"
    assert events[4]["response"].text == "先读取"
    assert events[4]["response"].finish == "tool-calls"


def test_volcengine_provider_post_stream_json_parses_sse(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def __iter__(self):
            yield b"data: {\"choices\":[{\"delta\":{\"content\":\"hi\"}}]}\n"
            yield b"\n"
            yield b"data: [DONE]\n"

    def fake_urlopen(req, timeout):
        captured["headers"] = dict(req.header_items())
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("openagent.providers.volcengine.request.urlopen", fake_urlopen)

    provider = VolcengineProvider(
        model="ep-test",
        api_key="secret",
        base_url="https://operator.las.cn-beijing.volces.com/api/v1",
    )

    chunks = list(provider._post_stream_json("/chat/completions", {"stream": True}))

    assert chunks == [{"choices": [{"delta": {"content": "hi"}}]}]
    assert captured["headers"]["Accept"] == "text/event-stream"
    assert captured["body"]["stream"] is True
