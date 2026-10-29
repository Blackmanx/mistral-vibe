Manage a long-running, user-approved objective that survives across turns.

Use `goal` only when the user asks for persistent autonomous work ("work on this until it is done", "keep going", "set a goal"). For normal multi-step requests use `todo` instead.

Actions:
- `create` — start a goal. Requires `objective`: one concrete, verifiable outcome. Optional positive `token_budget`. Fails while another goal is active or paused.
- `get` — return the current goal and its remaining budget.
- `complete` — end the goal only after every deliverable is verified against the current repository state. Budget exhaustion and a turn ending are not completion.
- `pause` / `resume` — park or re-activate the current goal.
- `drop` — discard the goal without completing it.

While a goal is active:
- Keep the whole objective intact; never redefine success as a smaller or easier subset.
- Update `todo` as you go so progress stays visible between continuations.
- Before `complete`, audit the current state: read the changed files, run the relevant checks, and match the verification scope to the claim.
- If the work is unfinished when a turn ends, leave the goal `active`; the runtime continues it.
