"""Magic keywords: standalone prose words that add hidden turn instructions.

Ported from oh-my-pi (``packages/tui/src/prompt/magic-keywords.ts`` and
``modes/magic-keywords.ts``). A keyword such as ``ultrathink`` typed as a
standalone lowercase prose word in a user prompt prepends a hidden
``<system_notice>`` block to that turn's user entry. The block follows the
fork's established hidden user-turn context pattern (``<auto_plan>``,
``<todo_context>``, ``<goal_context>``): the model reads it, the transcript
keeps the user's own text, and the notice applies only to the turn that
contains the keyword.

Detection is deliberately conservative: the word must appear as prose, never
inside a fenced code block, an inline code span, or an HTML/XML section, and
never glued into an identifier, path, symbol reference, or call syntax.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

__all__ = [
    "MAGIC_KEYWORDS",
    "contains_magic_keyword",
    "magic_keyword_notices",
    "mask_non_prose",
]


# Markdown fence opening a code block: up to three leading spaces, then three
# or more backticks or tildes (oh-my-pi ``FENCE_RE``).
_FENCE_RE = re.compile(r"^( {0,3})([`~]{3,})")

# HTML/XML tag or element name.
_TAG_NAME_RE = re.compile(r"[A-Za-z][A-Za-z0-9-]*")

# Characters that bind a keyword into an identifier, path or symbol reference
# on either side. Sentence punctuation and quotes may touch it.
_LEFT_BOUNDARY = r"(?<![\w./\\-])(?<!::)"  # no letter, digit, _, /, \, -, . or ::
_RIGHT_BOUNDARY = r"(?![\w/\\-])(?!\.[\w-])(?!\()"  # no identifier, extension, call


def _keyword_pattern(word: str) -> re.Pattern[str]:
    """Case-sensitive matcher for ``word`` at prose punctuation boundaries."""
    return re.compile(_LEFT_BOUNDARY + re.escape(word) + _RIGHT_BOUNDARY)


@dataclass(frozen=True, slots=True)
class MagicKeyword:
    """One trigger word and the hidden notice it prepends."""

    id: str
    word: str
    notice: str


_ULTRATHINK_NOTICE = (
    "<system_notice>\n"
    "Multi-step reasoning: the user asked for careful, deliberate work. Think "
    "the problem through step by step before responding: restate the goal, "
    "check your assumptions against the repository, consider the failure modes "
    "of the approach you are about to take, and verify the result instead of "
    "assuming it. Prefer one more verification pass over an optimistic claim.\n"
    "</system_notice>"
)

_ORCHESTRATE_NOTICE = (
    "<system_notice>\n"
    "User message: orchestration request. Act as the orchestrator under this "
    "contract; it overrides tendencies to yield early, narrate, or do all the "
    "work yourself.\n"
    "1. Decompose the request into phases before editing anything. Expand "
    "referenced plans, audits, and file lists into the full work surface; "
    '"most items" is failure. Track phases with `todo`.\n'
    "2. Dispatch substantial or independent work to subagents with `task` in "
    "parallel, in one message, never one-off. Give each a self-contained brief: "
    "target paths, the change, and observable acceptance criteria. Trivial "
    "self-contained edits are cheaper inline.\n"
    "3. Verify each phase before the next: run the project's checks and "
    "targeted tests on changed files. Breakage gets a fix-up pass and a "
    "re-verify; never advance on a red tree.\n"
    "4. Never yield before closure. Phase completion is not a yield point: "
    "start the next phase in the same turn. Stop only when every requested "
    "item is verifiably done or you are concretely blocked.\n"
    "5. No scope creep or shrink: never add unrequested work, and never "
    "relabel unfinished work as a follow-up.\n"
    "</system_notice>"
)

MAGIC_KEYWORDS: tuple[MagicKeyword, ...] = (
    MagicKeyword(id="ultrathink", word="ultrathink", notice=_ULTRATHINK_NOTICE),
    MagicKeyword(id="orchestrate", word="orchestrate", notice=_ORCHESTRATE_NOTICE),
)


def _backtick_run_end(text: str, start: int) -> int:
    end = start
    while end < len(text) and text[end] == "`":
        end += 1
    return end


def _find_backtick_close(
    text: str, from_index: int, run_len: int, masked: list[bool]
) -> int:
    """Index just past the closing backtick run of ``run_len``, or -1."""
    i = from_index
    while i < len(text):
        if masked[i]:
            i += 1
            continue
        if text[i] == "`":
            end = _backtick_run_end(text, i)
            if end - i == run_len:
                return end
            i = end
            continue
        i += 1
    return -1


def _find_tag_end(text: str, start: int) -> int:
    """Index of the ``>`` closing a tag opened at ``start``, honoring quotes."""
    quote = ""
    for i in range(start, len(text)):
        char = text[i]
        if quote:
            if char == quote:
                quote = ""
            continue
        if char in {'"', "'"}:
            quote = char
            continue
        if char == ">":
            return i
        if char == "<":
            return -1
    return -1


def _find_matching_close(text: str, start: int, name: str, masked: list[bool]) -> int:
    """Index past the ``</name>`` balancing an opening ``<name>``."""
    lower = name.lower()
    depth = 1
    i = start
    while i < len(text):
        if masked[i] or text[i] != "<":
            i += 1
            continue
        j = i + 1
        is_close = False
        if j < len(text) and text[j] == "/":
            is_close = True
            j += 1
        match = _TAG_NAME_RE.match(text, j)
        if match is None:
            i += 1
            continue
        gt = _find_tag_end(text, match.end())
        if gt < 0:
            i += 1
            continue
        if match.group(0).lower() == lower:
            if is_close:
                depth -= 1
                if depth == 0:
                    return gt + 1
            elif text[gt - 1] != "/":
                depth += 1
        i = gt + 1
    return -1


def _mask_tag_at(text: str, index: int, masked: list[bool]) -> int:
    """Mask the HTML/XML construct at ``index``; return the next index."""
    n = len(text)
    if text.startswith("<!--", index):
        end = text.find("-->", index + 4)
        stop = n if end < 0 else end + 3
        for p in range(index, stop):
            masked[p] = True
        return stop
    j = index + 1
    closing = False
    if j < n and text[j] == "/":
        closing = True
        j += 1
    match = _TAG_NAME_RE.match(text, j)
    if match is None:
        return index
    gt = _find_tag_end(text, match.end())
    if gt < 0:
        return index
    tag_end = gt + 1
    for p in range(index, tag_end):
        masked[p] = True
    if closing or text[gt - 1] == "/":
        return tag_end
    close = _find_matching_close(text, tag_end, match.group(0), masked)
    if close < 0:
        return tag_end
    for p in range(tag_end, close):
        masked[p] = True
    return close


def mask_non_prose(text: str) -> str:
    """Blank every non-prose region of ``text`` to spaces, keeping length.

    Non-prose regions are markdown fenced code blocks, inline code spans, and
    HTML/XML comments, tags, and the content they enclose, so a word-bounded
    match run against the mask never lands inside code or markup.
    """
    if "`" not in text and "<" not in text and "~~~" not in text:
        return text
    n = len(text)
    masked = [False] * n

    # Phase 1: fenced code blocks, line by line.
    fence_char = ""
    fence_len = 0
    line_start = 0
    while line_start <= n:
        newline = text.find("\n", line_start)
        if newline < 0:
            newline = n
        line = text[line_start:newline]
        open_fence = _FENCE_RE.match(line)
        if fence_char:
            for p in range(line_start, newline):
                masked[p] = True
            if (
                open_fence is not None
                and open_fence.group(2)[0] == fence_char
                and len(open_fence.group(2)) >= fence_len
                and line[open_fence.end() :].strip() == ""
            ):
                fence_char = ""
                fence_len = 0
        elif open_fence is not None:
            marker = open_fence.group(2)
            char = marker[0]
            # A backtick fence's info string may not contain a backtick.
            if not (char == "`" and "`" in line[open_fence.end() :]):
                fence_char = char
                fence_len = len(marker)
                for p in range(line_start, newline):
                    masked[p] = True
        if newline == n:
            break
        line_start = newline + 1

    _mask_inline_spans(text, masked)

    return "".join(" " if masked[p] else text[p] for p in range(n))


def _mask_inline_spans(text: str, masked: list[bool]) -> None:
    """Mask inline code spans and HTML/XML over not-yet-masked regions."""
    i = 0
    n = len(text)
    while i < n:
        if masked[i]:
            i += 1
            continue
        char = text[i]
        if char == "`":
            run_end = _backtick_run_end(text, i)
            close = _find_backtick_close(text, run_end, run_end - i, masked)
            if close >= 0:
                for p in range(i, close):
                    masked[p] = True
                i = close
            else:
                i = run_end
            continue
        if char == "<":
            end = _mask_tag_at(text, i, masked)
            i = end if end > i else i + 1
            continue
        i += 1


def contains_magic_keyword(text: str, word: str) -> bool:
    """Whether ``word`` appears in ``text`` as standalone lowercase prose."""
    if word not in text:
        return False
    return _keyword_pattern(word).search(mask_non_prose(text)) is not None


def magic_keyword_notices(text: str) -> list[str]:
    """Hidden notice blocks for every keyword standing as prose in ``text``."""
    masked = None
    notices: list[str] = []
    for keyword in MAGIC_KEYWORDS:
        if keyword.word not in text:
            continue
        masked = mask_non_prose(text) if masked is None else masked
        if _keyword_pattern(keyword.word).search(masked) is not None:
            notices.append(keyword.notice)
    return notices
