"""Tests for the project memory tool and its first-prompt injection."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import cast

from pydantic import JsonValue
import pytest

from mistralai_vibe_local_harness.protocol import (
    RustEvent,
    RustProvidedToolCall,
    RustProvidedToolCallAction,
    RustToolSucceededEvent,
)
from vibe.app_server._provided_tools import (
    MEMORY_TOOL_NAME,
    VIBE_TOOL_GROUP,
    VibeProvidedTools,
    vibe_tool_groups,
)
from vibe.core.tools.builtins.memory import (
    LEARNED_FILE_NAME,
    MEMORY_FILE_NAME,
    forget_entry,
    learn_lesson,
    learned_file,
    memory_file,
    read_learned_lessons,
    read_memory_entries,
    render_memory_block,
    retain_fact,
    search_memory,
)

_Executor = Callable[[RustProvidedToolCallAction], Awaitable[RustEvent]]


def _call(action_id: str, **arguments: JsonValue) -> RustProvidedToolCallAction:
    return RustProvidedToolCallAction(
        action_id=action_id,
        turn_id="turn-1",
        call_id=f"call-{action_id}",
        call=RustProvidedToolCall(
            group_name=VIBE_TOOL_GROUP, tool_name=MEMORY_TOOL_NAME, arguments=arguments
        ),
    )


def _structured(event: RustEvent) -> dict[str, object]:
    assert isinstance(event, RustToolSucceededEvent)
    return cast(dict[str, object], event.result.structured_content)


class TestMemoryStore:
    def test_retain_creates_the_file_and_dedups(self, tmp_path: Path) -> None:
        path = memory_file(tmp_path)

        result, entries = retain_fact(path, "Deployments run through scripts/deploy.sh")
        assert path.is_file()
        assert entries[0].id

        again, entries = retain_fact(path, "Deployments run through scripts/deploy.sh")
        assert "Already remembered" in (again.message or "")
        assert len(entries) == 1

    def test_retain_dedups_a_subset_fact(self, tmp_path: Path) -> None:
        path = memory_file(tmp_path)
        retain_fact(path, "Tests run with uv run pytest, never bare pytest")
        result, _entries = retain_fact(path, "tests run with uv run pytest")
        assert "Close to" in (result.message or "")

    def test_retain_rejects_empty_and_huge_facts(self, tmp_path: Path) -> None:
        path = memory_file(tmp_path)
        with pytest.raises(ValueError, match="empty"):
            retain_fact(path, "   ")
        with pytest.raises(ValueError, match="characters"):
            retain_fact(path, "x" * 2001)

    def test_read_recall_and_forget_round_trip(self, tmp_path: Path) -> None:
        path = memory_file(tmp_path)
        retain_fact(path, "The gateway needs SUDO_ASKPASS set", context="deploy")
        retain_fact(path, "Unit tests live in tests/unit")

        entries = read_memory_entries(path)
        assert len(entries) == 2
        assert entries[0].context == "deploy"

        matched = search_memory(path, "sudo askpass")
        assert len(matched) == 1
        assert "SUDO_ASKPASS" in matched[0].fact

        result, kept = forget_entry(path, entries[0].id)
        assert "Forgot" in (result.message or "")
        assert len(kept) == 1
        assert read_memory_entries(path)[0].id == kept[0].id

    def test_render_memory_block(self, tmp_path: Path) -> None:
        assert render_memory_block(memory_file(tmp_path)) is None
        retain_fact(tmp_path and memory_file(tmp_path), "Fact one")
        block = render_memory_block(memory_file(tmp_path))
        assert block is not None
        assert block.startswith("<project_memory>")
        assert "Fact one" in block

    def test_lessons_ride_the_block_after_facts(self, tmp_path: Path) -> None:
        retain_fact(memory_file(tmp_path), "Fact one")
        learn_lesson(learned_file(tmp_path), "Always run uv run pytest.")

        block = render_memory_block(memory_file(tmp_path))

        assert block is not None
        assert "Fact one" in block
        assert "Lessons learned in past sessions" in block
        assert "Always run uv run pytest." in block

    def test_lessons_alone_also_render(self, tmp_path: Path) -> None:
        learn_lesson(learned_file(tmp_path), "Always run uv run pytest.")
        block = render_memory_block(memory_file(tmp_path))
        assert block is not None
        assert "Always run uv run pytest." in block


class TestLearnLessons:
    def test_learn_is_newest_first_and_dedups(self, tmp_path: Path) -> None:
        path = learned_file(tmp_path)

        learn_lesson(path, "First lesson")
        learn_lesson(path, "Second lesson")
        again, lessons = learn_lesson(path, "first lesson")

        assert lessons == ["Second lesson", "First lesson"]
        assert "already learned" in (again.message or "")

    def test_learn_rejects_empty_and_huge(self, tmp_path: Path) -> None:
        path = learned_file(tmp_path)
        with pytest.raises(ValueError, match="empty"):
            learn_lesson(path, "  ")
        with pytest.raises(ValueError, match="characters"):
            learn_lesson(path, "x" * 2001)

    def test_learn_caps_at_100(self, tmp_path: Path) -> None:
        path = learned_file(tmp_path)
        for index in range(105):
            learn_lesson(path, f"Lesson {index}")

        lessons = read_learned_lessons(path)
        assert len(lessons) == 100
        assert lessons[0] == "Lesson 104"
        assert "Lesson 4" not in lessons

    def test_learned_file_lands_in_the_memory_directory(self, tmp_path: Path) -> None:
        learn_lesson(learned_file(tmp_path), "Always run uv run pytest.")
        assert (tmp_path / ".vibe" / "memory" / LEARNED_FILE_NAME).is_file()


class TestMemoryExecutor:
    def _executor(self, project: Path) -> _Executor:
        holder = VibeProvidedTools()
        factory = holder.executor_factory(
            project / "storage",
            max_todos=lambda: 25,
            project_cwd=lambda _session_id: str(project),
        )
        return factory("session-1")

    @pytest.mark.asyncio
    async def test_retain_then_recall_through_the_tool(self, tmp_path: Path) -> None:
        execute = self._executor(tmp_path)

        written = await execute(
            _call("a1", action="retain", fact="Runs on port 8080 by default")
        )
        assert "Remembered" in str(_structured(written)["message"])

        recalled = await execute(_call("a2", action="recall", query="port"))
        assert _structured(recalled)["action"] == "recall"
        matched = cast(list, _structured(recalled)["matched"])
        assert len(matched) == 1

        read = await execute(_call("a3", action="read"))
        assert len(cast(list, _structured(read)["entries"])) == 1

    @pytest.mark.asyncio
    async def test_forget_removes_the_entry(self, tmp_path: Path) -> None:
        execute = self._executor(tmp_path)
        written = await execute(_call("a1", action="retain", fact="Temporary fact"))
        entry_id = cast(list, _structured(written)["entries"])[0]["id"]

        forgotten = await execute(_call("a2", action="forget", entry_id=str(entry_id)))

        assert "Forgot" in str(_structured(forgotten)["message"])
        assert read_memory_entries(memory_file(tmp_path)) == []

    @pytest.mark.asyncio
    async def test_learn_through_the_tool(self, tmp_path: Path) -> None:
        execute = self._executor(tmp_path)

        learned = await execute(
            _call("a1", action="learn", fact="Always run uv run pytest.")
        )
        assert "Lesson learned" in str(_structured(learned)["message"])
        lessons = read_learned_lessons(learned_file(tmp_path))
        assert lessons == ["Always run uv run pytest."]

    @pytest.mark.asyncio
    async def test_recall_and_read_see_the_lessons(
        self, tmp_path: Path
    ) -> None:
        execute = self._executor(tmp_path)
        await execute(_call("a1", action="retain", fact="Runs on port 8080"))
        await execute(_call("a2", action="learn", fact="Always run uv run pytest."))

        recalled = await execute(_call("a3", action="recall", query="pytest"))
        matched = cast(list, _structured(recalled)["matched"])
        assert len(matched) == 1
        assert matched[0]["fact"] == "Always run uv run pytest."
        assert matched[0]["id"].startswith("lesson-")

        read = await execute(_call("a4", action="read"))
        entries = cast(list, _structured(read)["entries"])
        facts = {entry["fact"] for entry in entries}
        assert facts == {"Runs on port 8080", "Always run uv run pytest."}

    @pytest.mark.asyncio
    async def test_the_memory_file_lands_in_the_project_directory(
        self, tmp_path: Path
    ) -> None:
        execute = self._executor(tmp_path)
        await execute(_call("a1", action="retain", fact="Project fact"))

        assert (tmp_path / ".vibe" / "memory" / MEMORY_FILE_NAME).is_file()


class TestToolGroupRegistration:
    def _tool_names(self, **kwargs: object) -> set[str]:
        return {
            tool.name
            for group in vibe_tool_groups((), **kwargs)  # type: ignore[arg-type]
            for tool in group.tools
        }

    def test_memory_registers_when_enabled(self) -> None:
        assert "memory" in self._tool_names(memory_enabled=True)

    def test_memory_hidden_when_disabled(self) -> None:
        assert "memory" not in self._tool_names(memory_enabled=False)

    def test_memory_respects_the_disabled_tools_glob(self) -> None:
        assert "memory" not in self._tool_names(
            memory_enabled=True, disabled_tools=("mem*",)
        )


class TestFirstPromptInjection:
    @pytest.mark.asyncio
    async def test_first_prompt_gets_the_memory_block(self, tmp_path: Path) -> None:
        from tests.app_server.test_unified_harness_backend_adapter import (
            _inert_adapter,
            _RecordingSession,
        )
        from vibe.app_server.models import SessionTextContentBlock, TurnUserInputEntry
        from vibe.app_server.protocol import TurnEnqueueParams
        from vibe.core.tools.builtins.memory import memory_file

        retain_fact(memory_file(tmp_path), "Remembered project fact")

        adapter = _inert_adapter(_RecordingSession(), str(tmp_path), str(tmp_path))
        adapter._cwd_path = lambda: tmp_path  # type: ignore[method-assign]
        params = TurnEnqueueParams(
            session_id="session-1",
            entries=[
                TurnUserInputEntry(
                    content=[SessionTextContentBlock(text="First prompt")]
                )
            ],
        )

        async def empty_history(**_kwargs: object) -> list[str]:
            return []

        adapter._transcript_lines = empty_history  # type: ignore[method-assign]
        prepared = await adapter._with_memory_guidance(params)

        first = prepared.entries[0].content[0]
        assert isinstance(first, SessionTextContentBlock)
        assert "<project_memory>" in first.text
        assert "Remembered project fact" in first.text

    @pytest.mark.asyncio
    async def test_a_session_with_history_gets_nothing(self, tmp_path: Path) -> None:
        from tests.app_server.test_unified_harness_backend_adapter import (
            _inert_adapter,
            _RecordingSession,
        )
        from vibe.app_server.models import SessionTextContentBlock, TurnUserInputEntry
        from vibe.app_server.protocol import TurnEnqueueParams
        from vibe.core.tools.builtins.memory import memory_file

        retain_fact(memory_file(tmp_path), "Remembered project fact")

        adapter = _inert_adapter(_RecordingSession(), str(tmp_path), str(tmp_path))
        adapter._cwd_path = lambda: tmp_path  # type: ignore[method-assign]
        params = TurnEnqueueParams(
            session_id="session-1",
            entries=[
                TurnUserInputEntry(content=[SessionTextContentBlock(text="Follow-up")])
            ],
        )

        async def with_history(**_kwargs: object) -> list[str]:
            return ["USER: earlier"]

        adapter._transcript_lines = with_history  # type: ignore[method-assign]
        assert await adapter._with_memory_guidance(params) is params

    @pytest.mark.asyncio
    async def test_no_memory_file_no_injection(self, tmp_path: Path) -> None:
        from tests.app_server.test_unified_harness_backend_adapter import (
            _inert_adapter,
            _RecordingSession,
        )
        from vibe.app_server.models import SessionTextContentBlock, TurnUserInputEntry
        from vibe.app_server.protocol import TurnEnqueueParams

        adapter = _inert_adapter(_RecordingSession(), str(tmp_path), str(tmp_path))
        adapter._cwd_path = lambda: tmp_path  # type: ignore[method-assign]
        params = TurnEnqueueParams(
            session_id="session-1",
            entries=[TurnUserInputEntry(content=[SessionTextContentBlock(text="Hi")])],
        )

        assert await adapter._with_memory_guidance(params) is params


def test_config_field_defaults_on() -> None:
    from vibe.core.config import VibeConfigSchema

    assert VibeConfigSchema().project_memory is True
