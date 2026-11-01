"""The advisor: a second model that reviews each completed turn.

Ported from oh-my-pi's advisor subsystem (``docs/advisor-watchdog.md``) in a
lean, Vibe-native form. oh-my-pi runs the advisor as a full agent with its own
tools and interrupting severities; here the configured ``consult`` utility
model — tool-less, cheap, with fallbacks — reads the recent transcript after
each turn and leaves at most one note. A note is delivered as a hidden
``<advisor_note>`` block on the next user turn, the non-interrupting aside of
the original: the primary agent weighs it instead of being steered mid-run.
"""

from __future__ import annotations

import asyncio

from vibe.core.config import VibeConfigSchema
from vibe.core.prompts import UtilityPrompt
from vibe.observability.logging import logger

__all__ = ["ADVISOR_MAX_NOTE_CHARS", "advisor_note", "is_all_clear"]

ADVISOR_MAX_NOTE_CHARS = 600
REVIEW_TIMEOUT_SECONDS = 15.0
_ALL_CLEAR = {"ok", "ok.", "none", "no note", "all clear"}


def is_all_clear(response: str) -> bool:
    """Whether the advisor model approved the turn with no note."""
    return response.strip().strip("`\"' ").lower() in _ALL_CLEAR


async def advisor_note(
    *, config: VibeConfigSchema, transcript: str, session_id: str | None = None
) -> str | None:
    """One advisor note for the transcript, or None when the turn was sound.

    Best-effort: a slow or failing utility call means no note this turn, never
    a broken primary session.
    """
    from vibe.app_server._btw import complete_with_feature
    from vibe.core.config import UtilityFeature

    transcript = transcript.strip()
    if not transcript:
        return None
    try:
        async with asyncio.timeout(REVIEW_TIMEOUT_SECONDS):
            response = await complete_with_feature(
                config=config,
                feature=UtilityFeature.CONSULT,
                system_prompt=UtilityPrompt.ADVISOR.read(),
                content=transcript,
                max_tokens=200,
                session_id=session_id,
            )
    except Exception:
        logger.debug("Advisor review failed; continuing without it", exc_info=True)
        return None
    if is_all_clear(response):
        return None
    note = response.strip().strip("`\"' ")
    if len(note) > ADVISOR_MAX_NOTE_CHARS:
        note = note[:ADVISOR_MAX_NOTE_CHARS].rsplit(maxsplit=1)[0] + "…"
    return note or None


def render_advisor_block(note: str) -> str:
    """The hidden block that delivers one advisor note to the next turn."""
    return (
        "<advisor_note>\n"
        "A second model reviewed the previous turn and left this note. Weigh "
        "it: if it is right, act on it before continuing; if it is wrong, say "
        "why briefly and continue.\n"
        f"{note}\n"
        "</advisor_note>"
    )
