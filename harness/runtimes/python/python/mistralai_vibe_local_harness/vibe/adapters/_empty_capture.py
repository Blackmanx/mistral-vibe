"""What a provider sent when a completion finished without an answer.

An empty completion is well formed on the wire: a normal finish reason, no
error, and neither text nor a tool call. Nothing in the response says why -- a
reasoning model that ends its turn inside the thinking block looks exactly like
this -- and the event is rare enough that guessing is worse than recording it.
So the raw stream goes next to the logs, one file per event. The request is
recorded by shape only: roles, sizes and tool names, never its content.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
import json
import logging
import os
from pathlib import Path
import uuid

logger = logging.getLogger(__name__)

# One event's file, bounded: a pathological stream must not fill the disk.
_MAX_CHUNKS = 2000
_MAX_BYTES = 2 * 1024 * 1024


def _logs_root() -> Path:
    home = os.environ.get("VIBE_HOME")
    return (Path(home) if home else Path.home() / ".vibe") / "logs"


def _request_shape(
    messages: Iterable[object], tools: Iterable[object]
) -> dict[str, object]:
    """The request as counts and names, never as text: the dump stays shareable."""
    shape: list[dict[str, object]] = []
    for message in messages:
        content = getattr(message, "content", None)
        shape.append({
            "role": getattr(message, "role", None),
            "characters": len(str(content)) if content is not None else 0,
        })
    return {"messages": shape, "tools": [str(getattr(t, "name", "")) for t in tools]}


def capture_empty_completion(
    *,
    provider: str,
    model: str,
    reasoning: str | None,
    messages: Sequence[object] = (),
    tools: Sequence[object] = (),
    chunks: Sequence[object] = (),
    total_chunks: int = 0,
) -> Path | None:
    """Record what a provider sent for a completion that carried no answer.

    Best effort: a failure to record is logged and never fails the turn. The
    caller raises the retryable failure either way.
    """
    try:
        directory = _logs_root() / "empty-completion"
        directory.mkdir(parents=True, exist_ok=True)
        now = datetime.now(UTC)
        path = directory / f"empty-{now:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}.jsonl"
        header = {
            "type": "empty_completion",
            "when": now.isoformat(),
            "provider": provider,
            "model": model,
            "reasoning_effort": reasoning,
            "chunks": total_chunks,
            "request": _request_shape(messages, tools),
        }
        lines = [json.dumps(header)]
        written = len(lines[0])
        for chunk in list(chunks)[:_MAX_CHUNKS]:
            line = json.dumps({"type": "chunk", "chunk": chunk}, default=str)
            if written + len(line) > _MAX_BYTES:
                lines.append(json.dumps({"type": "truncated"}))
                break
            lines.append(line)
            written += len(line)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        path.chmod(0o600)
    except Exception:
        logger.warning("Could not record an empty completion", exc_info=True)
        return None
    logger.warning(
        "Model completion from %s (%s) carried no answer; raw stream saved to %s",
        provider,
        model,
        path,
    )
    return path
