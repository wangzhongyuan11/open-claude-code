from pathlib import Path

from openagent.agent.profile import AgentProfile
from openagent.agent.subagent import SubagentManager
from openagent.domain.messages import AgentResponse, ToolCall
from openagent.domain.tools import ToolContext
from openagent.permission.policy import SessionPermissionPolicy
from openagent.providers.base import BaseProvider
from openagent.session.store import SessionStore
from openagent.tools.builtin.files import ReadFileTool, WriteFileTool
from openagent.tools.registry import ToolRegistry


class ChildWriteProvider(BaseProvider):
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages, tools, system_prompt=None):
        self.calls += 1
        if self.calls == 1:
            return AgentResponse(
                tool_calls=[
                    ToolCall(
                        id="sub-write-1",
                        name="write_file",
                        arguments={"path": "child.txt", "content": "from child"},
                    )
                ]
            )
        return AgentResponse(text="done")


def test_permission_ask_blocks_until_once_reply(tmp_path: Path):
    store = SessionStore(tmp_path / ".openagent" / "sessions")
    session = store.create(tmp_path, session_id="sess-1")
    profile = AgentProfile(name="build")
    policy = SessionPermissionPolicy(store, profile, yolo=False)
    registry = ToolRegistry(permission_policy=policy)
    registry.register(WriteFileTool())

    replies: list[str] = []

    def ask_permission(request):
        replies.append(request.pattern)
        return "once"

    result = registry.invoke(
        "write_file",
        {"path": "demo.txt", "content": "hello"},
        ToolContext(
            workspace=tmp_path,
            session_id=session.id,
            agent_name="build",
            runtime_state={"ask_permission": ask_permission, "yolo_mode": "false"},
        ),
    )

    assert result.is_error is False
    assert replies == ["demo.txt"]
    session = store.load("sess-1")
    assert any(part.type == "permission" for message in session.messages for part in message.parts)


def test_permission_always_persists_and_reuses_rule(tmp_path: Path):
    store = SessionStore(tmp_path / ".openagent" / "sessions")
    session = store.create(tmp_path, session_id="sess-1")
    profile = AgentProfile(name="build")
    policy = SessionPermissionPolicy(store, profile, yolo=False)
    registry = ToolRegistry(permission_policy=policy)
    registry.register(WriteFileTool())

    ask_count = {"value": 0}

    def ask_permission(request):
        ask_count["value"] += 1
        return "always"

    context = ToolContext(
        workspace=tmp_path,
        session_id=session.id,
        agent_name="build",
        runtime_state={"ask_permission": ask_permission, "yolo_mode": "false"},
    )
    registry.invoke("write_file", {"path": "demo.txt", "content": "hello"}, context)
    registry.invoke("write_file", {"path": "demo.txt", "content": "hello again"}, context)

    assert ask_count["value"] == 1
    session = store.load("sess-1")
    assert session.permission["rules"]


def test_yolo_auto_approves_ask_but_not_explicit_deny(tmp_path: Path):
    store = SessionStore(tmp_path / ".openagent" / "sessions")
    session = store.create(tmp_path, session_id="sess-1")

    build_policy = SessionPermissionPolicy(store, AgentProfile(name="build"), yolo=True)
    build_registry = ToolRegistry(permission_policy=build_policy)
    build_registry.register(WriteFileTool())
    build_result = build_registry.invoke(
        "write_file",
        {"path": "demo.txt", "content": "hello"},
        ToolContext(workspace=tmp_path, session_id=session.id, agent_name="build", runtime_state={"yolo_mode": "true"}),
    )
    assert build_result.is_error is False

    explore_policy = SessionPermissionPolicy(
        store,
        AgentProfile(
            name="explore",
            allowed_tools={"read_file"},
        ),
        yolo=True,
    )
    explore_registry = ToolRegistry(permission_policy=explore_policy)
    explore_registry.register(WriteFileTool())
    deny_result = explore_registry.invoke(
        "write_file",
        {"path": "blocked.txt", "content": "nope"},
        ToolContext(workspace=tmp_path, session_id=session.id, agent_name="explore", runtime_state={"yolo_mode": "true"}),
    )
    assert deny_result.is_error is True
    assert deny_result.error is not None
    assert deny_result.error.type == "permission_denied"
    assert not (tmp_path / "blocked.txt").exists()


def test_subagent_uses_same_session_permission_state(tmp_path: Path):
    store = SessionStore(tmp_path / ".openagent" / "sessions")
    session = store.create(tmp_path, session_id="sess-main")

    def registry_factory(_agent_name: str):
        policy = SessionPermissionPolicy(store, AgentProfile(name="general"), yolo=False)
        registry = ToolRegistry(permission_policy=policy)
        registry.register(WriteFileTool())
        registry.register(ReadFileTool())
        return registry

    manager = SubagentManager(
        provider_factory=ChildWriteProvider,
        registry_factory=registry_factory,
        workspace=tmp_path,
        system_prompt="subagent prompt",
        session_id_factory=lambda: session.id,
        runtime_state_factory=lambda _agent: {"ask_permission": lambda request: "always", "yolo_mode": "false"},
    )

    result = manager.run("create child.txt")

    assert result.summary == "done"
    session = store.load(session.id)
    assert session.permission["rules"]
    assert (tmp_path / "child.txt").exists()
