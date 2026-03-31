from __future__ import annotations

from dataclasses import dataclass, field
import difflib

from openagent.domain.messages import Message, Part
from openagent.domain.tools import ToolArtifact, ToolExecutionResult


@dataclass(slots=True)
class AssistantMessageBuilder:
    message: Message = field(default_factory=lambda: Message(role="assistant", content="", parts=[]))
    _active_text_index: int | None = None
    _active_reasoning_index: int | None = None

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

    def start_text(self) -> None:
        if self._active_text_index is not None:
            return
        self.message.add_part(Part(type="text", content="", state={"status": "streaming"}))
        self._active_text_index = len(self.message.parts) - 1

    def add_text(self, text: str) -> None:
        if not text:
            return
        self.start_text()
        if self._active_text_index is None:
            return
        part = self.message.parts[self._active_text_index]
        if isinstance(part.content, str):
            part.content += text
            self.message.content = self.message._derive_content_from_parts()

    def end_text(self) -> None:
        if self._active_text_index is None:
            return
        self.message.parts[self._active_text_index].state["status"] = "completed"
        self._active_text_index = None

    def start_reasoning(self) -> None:
        if self._active_reasoning_index is not None:
            return
        self.message.add_part(Part(type="reasoning", content="", state={"status": "streaming"}))
        self._active_reasoning_index = len(self.message.parts) - 1

    def add_reasoning(self, text: str) -> None:
        if not text:
            return
        self.start_reasoning()
        if self._active_reasoning_index is None:
            return
        part = self.message.parts[self._active_reasoning_index]
        if isinstance(part.content, str):
            part.content += text
            self.message.content = self.message._derive_content_from_parts()

    def end_reasoning(self) -> None:
        if self._active_reasoning_index is None:
            return
        self.message.parts[self._active_reasoning_index].state["status"] = "completed"
        self._active_reasoning_index = None

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
        self.end_reasoning()
        self.end_text()
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
    result: ToolExecutionResult | None = None
    message: Message = field(init=False)

    def __post_init__(self) -> None:
        self.message = Message(
            role="tool",
            content="",
            tool_call_id=self.tool_call_id,
            name=self.name,
            parts=[],
        )

    def add_tool_result(self) -> None:
        metadata = self.result.metadata if self.result is not None else {}
        error_payload = None
        if self.result is not None and self.result.error is not None:
            error_payload = {
                "type": self.result.error.type,
                "message": self.result.error.message,
                "retryable": self.result.error.retryable,
                "hint": self.result.error.hint,
            }
        self.message.add_part(
            Part(
                type="tool",
                content={
                    "tool_call_id": self.tool_call_id,
                    "name": self.name,
                    "title": self.result.title if self.result is not None else self.name,
                    "arguments": self.arguments,
                    "output": self.content,
                    "metadata": metadata,
                    "error": error_payload,
                    "truncated": self.result.truncated if self.result is not None else False,
                },
                state={"status": self.result.status if self.result is not None else "succeeded"},
            )
        )

    def add_file_result(self, mutation: str | None = None) -> None:
        path = self.arguments.get("path")
        if not path:
            return
        state = {"status": self.result.status if self.result is not None else "succeeded"}
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
                state={"status": self.result.status if self.result is not None else "succeeded"},
            )
        )

    def add_artifact_results(self, artifacts: list[ToolArtifact]) -> None:
        for artifact in artifacts:
            if artifact.kind in {"file", "tool-output"} and artifact.path:
                self.message.add_part(
                    Part(
                        type="file",
                        content={
                            "source": "artifact",
                            "path": artifact.path,
                            "kind": artifact.kind,
                            "description": artifact.description,
                            "content": self.content if artifact.kind == "file" else "",
                        },
                        state={"status": "recorded"},
                    )
                )

    def build(self) -> Message:
        self.message.content = self.message._derive_content_from_parts()
        return self.message
