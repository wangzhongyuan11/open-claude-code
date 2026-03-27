from __future__ import annotations

from dataclasses import dataclass, field
import difflib

from openagent.domain.messages import Message, Part


@dataclass(slots=True)
class AssistantMessageBuilder:
    message: Message = field(default_factory=lambda: Message(role="assistant", content="", parts=[]))

    def start_step(self, requested_tools: int) -> None:
        self.message.add_part(
            Part(
                type="step-start",
                content={"phase": "llm", "requested_tools": requested_tools},
                state={"status": "started"},
            )
        )

    def update_requested_tools(self, requested_tools: int) -> None:
        for part in self.message.parts:
            if part.type == "step-start" and isinstance(part.content, dict):
                part.content["requested_tools"] = requested_tools
                return

    def add_text(self, text: str) -> None:
        if not text:
            return
        if self.message.parts and self.message.parts[-1].type == "text" and isinstance(self.message.parts[-1].content, str):
            self.message.parts[-1].content += text
            self.message.content = self.message._derive_content_from_parts()
            return
        self.message.add_part(Part(type="text", content=text))

    def add_reasoning(self, text: str) -> None:
        if not text:
            return
        if self.message.parts and self.message.parts[-1].type == "reasoning" and isinstance(self.message.parts[-1].content, str):
            self.message.parts[-1].content += text
            self.message.content = self.message._derive_content_from_parts()
            return
        self.message.add_part(Part(type="reasoning", content=text))

    def add_tool_request(self, tool_call_id: str, name: str, arguments: dict) -> None:
        self.message.add_part(
            Part(
                type="tool",
                content={
                    "id": tool_call_id,
                    "name": name,
                    "arguments": arguments,
                },
                state={"status": "requested"},
            )
        )

    def finish_step(self, finish: str, tokens: dict, cost: float) -> None:
        self.message.add_part(
            Part(
                type="step-finish",
                content={
                    "finish": finish,
                    "tokens": tokens,
                    "cost": cost,
                },
                state={"status": "completed"},
            )
        )

    def build(self, **message_fields) -> Message:
        for key, value in message_fields.items():
            setattr(self.message, key, value)
        return self.message


@dataclass(slots=True)
class ToolMessageBuilder:
    name: str
    tool_call_id: str
    arguments: dict
    content: str
    is_error: bool = False
    message: Message = field(init=False)

    def __post_init__(self) -> None:
        self.message = Message(
            role="tool",
            content=self.content,
            tool_call_id=self.tool_call_id,
            name=self.name,
            parts=[],
        )

    def add_tool_result(self) -> None:
        self.message.add_part(
            Part(
                type="tool",
                content={
                    "tool_call_id": self.tool_call_id,
                    "name": self.name,
                    "arguments": self.arguments,
                    "output": self.content,
                },
                state={"status": "error" if self.is_error else "completed"},
            )
        )

    def add_file_result(self, mutation: str | None = None) -> None:
        path = self.arguments.get("path")
        if not path:
            return
        state = {"status": "error" if self.is_error else "completed"}
        if mutation:
            state["mutation"] = mutation
        self.message.add_part(
            Part(
                type="file",
                content={
                    "source": "file",
                    "path": str(path),
                    "content": self.content,
                },
                state=state,
            )
        )

    def add_patch_result(self, before_content: str, after_content: str, path: str) -> None:
        diff = "".join(
            difflib.unified_diff(
                before_content.splitlines(keepends=True),
                after_content.splitlines(keepends=True),
                fromfile=f"a/{path}",
                tofile=f"b/{path}",
            )
        )
        if not diff:
            return
        self.message.add_part(
            Part(
                type="patch",
                content=diff,
                state={"status": "completed"},
            )
        )

    def add_snapshot_refs(self, before_ref: str | None, after_ref: str | None, path: str) -> None:
        refs = []
        if before_ref:
            refs.append({"ref": before_ref, "kind": "before"})
        if after_ref:
            refs.append({"ref": after_ref, "kind": "after"})
        for item in refs:
            self.message.add_part(
                Part(
                    type="snapshot",
                    content={
                        "path": path,
                        "ref": item["ref"],
                        "kind": item["kind"],
                    },
                    state={"status": "recorded"},
                )
            )

    def add_subtask_result(self) -> None:
        self.message.add_part(
            Part(
                type="subtask",
                content={
                    "prompt": self.arguments.get("prompt", ""),
                    "result": self.content,
                },
                state={"status": "error" if self.is_error else "completed"},
            )
        )

    def build(self) -> Message:
        return self.message
