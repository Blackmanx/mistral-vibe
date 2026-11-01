"""Tests for the write-time response rules hook."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("mistralai_vibe_local_harness.vibe")

from mistralai_vibe_local_harness.protocol import (
    RustAlwaysHookSelector,
    RustHarnessHookBinding,
    RustHookToolCall,
    RustPostToolCallHookInput,
    RustProtocolError,
    RustRuntimeBuiltinToolCall,
    RustTextContentBlock,
    RustToolFailureResult,
    RustToolSuccessResult,
)
from mistralai_vibe_local_harness.vibe import (
    CompiledHooks,
    HookContext,
    LocalRuntimeAdapterConfig,
)
from vibe.app_server._response_rules import rules_file
from vibe.app_server._response_rules_hook import (
    RESPONSE_RULES_HOOK_BINDING_ID,
    merge_response_rules_hook,
    response_rules_hook,
)
from vibe.utils import VIBE_WARNING_TAG


def _context(tmp_path: Path, session_id: str = "session-1") -> HookContext:
    return HookContext(
        config=LocalRuntimeAdapterConfig.at(cwd=tmp_path, roots=(tmp_path,)),
        messages=(),
        session_id=session_id,
    )


def _write_call(content: str) -> RustHookToolCall:
    return RustHookToolCall(
        action_id="action-1",
        call_id="call-1",
        call=RustRuntimeBuiltinToolCall(
            name="file_system.write_file",
            arguments={"path": "out.py", "content": content},
        ),
    )


def _edit_call(new_string: str) -> RustHookToolCall:
    return RustHookToolCall(
        action_id="action-1",
        call_id="call-1",
        call=RustRuntimeBuiltinToolCall(
            name="file_system.edit",
            arguments={
                "file_path": "out.py",
                "old_string": "a",
                "new_string": new_string,
            },
        ),
    )


def _hook_input(
    call: RustHookToolCall, result: RustToolSuccessResult | RustToolFailureResult
) -> RustPostToolCallHookInput:
    return RustPostToolCallHookInput(tool_call=call, tool_result=result)


def _success() -> RustToolSuccessResult:
    return RustToolSuccessResult(content=[RustTextContentBlock(text="hello")])


def _failure() -> RustToolFailureResult:
    return RustToolFailureResult(
        content=[],
        error=RustProtocolError(code="internal_error", message="boom", retryable=False),
    )


def _write_rules(project: Path, body: str) -> None:
    path = rules_file(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


@pytest.mark.asyncio
async def test_a_violating_write_gets_the_reminder_in_the_result(
    tmp_path: Path,
) -> None:
    _write_rules(
        tmp_path,
        '[[rule]]\nname = "no-print"\npattern = "console\\\\.log"\n'
        'message = "Use the logger, never console.log."\n',
    )
    handler = response_rules_hook()

    result = await handler(
        _hook_input(_write_call("console.log('hi')\n"), _success()), _context(tmp_path)
    )

    appended = result.output.tool_result.content[-1]
    assert isinstance(appended, RustTextContentBlock)
    assert appended.text.startswith(f"<{VIBE_WARNING_TAG}>")
    assert "Use the logger, never console.log." in appended.text
    assert "Fix it in this response" in appended.text
    # The tool's own content is preserved ahead of the reminder.
    original = result.output.tool_result.content[0]
    assert isinstance(original, RustTextContentBlock)
    assert original.text == "hello"


@pytest.mark.asyncio
async def test_a_clean_write_passes_through(tmp_path: Path) -> None:
    _write_rules(
        tmp_path,
        '[[rule]]\nname = "no-print"\npattern = "console\\\\.log"\n'
        'message = "Use the logger."\n',
    )
    handler = response_rules_hook()
    result = await handler(
        _hook_input(_write_call("print('hi')\n"), _success()), _context(tmp_path)
    )
    assert result.output.tool_result.content[-1].text == "hello"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_edit_checks_the_replacement_text(tmp_path: Path) -> None:
    _write_rules(
        tmp_path,
        '[[rule]]\nname = "no-leak"\npattern = "Box::leak"\n'
        'message = "Use Arc<str>."\n',
    )
    handler = response_rules_hook()
    result = await handler(
        _hook_input(_edit_call("let s = Box::leak(b);"), _success()), _context(tmp_path)
    )
    appended = result.output.tool_result.content[-1]
    assert isinstance(appended, RustTextContentBlock)
    assert "Use Arc<str>." in appended.text


@pytest.mark.asyncio
async def test_a_failed_write_passes_through(tmp_path: Path) -> None:
    _write_rules(
        tmp_path,
        '[[rule]]\nname = "no-print"\npattern = "console\\\\.log"\n'
        'message = "Use the logger."\n',
    )
    handler = response_rules_hook()
    result = await handler(
        _hook_input(_write_call("console.log('hi')"), _failure()), _context(tmp_path)
    )
    assert result.output.tool_result.error.message == "boom"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_no_rules_file_passes_through(tmp_path: Path) -> None:
    handler = response_rules_hook()
    result = await handler(
        _hook_input(_write_call("anything"), _success()), _context(tmp_path)
    )
    assert result.output.tool_result.content[-1].text == "hello"  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_every_violation_repeats_until_fixed(tmp_path: Path) -> None:
    """The write-time hook re-injects on every violation, TTSR-style."""
    _write_rules(
        tmp_path,
        '[[rule]]\nname = "no-print"\npattern = "console\\\\.log"\n'
        'message = "Use the logger."\n',
    )
    handler = response_rules_hook()
    for _ in range(2):
        result = await handler(
            _hook_input(_write_call("console.log('again')"), _success()),
            _context(tmp_path),
        )
        appended = result.output.tool_result.content[-1]
        assert isinstance(appended, RustTextContentBlock)
        assert "Use the logger." in appended.text


def test_merge_binds_after_the_last_binding() -> None:
    existing = CompiledHooks(
        bindings=(
            RustHarnessHookBinding(
                id="builtin:agents_md",
                point="post_tool_call",
                order=0,
                selector=RustAlwaysHookSelector(),
            ),
        )
    )
    merged = merge_response_rules_hook(existing)
    [binding] = [b for b in merged.bindings if b.id == RESPONSE_RULES_HOOK_BINDING_ID]
    assert binding.point == "post_tool_call"
    assert binding.order == 1
