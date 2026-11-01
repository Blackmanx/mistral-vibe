---
name: semantic-compression
description: >-
  Re-encode verbose prose into a dense telegraphic register — punctuation as
  connectives, label frames, verbless assertions — without losing normativity
  or precision. Use when compressing system prompts, tool or skill
  descriptions, agent instructions, or documentation; reducing token count or
  context bloat; making documentation token-efficient for LLM input; or
  rewriting text in compressed notation. Also use when asked to make any text
  shorter without losing meaning.
---

# Semantic Compression

Ported from oh-my-pi's `.omp/skills/semantic-compression`.

Compression is **re-encoding, not word deletion**. Filtering function words out of an English sentence leaves a damaged English sentence (`System design: efficient process incoming data, multiple sources`). Instead re-frame each claim in a register whose grammar is punctuation and layout — then the function words have no work left and drop out on their own.

Target texts are load-bearing: tool descriptions, system prompts, skills. A model executes them cold, with no author present to disambiguate. Compression that forces a guess is a bug, not a saving.

## Procedure

0. **Density gate — check before touching anything.** Two signals, in order: (a) are articles and copulas already near-absent? (b) compress one representative section and measure the token delta. Already in this register (house-style prompt, tool doc, spec) or delta under ~10%? **STOP. Report that it is already dense and keep the original.** On already-dense text the remaining words *are* the payload, and the expected saving is smaller than the expected loss.
1. **Split** the source into atomic claims: one definition, obligation, default, or fact each.
2. **Inventory the payload first, before deleting anything.** List every load-bearing token: identifiers, error/exception names, throw conditions, defaults with their units, bounds, and every MUST/NEVER/PREFER line. Anything you then drop is a loss you declare deliberately rather than discover later.
3. **Cut what the model already knows.** "JSON is a text format", "tests catch regressions" → delete. Keep only what is specific to this tool, repo, or domain.
4. **Cut restatements.** Merge every duplicate of one rule into a single canonical line, placed where it is needed. Two statements of one rule with *different scope* are not duplicates.
5. **Frame each claim** — definition · obligation · default · condition→consequence · enumeration · verdict. The frame picks the construction.
6. **Hoist repeated qualifiers** into one scope line: three mentions of "relative to the repo root" → `All paths repo-relative.` once, up top.
7. **Re-encode**, then run Verification.

## Frames

| Frame | English | Compressed |
| --- | --- | --- |
| definition | "The `name` field is the stable launch identifier." | `name: stable launch id.` |
| obligation | "You must call open before you can run code." | `MUST open before run.` |
| default | "If no value is given, the timeout defaults to 30 seconds." | `Default 30s.` |
| condition→consequence | "Because navigation re-renders the page, refs become stale, so you should snapshot again." | `Navigation invalidates refs → re-snapshot.` |
| property chain | "z' is an integer because z divides x²+y², and it is positive because x²+y²>0." | `z' integer since z divides x²+y²; positive since x²+y²>0.` |
| enumeration | "The action may be open, close, or run." | `action: open, close, run.` |
| exclusion | "any triple that is neither (1,1,1) nor (1,1,2)" | `triple ≠ (1,1,1),(1,1,2)` |
| verdict | "Claim A is true, and claim B is false as stated." | `A true; B false as stated.` |
| precondition | "This requires that the branch has already been checked out." | `Requires prior checkout.` |

Constructions behind them:

- **Verbless assertion** — `X true` / `X false` / `X required` / `X unsupported`. Copula deleted; the predicate carries.
- **Label frame** — `X: value` for "the X is / means / consists of". One colon per line, never nested.
- **Subject elision across a run** — name the subject once, chain bare predicates: `Integer since …; positive since …; unique.`
- **Asyndeton** — parallel items, no conjunction: `articles, copulas, expletives`.
- **Scope declaration** — one line retypes everything after it: `All paths repo-relative.` · `Times in ms.`
- **Lazy specification** — state only enough to decide: `3·13·34-1 big` (over the bound; exact value irrelevant). Name the bound somewhere the reader can see it.
- **Metonymy** — an object stands for the proposition about it: `y=z implies (1,1,1)`. Only where exactly one reading exists.

## Operators

Punctuation carries the connective:

