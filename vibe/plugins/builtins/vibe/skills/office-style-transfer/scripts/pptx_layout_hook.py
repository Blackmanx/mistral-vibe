#!/usr/bin/env python3
"""Run the PPTX layout gate after a deck-editing tool call.

Vibe `post_tool` hook. It finds `.pptx` paths in the tool input, skips
read-only officecli commands, then runs `check_overlaps.py --strict` and
returns the findings as `additional_context` so the model sees them on the
same turn. Empty stdout means the command was not a deck edit or the deck is
clean.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHECKER = HERE / "check_overlaps.py"
PPTX = re.compile(r"""(?:"([^"]+\.pptx)"|'([^']+\.pptx)'|((?:(?![\s"']).)+\.pptx))""", re.I)
READ_ONLY = frozenset(
    {"get", "query", "validate", "close", "list", "mcp", "help", "schema"}
)
MUTATING = frozenset(
    {"set", "batch", "import", "remove", "add", "refresh", "create", "replace"}
)
MAX_FILES = 2


def strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from strings(item)


def paths(value: object, cwd: Path) -> list[Path]:
    found: list[Path] = []
    for text in strings(value):
        for match in PPTX.finditer(text):
            raw = next(part for part in match.groups() if part)
            candidate = Path(raw).expanduser()
            if not candidate.is_absolute():
                candidate = cwd / candidate
            if candidate.name.startswith("~$"):
                continue
            if candidate.exists() and candidate.is_file():
                if candidate not in found:
                    found.append(candidate)
            if len(found) >= MAX_FILES:
                return found
    return found


def is_edit(tool_name: str, tool_input: object) -> bool:
    text = " ".join(strings(tool_input))
    if "check_overlaps.py" in text:
        return False
    if "officecli" in tool_name.lower() or "officecli" in text:
        try:
            parts = shlex.split(text)
        except ValueError:
            return True
        for index, part in enumerate(parts):
            if part == "officecli" and index + 1 < len(parts):
                command = parts[index + 1].lower()
                return command in MUTATING
        # An MCP officecli call sends the command line without the binary.
        for part in parts:
            if part.lower() in MUTATING:
                return True
        return False
    if "check_overlaps" in text or "validate" in text and "pptx" in text.lower():
        return False
    return bool(re.search(r"\b(?:cp|mv|clone_slide|extract_style)\b", text))


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        return 0
    if payload.get("hook_event_name") != "post_tool":
        return 0
    if not str(payload.get("tool_status", "success")).startswith("success"):
        return 0
    tool_name = str(payload.get("tool_name") or "")
    cwd = Path(payload.get("cwd") or os.getcwd())
    candidates = paths(payload.get("tool_input"), cwd)
    if not candidates or not is_edit(tool_name, payload.get("tool_input")):
        return 0

    findings: list[str] = []
    for deck in candidates:
        try:
            result = subprocess.run(
                [sys.executable, str(CHECKER), str(deck), "--strict"],
                capture_output=True,
                text=True,
                timeout=55,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            print(f"pptx layout gate: {error}", file=sys.stderr)
            continue
        if result.returncode:
            findings.append(f"{deck.name}:\n{result.stdout.strip()}")
    if not findings:
        return 0

    body = "\n\n".join(findings)
    print(
        json.dumps(
            {
                "system_message": f"PPTX layout gate found issues in {len(findings)} deck(s).",
                "hook_specific_output": {
                    "additional_context": (
                        "PPTX layout gate failed. Fix these before responding or "
                        "delivering the deck, then re-run "
                        "`python3 scripts/check_overlaps.py <deck> --strict` "
                        f"until it exits 0:\n{body}"
                    )
                },
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
