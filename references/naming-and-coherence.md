# Naming and coherence

A shared reference for the feature-development skills. Parallel fan-out is the moment coherence breaks: each subagent sees only its own issue and contract rows, so it names and structures locally, and five local-optimal choices read as five different authors. The orchestrator is the only role with the whole surface in view, so coherence is an orchestrator responsibility — pushed *down* at dispatch (the conventions contract) and audited *up* at checkpoints (the coherence sweep). This file is the single source of truth for both, plus the naming firewall that keeps planning vocabulary out of the code.

## The conventions contract

A feature's plan pins **wire contracts** (signatures, paths, data layouts) so parallel work compiles. It must also pin **conventions** so parallel work *coheres*. The conventions are the practical decisions every sub-PR inherits, written down once in the plan's `## Conventions` section and handed to every subagent alongside its contract rows.

A `## Conventions` block names, for the surfaces this feature touches:

- **Directory layout** — where new files/packages land, and the nesting rule (e.g. "tests under `<pkg>/specs/`, never flat beside helpers").
- **File and directory naming** — the scheme (kebab, snake, by-content vs by-action) and which one wins where.
- **Identifier naming** — the pattern for the new functions, types, vars, constants, and test names this feature adds.
- **Test and fixture naming/placement** — fixture-scenario names describe the *state or behaviour* they encode (`resumable-investigation`, `summarize-and-resume`), not the flow that happens to use them; scenarios get reused, so a flow-named scenario becomes a lie at the second consumer.
- **Vocabulary** — the locked terms (and their banned synonyms) the feature must use, lifted from the project's CLAUDE.md / AGENTS.md.

Most of this is already implied by the brainstorm and the existing codebase. The work isn't inventing conventions — it's *writing down the ones already in force* so six workers reach for the same answer instead of guessing. A convention you can't state in one line isn't agreed yet; agree it before dispatch, not after merge.

## The naming firewall

**Organizing labels are navigational only. They never become identifiers.**

`Flow 1`, `Phase 2`, `Wave 3`, `Part A` are scaffolding the *plan* uses to sequence work and the *issue tracker* uses to group it. They are an artifact of how the work was decomposed — not a property of the thing being built. The moment that ordinal lands in a directory name, a runtime id, a function name, a package, or a sentinel string, it has leaked: a reader of the code now has to know the planning history to parse it, and the name lies as soon as the plan is renumbered or the artifact is reused.

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

## Coherence is a signal

Good file structure and consistent naming (files, directories, functions, variables, fixtures, vocabulary) are a strong signal of coherent architecture. Inconsistency is a smell: two naming schemes for one kind of thing, an asymmetric API shape among siblings, or a structure that's defensible for one file but bakes in a no-growth convention often means a better structure is waiting to be found. Treat the smell as a prompt to *rework toward* that structure, not as cosmetic debt to defer.

Coherence drift is invisible to contract checks and acceptance criteria — every divergent choice is individually contract-satisfying, so a feature that is 100% contract-clean still reads as written by a committee. It only surfaces when someone reads the *union* of what shipped and asks: would one author have written it this way? That read is the orchestrator's job at every checkpoint; catching it at the wave boundary is far cheaper than after the external reviewer hits it on the integration PR.
