"""Tests for session-start memory consolidation."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
from typing import Any, cast

import pytest

from tests.conftest import build_test_vibe_config
from vibe.app_server._memory_consolidation import (
    CONSOLIDATED_FILE_NAME,
    ConsolidationHost,
    _parse_facts,
    consolidate_previous_session,
    render_history_text,
)
from vibe.core.tools.builtins.memory import memory_file, read_memory_entries


@dataclass
class _FakeSession:
    id: str
    updated_at: int = 0


@dataclass
class _FakeListItem:
    session: _FakeSession
    cwd: str | None = None


@dataclass
class _FakeListing:
    items: list[_FakeListItem] = field(default_factory=list)


@dataclass
class _FakeEntry:
    role: str
    text: str


@dataclass
class _FakeState:
    history: list[_FakeEntry]


@dataclass
class _FakeSnapshot:
    state: _FakeState


@dataclass
class _FakeReadResult:
    snapshot: _FakeSnapshot


class _FakeHost:
    def __init__(
        self, sessions: list[_FakeListItem], history: list[_FakeEntry]
    ) -> None:
        self.sessions = sessions
        self.history = history
        self.read_ids: list[str] = []

    async def list(self, **_kwargs: object) -> _FakeListing:
        return _FakeListing(self.sessions)

    async def read(self, params: Any) -> _FakeReadResult:
        self.read_ids.append(params.session_id)
        return _FakeReadResult(_FakeSnapshot(_FakeState(self.history)))


def _history() -> list[_FakeEntry]:
    return [
        _FakeEntry("user", "Fix the flaky deploy"),
        _FakeEntry(
            "assistant", "deploys need SUDO_ASKPASS set; used scripts/deploy.sh"
        ),
    ]


class TestRenderHistoryText:
    def test_only_user_and_assistant_lines(self) -> None:
        text = render_history_text([
            _FakeEntry("user", " hi "),
            _FakeEntry("assistant", "done"),
            _FakeEntry("system", "ignored"),
            _FakeEntry("user", ""),
        ])
        assert text == "USER: hi\nASSISTANT: done"


class TestParseFacts:
    def test_plain_json(self) -> None:
        assert _parse_facts('["a", "b"]') == ["a", "b"]

    def test_fenced_json(self) -> None:
        assert _parse_facts('```json\n["a"]\n```') == ["a"]

    def test_non_json_is_empty(self) -> None:
        assert _parse_facts("no facts here") == []

    def test_non_list_is_empty(self) -> None:
        assert _parse_facts('{"a": 1}') == []

    def test_caps_and_filters(self) -> None:
        facts = _parse_facts(json.dumps(["ok", "", 3, "x"] * 3))
        assert facts == ["ok", "x", "ok", "x", "ok"]


class TestConsolidatePreviousSession:
    @pytest.mark.asyncio
    async def test_retains_facts_and_marks_the_session(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from vibe.app_server import _memory_consolidation as module

        host = _FakeHost(
            [
                _FakeListItem(_FakeSession("current")),
                _FakeListItem(_FakeSession("stored-1", updated_at=10)),
            ],
            _history(),
        )

        async def extract(**_kwargs: object) -> list[str]:
            return ["Deploys need SUDO_ASKPASS set."]

        monkeypatch.setattr(module, "_extract_facts", extract)
        config = build_test_vibe_config()

        retained = await consolidate_previous_session(
            host=host,
            config=config,
            project_root=tmp_path,
            current_session_id="current",
        )

        assert retained == 1
        entries = read_memory_entries(memory_file(tmp_path))
        assert [entry.fact for entry in entries] == ["Deploys need SUDO_ASKPASS set."]
        ledger = tmp_path / ".vibe" / "memory" / CONSOLIDATED_FILE_NAME
        assert ledger.read_text(encoding="utf-8").strip() == "stored-1"
        # The stored session was the one read.
        assert host.read_ids == ["stored-1"]

    @pytest.mark.asyncio
    async def test_a_consolidated_session_is_not_reprocessed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from vibe.app_server import _memory_consolidation as module

        host = _FakeHost([_FakeListItem(_FakeSession("stored-1"))], _history())
        ledger = tmp_path / ".vibe" / "memory" / CONSOLIDATED_FILE_NAME
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text("stored-1\n", encoding="utf-8")

        async def fail(**_kwargs: object) -> str:
            raise AssertionError("must not extract")

        monkeypatch.setattr(module, "_extract_facts", fail)

        retained = await consolidate_previous_session(
            host=host,
            config=build_test_vibe_config(),
            project_root=tmp_path,
            current_session_id="current",
        )
        assert retained == 0
        assert host.read_ids == []

    @pytest.mark.asyncio
    async def test_disabled_config_is_a_no_op(self, tmp_path: Path) -> None:
        host = _FakeHost([_FakeListItem(_FakeSession("stored-1"))], _history())
        retained = await consolidate_previous_session(
            host=host,
            config=build_test_vibe_config(project_memory=False),
            project_root=tmp_path,
            current_session_id="current",
        )
        assert retained == 0

    @pytest.mark.asyncio
    async def test_an_empty_transcript_writes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from vibe.app_server import _memory_consolidation as module

        host = _FakeHost([_FakeListItem(_FakeSession("stored-1"))], [])

        async def fail(**_kwargs: object) -> list[str]:
            raise AssertionError("must not extract")

        monkeypatch.setattr(module, "_extract_facts", fail)

        retained = await consolidate_previous_session(
            host=host,
            config=build_test_vibe_config(),
            project_root=tmp_path,
            current_session_id="current",
        )
        assert retained == 0
        ledger = tmp_path / ".vibe" / "memory" / CONSOLIDATED_FILE_NAME
        assert not ledger.exists()
        assert not memory_file(tmp_path).exists()

    @pytest.mark.asyncio
    async def test_a_failing_listing_is_silent(self, tmp_path: Path) -> None:
        class _BrokenHost:
            async def list(self, **_kwargs: object) -> Any:
                raise RuntimeError("store down")

        retained = await consolidate_previous_session(
            host=cast(ConsolidationHost, _BrokenHost()),
            config=build_test_vibe_config(),
            project_root=tmp_path,
            current_session_id="current",
        )
        assert retained == 0

    @pytest.mark.asyncio
    async def test_a_failing_extraction_is_not_marked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from vibe.app_server import _memory_consolidation as module

        host = _FakeHost([_FakeListItem(_FakeSession("stored-1"))], _history())

        async def fail(**_kwargs: object) -> str:
            raise RuntimeError("provider down")

        monkeypatch.setattr(module, "_extract_facts", fail)

        retained = await consolidate_previous_session(
            host=host,
            config=build_test_vibe_config(),
            project_root=tmp_path,
            current_session_id="current",
        )
        assert retained == 0
        ledger = tmp_path / ".vibe" / "memory" / CONSOLIDATED_FILE_NAME
        assert not ledger.exists()
