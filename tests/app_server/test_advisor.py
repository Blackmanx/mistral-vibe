"""Tests for the advisor: turn review and note delivery."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from tests.conftest import build_test_vibe_config
from vibe.app_server._advisor import (
    ADVISOR_MAX_NOTE_CHARS,
    advisor_note,
    is_all_clear,
    render_advisor_block,
)


def _config() -> Any:
    return build_test_vibe_config()


@pytest.mark.asyncio
class TestAdvisorNote:
    async def test_ok_response_means_no_note(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from vibe.app_server import _btw

        async def complete(**_kwargs: object) -> str:
            return "OK"

        monkeypatch.setattr(_btw, "complete_with_feature", complete)
        assert await advisor_note(config=_config(), transcript="USER: hi") is None

    async def test_a_concern_becomes_the_note(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from vibe.app_server import _btw

        async def complete(**_kwargs: object) -> str:
            return "The fix no longer matches the user's acceptance criterion."

        monkeypatch.setattr(_btw, "complete_with_feature", complete)
        note = await advisor_note(config=_config(), transcript="USER: hi")
        assert note == "The fix no longer matches the user's acceptance criterion."

    async def test_empty_transcript_skips_the_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from vibe.app_server import _btw

        async def fail(**_kwargs: object) -> str:
            raise AssertionError("must not be called")

        monkeypatch.setattr(_btw, "complete_with_feature", fail)
        assert await advisor_note(config=_config(), transcript="  ") is None

    async def test_a_long_note_is_clamped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from vibe.app_server import _btw

        async def complete(**_kwargs: object) -> str:
            return "word " * 500

        monkeypatch.setattr(_btw, "complete_with_feature", complete)
        note = await advisor_note(config=_config(), transcript="USER: hi")
        assert note is not None
        assert len(note) <= ADVISOR_MAX_NOTE_CHARS + 2

    async def test_a_failing_completion_is_silent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from vibe.app_server import _btw

        async def complete(**_kwargs: object) -> str:
            raise RuntimeError("provider down")

        monkeypatch.setattr(_btw, "complete_with_feature", complete)
        assert await advisor_note(config=_config(), transcript="USER: hi") is None


class TestIsAllClear:
    def test_variants(self) -> None:
        assert is_all_clear("OK")
        assert is_all_clear(" ok. ")
        assert is_all_clear("`OK`")

    def test_a_note_is_not_all_clear(self) -> None:
        assert not is_all_clear("The tests were never run.")
        assert not is_all_clear("")


class TestRenderBlock:
    def test_wraps_the_note(self) -> None:
        block = render_advisor_block("Check the failing test.")
        assert block.startswith("<advisor_note>")
        assert "Check the failing test." in block
        assert block.endswith("</advisor_note>")


class TestAdapterDelivery:
    def _adapter(self, tmp_path: Path, *, enable_advisor: bool) -> Any:
        from tests.app_server.test_unified_harness_backend_adapter import (
            _inert_adapter,
            _RecordingSession,
        )

        config = build_test_vibe_config(enable_advisor=enable_advisor)
        return _inert_adapter(
            _RecordingSession(), str(tmp_path), str(tmp_path), config=config
        )

    @pytest.mark.asyncio
    async def test_pending_note_rides_the_next_turn(self, tmp_path: Path) -> None:
        from vibe.app_server.models import SessionTextContentBlock, TurnUserInputEntry
        from vibe.app_server.protocol import TurnEnqueueParams

        adapter = self._adapter(tmp_path, enable_advisor=True)
        adapter._advisor_pending_note = "Check the failing test."
        params = TurnEnqueueParams(
            session_id="session-1",
            entries=[
                TurnUserInputEntry(
                    content=[SessionTextContentBlock(text="next request")]
                )
            ],
        )

        prepared = adapter._with_advisor_note(params)

        first = prepared.entries[0].content[0]
        assert isinstance(first, SessionTextContentBlock)
        assert "<advisor_note>" in first.text
        assert "Check the failing test." in first.text
        # Delivered once, not on every following turn.
        assert adapter._advisor_pending_note is None
        again = adapter._with_advisor_note(prepared)
        assert again is prepared

    @pytest.mark.asyncio
    async def test_no_pending_note_leaves_params_untouched(
        self, tmp_path: Path
    ) -> None:
        from vibe.app_server.models import SessionTextContentBlock, TurnUserInputEntry
        from vibe.app_server.protocol import TurnEnqueueParams

        adapter = self._adapter(tmp_path, enable_advisor=True)
        params = TurnEnqueueParams(
            session_id="session-1",
            entries=[TurnUserInputEntry(content=[SessionTextContentBlock(text="hi")])],
        )

        assert adapter._with_advisor_note(params) is params

    @pytest.mark.asyncio
    async def test_a_repeated_note_is_not_delivered_twice(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from vibe.app_server import _advisor

        adapter = self._adapter(tmp_path, enable_advisor=True)
        adapter._advisor_last_note = "Same concern."

        async def lines(**_kwargs: object) -> list[str]:
            return ["USER: hi", "ASSISTANT: done"]

        async def note(**_kwargs: object) -> str | None:
            return "Same concern."

        monkeypatch.setattr(adapter, "_transcript_lines", lines)
        monkeypatch.setattr(_advisor, "advisor_note", note)
        await adapter._run_advisor_review()
        assert adapter._advisor_pending_note is None

    @pytest.mark.asyncio
    async def test_a_new_note_is_stored_for_the_next_turn(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from vibe.app_server import _advisor

        adapter = self._adapter(tmp_path, enable_advisor=True)

        async def lines(**_kwargs: object) -> list[str]:
            return ["USER: hi", "ASSISTANT: done"]

        async def note(**_kwargs: object) -> str | None:
            return "A fresh concern."

        monkeypatch.setattr(adapter, "_transcript_lines", lines)
        monkeypatch.setattr(_advisor, "advisor_note", note)
        await adapter._run_advisor_review()
        assert adapter._advisor_pending_note == "A fresh concern."
        assert adapter._advisor_last_note == "A fresh concern."

    @pytest.mark.asyncio
    async def test_only_the_delta_since_the_last_review_is_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from vibe.app_server import _advisor

        adapter = self._adapter(tmp_path, enable_advisor=True)
        seen: list[str] = []

        async def lines(**_kwargs: object) -> list[str]:
            return ["USER: one", "ASSISTANT: two", "USER: three", "ASSISTANT: four"]

        async def note(**_kwargs: object) -> str | None:
            seen.append(str(_kwargs.get("transcript", "")))
            return None

        monkeypatch.setattr(adapter, "_transcript_lines", lines)
        monkeypatch.setattr(_advisor, "advisor_note", note)

        await adapter._run_advisor_review()
        assert seen == ["USER: one\nASSISTANT: two\nUSER: three\nASSISTANT: four"]

        await adapter._run_advisor_review()
        # Nothing new was said: the advisor reads an empty delta, not the
        # whole transcript again.
        assert seen[-1] == ""
        assert adapter._advisor_reviewed_lines == 4

    @pytest.mark.asyncio
    async def test_a_shrunk_transcript_resets_the_cursor(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from vibe.app_server import _advisor

        adapter = self._adapter(tmp_path, enable_advisor=True)
        adapter._advisor_reviewed_lines = 10
        seen: list[str] = []

        async def lines(**_kwargs: object) -> list[str]:
            return ["USER: after compaction"]

        async def note(**_kwargs: object) -> str | None:
            seen.append(str(_kwargs.get("transcript", "")))
            return None

        monkeypatch.setattr(adapter, "_transcript_lines", lines)
        monkeypatch.setattr(_advisor, "advisor_note", note)
        await adapter._run_advisor_review()
        assert seen == ["USER: after compaction"]

    def test_disabled_config_never_schedules(self, tmp_path: Path) -> None:
        adapter = self._adapter(tmp_path, enable_advisor=False)
        adapter._schedule_advisor_review()
        assert adapter._advisor_review_in_flight is False

    @pytest.mark.asyncio
    async def test_enabled_config_schedules_one_review(self, tmp_path: Path) -> None:
        adapter = self._adapter(tmp_path, enable_advisor=True)
        adapter._schedule_advisor_review()
        assert adapter._advisor_review_in_flight is True
        # A second schedule while one runs does not double the review.
        adapter._schedule_advisor_review()
        # Let the background task finish; it fails silently without a provider.
        tasks = [
            task for task in asyncio.all_tasks() if task is not asyncio.current_task()
        ]
        await asyncio.gather(*tasks, return_exceptions=True)
        assert adapter._advisor_review_in_flight is False


def test_config_field_defaults_off() -> None:
    from vibe.core.config import VibeConfigSchema

    assert VibeConfigSchema().enable_advisor is False
