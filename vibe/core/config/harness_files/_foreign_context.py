"""Foreign context files: instructions other agent tools already wrote.

Ported from oh-my-pi's context files (``docs/context-files.md``), project
scope only: a repository that keeps its conventions in ``CLAUDE.md``,
``.claude/CLAUDE.md``, ``.gemini/GEMINI.md``, or
``.github/copilot-instructions.md`` works in Vibe without converting
anything, and its always-apply rule files from Cursor (``.cursorrules``,
``.cursor/rules/*.mdc`` with ``alwaysApply: true``), Windsurf
(``.windsurfrules``, ``.windsurf/rules/*.md``), and Cline (``.clinerules``)
ride along the same way. oh-my-pi also imports user-level foreign files
opt-in and converts glob-conditioned rules into its rulebook; this port
keeps the always-on project material, which carries nearly all of the
value, and leaves the rest to their own tools.

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
    "FOREIGN_USER_FILES",
    "collect_foreign_context_section",
    "load_foreign_project_docs",
    "load_foreign_rule_docs",
    "load_foreign_rule_pointers",
    "load_foreign_user_docs",
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

# User-scope foreign files, opt-in like oh-my-pi's enabledProviders: a tool's
# user-level instructions describe that person's habits, not this project, so
# they join only when the user asks for them.
FOREIGN_USER_FILES: tuple[tuple[str, ...], ...] = (
    (".claude", "CLAUDE.md"),
    (".gemini", "GEMINI.md"),
    (".copilot", "copilot-instructions.md"),
)

# Always-apply rule files of other tools, ported from oh-my-pi's cursor,
# windsurf, and cline providers. A rule file joins the context section only
# when it applies everywhere: legacy plaintext rule files always do; the
# frontmatter formats only when their metadata says so. Glob-conditioned
# rules stay with their own tool — Vibe has no rulebook of per-file globs,
# and guessing when one applies would be worse than leaving it out.
_MAX_RULE_FILES = 8
_FRONTMATTER_MARKER = "---"
_LEGACY_RULE_FILES = (".cursorrules", ".windsurfrules")


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


def render_foreign_context_section(
    docs: list[tuple[Path, str]],
    *,
    rule_pointers: list[tuple[Path, str, str]] | None = None,
) -> str | None:
    """One prompt section carrying the foreign files, or None when empty.

    The section says what these files are, so the model weighs them as the
    project's standing conventions without mistaking them for Vibe's own.
    Glob-scoped rule files are listed as pointers — which file holds the
    rule and which files it governs — instead of injected wholesale.
    """
    if not docs and not rule_pointers:
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
    if rule_pointers:
        lines.append(
            "Glob-scoped rule files also exist — read one before editing a "
            "file it governs:"
        )
        lines.append("")
        for path, globs, description in rule_pointers:
            label = f": {description}" if description else ""
            lines.append(f"- {path} (applies to {globs}){label}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _split_frontmatter(text: str) -> tuple[dict[str, str], str]:
    """Minimal ``key: value`` frontmatter: no schema, no nesting, no YAML."""
    lines = text.strip().splitlines()
    if not lines or lines[0].strip() != _FRONTMATTER_MARKER:
        return {}, text.strip()
    for index in range(1, len(lines)):
        if lines[index].strip() == _FRONTMATTER_MARKER:
            fields: dict[str, str] = {}
            for line in lines[1:index]:
                if ":" in line:
                    key, _, value = line.partition(":")
                    fields[key.strip()] = value.strip().strip("\"'")
            return fields, "\n".join(lines[index + 1 :]).strip()
    return {}, text.strip()


def _rule_applies_always(frontmatter: dict[str, str], default: bool) -> bool:
    """Explicit metadata wins; without it, the format's default applies."""
    always_apply = frontmatter.get("alwaysApply", "").strip().lower()
    if always_apply == "true":
        return True
    if always_apply == "false":
        return False
    trigger = frontmatter.get("trigger", "").strip().lower()
    if trigger:
        return trigger in {"always", "always_on"}
    return default


