"""Tests for magic keyword detection and turn injection."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from tests.conftest import build_test_vibe_config
from vibe.app_server._magic_keywords import (
    MAGIC_KEYWORDS,
    contains_magic_keyword,
    magic_keyword_notices,
    mask_non_prose,
)


class TestMaskNonProse:
    def test_plain_text_unchanged(self) -> None:
        assert mask_non_prose("ultrathink about the api design") == (
            "ultrathink about the api design"
        )

    def test_fenced_code_block_masked(self) -> None:
        text = "before\n```python\nultrathink = 1\n```\nafter"
        masked = mask_non_prose(text)
        assert "ultrathink" not in masked
        assert masked.startswith("before")
        assert masked.endswith("after")

    def test_tilde_fence_masked(self) -> None:
        masked = mask_non_prose("~~~\nultrathink\n~~~")
        assert "ultrathink" not in masked

    def test_inline_code_span_masked(self) -> None:
        masked = mask_non_prose("run `ultrathink --flag` now")
        assert "ultrathink" not in masked
        assert masked.startswith("run ")
        assert masked.endswith(" now")

    def test_unmatched_backticks_are_literal(self) -> None:
        # An opening run without a closing run of the same length stays text.
        assert contains_magic_keyword("a ` ultrathink", "ultrathink")

    def test_html_comment_masked(self) -> None:
        masked = mask_non_prose("<!-- ultrathink -->")
        assert "ultrathink" not in masked

    def test_xml_element_content_masked(self) -> None:
        masked = mask_non_prose("<system-notice>\nultrathink\n</system-notice>")
        assert "ultrathink" not in masked

    def test_length_preserved(self) -> None:
        text = "a `code span` and <!-- comment --> done"
        assert len(mask_non_prose(text)) == len(text)


class TestContainsMagicKeyword:
    def test_standalone_word_matches(self) -> None:
        assert contains_magic_keyword("please ultrathink this", "ultrathink")

    def test_sentence_punctuation_matches(self) -> None:
        assert contains_magic_keyword(
            'ultrathink, then act. "orchestrate"', "orchestrate"
        )

    def test_suffixes_do_not_match(self) -> None:
        assert not contains_magic_keyword("ultrathinking about it", "ultrathink")
        assert not contains_magic_keyword("orchestrated the migration", "orchestrate")

    def test_capitalized_does_not_match(self) -> None:
        assert not contains_magic_keyword("Ultrathink this", "ultrathink")

    def test_identifier_and_paths_do_not_match(self) -> None:
        assert not contains_magic_keyword("fix orchestrate() please", "orchestrate")
        assert not contains_magic_keyword("see orchestrate.ts", "orchestrate")
        assert not contains_magic_keyword("foo::orchestrate", "orchestrate")
        assert not contains_magic_keyword("run utils/orchestrate now", "orchestrate")

    def test_code_fences_do_not_match(self) -> None:
        text = "```python\nprint('ultrathink')\n```"
        assert not contains_magic_keyword(text, "ultrathink")

    def test_html_tags_do_not_match(self) -> None:
        assert not contains_magic_keyword(
            "<ultrathink>hidden</ultrathink>", "ultrathink"
        )


class TestMagicKeywordNotices:
    def test_ultrathink_notice(self) -> None:
        notices = magic_keyword_notices("ultrathink the failure modes")
        assert len(notices) == 1
        assert "<system_notice>" in notices[0]
        assert "Multi-step reasoning" in notices[0]

    def test_orchestrate_notice(self) -> None:
        notices = magic_keyword_notices("orchestrate the migration")
        assert len(notices) == 1
        assert "orchestration request" in notices[0]

    def test_both_keywords(self) -> None:
        notices = magic_keyword_notices("ultrathink and orchestrate it")
        assert len(notices) == 2

    def test_no_keyword_no_notice(self) -> None:
        assert magic_keyword_notices("just a normal prompt") == []

    def test_registered_words_are_stable(self) -> None:
        assert {keyword.word for keyword in MAGIC_KEYWORDS} == {
            "ultrathink",
            "orchestrate",
        }


class TestAdapterInjection:
    def _adapter(self, tmp_path: Path, *, magic_keywords: bool) -> Any:
        from tests.app_server.test_unified_harness_backend_adapter import (
            _inert_adapter,
            _RecordingSession,
        )

        config = build_test_vibe_config(magic_keywords=magic_keywords)
        return _inert_adapter(
            _RecordingSession(), str(tmp_path), str(tmp_path), config=config
        )

    def test_notice_prepended_to_user_entry(self, tmp_path: Path) -> None:
        from vibe.app_server.models import SessionTextContentBlock, TurnUserInputEntry
        from vibe.app_server.protocol import TurnEnqueueParams

        adapter = self._adapter(tmp_path, magic_keywords=True)
        params = TurnEnqueueParams(
            session_id="session-1",
            entries=[
                TurnUserInputEntry(
                    content=[SessionTextContentBlock(text="ultrathink the refactor")]
                )
            ],
        )

        prepared = adapter._with_magic_keywords(params)

        entry = prepared.entries[0]
        first = entry.content[0]
        assert isinstance(first, SessionTextContentBlock)
        assert "<system_notice>" in first.text
        user_block = entry.content[1]
        assert isinstance(user_block, SessionTextContentBlock)
        assert user_block.text == "ultrathink the refactor"

    def test_disabled_config_leaves_params_untouched(self, tmp_path: Path) -> None:
        from vibe.app_server.models import SessionTextContentBlock, TurnUserInputEntry
        from vibe.app_server.protocol import TurnEnqueueParams

        adapter = self._adapter(tmp_path, magic_keywords=False)
        params = TurnEnqueueParams(
            session_id="session-1",
            entries=[
                TurnUserInputEntry(
                    content=[SessionTextContentBlock(text="ultrathink this")]
                )
            ],
        )

        assert adapter._with_magic_keywords(params) is params

    def test_prompt_without_keywords_untouched(self, tmp_path: Path) -> None:
        from vibe.app_server.models import SessionTextContentBlock, TurnUserInputEntry
        from vibe.app_server.protocol import TurnEnqueueParams

        adapter = self._adapter(tmp_path, magic_keywords=True)
        params = TurnEnqueueParams(
            session_id="session-1",
            entries=[
                TurnUserInputEntry(
                    content=[SessionTextContentBlock(text="fix the bug")]
                )
            ],
        )

        assert adapter._with_magic_keywords(params) is params


def test_config_field_defaults_on() -> None:
    from vibe.core.config import VibeConfigSchema

    assert VibeConfigSchema().magic_keywords is True
