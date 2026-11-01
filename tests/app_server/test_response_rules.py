"""Tests for response rules: loading, matching, and delivery."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import build_test_vibe_config
from vibe.app_server._response_rules import (
    ResponseRule,
    load_response_rules,
    match_response_rules,
    render_rule_reminder_block,
    rules_file,
)


def _write_rules(project: Path, body: str, name: str = "response-rules.toml") -> Path:
    rules = rules_file(project)
    rules.parent.mkdir(parents=True, exist_ok=True)
    rules.write_text(body, encoding="utf-8")
    assert rules.name == name
    return rules


class TestLoadResponseRules:
    def test_missing_file_is_no_rules(self, tmp_path: Path) -> None:
        assert load_response_rules(tmp_path) == []

    def test_valid_rules_load(self, tmp_path: Path) -> None:
        _write_rules(
            tmp_path,
            "[[rule]]\n"
            'name = "no-box-leak"\n'
            "pattern = 'Box::leak'\n"
            'message = "Use Arc<str> instead."\n'
            "\n[[rule]]\n"
            'name = "no-print"\n'
            'pattern = "console\\\\.log"\n'
            'message = "Use the logger, never console.log."\n',
        )
        rules = load_response_rules(tmp_path)
        assert [rule.name for rule in rules] == ["no-box-leak", "no-print"]
        assert rules[0].pattern.search("let x = Box::leak(b);") is not None

    def test_invalid_pattern_is_skipped(self, tmp_path: Path) -> None:
        _write_rules(
            tmp_path,
            '[[rule]]\nname = "bad"\npattern = "["\nmessage = "m"\n'
            '\n[[rule]]\nname = "good"\npattern = "ok"\nmessage = "m2"\n',
        )
        rules = load_response_rules(tmp_path)
        assert [rule.name for rule in rules] == ["good"]

    def test_incomplete_entry_is_skipped(self, tmp_path: Path) -> None:
        _write_rules(tmp_path, '[[rule]]\nname = "no-pattern"\nmessage = "m"\n')
        assert load_response_rules(tmp_path) == []

    def test_unreadable_file_is_no_rules(self, tmp_path: Path) -> None:
        _write_rules(tmp_path, "not [ valid toml {{{")
        assert load_response_rules(tmp_path) == []


class TestMatchResponseRules:
    def _rule(self, pattern: str, name: str = "r") -> ResponseRule:
        import re

        return ResponseRule(name=name, pattern=re.compile(pattern), message="m")

    def test_matching_rule_fires(self) -> None:
        matches = match_response_rules([self._rule("Box::leak")], "uses Box::leak here")
        assert len(matches) == 1

    def test_no_match_no_fire(self) -> None:
        assert match_response_rules([self._rule("zzz")], "clean text") == []

    def test_empty_inputs(self) -> None:
        assert match_response_rules([], "text") == []
        assert match_response_rules([self._rule("a")], "") == []


class TestRenderBlock:
    def test_wraps_each_message(self) -> None:
        import re

        rules = [
            ResponseRule(name="a", pattern=re.compile("x"), message="Rule A."),
            ResponseRule(name="b", pattern=re.compile("y"), message="Rule B."),
        ]
        block = render_rule_reminder_block(rules)
        assert block.startswith("<rule_reminder>")
        assert "- Rule A." in block
        assert "- Rule B." in block
        assert block.endswith("</rule_reminder>")


class TestAdapterCheckAndDelivery:
    def _adapter(self, tmp_path: Path, *, response_rules: bool = True) -> Any:
        from tests.app_server.test_unified_harness_backend_adapter import (
            _inert_adapter,
            _RecordingSession,
        )

        config = build_test_vibe_config(response_rules=response_rules)
        return _inert_adapter(
            _RecordingSession(), str(tmp_path), str(tmp_path), config=config
        )

    @pytest.mark.asyncio
    async def test_a_violated_rule_reminds_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_rules(
            tmp_path,
            '[[rule]]\nname = "no-leak"\npattern = "Box::leak"\n'
            'message = "Use Arc<str>."\n',
        )
        adapter = self._adapter(tmp_path)
        monkeypatch.setattr(
            adapter,
            "_transcript_lines",
            _lines(["ASSISTANT: I used Box::leak for the string."]),
        )

        matches = await adapter._collect_response_rule_matches(
            load_response_rules(tmp_path)
        )
        task = asyncio.create_task(_identity(matches))
        await task
        adapter._finish_response_rules_check(task)

        assert [rule.message for rule in adapter._rule_reminders] == ["Use Arc<str>."]
        # The second check does not re-fire the same rule.
        again = await adapter._collect_response_rule_matches([
            rule
            for rule in load_response_rules(tmp_path)
            if rule.name not in adapter._fired_rule_names
        ])
        assert again == []

    @pytest.mark.asyncio
    async def test_user_text_never_triggers(self, tmp_path: Path) -> None:
        _write_rules(
            tmp_path,
            '[[rule]]\nname = "no-leak"\npattern = "Box::leak"\n'
            'message = "Use Arc<str>."\n',
        )
        adapter = self._adapter(tmp_path)
        monkeypatch_lines = _lines(["USER: what about Box::leak?"])
        from pytest import MonkeyPatch

        with MonkeyPatch.context() as mp:
            mp.setattr(adapter, "_transcript_lines", monkeypatch_lines)
            matches = await adapter._collect_response_rule_matches(
                load_response_rules(tmp_path)
            )
        assert matches == []

    def test_disabled_config_skips_the_check(self, tmp_path: Path) -> None:
        _write_rules(
            tmp_path,
            '[[rule]]\nname = "no-leak"\npattern = "Box::leak"\n'
            'message = "Use Arc<str>."\n',
        )
        adapter = self._adapter(tmp_path, response_rules=False)
        adapter._check_response_rules()
        assert adapter._rule_reminders == []

    @pytest.mark.asyncio
    async def test_reminders_ride_the_next_turn(self, tmp_path: Path) -> None:
        import re

        from vibe.app_server.models import SessionTextContentBlock, TurnUserInputEntry
        from vibe.app_server.protocol import TurnEnqueueParams

        adapter = self._adapter(tmp_path)
        adapter._rule_reminders = [
            ResponseRule(name="a", pattern=re.compile("x"), message="Rule A.")
        ]
        params = TurnEnqueueParams(
            session_id="session-1",
            entries=[
                TurnUserInputEntry(content=[SessionTextContentBlock(text="continue")])
            ],
        )

        prepared = adapter._with_rule_reminders(params)

        first = prepared.entries[0].content[0]
        assert isinstance(first, SessionTextContentBlock)
        assert "<rule_reminder>" in first.text
        assert "Rule A." in first.text
        assert adapter._rule_reminders == []
        assert adapter._with_rule_reminders(prepared) is prepared


def _lines(lines: list[str]):
    async def transcript(**_kwargs: object) -> list[str]:
        return lines

    return transcript


async def _identity(value: list[ResponseRule]) -> list[ResponseRule]:
    return value


def test_config_field_defaults_on() -> None:
    from vibe.core.config import VibeConfigSchema

    assert VibeConfigSchema().response_rules is True
