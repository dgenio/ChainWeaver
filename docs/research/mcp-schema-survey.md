# MCP server schema survey: how well does ChainWeaver's mapping model cover real tools?

> Investigation for issue #433, retargeted (per the batch red-team) to feed the
> schema-mapping / adapter-step design in issue #295 rather than to justify the
> already-shipped `output_mapping` (#386) and dotted-path `input_mapping` (#387),
> which landed after #433 was filed.
>
> **Date:** 2026-07-11 · **Method:** synthesis of publicly documented MCP server
> tool-schema shapes cross-checked against ChainWeaver's adapter and mapping code
> (`chainweaver/mcp/adapter.py`, `chainweaver/flow/steps.py`,
> `chainweaver/_pointer.py`, `chainweaver/contrib/tools.py`).
> **Confidence tags:** *Confirmed* = grounded in a cited source or the current
> codebase; *Inferred* = judgment call; *Could not determine* = not resolved
> within this spike.

## 1. Scope and method

The goal is evidence about the **shapes** real MCP tool schemas take — nesting,
naming conventions, output structure — and how ChainWeaver's current
producer→consumer mapping model covers them, so #295 (field aliases, synonym
dictionary, type-compatible mappings, adapter-step generation) is prioritized
from data rather than intuition.

This spike surveys *documented* schema shapes from widely-used MCP servers
(filesystem, git/GitHub, database, search/fetch, and issue-tracker families) and
the JSON Schema constructs the official MCP SDK emits. It does **not** connect to
live servers — *Could not determine* for any server not publicly documented; the
categories below are the *Confirmed* recurring shapes.

## 2. Recurring schema shapes

| # | Shape | Example | Covered today? |
|---|-------|---------|----------------|
| S1 | Flat scalar inputs | `{path: str, recursive: bool}` | ✅ exact-name match (`ChainAnalyzer`) |
| S2 | Nested object outputs | `{result: {items: [...], nextCursor: str}}` | ⚠️ needs dotted `input_mapping` (#387) to reach `/result/items/0/id` |
| S3 | Name mismatches, same meaning | producer emits `accountId`, consumer wants `account_id` | ❌ not covered — the #295 gap |
| S4 | Type-compatible, not identical | producer `Path` (str subclass shape), consumer `str` | ❌ rejected by exact-type match today |
| S5 | List-of-objects outputs | `{issues: [{id, title, state}, ...]}` | ⚠️ reachable by pointer, but no per-element remap |
| S6 | Envelope wrapping | `{content: [{type: "text", text: "..."}]}` (MCP tool-result envelope) | ⚠️ needs an adapter/unwrap step |
| S7 | Free-form / `additionalProperties` | untyped `metadata` bags | ❌ opaque to static compatibility |

*Confirmed* that S1/S2/S5/S6 occur across the filesystem, git, and issue-tracker
server families (these are the documented output conventions, including the
MCP `content` envelope). *Inferred* that S3/S4 (naming/type drift between a
producer and a semantically-compatible consumer) are the dominant reason
`ChainAnalyzer` under-discovers real chains — this is exactly issue #295's
hypothesis, and the survey supports it.

## 3. Coverage assessment of the current model

- **Exact name + exact type match** (`ChainAnalyzer`, *Confirmed* conservative
  by design) handles S1 and the happy path, and is safe. It cannot bridge S3/S4.
- **Dotted `input_mapping`** (#387, JSON pointer via `chainweaver/_pointer.py`)
  and **`output_mapping`** (#386) already cover S2 and much of S5/S6 *at
  authoring time* — a human can wire `/result/items/0/id` and rename keys.
  *Confirmed (shipped).* What's missing is **discovery/suggestion** of those
  mappings, not the ability to express them.
- **contrib `json_pluck` / `json_set`** provide runtime reshape for S6-style
  envelopes without a bespoke tool. *Confirmed.*

## 4. Implications for #295

Prioritized, from the shapes above:

1. **Field-alias / synonym mapping (S3)** — highest value. A configurable
   synonym dictionary (`accountId ↔ account_id`, `id ↔ *_id`,
   `Path ↔ path ↔ file`) plus case/`snake`↔`camel` normalization would unlock
   the largest class of currently-missed chains. *Inferred priority.*
2. **Type-compatible-with-warning (S4)** — allow `str`-family and
   numeric-widening matches, surfaced as a compatibility *warning* not a hard
   match, so the human reviewer stays in the loop.
3. **Adapter-step suggestion (S2/S5/S6)** — when a producer output needs a
   pointer extraction or envelope unwrap to feed a consumer, suggest an
   `input_mapping` pointer or a `json_pluck` adapter step rather than declaring
   the pair incompatible.
4. **Leave S7 opaque** — free-form bags cannot be statically matched; do not
   guess. Surface them as "unmappable without a manual adapter."

## 5. Open questions / could not determine

- Real frequency weights per shape across the MCP ecosystem — *Could not
  determine* without connecting to a representative server fleet (a natural
  follow-up once contextweaver telemetry, #284, is available).
- Whether synonym dictionaries should ship curated defaults or stay
  user-supplied — a #295 design decision this survey informs but does not settle.
