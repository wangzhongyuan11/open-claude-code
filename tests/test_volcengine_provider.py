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
