"""Run Vibe's own tools inside a Unified Harness session.

Todo semantics come from the legacy tool's own module so the two harnesses cannot
drift; only the storage differs, and the list is deliberately not carried across
compaction -- durable notes belong in the scratchpad, which the agent reads back.
Goal state is session-owned runtime state: it drives the adapter's bounded
autonomous continuation loop and is not persisted across sessions.

Design: ``vibe/docs/design/unified-harness-todo-and-scratchpad.md``.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Container, Mapping, Sequence
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ValidationError

from mistralai_vibe_local_harness.protocol import (  # pyright: ignore[reportMissingImports]
    RustProtocolError,
    RustProvidedToolCall,
    RustProvidedToolCallAction,
    RustProvidedToolDefinition,
    RustTextContentBlock,
    RustToolFailedEvent,
    RustToolFailureResult,
    RustToolGroupDefinition,
    RustToolSucceededEvent,
    RustToolSuccessResult,
)

if TYPE_CHECKING:
    # Deferred, unlike `protocol` above: this subpackage pulls in `mcp` and
    # `mistralai`, which `test_importing_app_server_local_does_not_import_mcp_package`
    # keeps off the CLI's startup path.
    from mistralai_vibe_local_harness.vibe import (  # pyright: ignore[reportMissingImports]
        ProvidedToolExecutor,
        ProvidedToolExecutorFactory,
        ToolApprovalMode,
    )
    from vibe.core.config import VibeConfigSchema

from vibe.app_server._cron import (
    CRON_TOOL_DESCRIPTION,
    CRON_TOOL_NAME,
    CronArgs,
    CronResult,
    cron_input_schema,
    run_cron,
)
from vibe.app_server._session_spawn import (
    START_SESSION_TOOL_DESCRIPTION,
    START_SESSION_TOOL_NAME,
    SessionOriginResolver,
    SessionSpawner,
    SessionSpawnError,
    SpawnModel,
    StartSessionArgs,
    StartSessionResult,
    run_start_session,
    start_session_input_schema,
)
from vibe.app_server._unified_scheduled_loops import (
    ScheduledLoopStoreError,
    UnifiedScheduledLoops,
)
from vibe.app_server._unified_scratchpad import (
    SCRATCHPAD_TOOL_DESCRIPTION,
    SCRATCHPAD_TOOL_NAME,
    ScratchpadArgs,
    ScratchpadResult,
    run_scratchpad,
    scratchpad_dir,
)
from vibe.core.loop import LoopError
from vibe.core.tools.builtins.consult import Consult, ConsultArgs, ConsultResult
from vibe.core.tools.builtins.goal import (
    Goal,
    GoalArgs,
    GoalRecord,
    GoalResult,
    GoalStatus,
    add_goal_tokens,
    apply_goal_action,
    create_goal,
)
from vibe.core.tools.builtins.todo import (
    Todo,
    TodoArgs,
    TodoConfig,
    TodoItem,
    TodoResult,
    apply_todo_action,
)
from vibe.core.types import ImageAttachment
from vibe.core.utils.matching import name_matches

VIBE_TOOL_GROUP = "vibe"

TODO_TOOL_NAME = "todo"
GOAL_TOOL_NAME = "goal"
CONSULT_TOOL_NAME = "consult"

# Routes the Runtime gates by, mapped to the names Vibe configures the tools under,
# so the permission resolver reads `[tools.todo]` for `vibe.todo`.
VIBE_PROVIDED_TOOL_NAMES = {
    f"{VIBE_TOOL_GROUP}.{TODO_TOOL_NAME}": TODO_TOOL_NAME,
    f"{VIBE_TOOL_GROUP}.{GOAL_TOOL_NAME}": GOAL_TOOL_NAME,
    f"{VIBE_TOOL_GROUP}.{CONSULT_TOOL_NAME}": CONSULT_TOOL_NAME,
    f"{VIBE_TOOL_GROUP}.{CRON_TOOL_NAME}": CRON_TOOL_NAME,
    f"{VIBE_TOOL_GROUP}.{START_SESSION_TOOL_NAME}": START_SESSION_TOOL_NAME,
}

# "ask" routes through Vibe's permission resolver. Cron defaults to allowed there,
# while explicit config and session permission overrides still take precedence.
# Starting a session kicks off real work, so it keeps the resolver's default: ask.
# Scratchpad writes only inside the session's own storage and is pinned allowed.
VIBE_PROVIDED_TOOL_MODES: dict[str, ToolApprovalMode] = {
    TODO_TOOL_NAME: "ask",
    GOAL_TOOL_NAME: "allow",
    CONSULT_TOOL_NAME: "allow",
    CRON_TOOL_NAME: "ask",
    START_SESSION_TOOL_NAME: "ask",
    SCRATCHPAD_TOOL_NAME: "allow",
}


def vibe_tool_groups(
    available_tools: Container[str],
    *,
    enabled_tools: Sequence[str] = (),
    disabled_tools: Sequence[str] = (),
    session_spawn: Sequence[SpawnModel] | None = None,
) -> list[RustToolGroupDefinition]:
    # Todo follows the legacy roster, so a tool switched off in config stays off here
    # too. The scratchpad has no catalogue entry to be filtered out of, so it reads
    # the same globs itself rather than escaping tool filtering entirely.
    tools: list[RustProvidedToolDefinition] = []
    if TODO_TOOL_NAME in available_tools:
        tools.append(
            RustProvidedToolDefinition(
                name=TODO_TOOL_NAME,
                description=Todo.get_full_description(),
                input_schema=TodoArgs.model_json_schema(),
                output_schema=TodoResult.model_json_schema(),
                # Programmatic too: a `run_typescript` program is one tool call, so a
                # direct-only tool leaves the list frozen until the program returns.
                exposure="direct_and_programmatic",
            )
        )
    if GOAL_TOOL_NAME in available_tools:
        tools.append(
            RustProvidedToolDefinition(
                name=GOAL_TOOL_NAME,
                description=Goal.get_full_description(),
                input_schema=GoalArgs.model_json_schema(),
                output_schema=GoalResult.model_json_schema(),
                exposure="direct",
            )
        )
    if CONSULT_TOOL_NAME in available_tools:
        tools.append(
            RustProvidedToolDefinition(
                name=CONSULT_TOOL_NAME,
                description=Consult.get_full_description(),
                input_schema=ConsultArgs.model_json_schema(),
                output_schema=ConsultResult.model_json_schema(),
                exposure="direct",
            )
        )
    if _passes_tool_filters(
        SCRATCHPAD_TOOL_NAME, enabled=enabled_tools, disabled=disabled_tools
    ):
        tools.append(
            RustProvidedToolDefinition(
                name=SCRATCHPAD_TOOL_NAME,
                description=SCRATCHPAD_TOOL_DESCRIPTION,
                input_schema=ScratchpadArgs.model_json_schema(),
                output_schema=ScratchpadResult.model_json_schema(),
                exposure="direct",
            )
        )
    if _passes_tool_filters(
        CRON_TOOL_NAME, enabled=enabled_tools, disabled=disabled_tools
    ):
        tools.append(
            RustProvidedToolDefinition(
                name=CRON_TOOL_NAME,
                description=CRON_TOOL_DESCRIPTION,
                input_schema=cron_input_schema(),
                output_schema=CronResult.model_json_schema(),
                exposure="direct",
            )
        )
    if session_spawn is not None and _passes_tool_filters(
        START_SESSION_TOOL_NAME, enabled=enabled_tools, disabled=disabled_tools
    ):
        tools.append(
            RustProvidedToolDefinition(
                name=START_SESSION_TOOL_NAME,
                description=START_SESSION_TOOL_DESCRIPTION,
                input_schema=start_session_input_schema(session_spawn),
                output_schema=StartSessionResult.model_json_schema(),
                exposure="direct",
            )
        )
    if not tools:
        return []

    return [
        RustToolGroupDefinition(
            name=VIBE_TOOL_GROUP, description="Vibe's own tools.", tools=tools
        )
    ]


def _passes_tool_filters(
    name: str, *, enabled: Sequence[str], disabled: Sequence[str]
) -> bool:
    if enabled and not name_matches(name, list(enabled)):
        return False
    return not (disabled and name_matches(name, list(disabled)))


class VibeProvidedTools:
    def __init__(self) -> None:
        # Held here rather than in the executor closure so a rewind can drop it: an
        # in-place rewind keeps the session alive, and a list that outlived the
        # truncated history would let `todo read` return the discarded entries.
        self._todos: dict[str, list[TodoItem]] = {}
        # Goal state is session-owned and deliberately in memory: a resumed session
        # starts without an autonomous loop unless the user re-creates the goal.
        self._goals: dict[str, GoalRecord] = {}
        # Installed by the live adapter so a `todo` tool call can push the list to
        # the client instead of waiting for a transcript snapshot. Keyed by
        # session because forks can share one context.
        self._notifiers: dict[str, Callable[[list[TodoItem]], None]] = {}

    def executor_factory(
        self,
        storage_root: str | Path,
        *,
        max_todos: Callable[[], int],
        scheduled_loops: Callable[[str], UnifiedScheduledLoops] | None = None,
        session_spawner: SessionSpawner | None = None,
        session_origin: SessionOriginResolver | None = None,
        config_getter: Callable[[], VibeConfigSchema] | None = None,
    ) -> ProvidedToolExecutorFactory:
        root = Path(storage_root).expanduser().resolve()

        def build(session_id: str) -> ProvidedToolExecutor:
            todos = self._todos.setdefault(session_id, [])
            directory = scratchpad_dir(root, session_id)

            async def execute(
                action: RustProvidedToolCallAction,
            ) -> RustToolSucceededEvent | RustToolFailedEvent:
                try:
                    if action.call.tool_name == CRON_TOOL_NAME:
                        if scheduled_loops is None:
                            raise ValueError(
                                "Scheduled prompts are not available for this session"
                            )
                        result = await run_cron(
                            CronArgs.model_validate(action.call.arguments),
                            scheduled_loops=scheduled_loops(session_id),
                        )
                    elif action.call.tool_name == START_SESSION_TOOL_NAME:
                        if session_spawner is None or session_origin is None:
                            raise ValueError(
                                "Starting sessions is not available for this session"
                            )
                        result = await run_start_session(
                            StartSessionArgs.model_validate(action.call.arguments),
                            parent_session_id=session_id,
                            invocation_id=action.action_id,
                            origin_of=session_origin,
                            spawner=session_spawner,
                        )
                    elif action.call.tool_name == CONSULT_TOOL_NAME:
                        if config_getter is None:
                            raise ValueError(
                                "The consult tool is not available for this session"
                            )
                        result = await _run_consult(
                            action.call.arguments,
                            config=config_getter(),
                            session_id=session_id,
                        )
                    else:
                        result = await _run(
                            action.call,
                            todos=todos,
                            goals=self._goals,
                            session_id=session_id,
                            directory=directory,
                            max_todos=max_todos(),
                        )
                        if (
                            action.call.tool_name == TODO_TOOL_NAME
                            and action.call.arguments.get("action") != "read"
                        ):
                            notify = self._notifiers.get(session_id)
                            if notify is not None:
                                notify(list(todos))
                # A rejected call reaches the model as a correctable tool failure
                # rather than killing the turn.
                except (
                    ValidationError,
                    ValueError,
                    OSError,
                    LoopError,
                    ScheduledLoopStoreError,
                    SessionSpawnError,
                ) as error:
                    return _failed(action, error)
                return _succeeded(action, result)

            return execute

        return build

    def todos(self, session_id: str) -> list[TodoItem]:
        return list(self._todos.get(session_id, []))

    def set_notifier(
        self, session_id: str, notifier: Callable[[list[TodoItem]], None] | None
    ) -> None:
        if notifier is None:
            self._notifiers.pop(session_id, None)
        else:
            self._notifiers[session_id] = notifier

    def replace_todos(self, session_id: str, todos: list[TodoItem]) -> list[TodoItem]:
        target = self._todos.setdefault(session_id, [])
        target[:] = todos
        return list(target)

    def forget_todos(self, session_id: str) -> None:
        # In place, because the session's executor closure holds this same list.
        self._todos.get(session_id, []).clear()

    def goal(self, session_id: str) -> GoalRecord | None:
        return self._goals.get(session_id)

    def set_goal(
        self, session_id: str, objective: str, token_budget: int | None
    ) -> GoalRecord:
        return create_goal(
            self._goals,
            session_id=session_id,
            objective=objective,
            token_budget=token_budget,
        )

    def clear_goal(self, session_id: str) -> bool:
        return self._goals.pop(session_id, None) is not None

    def pause_goal(self, session_id: str) -> GoalRecord | None:
        goal = self._goals.get(session_id)
        if goal is None or goal.status is not GoalStatus.ACTIVE:
            return goal
        paused = goal.model_copy(update={"status": GoalStatus.PAUSED})
        self._goals[session_id] = paused
        return paused

    def resume_goal(self, session_id: str) -> GoalRecord | None:
        goal = self._goals.get(session_id)
        if goal is None or goal.status is not GoalStatus.PAUSED:
            return goal
        resumed = goal.model_copy(update={"status": GoalStatus.ACTIVE})
        self._goals[session_id] = resumed
        return resumed

    def add_goal_tokens(self, session_id: str, tokens: int) -> GoalRecord | None:
        add_goal_tokens(self._goals, session_id=session_id, tokens=tokens)
        return self._goals.get(session_id)

    def adopt(self, other: VibeProvidedTools) -> None:
        # By reference: a live session's executor closes over the lists the previous
        # holder handed out, so a copy would leave them unreachable.
        self._todos = other._todos
        self._goals = other._goals


async def _run(
    call: RustProvidedToolCall,
    *,
    todos: list[TodoItem],
    goals: dict[str, GoalRecord],
    session_id: str,
    directory: Path,
    max_todos: int,
) -> BaseModel:
    if call.tool_name == TODO_TOOL_NAME:
        return _run_todo(call.arguments, todos, max_todos=max_todos)
    if call.tool_name == GOAL_TOOL_NAME:
        return _run_goal(call.arguments, goals, session_id=session_id)
    if call.tool_name == SCRATCHPAD_TOOL_NAME:
        args = ScratchpadArgs.model_validate(call.arguments)
        return await asyncio.to_thread(run_scratchpad, args, directory=directory)
    raise ValueError(f"Unsupported {VIBE_TOOL_GROUP} tool: {call.tool_name}")


def _run_goal(
    arguments: object, goals: dict[str, GoalRecord], *, session_id: str
) -> GoalResult:
    args = GoalArgs.model_validate(arguments)
    return apply_goal_action(args, goals, session_id=session_id)


async def _run_consult(
    arguments: object, *, config: VibeConfigSchema, session_id: str
) -> ConsultResult:
    from vibe.app_server._btw import complete_with_feature
    from vibe.core.config import UtilityFeature
    from vibe.core.llm.utility_completion import select_utility_model
    from vibe.core.prompts import UtilityPrompt

    args = ConsultArgs.model_validate(arguments)
    model, _provider = select_utility_model(config, feature=UtilityFeature.CONSULT)
    content = args.question.strip()
    if args.context and args.context.strip():
        content = f"CONTEXT:\n{args.context.strip()}\n\nQUESTION:\n{content}"
    images = _consult_images(args.image_paths)
    if images and not model.supports_images:
        raise ValueError(
            "The consult model does not accept images; configure "
            "[utility_models] consult with a vision-capable model"
        )
    answer = await complete_with_feature(
        config=config,
        feature=UtilityFeature.CONSULT,
        system_prompt=UtilityPrompt.CONSULT.read(),
        content=content,
        max_tokens=800,
        session_id=session_id,
        images=images,
    )
    if not answer:
        raise ValueError("The consult model returned no answer")
    return ConsultResult(answer=answer, model=model.alias)


MAX_CONSULT_IMAGES = 4


def _consult_images(paths: list[str] | None) -> list[ImageAttachment]:
    from pathlib import Path

    from vibe.core.session.image_snapshot import ImageSnapshotError, snapshot_image

    images = []
    for index, raw in enumerate(paths or []):
        if index >= MAX_CONSULT_IMAGES:
            raise ValueError(f"consult accepts at most {MAX_CONSULT_IMAGES} images")
        path = Path(raw).expanduser()
        if not path.is_absolute():
            path = Path.cwd() / path
        try:
            images.append(
                snapshot_image(path, alias=f"consult-{index + 1}", session_dir=None)
            )
        except ImageSnapshotError as exc:
            raise ValueError(str(exc)) from exc
    return images


def _run_todo(
    arguments: object, todos: list[TodoItem], *, max_todos: int
) -> TodoResult:
    args = TodoArgs.model_validate(arguments)
    return apply_todo_action(args, todos, max_todos=max_todos)


def resolved_max_todos(overrides: Mapping[str, Any] | None) -> int:
    """``[tools.todo].max_todos``, validated by the legacy tool's own config model."""
    try:
        return TodoConfig.model_validate(dict(overrides or {})).max_todos
    except ValidationError:
        return TodoConfig().max_todos


def _succeeded(
    action: RustProvidedToolCallAction, result: BaseModel
) -> RustToolSucceededEvent:
    payload = result.model_dump(mode="json")
    return RustToolSucceededEvent(
        action_id=action.action_id,
        call_id=action.call_id,
        result=RustToolSuccessResult(
            content=[
                RustTextContentBlock(text=json.dumps(payload, ensure_ascii=False))
            ],
            structured_content=payload,
        ),
    )


def _failed(
    action: RustProvidedToolCallAction, error: Exception
) -> RustToolFailedEvent:
    return RustToolFailedEvent(
        action_id=action.action_id,
        call_id=action.call_id,
        result=RustToolFailureResult(
            error=RustProtocolError(
                code="tool_failed", message=str(error), retryable=False, details=None
            )
        ),
    )


__all__ = [
    "CONSULT_TOOL_NAME",
    "GOAL_TOOL_NAME",
    "TODO_TOOL_NAME",
    "VIBE_PROVIDED_TOOL_MODES",
    "VIBE_PROVIDED_TOOL_NAMES",
    "VIBE_TOOL_GROUP",
    "VibeProvidedTools",
    "resolved_max_todos",
    "vibe_tool_groups",
]
