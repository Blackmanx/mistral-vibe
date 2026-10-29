from __future__ import annotations

from vibe.app_server.protocol import SessionGoalReadResponse, SessionGoalSetResponse
from vibe.core.tools.builtins.goal import GoalRecord


def _goal() -> GoalRecord:
    return GoalRecord(
        id="goal-1",
        objective="Ship it",
        token_budget=100,
        tokens_used=40,
        created_at=1,
        updated_at=2,
    )


def test_goal_wire_fields_are_camel_case_for_the_client() -> None:
    payload = SessionGoalSetResponse(goal=_goal()).model_dump(
        mode="json", by_alias=True
    )

    assert payload["goal"]["tokenBudget"] == 100
    assert payload["goal"]["tokensUsed"] == 40
    assert payload["goal"]["remainingTokens"] == 60


def test_goal_read_serializes_an_empty_goal_as_null() -> None:
    payload = SessionGoalReadResponse().model_dump(mode="json", by_alias=True)

    assert payload == {"goal": None, "continuationRounds": 0}


def test_todo_notification_carries_the_wire_fields() -> None:
    from vibe.app_server.models import TodoEffectItem
    from vibe.app_server.protocol import SessionTodoUpdatedParams

    payload = SessionTodoUpdatedParams(
        event_id=0,
        session_id="s",
        emitted_at=1,
        todos=[TodoEffectItem(id="1", content="Blocked step", status="blocked")],
        source="auto_plan",
    ).model_dump(mode="json", by_alias=True)

    assert payload["todos"][0]["status"] == "blocked"
    assert payload["source"] == "auto_plan"
