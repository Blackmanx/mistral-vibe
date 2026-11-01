"""Session-start memory consolidation, ported from oh-my-pi's local memory.

oh-my-pi runs a background pipeline at startup that extracts durable signal
from each past session and consolidates it into the project's memory
(``docs/memory.md``). This port keeps the lean form: when a session starts in a
project with ``project_memory`` on, the most recent stored session of that
project that has not been consolidated yet is read back, the cheap utility
model extracts at most a handful of durable facts, and each is retained into
``.vibe/memory/MEMORY.md`` with the same dedup the ``memory`` tool uses. One
session is consolidated per start, so successive sessions catch up; a session
id is recorded once its facts are written and is never processed twice.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from vibe.observability.logging import logger

if TYPE_CHECKING:
    from vibe.core.config import VibeConfigSchema

__all__ = [
    "CONSOLIDATED_FILE_NAME",
    "ConsolidationHost",
    "consolidate_previous_session",
    "render_history_text",
]

CONSOLIDATED_FILE_NAME = "consolidated.txt"
EXTRACT_TIMEOUT_SECONDS = 30.0
EXTRACT_MAX_TOKENS = 400
MAX_FACTS = 5
HISTORY_LIMIT = 120
LIST_LIMIT = 50


class ConsolidationHost(Protocol):
    """The host surface consolidation reads: list stored sessions, read one."""

    async def list(
        self, *, limit: int, cursor: str | None = ..., cwd: str | None = ...
    ) -> Any: ...

    async def read(self, params: Any) -> Any: ...


def _consolidated_path(project_root: Path) -> Path:
    return project_root / ".vibe" / "memory" / CONSOLIDATED_FILE_NAME


def _already_consolidated(project_root: Path) -> set[str]:
    path = _consolidated_path(project_root)
    if not path.is_file():
        return set()
    try:
        return {
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        }
    except OSError:
        logger.debug("Consolidation ledger unreadable; treating as empty")
        return set()


def _mark_consolidated(project_root: Path, session_id: str) -> None:
    path = _consolidated_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{session_id}\n")


def render_history_text(history: list[Any]) -> str:
    """``ROLE: text`` lines for the message entries, as the advisor renders."""
    lines: list[str] = []
    for entry in history:
        role = getattr(entry, "role", None)
        if role not in {"user", "assistant"}:
            continue
        text = str(getattr(entry, "text", "") or "").strip()
        if text:
            lines.append(f"{str(role).upper()}: {text}")
    return "\n".join(lines)


def _parse_facts(response: str) -> list[str]:
    """The JSON array of facts, tolerating a fenced code block."""
    text = response.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        logger.debug("Memory extraction returned non-JSON; ignoring it")
        return []
    if not isinstance(value, list):
        return []
    facts = []
    for item in value:
        if isinstance(item, str) and item.strip():
            facts.append(item.strip())
        if len(facts) >= MAX_FACTS:
            break
    return facts


async def _extract_facts(
    *, config: VibeConfigSchema, transcript: str, session_id: str | None
) -> list[str]:
    from vibe.app_server._btw import complete_with_feature
    from vibe.core.config import UtilityFeature
    from vibe.core.prompts import UtilityPrompt

    async with asyncio.timeout(EXTRACT_TIMEOUT_SECONDS):
        response = await complete_with_feature(
            config=config,
            feature=UtilityFeature.CONSULT,
            system_prompt=UtilityPrompt.MEMORY_EXTRACT.read(),
            content=transcript,
            max_tokens=EXTRACT_MAX_TOKENS,
            session_id=session_id,
        )
    return _parse_facts(response)


def _newest_unconsolidated(
    listing: Any, done: set[str], current_session_id: str
) -> str | None:
    """The newest stored session of the project not yet consolidated."""
    for item in getattr(listing, "items", ()) or ():
        session_id = getattr(item.session, "id", None)
        if session_id and session_id != current_session_id and session_id not in done:
            return str(session_id)
    return None


async def _pick_consolidation_target(
    host: ConsolidationHost, project_root: Path, current_session_id: str
) -> str | None:
    """The newest stored session of the project not yet consolidated."""
    done = _already_consolidated(project_root)
    try:
        listing = await host.list(limit=LIST_LIMIT, cwd=str(project_root))
    except Exception:
        logger.debug("Memory consolidation skipped; session listing failed")
        return None
    return _newest_unconsolidated(listing, done, current_session_id)


async def consolidate_previous_session(
    *,
    host: ConsolidationHost,
    config: VibeConfigSchema,
    project_root: Path,
    current_session_id: str,
) -> int:
    """Retain durable facts from the newest unconsolidated stored session.

    Returns the number of facts retained. Best-effort: every failure means no
    consolidation this start, never a broken session start.
    """
    if not config.project_memory:
        return 0
    from mistralai_vibe_local_harness.session_protocol import (
        SessionReadParams as HarnessSessionReadParams,
    )
    from vibe.core.tools.builtins.memory import memory_file, retain_fact

    session_id = await _pick_consolidation_target(
        host, project_root, current_session_id
    )
    if session_id is None:
        return 0
    try:
        result = await host.read(
            HarnessSessionReadParams(session_id=session_id, history_limit=HISTORY_LIMIT)
        )
    except Exception:
        logger.debug(
            "Memory consolidation skipped; stored session %s unreadable", session_id
        )
        return 0
    transcript = render_history_text(list(result.snapshot.state.history or []))
    if not transcript:
        # Nothing durable to extract. Not marked either: an empty session
        # costs one read the next start, and writing a ledger for it would
        # dirty a project that never asked for memory.
        return 0
    try:
        facts = await _extract_facts(
            config=config, transcript=transcript, session_id=session_id
        )
    except Exception:
        logger.debug("Memory extraction failed for %s", session_id, exc_info=True)
        # Not marked: a later session may retry with a working provider.
        return 0
    retained = 0
    path = memory_file(project_root)
    for fact in facts:
        result_message, _entries = retain_fact(path, fact)
        if (result_message.message or "").startswith("Remembered"):
            retained += 1
    _mark_consolidated(project_root, session_id)
    return retained