def load_foreign_rule_docs(project_root: Path) -> list[tuple[Path, str]]:
    """``(path, content)`` pairs for the project's always-apply rule files.

    Legacy plaintext rules (``.cursorrules``, ``.windsurfrules``) always
    apply. Cursor ``.cursor/rules/*.mdc`` applies with ``alwaysApply: true``;
    Windsurf ``.windsurf/rules/*.md`` applies with ``alwaysApply: true`` or a
    ``trigger`` that names an everywhere rule. Cline's ``.clinerules`` — a
    file, or a directory of rule files — has no condition and always applies.
    Frontmatter is stripped from what renders.
    """
    root = project_root.resolve()
    docs: list[tuple[Path, str]] = []

    def push(path: Path, default_always: bool) -> None:
        if len(docs) >= _MAX_RULE_FILES:
            return
        content = _read_doc(path)
        if content is None:
            return
        fields, body = _split_frontmatter(content)
        if not body or not _rule_applies_always(fields, default_always):
            return
        docs.append((path, body))

    for name in _LEGACY_RULE_FILES:
        push(root / name, default_always=True)
    for path in sorted((root / ".cursor" / "rules").glob("*.mdc")):
        push(path, default_always=False)
    for path in sorted((root / ".windsurf" / "rules").glob("*.md")):
        push(path, default_always=False)
    clinerules = root / ".clinerules"
    if clinerules.is_dir():
        for path in sorted(clinerules.glob("*.md")):
            push(path, default_always=True)
    else:
        push(clinerules, default_always=True)
    return docs


def load_foreign_user_docs(home: Path | None = None) -> list[tuple[Path, str]]:
    """``(path, content)`` pairs for the user-scope foreign files.

    Read from the home directory (overridable for tests): the same files the
    project scope reads, at the user level. Empty when the files do not
    exist; one file per tool, never merged.
    """
    base = (home or Path.home()).resolve()
    docs: list[tuple[Path, str]] = []
    for segments in FOREIGN_USER_FILES:
        path = base.joinpath(*segments)
        content = _read_doc(path)
        if content is not None:
            docs.append((path, content))
    return docs


def load_foreign_rule_pointers(project_root: Path) -> list[tuple[Path, str, str]]:
    """``(path, globs, description)`` for the glob-conditioned rule files.

    oh-my-pi lists these in its rulebook instead of injecting them — they
    apply to some files, not all, so auto-injecting would spend context on
    every turn. The listing says which file holds the rule and which files
    it governs, so the agent reads it before editing a matching file.
    """
    root = project_root.resolve()
    pointers: list[tuple[Path, str, str]] = []
    for directory, suffix in (
        (root / ".cursor" / "rules", ".mdc"),
        (root / ".windsurf" / "rules", ".md"),
    ):
        if not directory.is_dir():
            continue
        for path in sorted(directory.glob(f"*{suffix}")):
            content = _read_doc(path)
            if content is None:
                continue
            fields, _body = _split_frontmatter(content)
            if fields.get("alwaysApply", "").lower() == "true":
                continue  # injected wholesale by load_foreign_rule_docs
            globs = fields.get("globs", "").strip()
            if not globs:
                continue
            description = fields.get("description", "").strip()
            pointers.append((path, globs, description))
    return pointers[:_MAX_RULE_FILES]


def collect_foreign_context_section(
    harness_files: Any, *, include_user_files: bool = False
) -> str | None:
    """The rendered section for every open project root's foreign files.

    ``harness_files`` is the session's :class:`HarnessFilesManager` view; the
    trust root of each project root bounds the standalone walk, exactly as
    the AGENTS.md walk is bounded. With ``include_user_files`` the user-scope
    foreign files ride in front, opt-in like oh-my-pi's enabledProviders.
    """
    docs: list[tuple[Path, str]] = []
    pointers: list[tuple[Path, str, str]] = []
    if include_user_files:
        docs.extend(load_foreign_user_docs())
    for root in harness_files.project_roots:
        trust_root = harness_files.trust_store.find_trust_root(root) or root
        docs.extend(load_foreign_project_docs(root, trust_root))
        docs.extend(load_foreign_rule_docs(root))
        pointers.extend(load_foreign_rule_pointers(root))
    return render_foreign_context_section(docs, rule_pointers=pointers)
