Track the plan for the current session. Use it for any task that needs 3 or more steps, touches several files, or was given to you as a list.

Write the list before the work, in the same response as your next real tool call. `todo` never earns a turn of its own: pair `write`/`start`/`done` with the read, edit, or check you are about to run. Keep every user requirement as its own item and give each a short, concrete label a later turn can execute without re-planning.

Actions:
- `read` — view the current list.
- `write` — replace the whole list. Include every item you want to keep.
- `append` — add new items without resending the full list.
- `start` — mark the given ids `in_progress`.
- `done` — mark the given ids `completed`; omit `ids` to complete every open task.
- `block` / `unblock` — park work that waits on the user or an external service.
- `clear` — empty the list.

Rules:
- Exactly one item is `in_progress` at a time. Start the next item before working on it.
- Mark an item `completed` immediately after it is verified, never at the end of the turn.
- On a new user request, reconcile the current list before continuing: mark finished items `completed`, cancel items that no longer apply, and append the new work. An item left `in_progress` by an interrupted turn is not proof that it finished.
- Keep ids stable across updates; reuse them instead of resending `write`.
- If a task turns out to be unnecessary, mark it `cancelled` rather than deleting it.
- Do not recreate a list the user removed or cleared.
- Inside a long-running `run_typescript` program, call `tools.vibe.todo` so the list advances while the program runs.
