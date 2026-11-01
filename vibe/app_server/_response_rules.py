"""Response rules: dormant project rules that wake when the agent violates them.

Ported from oh-my-pi's Time Traveling Stream Rules (``docs/ttsr-injection-lifecycle.md``)
in a deterministic, Vibe-native form. oh-my-pi aborts the stream mid-token and
retries with the rule injected; the Unified Harness owns that stream, so this
port keeps the second half of the idea — a rule sits at zero context cost
until the assistant's text matches its pattern, and the reminder then rides in
as a hidden ``<rule_reminder>`` block on the next turn, once per rule.

Rules live in ``.vibe/response-rules.toml`` at the project root:

    [[rule]]
    name = "no-box-leak"
    pattern = 'Box::leak'
    message = "Don't reach for Box::leak in production code paths."

``pattern`` is a case-sensitive regular expression matched against the
assistant text of completed turns. A rule with an invalid pattern is reported
as a warning in the log and ignored, never a broken turn.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import tomllib

from vibe.observability.logging import logger

__all__ = [
    "ResponseRule",
    "load_response_rules",
    "match_response_rules",
    "render_rule_reminder_block",
]

RULES_FILE_NAME = "response-rules.toml"


@dataclass(frozen=True, slots=True)
class ResponseRule:
    """One dormant rule: a name, a pattern, and the reminder it injects."""

    name: str
    pattern: re.Pattern[str]
    message: str


def rules_file(project_root: Path) -> Path:
    return project_root / ".vibe" / RULES_FILE_NAME


def load_response_rules(project_root: Path) -> list[ResponseRule]:
    """Parse the project's rules; a missing or empty file is no rules.

    An invalid entry is logged and skipped: the session must never fail
    because a rule file is wrong.
    """
    path = rules_file(project_root)
    if not path.is_file():
        return []
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError):
        logger.warning("Response rules file %s is unreadable; ignoring it", path)
        return []
    rules: list[ResponseRule] = []
    for entry in raw.get("rule", []):
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name", "")).strip()
        pattern_text = str(entry.get("pattern", "")).strip()
        message = str(entry.get("message", "")).strip()
        if not name or not pattern_text or not message:
            logger.warning(
                "Response rule skipped in %s: name, pattern and message are "
                "all required",
                path,
            )
            continue
        try:
            pattern = re.compile(pattern_text)
        except re.error:
            logger.warning(
                "Response rule %s skipped: invalid pattern %r", name, pattern_text
            )
            continue
        rules.append(ResponseRule(name=name, pattern=pattern, message=message))
    return rules


def match_response_rules(rules: list[ResponseRule], text: str) -> list[ResponseRule]:
    """The rules whose pattern matches anywhere in ``text``."""
    if not rules or not text:
        return []
    return [rule for rule in rules if rule.pattern.search(text) is not None]


def render_rule_reminder_block(matches: list[ResponseRule]) -> str:
    """The hidden block that delivers violated rules to the next turn."""
    lines = [
        "<rule_reminder>",
        "Project rules the previous turn violated. Each rule below is "
        "load-bearing for this repository; honor it from here on and fix what "
        "broke it before continuing.",
    ]
    lines.extend(f"- {rule.message}" for rule in matches)
    lines.append("</rule_reminder>")
    return "\n".join(lines)
