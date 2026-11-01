"""Project memory: durable, agent-curated facts that survive a session.

Ported from oh-my-pi's local memory backend (``docs/memory.md``), lean form:
one markdown file per project holds the facts the agent retains with
``memory retain``, and a session's first prompt injects the current facts as
a hidden ``<project_memory>`` block. The store is plain markdown the user can
read, edit, and put under version control, and ``memory recall`` searches it
without a model call.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
import threading
import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field

from vibe.core.tools.base import BaseTool, BaseToolConfig, BaseToolState, ToolPermission

__all__ = [
    "MEMORY_FILE_NAME",
    "MemoryArgs",
    "MemoryEntry",
    "MemoryResult",
    "forget_entry",
    "memory_dir",
    "memory_file",
    "read_memory_entries",
    "render_memory_block",
    "retain_fact",
]

MEMORY_FILE_NAME = "MEMORY.md"
_HEADER = (
    "# Project memory\n"
    "\n"
    "Durable facts about this project, kept by the agent across sessions.\n"
    "Edit freely; the `memory` tool rewrites this file.\n"
)
_ENTRY_RE = re.compile(r"^- \[([0-9a-f]{6})\] (.+)$")
_MAX_FACT_CHARS = 2000
_MAX_ENTRIES = 200

# The file is one per project but sessions can run in threads.
_file_lock = threading.Lock()


class MemoryEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    fact: str
    context: str | None = None
    created_at: int


MemoryAction = Literal["retain", "recall", "read", "forget"]


class MemoryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: MemoryAction = Field(description="Memory operation to perform")
    fact: str | None = Field(
        default=None, description="Required for retain: the durable fact, one sentence"
    )
    context: str | None = Field(
        default=None,
        description="Optional for retain: where the fact applies (file, command, env)",
    )
    query: str | None = Field(
        default=None,
        description="Required for recall: keyword search over the stored facts",
    )
    entry_id: str | None = Field(
        default=None, description="Required for forget: the id of the entry to remove"
    )


class MemoryResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: MemoryAction
    entries: list[MemoryEntry] = Field(default_factory=list)
    matched: list[MemoryEntry] = Field(default_factory=list)
    message: str | None = None

    @computed_field
    @property
    def summary(self) -> str:
        if self.action == "recall":
            return f"{len(self.matched)} matching fact(s)."
        return self.message or ""


class MemoryConfig(BaseToolConfig):
    permission: ToolPermission = ToolPermission.ALWAYS


class MemoryState(BaseToolState):
    pass


class Memory(BaseTool[MemoryArgs, MemoryResult, MemoryConfig, MemoryState]):
    pass


def memory_dir(project_root: Path) -> Path:
    return project_root / ".vibe" / "memory"


def memory_file(project_root: Path) -> Path:
    return memory_dir(project_root) / MEMORY_FILE_NAME


def _entry_id(fact: str) -> str:
    digest = hashlib.sha1(fact.strip().lower().encode()).hexdigest()
    return digest[:6]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _write_entries(path: Path, entries: list[MemoryEntry]) -> None:
    lines = [_HEADER]
    for entry in entries:
        suffix = f" — {entry.context.strip()}" if entry.context else ""
        lines.append(f"- [{entry.id}] {entry.fact.strip()}{suffix}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_memory_entries(path: Path) -> list[MemoryEntry]:
    """Parse the memory file into entries; a missing file is an empty list."""
    if not path.is_file():
        return []
    entries: list[MemoryEntry] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _ENTRY_RE.match(line.strip())
        if match is None:
            continue
        fact_text = match.group(2)
        context: str | None = None
        if " — " in fact_text:
            fact_text, context = fact_text.split(" — ", 1)
        entries.append(
            MemoryEntry(
                id=match.group(1),
                fact=fact_text.strip(),
                context=context.strip() if context else None,
                created_at=0,
            )
        )
    return entries


def retain_fact(
    path: Path, fact: str, context: str | None = None
) -> tuple[MemoryResult, list[MemoryEntry]]:
    """Append a durable fact, deduplicating against the stored ones."""
    fact = fact.strip()
    if not fact:
        raise ValueError("The fact is empty.")
    if len(fact) > _MAX_FACT_CHARS:
        raise ValueError(
            f"The fact is {len(fact)} characters; keep it under "
            f"{_MAX_FACT_CHARS} as one durable sentence."
        )
    with _file_lock:
        entries = read_memory_entries(path)
        new_id = _entry_id(fact)
        new_norm = _normalize(fact)
        for entry in entries:
            if entry.id == new_id:
                return (
                    MemoryResult(
                        action="retain",
                        entries=entries,
                        message=f"Already remembered as [{entry.id}].",
                    ),
                    entries,
                )
            existing = _normalize(entry.fact)
            if new_norm in existing or existing in new_norm:
                return (
                    MemoryResult(
                        action="retain",
                        entries=entries,
                        message=(
                            f'Close to [{entry.id}] "{entry.fact}"; kept the '
                            "existing entry. Use forget first if it is wrong."
                        ),
                    ),
                    entries,
                )
        created = MemoryEntry(
            id=new_id,
            fact=fact,
            context=context.strip() if context else None,
            created_at=int(time.time()),
        )
        entries.append(created)
        if len(entries) > _MAX_ENTRIES:
            entries = entries[-_MAX_ENTRIES:]
        _write_entries(path, entries)
        return (
            MemoryResult(
                action="retain", entries=entries, message=f"Remembered [{created.id}]."
            ),
            entries,
        )


def forget_entry(path: Path, entry_id: str) -> tuple[MemoryResult, list[MemoryEntry]]:
    """Remove one entry by id."""
    with _file_lock:
        entries = read_memory_entries(path)
        kept = [entry for entry in entries if entry.id != entry_id.strip().lower()]
        if len(kept) == len(entries):
            return (
                MemoryResult(
                    action="forget",
                    entries=entries,
                    message=f"No entry with id {entry_id}.",
                ),
                entries,
            )
        if kept:
            _write_entries(path, kept)
        else:
            # Keep the file with just the header, so `read` stays consistent.
            _write_entries(path, [])
        return (
            MemoryResult(
                action="forget",
                entries=kept,
                message=f"Forgot [{entry_id.strip().lower()}].",
            ),
            kept,
        )


def search_memory(path: Path, query: str) -> list[MemoryEntry]:
    """Keyword search over the stored facts, newest last."""
    terms = [term for term in _normalize(query).split() if term]
    if not terms:
        return []
    entries = read_memory_entries(path)
    matched = []
    for entry in entries:
        haystack = _normalize(f"{entry.fact} {entry.context or ''}")
        if any(term in haystack for term in terms):
            matched.append(entry)
    return matched


_BLOCK_PREAMBLE_LINES = 2


def render_memory_block(path: Path, *, limit_chars: int = 6000) -> str | None:
    """The hidden ``<project_memory>`` block for a session's first prompt.

    None when the project has no memory yet, so a fresh project pays nothing.
    """
    entries = read_memory_entries(path)
    if not entries:
        return None
    lines = [
        "<project_memory>",
        "Durable facts remembered for this project across sessions. Treat "
        "them as heuristic context: prefer the current repository state and "
        "the user's instructions when they conflict, and treat a memory that "
        "contradicts the code as stale.",
    ]
    used = 0
    for entry in entries:
        suffix = f" — {entry.context}" if entry.context else ""
        line = f"- [{entry.id}] {entry.fact}{suffix}"
        if used + len(line) > limit_chars and len(lines) > _BLOCK_PREAMBLE_LINES:
            remaining = len(entries) - (len(lines) - _BLOCK_PREAMBLE_LINES)
            lines.append(
                f"- …and {remaining} more; call `memory recall` to search them."
            )
            break
        lines.append(line)
        used += len(line)
    lines.append("</project_memory>")
    return "\n".join(lines)
