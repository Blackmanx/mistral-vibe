from __future__ import annotations

from vibe.app_server._btw import MAX_TRANSCRIPT_CHARS, _compact_transcript


def test_the_newest_transcript_lines_survive_the_cap() -> None:
    lines = ["OLD " + ("x" * 100), "middle", "NEW"]

    text = _compact_transcript(lines + ["y" * MAX_TRANSCRIPT_CHARS])

    assert "OLD" not in text
    assert "[earlier conversation omitted]" in text
    assert text.endswith("y" * MAX_TRANSCRIPT_CHARS)


def test_a_short_transcript_is_kept_verbatim() -> None:
    assert _compact_transcript(["USER: hi", "ASSISTANT: hello"]) == (
        "USER: hi\nASSISTANT: hello"
    )
