from __future__ import annotations

from pathlib import Path

from openagent.domain.session import Session, SessionTodo
from openagent.session.task_validation import ChecklistStep, MultiStepRequirements, validate_multistep_requirements

VALID_PRIORITIES = {"low", "medium", "high"}


def render_todos(session: Session) -> str:
    if not session.todos:
        return "No todos."
    lines: list[str] = []
    for index, todo in enumerate(session.todos, start=1):
        lines.append(f"{index}. [{todo.status}] ({todo.priority}) {todo.content}")
    return "\n".join(lines)


def add_todo(session: Session, content: str, priority: str = "medium") -> None:
    priority = priority if priority in VALID_PRIORITIES else "medium"
    session.todos.append(SessionTodo(content=content, priority=priority))
    session.metadata["todo_pending_count"] = str(sum(1 for todo in session.todos if todo.status != "completed"))
    session.touch()


def mark_todo_done(session: Session, index: int) -> None:
    session.todos[index].status = "completed"
    session.metadata["todo_pending_count"] = str(sum(1 for todo in session.todos if todo.status != "completed"))
    session.touch()


def clear_todos(session: Session) -> None:
    session.todos.clear()
    session.metadata["todo_pending_count"] = "0"
    session.touch()


def sync_auto_checklist(session: Session, requirements: MultiStepRequirements) -> None:
    manual = [todo for todo in session.todos if todo.source != "auto-checklist"]
    existing = {todo.key: todo for todo in session.todos if todo.source == "auto-checklist" and todo.key}
    auto: list[SessionTodo] = []
    for step in requirements.steps:
        key = f"checklist:{step.number}"
        current = existing.get(key)
        auto.append(
            SessionTodo(
                content=f"[{step.number}] {step.text}",
                status=current.status if current is not None else "pending",
                priority="high" if step.number == 1 else "medium",
                source="auto-checklist",
                key=key,
            )
        )
    session.todos = manual + auto
    session.metadata["todo_pending_count"] = str(sum(1 for todo in session.todos if todo.status != "completed"))
    session.touch()


def sync_auto_checklist_progress(session: Session, requirements: MultiStepRequirements) -> None:
    overall = validate_multistep_requirements(Path(session.workspace), requirements)
    for todo in session.todos:
        if todo.source != "auto-checklist" or not todo.key:
            continue
        try:
            number = int(todo.key.split(":")[1])
        except (IndexError, ValueError):
            continue
        step = next((item for item in requirements.steps if item.number == number), None)
        if step is None:
            continue
        if _step_is_complete(Path(session.workspace), step, requirements, overall.complete):
            todo.status = "completed"
    session.metadata["todo_pending_count"] = str(sum(1 for todo in session.todos if todo.status != "completed"))
    session.touch()


def _step_is_complete(workspace: Path, step: ChecklistStep, requirements: MultiStepRequirements, overall_complete: bool) -> bool:
    parsed_anything = False
    if step.directories:
        parsed_anything = True
        for directory in step.directories:
            path = (workspace / directory).resolve()
            if not path.is_dir():
                return False
    if step.created_files:
        parsed_anything = True
        for rel_path, expected_content in step.created_files.items():
            path = (workspace / rel_path).resolve()
            if not path.is_file():
                return False
            actual = path.read_text(encoding="utf-8")
            if _normalize_ws(actual) != _normalize_ws(expected_content) and not _path_is_modified_later(requirements, step.number, rel_path):
                return False
    if step.replacements:
        parsed_anything = True
        for rel_path, old_text, new_text in step.replacements:
            path = (workspace / rel_path).resolve()
            if not path.is_file():
                return False
            actual = path.read_text(encoding="utf-8")
            if new_text not in actual:
                return False
            if old_text != new_text and old_text in actual:
                return False
    if step.verification_only:
        return overall_complete
    if parsed_anything:
        return True
    return overall_complete


def _normalize_ws(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines())


def _path_is_modified_later(requirements: MultiStepRequirements, step_number: int, rel_path: str) -> bool:
    for later_step in requirements.steps:
        if later_step.number <= step_number:
            continue
        if rel_path in later_step.created_files:
            return True
        if any(path == rel_path for path, _, _ in later_step.replacements):
            return True
    return False
