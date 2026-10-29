"""Automatic plan and TODO generation for a new user task.

The triage and TODO steps run on the configured cheap utility model; a complex
task first gets a plan from the configured plan model. Every step is best-effort:
a slow or failing secondary call leaves the turn untouched.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json

from vibe.app_server._btw import complete_with_feature
from vibe.core.config import UtilityFeature, VibeConfigSchema
from vibe.core.prompts import UtilityPrompt
from vibe.core.tools.builtins.todo import TodoItem, TodoPriority, TodoStatus
from vibe.observability.logging import logger

TRIAGE_TIMEOUT_SECONDS = 8.0
PLAN_TIMEOUT_SECONDS = 45.0
TODO_TIMEOUT_SECONDS = 15.0
MAX_TODOS = 8
MIN_TODOS = 2
MIN_TODO_CHARS = 3
MIN_REQUEST_CHARS = 12
MAX_CONTEXT_CHARS = 12_000


@dataclass(frozen=True, slots=True)
class AutoPlan:
    plan: str | None
    todos: list[TodoItem]
    complex: bool


async def build_auto_plan(
    *,
    config: VibeConfigSchema,
    user_text: str,
    context: str = "",
    session_id: str | None = None,
    auto_plan: bool = True,
) -> AutoPlan | None:
    """Return a plan and TODO list, or None when the request needs neither."""
    text = user_text.strip()
    if len(text) < MIN_REQUEST_CHARS:
        return None
    prompt_input = _prompt_input(context, text)

    triage = await _triage(config, prompt_input, session_id)
    if triage is None or not triage.get("task"):
        return None

    plan: str | None = None
    if auto_plan and triage.get("complex"):
        plan = await _plan(config, prompt_input, session_id)

    todos = await _todos(config, prompt_input, plan, session_id)
    if not todos:
        return None
    return AutoPlan(plan=plan, todos=todos, complex=bool(triage.get("complex")))


async def _triage(
    config: VibeConfigSchema, prompt_input: str, session_id: str | None
) -> dict[str, object] | None:
    try:
        async with asyncio.timeout(TRIAGE_TIMEOUT_SECONDS):
            raw = await complete_with_feature(
                config=config,
                feature=UtilityFeature.TODO,
                system_prompt=UtilityPrompt.TRIAGE.read(),
                content=prompt_input,
                max_tokens=64,
                session_id=session_id,
            )
    except Exception as exc:
        logger.debug("Auto-plan triage failed", exc_info=exc)
        return None
    payload = _json_value(raw, expected=dict)
    if not isinstance(payload, dict):
        return None
    return {
        "task": payload.get("task") is True,
        "complex": payload.get("complex") is True,
    }


async def _plan(
    config: VibeConfigSchema, prompt_input: str, session_id: str | None
) -> str | None:
    try:
        async with asyncio.timeout(PLAN_TIMEOUT_SECONDS):
            plan = await complete_with_feature(
                config=config,
                feature=UtilityFeature.PLAN,
                system_prompt=UtilityPrompt.PLAN.read(),
                content=prompt_input,
                max_tokens=1_200,
                session_id=session_id,
            )
    except Exception as exc:
        logger.debug("Auto-plan planning failed", exc_info=exc)
        return None
    return plan.strip() or None


async def _todos(
    config: VibeConfigSchema,
    prompt_input: str,
    plan: str | None,
    session_id: str | None,
) -> list[TodoItem]:
    content = prompt_input
    if plan:
        content = f"{prompt_input}\n\nPLAN:\n{plan}"
    try:
        async with asyncio.timeout(TODO_TIMEOUT_SECONDS):
            raw = await complete_with_feature(
                config=config,
                feature=UtilityFeature.TODO,
                system_prompt=UtilityPrompt.TODO.read(),
                content=content,
                max_tokens=400,
                session_id=session_id,
            )
    except Exception as exc:
        logger.debug("Auto-plan TODO generation failed", exc_info=exc)
        return []
    return _normalize_todos(_json_value(raw, expected=list))


def _normalize_todos(payload: object) -> list[TodoItem]:
    if not isinstance(payload, list):
        return []
    items: list[TodoItem] = []
    seen: set[str] = set()
    for entry in payload:
        if isinstance(entry, dict):
            entry = entry.get("content") or entry.get("title")
        if not isinstance(entry, str):
            continue
        text = " ".join(entry.split())[:200].strip()
        key = text.casefold()
        if len(text) < MIN_TODO_CHARS or key in seen:
            continue
        seen.add(key)
        items.append(
            TodoItem(
                id=str(len(items) + 1),
                content=text,
                status=(TodoStatus.IN_PROGRESS if not items else TodoStatus.PENDING),
                priority=TodoPriority.MEDIUM,
            )
        )
        if len(items) >= MAX_TODOS:
            break
    return items if len(items) >= MIN_TODOS else []


def _json_value(raw: str, *, expected: type) -> object | None:
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
        if text.endswith("```"):
            text = text[:-3]
    start = min(
        (index for index in (text.find("["), text.find("{")) if index >= 0), default=-1
    )
    if start < 0:
        return None
    end = max(text.rfind("]"), text.rfind("}"))
    if end < start:
        return None
    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, expected) else None


def _prompt_input(context: str, user_text: str) -> str:
    context = context.strip()
    if len(context) > MAX_CONTEXT_CHARS:
        context = "[earlier conversation omitted]\n" + context[-MAX_CONTEXT_CHARS:]
    if not context:
        return f"REQUEST:\n{user_text}"
    return f"RECENT CONVERSATION:\n{context}\n\nREQUEST:\n{user_text}"


__all__ = ["AutoPlan", "build_auto_plan"]
