from __future__ import annotations

from openagent.domain.session import Session, SessionTodo

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
