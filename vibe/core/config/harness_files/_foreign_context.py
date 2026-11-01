"""Foreign context files: instructions other agent tools already wrote.

Ported from oh-my-pi's context files (``docs/context-files.md``), project
scope only: a repository that keeps its conventions in ``CLAUDE.md``,
``.claude/CLAUDE.md``, ``.gemini/GEMINI.md``, or
``.github/copilot-instructions.md`` works in Vibe without converting
anything. oh-my-pi also imports user-level foreign files opt-in and converts
Cursor/Windsurf rule files into its rulebook; this port keeps the
always-on project files, which carry nearly all of the value, and leaves the
rest to their own tools.

Discovery mirrors the AGENTS.md walk: standalone ``CLAUDE.md`` files ride the
same project-root-to-trust-root chain, one per depth, hidden directories
excepted — ``.claude/CLAUDE.md`` belongs to its own provider, not the
standalone walk. Config-directory files (``.claude``, ``.gemini``, ``.github``)
are read from the project root only, like oh-my-pi's no-walk-up providers.
Subagents do not inherit these sections, matching oh-my-pi's session-type
filter.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vibe.utils.io import read_safe

__all__ = [
    "FOREIGN_CONTEXT_FILES",
    "collect_foreign_context_section",
    "load_foreign_project_docs",
    "render_foreign_context_section",
]

# (label, segments, walk_up): segments are the file's path parts below a
# project directory; walk_up means the standalone-chain walk toward the trust
# root, one file per depth.
FOREIGN_CONTEXT_FILES: tuple[tuple[str, tuple[str, ...], bool], ...] = (
    ("CLAUDE.md", ("CLAUDE.md",), True),
    ("CLAUDE.md", (".claude", "CLAUDE.md"), False),
    ("GEMINI.md", (".gemini", "GEMINI.md"), False),
    ("copilot-instructions.md", (".github", "copilot-instructions.md"), False),
)

_MAX_DOCS = 12
_MAX_DOC_CHARS = 100_000


def _read_doc(path: Path) -> str | None:
    """The file's non-empty text, or None. Oversized docs are skipped."""
    try:
        if not path.is_file():
            return None
        text = read_safe(path).text.strip()
    except (OSError, ValueError):
        return None
    if not text or len(text) > _MAX_DOC_CHARS:
        return None
    return text


def _hidden_dir(directory: Path) -> bool:
    return directory.name.startswith(".")


def load_foreign_project_docs(
    project_root: Path, trust_root: Path
) -> list[tuple[Path, str]]:
    """``(path, content)`` pairs for the foreign instruction files below one
    project root, outermost-first; the same resolved path is emitted once.

    The standalone ``CLAUDE.md`` walks from the project root toward the trust
    root like ``AGENTS.md`` does, skipping hidden directories (a config
    directory's file is its own provider's). Config-directory files are read
    from the project root only.
    """
    root = project_root.resolve()
    stop = trust_root.resolve()
    docs: list[tuple[Path, str]] = []
    seen: set[Path] = set()

    for _label, segments, walk_up in FOREIGN_CONTEXT_FILES:
        if not walk_up:
            path = root.joinpath(*segments)
            content = _read_doc(path)
            if content is not None:
                resolved = path.resolve()
                if resolved not in seen:
                    seen.add(resolved)
                    docs.append((path, content))
            continue
        current = root
        while True:
            if not _hidden_dir(current):
                path = current / segments[0]
                content = _read_doc(path)
                if content is not None:
                    resolved = path.resolve()
                    if resolved not in seen:
                        seen.add(resolved)
                        docs.append((path, content))
            if not current.is_relative_to(stop) or current == stop:
                break
            parent = current.parent
            if parent == current:  # fs-root safety
                break
            current = parent

    # Outermost first, mirroring the AGENTS.md ordering.
    return list(reversed(docs))[:_MAX_DOCS]


def render_foreign_context_section(docs: list[tuple[Path, str]]) -> str | None:
    """One prompt section carrying the foreign files, or None when empty.

    The section says what these files are, so the model weighs them as the
    project's standing conventions without mistaking them for Vibe's own.
    """
    if not docs:
        return None
    lines = [
        "## Instructions from other agent tools",
        "This project keeps instructions in files written for other agent "
        "tools. They carry the same standing as project AGENTS.md docs: "
        "repository conventions that apply to the work at hand.",
        "",
    ]
    for path, content in docs:
        lines.append(f"Contents of {path}:")
        lines.append("")
        lines.append(content)
        lines.append("")
    return "\n".join(lines).rstrip()


def collect_foreign_context_section(harness_files: Any) -> str | None:
    """The rendered section for every open project root's foreign files.

    ``harness_files`` is the session's :class:`HarnessFilesManager` view; the
    trust root of each project root bounds the standalone walk, exactly as
    the AGENTS.md walk is bounded.
    """
    docs: list[tuple[Path, str]] = []
    for root in harness_files.project_roots:
        trust_root = harness_files.trust_store.find_trust_root(root) or root
        docs.extend(load_foreign_project_docs(root, trust_root))
    return render_foreign_context_section(docs)
