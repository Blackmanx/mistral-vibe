"""Write-time response rules: a violated rule reminds at the moment of writing.

The companion of the post-turn response rules (``vibe/app_server/_response_rules.py``):
this post-tool hook checks what the builtin write tools are about to commit —
``write_file``'s whole content, ``edit``'s replacement text — against the
project's rules, and appends the violated rules' messages to the tool result.
That is the closest Vibe gets to oh-my-pi's mid-stream rule injection: the
model learns it violated a rule in the same tool result it reads, and fixes
it in the same response, instead of one turn later.

Like the AGENTS.md builtin (``_agents_md_hooks.py``), the handler registers
Host-globally so it never surfaces as a foreign hook notice, and only the
binding rides each session's compiled hooks — bound only when the session's
``response_rules`` setting is on. The rules file is read per project root and
cached by mtime; a missing file costs one stat per write.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from mistralai_vibe_local_harness.protocol import (
    RustAlwaysHookSelector,
    RustHarnessHookBinding,
    RustPostToolCallHookInput,
    RustPostToolCallHookResult,
    RustPostToolCallOutput,
    RustRuntimeBuiltinToolCall,
    RustTextContentBlock,
    RustToolResult,
    RustToolSuccessResult,
)
from mistralai_vibe_local_harness.vibe import (
    CompiledHooks,
    HookContext,
    HookHandlers,
    PostToolCallHookHandler,
)
from vibe.app_server._response_rules import match_response_rules
from vibe.utils import VIBE_WARNING_TAG

__all__ = [
    "RESPONSE_RULES_HOOK_BINDING_ID",
    "merge_response_rules_hook",
    "response_rules_hook",
    "response_rules_hook_handlers",
]

RESPONSE_RULES_HOOK_BINDING_ID = "builtin:response_rules"

# The builtins whose arguments carry written content, and the argument
# naming the file being written.
_WRITE_TOOL_ARGUMENTS = {
    "file_system.write_file": ("path", "content"),
    "file_system.edit": ("file_path", "new_string"),
}


def _passthrough(tool_result: RustToolResult) -> RustPostToolCallHookResult:
    return RustPostToolCallHookResult(
        output=RustPostToolCallOutput(tool_result=tool_result)
    )


def _write_arguments(
    call: RustRuntimeBuiltinToolCall,
) -> tuple[str | None, str | None] | None:
    """``(file_path, content)`` for a writing builtin call, else None."""
    arguments = _WRITE_TOOL_ARGUMENTS.get(call.name)
    if arguments is None:
        return None
    path_argument, content_argument = arguments
    raw_path = call.arguments.get(path_argument)
    raw_content = call.arguments.get(content_argument)
    path = raw_path if isinstance(raw_path, str) and raw_path.strip() else None
    content = raw_content if isinstance(raw_content, str) and raw_content else None
    return path, content


def _project_root(context: HookContext) -> Path | None:
    try:
        cwd = context.config.workspace.cwd
        return Path(cwd).expanduser().resolve() if cwd else None
    except (OSError, ValueError):
        return None


def _violated_rules(
    call: Any, tool_result: RustToolResult, context: HookContext, load_rules: Any
) -> list[Any]:
    """The rules the call's written content violates; empty when there is
    nothing to check. Raises only through the rules load, which the handler
    treats as a passthrough.
    """
    if not isinstance(call, RustRuntimeBuiltinToolCall):
        return []
    if not isinstance(tool_result, RustToolSuccessResult):
        # A failed write carries nothing to remind about; the failure itself
        # already has the model's attention.
        return []
    write = _write_arguments(call)
    if write is None:
        return []
    file_path, content = write
    root = _project_root(context)
    if root is None or content is None:
        return []
    resolved: Path | None = None
    if file_path is not None:
        candidate = Path(file_path).expanduser()
        if not candidate.is_absolute():
            candidate = root / candidate
        resolved = candidate
    return match_response_rules(load_rules(root), content, path=resolved)


def response_rules_hook() -> PostToolCallHookHandler:
    """The post-tool hook body. The rules cache is keyed by project root."""
    from vibe.app_server._response_rules import rules_file

    cache: dict[Path, tuple[float, list[Any]]] = {}

    def load_rules(root: Path) -> list[Any]:
        path = rules_file(root)
        try:
            mtime = path.stat().st_mtime_ns / 1_000_000_000
        except OSError:
            cache.pop(root, None)
            return []
        cached = cache.get(root)
        if cached is not None and cached[0] == mtime:
            return cached[1]
        from vibe.app_server._response_rules import load_response_rules

        rules = load_response_rules(root)
        cache[root] = (mtime, rules)
        return rules

    async def handler(
        hook_input: RustPostToolCallHookInput, context: HookContext
    ) -> RustPostToolCallHookResult:
        tool_result = hook_input.tool_result
        try:
            violated = _violated_rules(
                hook_input.tool_call.call, tool_result, context, load_rules
            )
        except Exception:
            return _passthrough(tool_result)
        if not violated:
            return _passthrough(tool_result)
        lines = [
            f"<{VIBE_WARNING_TAG}>",
            "Project rules this write violates. Fix it in this response,",
            "in the same turn:",
            *(f"- {rule.message}" for rule in violated),
            f"</{VIBE_WARNING_TAG}>",
        ]
        text = "\n".join(lines)
        return RustPostToolCallHookResult(
            output=RustPostToolCallOutput(
                tool_result=tool_result.model_copy(
                    update={
                        "content": [
                            *tool_result.content,
                            RustTextContentBlock(text=text),
                        ]
                    }
                )
            )
        )

    return handler


def response_rules_hook_handlers() -> HookHandlers:
    """The Host-global builtin registry payload for ``configure_hook_handlers``."""
    return HookHandlers(
        post_tool_call={RESPONSE_RULES_HOOK_BINDING_ID: response_rules_hook()}
    )


def merge_response_rules_hook(hooks: CompiledHooks) -> CompiledHooks:
    """Bind the write-time rules hook on a session's Core. Binding only; the
    handler is Host-global (see ``response_rules_hook_handlers``). The order
    slots after the last existing binding, the same collision rule the
    AGENTS.md builtin follows.
    """
    binding = RustHarnessHookBinding(
        id=RESPONSE_RULES_HOOK_BINDING_ID,
        point="post_tool_call",
        order=max((binding.order for binding in hooks.bindings), default=-1) + 1,
        selector=RustAlwaysHookSelector(),
    )
    return replace(hooks, bindings=(*hooks.bindings, binding))
