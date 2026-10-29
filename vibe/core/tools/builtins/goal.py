from __future__ import annotations

from enum import StrEnum, auto
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field
from pydantic.alias_generators import to_camel

from vibe.core.tools.base import BaseTool, BaseToolConfig, BaseToolState, ToolPermission


class GoalStatus(StrEnum):
    ACTIVE = auto()
    PAUSED = auto()
    COMPLETE = auto()
    DROPPED = auto()


GoalAction = Literal["create", "get", "complete", "pause", "resume", "drop"]


class GoalRecord(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    id: str
    objective: str
    status: GoalStatus = GoalStatus.ACTIVE
    token_budget: int | None = None
    tokens_used: int = 0
    created_at: int
    updated_at: int

    @computed_field
    @property
    def remaining_tokens(self) -> int | None:
        if self.token_budget is None:
            return None
        return max(0, self.token_budget - self.tokens_used)


class GoalArgs(BaseModel):
    action: GoalAction = Field(description="Goal operation to perform")
    objective: str | None = Field(
        default=None, description="Required for create: the concrete outcome to reach"
    )
    token_budget: int | None = Field(
        default=None, ge=1, description="Optional token budget for the goal"
    )


class GoalResult(BaseModel):
    action: GoalAction
    goal: GoalRecord | None = None

    @computed_field
    @property
    def message(self) -> str:
        if self.goal is None:
            return "No active goal."
        budget = (
            "unbounded"
            if self.goal.token_budget is None
            else f"{self.goal.tokens_used}/{self.goal.token_budget} tokens"
        )
        return f"Goal {self.goal.status}: {self.goal.objective} ({budget})"


class GoalValidationError(ValueError):
    pass


def create_goal(
    goals: dict[str, GoalRecord],
    *,
    session_id: str,
    objective: str | None,
    token_budget: int | None,
    now: int | None = None,
    goal_id: str | None = None,
) -> GoalRecord:
    text = (objective or "").strip()
    if not text:
        raise GoalValidationError("create requires a non-empty objective")
    current = goals.get(session_id)
    if current is not None and current.status in {GoalStatus.ACTIVE, GoalStatus.PAUSED}:
        raise GoalValidationError(
            "A goal is already active. Complete or drop it before creating another."
        )
    timestamp = int(time.time() * 1000) if now is None else now
    goal = GoalRecord(
        id=goal_id or f"goal-{timestamp}",
        objective=text,
        token_budget=token_budget,
        created_at=timestamp,
        updated_at=timestamp,
    )
    goals[session_id] = goal
    return goal


def apply_goal_action(  # noqa: PLR0911 - one branch per action
    args: GoalArgs, goals: dict[str, GoalRecord], *, session_id: str
) -> GoalResult:
    current = goals.get(session_id)
    match args.action:
        case "get":
            return GoalResult(action=args.action, goal=current)
        case "create":
            return GoalResult(
                action=args.action,
                goal=create_goal(
                    goals,
                    session_id=session_id,
                    objective=args.objective,
                    token_budget=args.token_budget,
                ),
            )
        case "complete":
            if current is None:
                raise GoalValidationError("No goal to complete")
            if current.status is GoalStatus.COMPLETE:
                return GoalResult(action=args.action, goal=current)
            current = current.model_copy(
                update={"status": GoalStatus.COMPLETE, "updated_at": _now()}
            )
            goals[session_id] = current
            return GoalResult(action=args.action, goal=current)
        case "pause":
            if current is None:
                raise GoalValidationError("No goal to pause")
            if current.status is not GoalStatus.ACTIVE:
                raise GoalValidationError("Only an active goal can be paused")
            current = current.model_copy(
                update={"status": GoalStatus.PAUSED, "updated_at": _now()}
            )
            goals[session_id] = current
            return GoalResult(action=args.action, goal=current)
        case "resume":
            if current is None:
                raise GoalValidationError("No goal to resume")
            if current.status is GoalStatus.COMPLETE:
                raise GoalValidationError("A completed goal cannot be resumed")
            if current.status is GoalStatus.DROPPED:
                raise GoalValidationError("A dropped goal cannot be resumed")
            current = current.model_copy(
                update={"status": GoalStatus.ACTIVE, "updated_at": _now()}
            )
            goals[session_id] = current
            return GoalResult(action=args.action, goal=current)
        case "drop":
            dropped = (
                current.model_copy(
                    update={"status": GoalStatus.DROPPED, "updated_at": _now()}
                )
                if current is not None
                else None
            )
            goals.pop(session_id, None)
            return GoalResult(action=args.action, goal=dropped)


def add_goal_tokens(
    goals: dict[str, GoalRecord], *, session_id: str, tokens: int
) -> None:
    current = goals.get(session_id)
    if current is None or tokens <= 0:
        return
    goals[session_id] = current.model_copy(
        update={"tokens_used": current.tokens_used + tokens, "updated_at": _now()}
    )


def _now() -> int:
    return int(time.time() * 1000)


class GoalConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS


class GoalState(BaseToolState):
    pass


class Goal(BaseTool[GoalArgs, GoalResult, GoalConfig, GoalState]):
    pass
