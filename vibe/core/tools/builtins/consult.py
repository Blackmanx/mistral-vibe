from __future__ import annotations

from pydantic import BaseModel, Field

from vibe.core.tools.base import BaseTool, BaseToolConfig, BaseToolState, ToolPermission


class ConsultArgs(BaseModel):
    question: str = Field(description="Focused question for the second-opinion model")
    context: str | None = Field(
        default=None,
        description="Optional code, error, or plan excerpt the answer needs",
    )
    image_paths: list[str] | None = Field(
        default=None,
        description=(
            "Optional workspace-relative image paths. The configured consult "
            "model must accept images."
        ),
    )


class ConsultResult(BaseModel):
    answer: str
    model: str


class ConsultConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS


class ConsultState(BaseToolState):
    pass


class Consult(BaseTool[ConsultArgs, ConsultResult, ConsultConfig, ConsultState]):
    pass
