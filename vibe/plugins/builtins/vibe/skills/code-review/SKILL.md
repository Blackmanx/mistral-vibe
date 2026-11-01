---
name: code-review
description: >-
  Review a change and give a prioritized verdict before it ships. Use when the
  user asks to review code, check a diff, audit a PR or branch, asks "does this
  look right / should this ship", or before committing or opening a pull
  request on substantial work. Produces findings ranked P0-P3 with confidence,
  each anchored to file and line, and ends with a plain verdict: correct or
  incorrect, and why in 1-3 sentences.
---

# Code review

Review what the change actually introduces — never pre-existing bugs it did not touch.

## Scope

1. The patch: `git diff` for uncommitted work, `git diff <base>...HEAD` for a branch, `git show <commit>` for one commit.
2. Read the full context of every modified file, not just the hunk.
3. For each type, variant, or value the patch sends across a function or module boundary (event, message, enum, queue item, payload), find the consuming-side dispatch and confirm it is forwarded, not silently dropped. The dispatch point is often outside the diff; read it before concluding the producing side is correct.
4. Run the project's checks when the patch is meant to work, and report what you actually ran.

## What qualifies as a finding

Report an issue only when it meets ALL of these:

- **Provable impact** — a specific affected code path, not speculation.
- **Actionable** — a discrete fix, not "consider improving X".
- **Unintentional** — clearly not a deliberate design choice.
- **Introduced by the patch** — not a pre-existing bug.
- **Proportionate rigor** — the fix demands no rigor absent elsewhere in the codebase.

Correctness ignores non-blocking issues: style, docs, nits.

## Priorities

| Level | Criteria | Example |
| --- | --- | --- |
| P0 | Blocks release or operations; universal, no input assumptions | Data corruption, auth bypass |
| P1 | High; fix next cycle | Race condition under load |
| P2 | Medium; fix eventually | Edge case mishandled |
| P3 | Info; nice to have | Suboptimal but correct |

## Output

- Each finding: a one-paragraph body (bug, trigger condition, impact), neutral tone, with `file:line` that overlaps the diff, its P-level, and a 0.0-1.0 confidence it is real.
- Order findings P0 first; never pad with findings that fail the criteria.
- End with the verdict: `correct` (no bugs or blockers) or `incorrect`, a 1-3 sentence plain summary, and overall confidence. State which checks you ran and which you could not.

For a large diff, fan the reading out to `task` subagents per disjoint area and verify their findings yourself before reporting; a subagent's claim is not evidence until you have read the code.
