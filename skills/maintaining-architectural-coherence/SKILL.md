---
name: maintaining-architectural-coherence
description:
  Use when work is split across multiple PRs, agents, or waves and the merged
  result must read as if one author wrote it — when agreeing conventions before
  parallel work starts, when dispatching it, and when reviewing what merged; or
  when a structural, interface, naming, or vocabulary inconsistency surfaces as
  a smell.
---

# maintaining-architectural-coherence

## Overview

Work split across contributors drifts. Each piece is built in isolation against its own slice of the problem, so each contributor optimizes locally — and the union reads as written by a committee: two ways to structure the same thing, two error conventions, an interface shaped one way here and another there. **Coherence is the property that the whole reads as one author would have written it.**

The trap: coherence is invisible to per-piece checks. Every PR passes its own review and CI; every contract and acceptance criterion is satisfied; the drift lives only in the *relationships between* pieces. So it has to be designed in up front and audited across the union — neither of which a single diff review does. In decomposed work that is the orchestrator's job, because the orchestrator is the only role that sees the whole surface.

## The dimensions of coherence

Naming is the most visible dimension, not the only one. Read the union across all of them:

- **Structure / layout** — parallel things live in parallel places; new files and packages land by one rule; no piece sits flat where a sibling nests.
- **Interfaces / API shape** — sibling functions, types, and options share a shape; return / error / option conventions match; no asymmetric outlier without a recorded reason.
- **Layering / separation** — the same concern is handled in the same layer across pieces (validation, auth, persistence, config access); no piece reaches across a boundary the others respect.
- **Naming** — one scheme per kind of thing: files, directories, packages, types, functions, variables, constants, fixtures, tests. Plus the naming firewall below.
- **Vocabulary** — the domain's locked terms, with no synonyms for the same concept.
- **Idiom** — the same problem solved the same way each time: error handling, logging, config access, test layout.

## The discipline

1. **Agree the conventions before dispatch.** Pin the decisions every piece inherits — the dimensions above, for the surfaces this work touches — in one place (in this workflow, a plan's `## Conventions` block). Most are already implied by the existing codebase; the work is *writing them down* so N contributors reach the same answer instead of guessing. A convention you can't state in one line isn't agreed yet — agree it before dispatch, not after merge.
2. **Hand them down.** Every dispatched piece gets the conventions and builds against them, not against its own invention.
3. **Audit the union, not the pieces.** Read what all the pieces shipped *together* and ask: would one author have written it this way? Inconsistency is a **signal**, not cosmetic debt — two schemes for one kind of thing, an asymmetric interface, or a structure that's fine for one file but bakes in a no-growth shape usually means a better structure is waiting. Rework toward it now; it is far cheaper than after an external reviewer hits it.

## The naming firewall

**Organizing labels are navigational only. They never become identifiers.**

`Flow 1`, `Phase 2`, `Wave 3`, `Part A` are scaffolding the plan uses to sequence work and the tracker uses to group it. They are an artifact of *how* the work was decomposed — not a property of the thing being built. The moment that ordinal lands in a directory name, a runtime id, a function, a package, or a sentinel string, it has leaked: a reader of the code now has to know the planning history to parse it, and the name lies as soon as the plan is renumbered or the thing is reused.

| Surface | `Flow N` allowed? | Name it instead by |
| --- | --- | --- |
| Epic / sub-issue title prose | yes (a clean prefix: `Flow 2: investigation happy path`) | — |
| Plan / spec narrative and section headings | yes (it indexes the decomposition) | — |
| Branch / PR title | no | the capability (`feature/investigation-e2e`) |
| Directory / file name | no | the content or behaviour |
| Package / type / function / variable / constant | no | what it is or does |
| Fixture / scenario name | no | the state or behaviour it encodes |
| Test name | no | the behaviour under test |
| Sentinel / marker string, config key, env var | no | the thing it marks |

The firewall is a one-way membrane: a label may *appear in* a title or a spec heading, but nothing downstream may *inherit* it as a name. When you catch yourself about to write `flow2-fixture`, `TestFlow2…`, or `…_FLOW2_…`, that is the leak — name the thing for what it is.

## Quick reference

| Dimension | Smell | Fix |
| --- | --- | --- |
| Structure | one piece flat, a sibling nested | one layout rule |
| Interface | sibling APIs shaped differently | align, or record why it differs |
| Layering | one concern handled in different layers | one layer for the concern |
| Naming | two schemes for one kind of thing | one scheme |
| Naming | an organizing label (`Flow N`) in an identifier | name by what the thing is |
| Vocabulary | synonyms for one concept | the locked term |
| Idiom | the same problem solved several ways | one way |

## Common mistakes

- **Declaring "all clean" on per-piece checks.** Contracts, CI, and acceptance criteria never see cross-piece coherence. Read the union before claiming clean.
- **Deferring inconsistency as cosmetic.** It is a signal that a better structure exists; rework toward it rather than shipping the drift.
- **Dispatching parallel work with no agreed conventions.** Each piece invents its own layout and shape; the drift surfaces at integration, where it is expensive.
- **Auditing only names.** Structure, interfaces, layering, vocabulary, and idiom drift too — and an inconsistent interface costs more than an inconsistent name.
