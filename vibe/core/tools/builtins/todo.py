from __future__ import annotations

from enum import StrEnum, auto
from typing import Literal

from pydantic import BaseModel, Field, computed_field

from vibe.core.tools.base import BaseTool, BaseToolConfig, BaseToolState, ToolPermission


class TodoStatus(StrEnum):
    PENDING = auto()
    IN_PROGRESS = auto()
    BLOCKED = auto()
    COMPLETED = auto()
    CANCELLED = auto()


class TodoPriority(StrEnum):
    LOW = auto()
    MEDIUM = auto()
    HIGH = auto()


class TodoItem(BaseModel):
    id: str = Field(
        description="Stable unique identifier for the task, reused across updates"
    )
    content: str = Field(description="Brief description of the task")
    status: TodoStatus = Field(
        default=TodoStatus.PENDING,
        description=(
            "Current status: pending, in_progress, blocked, completed, or cancelled"
        ),
    )
    priority: TodoPriority = Field(
        default=TodoPriority.MEDIUM,
        description="Priority level of the task: high, medium, low",
    )


TodoAction = Literal[
    "read", "write", "append", "start", "done", "block", "unblock", "clear"
]


class TodoArgs(BaseModel):
    action: TodoAction = Field(
        description=(
            "read: view the list; write: replace it; append: add todos; start: mark "
            "ids in progress; done: mark ids complete; block/unblock: toggle blocked "
            "ids; clear: empty the list"
        )
    )
    todos: list[TodoItem] | None = Field(
        default=None,
        description="Required for write (the full replacement) and append (new items)",
    )
    ids: list[str] | None = Field(
        default=None,
        description=(
            "Task ids for start, done, block, and unblock. Omit ids on done to "
            "complete every open task."
        ),
    )


class TodoResult(BaseModel):
    verb: str
    todos: list[TodoItem]
    total_count: int

    @computed_field
    @property
    def message(self) -> str:
        return f"{self.verb} {self.total_count} todos"


class TodoValidationError(ValueError):
    pass


def read_todos(todos: list[TodoItem]) -> TodoResult:
    return TodoResult(verb="Retrieved", todos=todos, total_count=len(todos))


def write_todos(todos: list[TodoItem], *, max_todos: int) -> TodoResult:
    _validate(todos, max_todos=max_todos)
    return TodoResult(verb="Updated", todos=todos, total_count=len(todos))


def apply_todo_action(  # noqa: PLR0911 - one branch per action
    args: TodoArgs, todos: list[TodoItem], *, max_todos: int
) -> TodoResult:
    """Apply one todo action atomically.

    ``todos`` is mutated only once the whole action is valid, so a rejected
    update leaves the model and the UI on the previous snapshot.
    """
    match args.action:
        case "read":
            return read_todos(todos)
        case "write":
            if args.todos is None:
                raise TodoValidationError("write requires the full todos list")
            result = write_todos(list(args.todos), max_todos=max_todos)
            todos[:] = result.todos
            return result
        case "append":
            if not args.todos:
                raise TodoValidationError("append requires at least one todo")
            merged = [*todos, *args.todos]
            result = TodoResult(verb="Updated", todos=merged, total_count=len(merged))
            _validate(merged, max_todos=max_todos)
            todos[:] = merged
            return result
        case "clear":
            todos.clear()
            return TodoResult(verb="Cleared", todos=[], total_count=0)
        case "start":
            started = set(_required_ids(args, "start"))
            _check_ids_exist(todos, started)
            updated = [
                todo.model_copy(
                    update={
                        "status": TodoStatus.IN_PROGRESS
                        if todo.id in started
                        else TodoStatus.PENDING
                        if todo.status == TodoStatus.IN_PROGRESS
                        else todo.status
                    }
                )
                for todo in todos
            ]
            return _store(updated, todos, verb="Started")
        case "done":
            targets = args.ids
            updated = _update_status(
                todos,
                ids=targets
                if targets
                else [
                    todo.id
                    for todo in todos
                    if todo.status
                    in {TodoStatus.PENDING, TodoStatus.IN_PROGRESS, TodoStatus.BLOCKED}
                ],
                status=TodoStatus.COMPLETED,
            )
            return _store(_advance(updated), todos, verb="Completed")
        case "block":
            updated = _update_status(
                todos, ids=_required_ids(args, "block"), status=TodoStatus.BLOCKED
            )
            return _store(_advance(updated), todos, verb="Blocked")
        case "unblock":
            updated = []
            ids = set(_required_ids(args, "unblock"))
            for todo in todos:
                if todo.id in ids:
                    if todo.status is not TodoStatus.BLOCKED:
                        raise TodoValidationError(f"Todo {todo.id!r} is not blocked")
                    updated.append(
                        todo.model_copy(update={"status": TodoStatus.PENDING})
                    )
                else:
                    updated.append(todo)
            return _store(_advance(updated), todos, verb="Unblocked")


def _validate(todos: list[TodoItem], *, max_todos: int) -> None:
    if len(todos) > max_todos:
        raise TodoValidationError(f"Cannot store more than {max_todos} todos")
    ids = [todo.id for todo in todos]
    if len(ids) != len(set(ids)):
        raise TodoValidationError("Todo IDs must be unique")


def _check_ids_exist(todos: list[TodoItem], ids: set[str]) -> None:
    missing = ids - {todo.id for todo in todos}
    if missing:
        raise TodoValidationError("Unknown todo ids: " + ", ".join(sorted(missing)))


def _required_ids(args: TodoArgs, action: str) -> list[str]:
    if not args.ids:
        raise TodoValidationError(f"{action} requires at least one todo id")
    return args.ids


def _update_status(
    todos: list[TodoItem], *, ids: list[str], status: TodoStatus
) -> list[TodoItem]:
    wanted = set(ids)
    _check_ids_exist(todos, wanted)
    return [
        todo.model_copy(update={"status": status}) if todo.id in wanted else todo
        for todo in todos
    ]


def _advance(todos: list[TodoItem]) -> list[TodoItem]:
    """Point at the next pending task when no task is active."""
    if any(todo.status == TodoStatus.IN_PROGRESS for todo in todos):
        return todos
    for index, todo in enumerate(todos):
        if todo.status == TodoStatus.PENDING:
            return [
                *todos[:index],
                todo.model_copy(update={"status": TodoStatus.IN_PROGRESS}),
                *todos[index + 1 :],
            ]
    return todos


def _store(updated: list[TodoItem], todos: list[TodoItem], *, verb: str) -> TodoResult:
    todos[:] = updated
    return TodoResult(verb=verb, todos=updated, total_count=len(updated))


class TodoConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS
    max_todos: int = 100


class TodoState(BaseToolState):
    todos: list[TodoItem] = Field(default_factory=list)


class Todo(BaseTool[TodoArgs, TodoResult, TodoConfig, TodoState]):
    pass
