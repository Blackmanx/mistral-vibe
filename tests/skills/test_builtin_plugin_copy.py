"""Guards on the shipped vibe plugin's skill copies.

The plugin package is the single source of the builtin skills; these tests
keep the copies' self-declared facts honest so drift cannot silently change
how a skill is reached or what its body documents.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

_PLUGIN_SKILLS = ("vibe", "skill-creator")


def _plugin_skill_dir(name: str) -> Path:
    import vibe.plugins.builtins as builtins_pkg

    return Path(builtins_pkg.__file__).parent / "vibe" / "skills" / name


def _plugin_skill(name: str) -> dict[str, Any]:
    text = (_plugin_skill_dir(name) / "SKILL.md").read_text(encoding="utf-8")
    _, frontmatter, body = text.split("---\n", 2)
    return {**yaml.safe_load(frontmatter), "body": body.strip()}


class TestShippedPluginSkillCopies:
    @pytest.mark.parametrize("name", _PLUGIN_SKILLS)
    def test_the_skill_declares_the_name_of_its_directory(self, name: str) -> None:
        assert _plugin_skill(name)["name"] == name

    @pytest.mark.parametrize("name", _PLUGIN_SKILLS)
    def test_the_skill_declares_a_routing_description(self, name: str) -> None:
        description = str(_plugin_skill(name)["description"])
        assert description.strip()


class TestTheVibeCopyBody:
    def test_does_not_pin_a_version_it_cannot_know(self) -> None:
        # A checked-in file cannot interpolate the running version, so the copy
        # points at main rather than at whatever version was current when it
        # was generated.
        body = str(_plugin_skill("vibe")["body"])
        assert "__VIBE_VERSION__" not in body
        assert "https://github.com/mistralai/mistral-vibe/blob/main/README.md" in body

    def test_documents_the_unified_hook_payload(self) -> None:
        body = str(_plugin_skill("vibe")["body"])
        assert '"tool_name": "file_system.bash"' in body
        assert '"duration_ms": 0' in body
        assert '"returncode": 0' in body
        assert "re:bash|process_start" in body
        assert '{"output": "..."}' not in body
        assert "success | failure | cancelled" not in body
        assert 'match = "task"' not in body


class TestOfficeStyleTransferSkill:
    """The fork ships this skill with helper scripts, so its frontmatter must route it."""

    def test_ships_with_its_scripts(self) -> None:
        skill = _plugin_skill("office-style-transfer")
        root = _plugin_skill_dir("office-style-transfer")

        assert skill["name"] == "office-style-transfer"
        assert "template" in str(skill["description"])
        assert {path.name for path in (root / "scripts").glob("*.py")} == {
            "check_overlaps.py",
            "clone_slide.py",
            "extract_style.py",
            "pptx_layout_hook.py",
        }
