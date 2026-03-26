from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from openagent.agent.runtime import AgentRuntime
from openagent.config.settings import Settings
from openagent.domain.messages import AgentResponse, ToolCall
from openagent.session.manager import SessionManager
from openagent.session.store import SessionStore
from openagent.providers.base import BaseProvider


class DemoProvider(BaseProvider):
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, messages, tools, system_prompt=None):
        self.calls += 1
        if self.calls == 1:
            return AgentResponse(
                text="我会创建 demo.txt。",
                tool_calls=[
                    ToolCall(
                        id="demo-tool-1",
                        name="write_file",
                        arguments={"path": "demo.txt", "content": "hello from demo"},
                    )
                ],
            )
        return AgentResponse(text="演示完成。")


def main() -> None:
    with TemporaryDirectory() as tmp:
        workspace = Path(tmp)
        settings = Settings.from_workspace(workspace)
        manager = SessionManager(SessionStore(settings.session_root))
        session = manager.start(workspace=workspace)
        runtime = AgentRuntime(
            provider=DemoProvider(),
            provider_factory=DemoProvider,
            workspace=workspace,
            session_manager=manager,
            session=session,
            settings=settings,
        )
        reply = runtime.run_turn("创建一个 demo.txt")
        print("reply:", reply)
        print("file:", (workspace / "demo.txt").read_text(encoding="utf-8"))
        print("session:", runtime.session_id)


if __name__ == "__main__":
    main()
