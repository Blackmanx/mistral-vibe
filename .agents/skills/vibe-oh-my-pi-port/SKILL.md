---
name: vibe-oh-my-pi-port
description: Port an oh-my-pi agent feature into Mistral Vibe. Use when adding or adapting plan/TODO, goals, /btw, image paste, checkpoints, or any other oh-my-pi capability to the Vibe app server and Rust TUI.
metadata:
  display-name: Port from oh-my-pi
---

# Porting oh-my-pi features into Mistral Vibe

Use this skill for every change that adapts an oh-my-pi feature. It is also the
pre-flight checklist for any agent change inspired by oh-my-pi.

## 1. Pull and reconcile before every change

Never start from a stale checkout. Run this first, from the workspace that holds
both repositories:

```bash
cd oh-my-pi && git pull --ff-only && git status -sb
cd ../mistral-vibe && git pull --ff-only && git status -sb
```

- If `mistral-vibe` has local commits or uncommitted work, reconcile before
  editing: rebase/merge onto `origin/main` and re-read the files you plan to
  touch. Do not overwrite local work to make a port fit.
- Re-run this pull/reconcile step at the start of every new change, not once per
  session. Upstream moves the TUI and the app server quickly.
- If the pull touched a file you are about to edit, re-read it. Do not trust
  earlier line numbers.
- Never edit `oh-my-pi` unless the user explicitly asks. It is a read-only
  reference for this work.

## 2. Architecture rules (Vibe wins)

- Server-owned behavior belongs in the Python app server: session state,
  persistence, tools, prompts, model calls. The Rust TUI is a thin client
  (ADR 0002, ADR 0009, ADR 0016); only presentation state lives there.
- New agent capabilities are modular app-server features (ADR 0018). Prefer a
  **provided tool** (`vibe/core/tools/builtins/<name>.py` plus
  `vibe/app_server/_provided_tools.py`) over a native harness builtin. A native
  builtin needs an explicit Core/Runtime scope agreement.
- A provided tool gets its JSON schema from a Pydantic `BaseTool` subclass. Its
  description comes from the sibling `prompts/<name>.md`, so prompt edits do not
  touch code.
- Keep the Rust client to a wire type, a reducer arm, and a renderer. No agent
  logic in Rust.
- Rust source files stay under 300 lines; no inline `#[cfg(test)]` modules.

## 3. Feature map

| Capability | oh-my-pi reference | Vibe destination |
| --- | --- | --- |
| TODO / plan | `packages/coding-agent/src/tools/todo.ts`, `session/todo-tracker.ts`, `prompts/tools/todo.md` | `vibe/core/tools/builtins/todo.py`, `prompts/todo.md`, `vibe/app_server/_provided_tools.py`, `vibe/cli-rust/src/todo_tracker.rs` |
| Plan-first turn | `prompts/system/prewalk-plan.md`, `plan-mode-active.md` | `/plan` command in `vibe/cli-rust/src/commands/plan.rs` |
| Goal mode | `packages/coding-agent/src/goals/*`, `prompts/goals/*` | `vibe/core/tools/builtins/goal.py`, `vibe/app_server/_provided_tools.py`, adapter continuation, `/goal` |
| `/btw` | `session/btw-turn.ts`, `prompts/system/btw-user.md` | `vibe/app_server/_btw.py`, `vibe/core/prompts/btw.md`, `/btw` |
| Image paste | `utils/clipboard.ts`, `crates/pi-natives/src/clipboard.rs` | `vibe/cli-rust/src/paste_image.rs` (Linux via `wl-paste`/`xclip`, macOS via `osascript`/`sips`) |
| Checkpoint / rewind | `tools/checkpoint.ts` | `/rewind` and `session/rewind` already exist |
| Handoff | `session/session-handoff.ts` | `session/compact` plus context inject, if needed later |

## 4. Adding a provided tool

1. `vibe/core/tools/builtins/<name>.py`: `BaseTool` subclass, `BaseToolConfig`,
   args/result models, pure action functions that mutate only after validation.
2. `vibe/core/tools/builtins/prompts/<name>.md`: model-facing description.
3. `vibe/app_server/_provided_tools.py`: constant, entry in
   `VIBE_PROVIDED_TOOL_NAMES` and `VIBE_PROVIDED_TOOL_MODES`, definition in
   `vibe_tool_groups`, executor branch.
4. Tests in `tests/app_server/test_provided_tools.py` for schema, mutation,
   validation, and per-session isolation.
5. Optional effect kind in `vibe/utils/tool_presentation.py` and
   `vibe/app_server/_effect_models.py` only when the TUI needs a custom card.

## 5. Adding an app-server method

1. `vibe/app_server/protocol.py`: add the name to `SERVER_METHODS` and the
   params/response models next to their siblings.
2. Route it: a first-class `SessionBackend` method needs
   `_session_backend_port.py`, `server.py`, and the adapter. A
   `session/*` extension only needs `dispatch_extension` in
   `_unified_harness_backend_adapter.py`.
3. Add the Rust `method` constant in `vibe/cli-rust/src/server/types.rs`.
4. Add the command module, table entry, dispatch arm, and a `CommandEvent` if the
   result is async.
5. Update `tests/app_server/test_session_backend_port.py` only when the shared
   `SessionBackend` surface changed.

## 6. Prompting for Mistral and GLM models

These models reward short, explicit instructions and penalize schema sprawl:

- Keep one flat argument object per tool. Avoid deep unions and nested phases.
- Tell the model exactly when to call the tool, and pair state-changing tool
  calls with the next real action so a turn is never spent on bookkeeping.
- Prefer explicit `action` enums and stable string ids over free-form protocols.
- Put persistent context in a short XML block (`<goal_context>`, ...) at the
  start of the user turn; do not restate it in every message.
- Keep refusal/error text actionable: the model gets one sentence explaining the
  fix, not a stack trace.
- Verify tool schemas with `model_json_schema()` tests; Mistral/GLM tool calling
  rejects unnamed or ambiguous fields more often than Claude/GPT.

## 7. Installing the fork over an existing Vibe

`./install.sh --source .` builds this checkout and replaces the `mistral-vibe`
uv tool. The remote form is:

```bash
curl -fsSL https://raw.githubusercontent.com/Blackmanx/mistral-vibe/main/install.sh | bash
```

The installer clones or reuses `~/.local/share/mistral-vibe-fork`, builds the
wheel (Rust TUI + Unified Harness), runs `uv tool install --force`, and keeps
`~/.vibe`. It installs uv and rustup when missing, and reports a non-uv `vibe`
that still wins in `PATH` instead of deleting it. Re-run it after every port so
the installed binary matches the checkout.

## 8. Verification

Run the focused gates, not the whole world:

```bash
cd mistral-vibe
uv run ruff check --fix .
uv run ruff format .
uv run pyright
uv run pytest tests/app_server/test_provided_tools.py -q
uv run pytest tests/app_server/test_protocol_models.py -q
```

Rust, from `vibe/cli-rust`:

```bash
make test_rust QUIET=1
```

Any user-visible TUI change also needs a `client-e2e` scenario and a regenerated
golden (`make store_golden`). Before finishing, run `git diff --stat` and state
which gates were not run.
