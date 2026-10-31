from __future__ import annotations

import pytest

from vibe.core.tools.builtins.goal import (
    GoalRecord,
    GoalStatus,
    GoalValidationError,
    create_goal,
    replace_goal,
)


def test_replace_goal_swaps_the_objective_and_resets_counters() -> None:
    goals: dict[str, GoalRecord] = {}
    created = create_goal(
        goals, session_id="s1", objective="First", token_budget=100, now=1
    )
    spent = created.model_copy(update={"tokens_used": 60})
    goals["s1"] = spent

    replaced = replace_goal(
        goals, session_id="s1", objective="Second", now=2, goal_id="goal-2"
    )

    assert replaced.id == "goal-2"
    assert replaced.objective == "Second"
    assert replaced.token_budget is None
    assert replaced.tokens_used == 0
    assert replaced.status == GoalStatus.ACTIVE
    assert goals["s1"] is replaced


def test_replace_goal_overrides_the_budget_when_given() -> None:
    goals: dict[str, GoalRecord] = {}
    create_goal(goals, session_id="s1", objective="First", token_budget=None, now=1)

    replaced = replace_goal(
        goals,
        session_id="s1",
        objective="Second",
        token_budget=500,
        now=2,
        goal_id="goal-2",
    )

    assert replaced.token_budget == 500
    assert replaced.remaining_tokens == 500


def test_replace_goal_requires_an_objective() -> None:
    goals: dict[str, GoalRecord] = {}
    create_goal(goals, session_id="s1", objective="First", token_budget=None, now=1)

    with pytest.raises(GoalValidationError):
        replace_goal(goals, session_id="s1", objective="  ", now=2)
