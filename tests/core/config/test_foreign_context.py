"""Tests for foreign context files: discovery, rendering, and wiring."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from vibe.core.config.harness_files._foreign_context import (
    collect_foreign_context_section,
    load_foreign_project_docs,
    render_foreign_context_section,
)


def _write(path: Path, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


class TestLoadForeignProjectDocs:
    def test_standalone_claude_md_walks_to_the_trust_root(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _write(root / "src" / "CLAUDE.md", "src conventions")
        _write(root / "CLAUDE.md", "root conventions")

        docs = load_foreign_project_docs(root / "src", root)

        # Outermost first: the root doc before the nested one.
        assert [content for _path, content in docs] == [
            "root conventions",
            "src conventions",
        ]

    def test_config_directory_files_are_root_only(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _write(root / ".claude" / "CLAUDE.md", "claude config instructions")
        _write(root / ".gemini" / "GEMINI.md", "gemini instructions")
        _write(root / ".github" / "copilot-instructions.md", "copilot instructions")
        _write(root / "deep" / ".claude" / "CLAUDE.md", "must not load")

        docs = load_foreign_project_docs(root, root)
        contents = [content for _path, content in docs]

        assert "claude config instructions" in contents
        assert "gemini instructions" in contents
        assert "copilot instructions" in contents
        assert "must not load" not in contents

    def test_a_hidden_parent_is_not_the_standalone_walk(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        # .claude/CLAUDE.md must not double-load through the standalone walk.
        _write(root / ".claude" / "CLAUDE.md", "claude config instructions")

        docs = load_foreign_project_docs(root, root)

        assert [content for _path, content in docs] == ["claude config instructions"]

    def test_empty_and_oversized_files_are_skipped(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _write(root / "CLAUDE.md", "   ")
        _write(root / ".gemini" / "GEMINI.md", "x" * 200_001)

        assert load_foreign_project_docs(root, root) == []

    def test_no_files_no_docs(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        root.mkdir()
        assert load_foreign_project_docs(root, root) == []


class TestRenderSection:
    def test_none_when_empty(self) -> None:
        assert render_foreign_context_section([]) is None

    def test_names_the_files(self, tmp_path: Path) -> None:
        section = render_foreign_context_section([
            (tmp_path / "CLAUDE.md", "root conventions")
        ])
        assert section is not None
        assert section.startswith("## Instructions from other agent tools")
        assert f"Contents of {tmp_path / 'CLAUDE.md'}:" in section
        assert "root conventions" in section


class TestCollectSection:
    def test_uses_project_roots_and_trust_store(self, tmp_path: Path) -> None:
        root = tmp_path / "repo"
        _write(root / "CLAUDE.md", "root conventions")
        trust_root = tmp_path

        class _TrustStore:
            def find_trust_root(self, candidate: Path) -> Path | None:
                return trust_root if candidate == root else None

        class _Files:
            def __init__(self) -> None:
                self.project_roots = [root]
                self.trust_store = _TrustStore()

        section = collect_foreign_context_section(_Files())
        assert section is not None
        assert "root conventions" in section


class TestConfigField:
    def test_defaults_on(self) -> None:
        from vibe.core.config import VibeConfigSchema

        assert VibeConfigSchema().foreign_context_files is True


def test_agents_home_env_override(tmp_path: Path, monkeypatch: Any) -> None:
    """VIBE_AGENTS_HOME relocates the shared agent directory."""
    import vibe.core.paths._agents_home as module

    assert module._get_agents_home() == module._DEFAULT_AGENTS_HOME
    monkeypatch.setenv("VIBE_AGENTS_HOME", str(tmp_path / "agents"))
    assert module._get_agents_home() == tmp_path / "agents"
