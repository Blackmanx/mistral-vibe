---
name: atomic-commit
description: >-
  Turn the working tree into one or more atomic, well-messaged commits. Use
  when the user asks to commit ("commit this", "haz un commit", "commitea"),
  to split unrelated changes into separate commits, to prepare a PR, or when
  finishing work that touched several unrelated areas. Groups unrelated
  changes, orders commits by dependency, writes conventional past-tense
  messages under 72 characters, and never commits a red tree or unrequested
  work.
---

# Atomic commits

Ported from oh-my-pi's `omp commit` workflow: read the tree, group, message, validate — then commit only what the user asked to commit.

## Read the tree first

1. `git status` plus `git diff` (and `git diff --staged` when something is already staged): every changed file, its shape, and the stat summary.
2. For large diffs, read specific hunks (`git diff -- <path>`) instead of the whole file; keep to the few calls that answer the question.
3. `git log --oneline -10` for the repository's message style when unclear.
4. Lock files (`.lock`, `uv.lock`, `bun.lock`, `package-lock.json`, …) ride along with the commit that caused them; they are never analyzed or split on their own.

## Group

- One commit per unrelated change. Changes to the same feature, the same fix, or files that only make sense together belong together; everything else splits.
- No file appears in two commits, and every file the user asked to commit appears in exactly one. Anything left over is reported, not silently dropped or silently included.
- Order commits by dependency: the module others import from lands before its consumers. If the groups form a cycle, stop and say so — a cycle means the split is wrong, not that one big commit is fine.
- Headline order within one push: source before tests, tests before docs, docs before configs, changelog last.

## Message

- Summary line: past-tense verb, ≤ 72 characters, no trailing period, lowercase scope.
- `type(scope): summary` following the repository's existing convention; when `git log` shows no convention, plain past-tense summaries.
- Never: "comprehensive", "various", "several", "improved", "enhanced", "better", "this commit", "this change", "updated code", "modified files".
- Optional detail lines (0-6), each one sentence ≤ 120 characters, only when the summary alone would hide something load-bearing.

## Before committing

- Run the project's checks on the group when the group is meant to work on its own; never commit a red tree — fix or exclude it and say which.
- Stage exactly the group's files (`git add <paths>`), never `git add -A` when other groups are pending.
- One commit at a time, verifying staging between commits, so a failure leaves the tree understood.
- Respect the repository's signature convention (Co-Authored-By) and never commit secrets, credentials, or files the user did not ask about.
