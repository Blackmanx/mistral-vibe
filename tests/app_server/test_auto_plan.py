from __future__ import annotations

from collections.abc import Awaitable, Callable
import json

import pytest

from tests.conftest import build_test_vibe_config
from vibe.app_server import _auto_plan
from vibe.core.config import UtilityFeature
from vibe.core.tools.builtins.todo import TodoStatus

_Complete = Callable[..., Awaitable[str]]


def _install(
    monkeypatch: pytest.MonkeyPatch, replies: dict[UtilityFeature, str]
) -> list:
    calls: list[UtilityFeature] = []

    async def complete(*, feature: UtilityFeature, **_: object) -> str:
        calls.append(feature)
        return replies[feature]

    monkeypatch.setattr(_auto_plan, "complete_with_feature", complete)
    return calls


@pytest.mark.asyncio
async def test_a_complex_task_plans_then_builds_todos_from_the_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[UtilityFeature] = []
    replies = iter([
        json.dumps({"task": True, "complex": True}),
        "## Context\nDo it.\n## Steps\n1. Change parser.",
        '["Inspect the parser", "Add the option", "Run tests"]',
    ])

    async def complete(*, feature: UtilityFeature, **_: object) -> str:
        calls.append(feature)
        return next(replies)

    monkeypatch.setattr(_auto_plan, "complete_with_feature", complete)

    plan = await _auto_plan.build_auto_plan(
        config=build_test_vibe_config(), user_text="Add a --json flag to the parser"
    )

    assert plan is not None
    assert plan.complex is True
    assert plan.plan is not None and "Change parser" in plan.plan
    assert [todo.content for todo in plan.todos] == [
        "Inspect the parser",
        "Add the option",
        "Run tests",
    ]
    assert plan.todos[0].status is TodoStatus.IN_PROGRESS
    assert plan.todos[1].status is TodoStatus.PENDING
    assert calls == [UtilityFeature.TODO, UtilityFeature.PLAN, UtilityFeature.TODO]


@pytest.mark.asyncio
async def test_a_question_creates_no_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(
        monkeypatch,
        {UtilityFeature.TODO: json.dumps({"task": False, "complex": False})},
    )

    plan = await _auto_plan.build_auto_plan(
        config=build_test_vibe_config(), user_text="What does the parser do?"
    )

    assert plan is None


@pytest.mark.asyncio
async def test_a_simple_task_skips_the_plan_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _install(
        monkeypatch, {UtilityFeature.TODO: json.dumps({"task": True, "complex": False})}
    )
    replies = iter([
        json.dumps({"task": True, "complex": False}),
        '["Fix the typo", "Run the test"]',
    ])

    async def complete(*, feature: UtilityFeature, **_: object) -> str:
        calls.append(feature)
        return next(replies)

    monkeypatch.setattr(_auto_plan, "complete_with_feature", complete)

    plan = await _auto_plan.build_auto_plan(
        config=build_test_vibe_config(), user_text="Fix the typo in main.py"
    )

    assert plan is not None
    assert plan.plan is None
    assert [todo.id for todo in plan.todos] == ["1", "2"]
    assert UtilityFeature.PLAN not in calls


def test_todo_json_accepts_fences_and_rejects_one_item() -> None:
    assert _auto_plan._json_value('```json\n["a", "b"]\n```', expected=list) == [
        "a",
        "b",
    ]
    todos = _auto_plan._normalize_todos(["only one"])
    assert todos == []
