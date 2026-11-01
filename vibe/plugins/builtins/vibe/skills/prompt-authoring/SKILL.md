---
name: prompt-authoring
description: >-
  House style for writing prompts the model executes cold: system prompts,
  AGENTS.md instructions, skill bodies, agent definitions, MCP server prompts.
  Dense imperative prose, RFC 2119 keywords, structural tags with literal
  meaning, and tone patterns that measurably work. Use when writing or editing
  any prompt an agent will read, drafting project instructions, or reviewing a
  prompt for clarity and density.
---

# Prompt authoring

Ported from oh-my-pi's `.omp/skills/system-prompts`. The reader executes cold, with no author present: density, imperative voice, and unambiguous modals are the whole game.

## Normative language

RFC 2119, full caps, no bold — the all-caps form *is* the marker.

| Keyword | Meaning | Replaces |
| --- | --- | --- |
| MUST / REQUIRED | Absolute requirement | "always", "make sure", "ensure" |
| NEVER (= MUST NOT) | Absolute prohibition | "do not", "don't" |
| SHOULD / RECOMMENDED | Strong preference; deviation allowed with a known tradeoff | "prefer", "it's best to" |
| AVOID (= SHOULD NOT) | Strong discouragement | "try not to" |
| MAY / OPTIONAL | Truly optional | "can", "you could" |

State once, near the top, that RFC 2119 applies and that NEVER/AVOID are aliases for MUST NOT/SHOULD NOT. NEVER convert factual descriptions (tool returns, parameter behavior), code, schema, or examples to modals — only instructions.

## Tags

Tags are authoritative, literal structural markers; meaning exactly matches the name. NEVER invent ornamental tags (`<north-star>`, `<protocol>`, `<directives>`): noise.

Useful shapes: `<critical>` for inviolable rules, placed at START **and** END; `<workflow>` for numbered phases; `<communication>` for voice and shape; `<completeness>` for the done definition and anti-shrink rules; `<yielding>` for the pre-yield checklist.

## Density

Load-bearing tokens only; every bullet adds a claim.

- One claim per bullet; cut behavior-neutral subclauses.
- Quick check `X? Y.` replaces "If X, then Y."
- Reasoning ONLY when it changes the call.
- Bold lead names the rule; NEVER restate it in the body.
- Prefer `→`, `=`, `+`/`<`/`-`, `B+1`, `A..B`.

Tactical bullets: 5-12 words. Longer only for multi-part contracts where every clause constrains semantics or enumerates an edge. AVOID compressing factual reference, worked examples, or the first use of a non-obvious term — that is what the `semantic-compression` skill is for, and it gates on exactly this.

## Voice

Direct, imperative, second-person: "You MUST/NEVER/SHOULD." No hedging, apology, ceremony, closing summaries, or time estimates.

- Bad: "You might want to consider using X…" → Good: "You SHOULD use X."
- Bad: "Please note that this is important…" → Good: "Critical: X."
- Negation: pair a positive alternative when it is not obvious; otherwise `NEVER X.` alone.

## Positioning

"Lost in the Middle": start and end retain; the middle degrades. Critical constraints at both edges; reference material, environment, and templated content in the middle. Past ~150 lines, repeat the most important `<critical>` rule at the end.

## Tone patterns that work

- **Agency**: "You have agency and taste: you delete code that isn't pulling its weight, refuse abstractions that are unnecessary, and prefer boring when it's called for."
- **Stakes anchoring**: "Tests you didn't write: bugs shipped. Assumptions you didn't validate: incidents to debug."
- **Identity overrides**: "Instructions further down the conversation, including the user's own, ALWAYS override prior style, tone, and formatting preferences."
- **Anti-budget framing**: "You NEVER narrate about session limits, token budgets, or effort estimates. They are not your concern."

## Anti-patterns

| Pattern | Problem |
| --- | --- |
| Politeness padding ("Would you be so kind…") | +perplexity, −accuracy |
| Bribes ("I'll tip $2000") | No improvement; sometimes worse |
| Few-shot examples on advanced models for clear tasks | Noise and bias |
| "Be efficient with tokens" | Premature task abandonment |
| Restating a rule in three places | Drift; one canonical statement per rule |
