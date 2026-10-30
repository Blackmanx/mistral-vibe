from __future__ import annotations

import json

import pytest

from mistralai_vibe_local_harness.vibe.adapters._empty_capture import (
    capture_empty_completion,
)
from mistralai_vibe_local_harness.vibe.adapters._provider_failure import (
    EmptyProviderCompletion,
)
from mistralai_vibe_local_harness.vibe.adapters._tool_call_finish import (
    CompletionSource,
)
from mistralai_vibe_local_harness.vibe.adapters.mistral import (
    _EmptyStreamWatch,
    _read_stream,
    _streamed_parts,
)

SOURCE = CompletionSource(provider="mistral", model="zai-glm-5-3-flash")
USAGE = {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}


def _chunk(delta: dict, finish: str | None = None) -> dict:
    return {
        "id": "chunk",
        "object": "chat.completion.chunk",
        "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        "usage": USAGE if finish is not None else None,
    }


def _thinking(text: str) -> dict:
    return {
        "content": [{"type": "thinking", "thinking": [{"type": "text", "text": text}]}]
    }


async def _stream(*chunks: dict):
    for chunk in chunks:
        yield chunk


async def _read(*chunks: dict, watch=None):
    return await _read_stream(
        _stream(*chunks), emits_finish_reason=True, source=SOURCE, watch=watch
    )


class TestEmptyCompletion:
    @pytest.mark.asyncio
    async def test_answer_is_kept_after_reasoning(self):
        result = await _read(
            _chunk(_thinking("contesto porque...")),
            _chunk({"content": "Hola"}),
            _chunk({"content": ""}, "stop"),
        )

        texts = [part.text for part in result.parts if hasattr(part, "text")]
        assert texts == ["Hola"]

    @pytest.mark.asyncio
    async def test_reasoning_only_completion_fails_instead_of_committing_a_blank(self):
        with pytest.raises(EmptyProviderCompletion):
            await _read(
                _chunk(_thinking("pienso y no concluyo")),
                _chunk({"content": ""}, "stop"),
            )

    @pytest.mark.asyncio
    async def test_empty_completion_is_never_a_text_block(self):
        assert (
            _streamed_parts(
                reasoning="", reasoning_meta={}, text="", tool_call_parts=[]
            )
            == []
        )

    @pytest.mark.asyncio
    async def test_tool_call_only_completion_is_kept(self):
        result = await _read(
            _chunk(_thinking("consulto el scratchpad")),
            _chunk(
                {
                    "content": "",
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_1",
                            "function": {
                                "name": "scratchpad",
                                "arguments": '{"action": "list"}',
                            },
                        }
                    ],
                },
                "tool_calls",
            ),
        )

        assert [part.name for part in result.parts if hasattr(part, "name")] == [
            "scratchpad"
        ]

    @pytest.mark.asyncio
    async def test_empty_completion_reports_the_raw_stream(self):
        seen: list[tuple[list[object], int]] = []

        with pytest.raises(EmptyProviderCompletion):
            await _read(
                _chunk(_thinking("no llego a responder")),
                _chunk({"content": ""}, "stop"),
                watch=_EmptyStreamWatch(
                    lambda chunks, total: seen.append((chunks, total))
                ),
            )

        assert seen and seen[0][1] == 2
        assert "no llego a responder" in json.dumps(seen[0][0], default=str)


class TestCapture:
    def test_records_header_and_chunks_under_the_logs_directory(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("VIBE_HOME", str(tmp_path))

        path = capture_empty_completion(
            provider="mistral",
            model="zai-glm-5-3-flash",
            reasoning="high",
            messages=[_Message("user", "hola")],
            tools=[_Message("tool", "x")],
            chunks=[{"choices": []}, {"note": "fin"}],
            total_chunks=2,
        )

        assert path is not None
        records = [json.loads(line) for line in path.read_text().splitlines()]
        assert records[0]["type"] == "empty_completion"
        assert records[0]["model"] == "zai-glm-5-3-flash"
        assert records[0]["reasoning_effort"] == "high"
        assert records[0]["chunks"] == 2
        assert records[0]["request"]["messages"] == [
            {"role": "user", "characters": len("hola")}
        ]
        assert [record["type"] for record in records[1:]] == ["chunk", "chunk"]
        assert path.stat().st_mode & 0o777 == 0o600

    def test_never_raises_when_the_log_cannot_be_written(self, monkeypatch):
        monkeypatch.setenv("VIBE_HOME", "/proc/self/no-permite-escribir")

        assert (
            capture_empty_completion(
                provider="mistral", model="m", reasoning=None, chunks=[]
            )
            is None
        )


class _Message:
    """The shape the capture reads: a role and a content, never its text."""

    def __init__(self, role: str, content: str) -> None:
        self.role = role
        self.content = content
