from pathlib import Path

from openagent.agent.profile import AgentProfile
from openagent.agent.store import AgentStore


def test_agent_store_roundtrip_markdown(tmp_path: Path):
    store = AgentStore(tmp_path)
    profile = AgentProfile(
        name="ts-reviewer",
        description="Use this agent when reviewing TypeScript code.",
        mode="all",
        native=False,
        prompt="You are a TypeScript reviewer.",
        steps=9,
        inherits_default_prompt=False,
        allowed_tools={"read_file", "grep"},
    )
    store.save(profile)

    restored = store.get("ts-reviewer")

    assert restored is not None
    assert restored.name == "ts-reviewer"
    assert restored.description.startswith("Use this agent when")
    assert restored.prompt == "You are a TypeScript reviewer."
    assert restored.allowed_tools == {"read_file", "grep"}