- `:` — announce, name, define ("is", "means", "the following")
- `→` — yields, produces, becomes ("which results in")
- `⇒` — therefore, concludes
- `—` — gloss, or "therefore"
- `/` — equivalently, i.e.
- `;` — next step, same topic ("Then,", "After that,")
- `,` — inference chain ("and so")
- `≠` — neither/nor, distributed over a list
- `✓` — verified, obligation discharged
- `>` — precedence ("arg > env > default")
- `|` — alternatives within an enum ("open | close | run")

Ambiguity is the only disqualifier, never unfamiliarity. Where a glyph takes a second reading *in its slot* — `—` as a parenthetical dash, `/` as a path separator or "per", `,` as a list comma — write the word instead.

**Symbols do not save tokens; structure does.** A one-for-one word→glyph swap saves nothing and costs clarity. Substitute a glyph only where it eats a *multi-word phrase*. Superscripts do pay: `x²+y²` beats `x^2+y^2`. Never invent private glyphs — a bespoke one needs a legend that costs more than it saves.

## Deletion

**Always delete:** articles; copulas (is/are/was/be/been); expletive there/it; complementizer `that`; relative pronouns; intensifiers (very, quite, really); filler ("in order to"→to, "due to the fact that"→because, "it is important to note that"→∅); politeness ("please"); hedged framing ("you may want to consider").

**Delete unless load-bearing:** auxiliaries (have/do/will); pronouns with an obvious referent; prepositions of/for/to/in/on/at/by; conjunctions where the list is obvious; adverbs already implied by the verb.

**Never delete — this is the payload:**

- Normative modals: MUST, NEVER, SHOULD, MAY. The RFC 2119 word *is* the instruction.
- Negation and exception: not, no, never, without, none, except, unless.
- Numbers, units, bounds, quantifiers: "at least 5", "≤100", "max 1 MiB", "1-indexed".
- Conditionals and causality: if, unless, because, since, so.
- True hedges: "approximately", "usually", "appears" — deleting one asserts certainty the source did not have.
- Exact strings: identifiers, API names, flags, paths, regexes, format literals, error text.
- Examples that demonstrate a shape. Compressing an example destroys the thing it demonstrates.
- Prepositions where the relation flips meaning: "read from X" ≠ "read to X".
- Throw/failure conditions, and warnings about silent failure. They read like padding and are behavioral.
- Scar tissue: a line that exists because someone already made that mistake. It looks redundant *because* it now prevents the error. `git blame` before cutting anything that looks obvious.

## Private register — never ship

The scratchpad style carries features that work only while writer and reader are the same person, minutes apart. Strip all of them:

- **External deixis** — `A`, `B`, `C`, "the equation", "the claim above". Shipped text is self-contained: name the thing.
- **Scratchpad residue** — `Hmm`, `Actually`, `Wait`, `just`, `fine`; goals revised mid-line; abandoned clauses.
- **Layered corrections** — a wrong value left standing beside its fix. A cold reader cannot tell which pass won. Delete the loser.
- **Dead branches** — an abandoned approach left beside the chosen one. A model may execute the abandoned one.
- **Ambiguous `...` and `?`** — in notes they mean omitted / abandoned / conjecture. In shipped text they mean nothing. Drop both.
- **Nested colons** — one colon per line.
- **Unmarked instruction vs data** — a bare instruction line sitting in content is indistinguishable from content. Keep instructions in a marked channel: heading, tag, or MUST line.
- **Revisiting instead of rewriting** — fine while thinking, fatal in a prompt. One canonical statement per rule.

## Descriptions are retrieval surface

A tool's or skill's `description` field is matched against the user's own phrasing. Keep natural, keyword-redundant alternatives ("compress prompt", "reduce token count", "token-efficient") even though a reader needs only one. Compress the body; NEVER compress the trigger.

## Worked example

Source (63 tokens):

> The `timeout` parameter controls how long the tool will wait for the process to become ready. If you do not provide a value, it defaults to 30 seconds. Note that if you have specified both a log pattern and a port, then both of these conditions must be satisfied before the process is considered ready.

Compressed (20 tokens):

> `Readiness timeout: default 30s. Log pattern + port both supplied ⇒ BOTH must pass.`

Rejected as over-compressed — `timeout 30 log+port both`: loses the unit, loses that 30 is a *default* rather than a fixed value, loses the obligation, and leaves `both` dangling.
