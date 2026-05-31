---
name: product-epic
description:
  Use when scoping, refining, or clarifying a product-level epic — a rough
  idea, a few bullets, or an early draft — so an engineer can pick it up to
  design an implementation against, or when judging whether an epic is ready
  to hand to engineering.
---

# product-epic

A product epic is the artifact an engineer reads to start designing a solution, and the artifact the wider team reads to understand why the work matters. This skill takes whatever a product manager has — a rough idea, a few bullets, an early draft — and drives it to a coherent epic where every unknown is either resolved or explicitly marked for confirmation, then files it as an issue in the repo the user names.

This skill is standalone. Nothing in the feature-development flow routes into it, and it routes into nothing except `feature-dev-workflow:writing-github-issues` to land the result. It sits upstream of `feature-dev-workflow:planning-a-feature`, which is where an engineer designs the solution against a ready epic. Invoke it whenever an epic needs scoping or a readiness check.

## Core principle: readiness is proven by a reader, never asserted

You cannot judge whether an epic is ready by re-reading your own draft. You hold the whole idea in your head, so it always reads clearly to you, and that judgment is worthless for finding gaps. The test is a reader who has only the epic text. This is the same Iron Law as `feature-dev-workflow:writing-docs`: no claim of readiness without a fresh reader passing first.

The principle has a second half. **Nothing unconfirmed is written as fact.** Every line in the epic is either something the PM decided or something the team or codebase confirmed. Anything else is an open confirmation, marked as such — never a default you invented and dressed up as settled.

## Two readers

- **The engineer** who must design the implementation. From the epic alone, can they design a solution, or do they hit an unknown they would have to guess at? This is the primary gate.
- **The wider team / stakeholder.** From the epic alone, do they understand the user problem, who it is for, and why it is worth doing now?

## Challenge, don't transcribe

A product epic is not a transcription of the PM's first framing. Interrogate it on two fronts.

**Scope versus usability.** The narrowest scope that solves the user problem and the most usable or valuable solution often pull apart. Surface the tension, lay out the candidate cuts, and let the PM choose — this is the PM's call, not yours. Record the chosen cut and the reasoning for it in the epic, so a later reader knows the scope was deliberate and why this candidate won.

**Feasibility honesty.** Is a requirement confirmed feasible at the engineering level, or is it an assumption? An unconfirmed assumption is never written in as fact. It becomes an open confirmation task — "confirm X is feasible before this epic is ready" — owned by someone.

## Readiness bar

Ready does not mean every question is answered. It means **no surprise blockers**: every unknown a fresh engineer would hit is either resolved in the epic or sits in the `## Open confirmations` checklist as an owned task to close before design. Everything is either sorted or marked for confirmation. A named, owned confirmation is fine; an unconfirmed item written as settled fact is not.

## The loop

1. **Take what the PM has, and read it for decided-versus-assumed.** Get the raw epic and the repo it will land in. Do not start filling gaps. First separate what the PM has actually decided from what is assumed or missing.

2. **Prime: sweep the dimensions and the two challenges.** Walk the draft against the readiness dimensions — problem, value, target users, success criteria, scope and non-goals, constraints, dependencies, risks — and the two challenges above. This produces a candidate gap list that seeds the conversation. It does not decide readiness, and you do not fill the gaps from it yourself.

3. **RED — run the readers, do not imagine them.** Dispatch a fresh subagent per reader, given only the current epic text and that reader's job:
   - engineer: design an implementation against this; list every point where you are blocked or would have to guess.
   - stakeholder: what is the problem, who is it for, why is it worth doing, and what can you not answer?

   Record their blockers verbatim. Those blockers are the missing items. If both readers pass with nothing blocking, the epic is already coherent — go to step 7. If you genuinely cannot dispatch a subagent, simulate the reader using only the words on the page and nothing you know from the conversation, and treat the result as provisional: a real fresh-reader pass is still owed before the epic is called ready.

4. **GREEN — brainstorm the gaps with the PM, one at a time.** Take each blocker to the PM and either resolve it or record it as a confirmation task. Do not invent the answer; a default you made up is not a resolution. Two moves apply here:
   - a scope-versus-usability collision: present the candidates, the PM decides, you record the cut and the reasoning.
   - an unconfirmed feasibility assumption: an owned confirmation task in `## Open confirmations`.

   Ask one question at a time, as in `superpowers:brainstorming`. Refine the epic to the quality bar of `feature-dev-workflow:writing-docs`: precise, every sentence earns its place, no marketing fluff.

5. **Re-run the readers** until the engineer hits no unflagged blocker and the stakeholder understands the why. Readiness is what the readers prove, not what you assert.

6. **REFACTOR — cut anything no reader needed.** Length is justified only by a question a reader actually had.

7. **Land it.** Fill the template, then hand the body to `feature-dev-workflow:writing-github-issues` to create the epic (label `epic`) in the repo the PM named. That skill owns the confirmation gate, the label, and the assignee.

## Template

One template carries the shape and the per-section guidance:

- `${CLAUDE_PLUGIN_ROOT}/skills/product-epic/templates/product-epic.md`

Fill each section per its `<!-- -->` guidance. The detailed implementation design is deliberately not part of it — that is the engineer's downstream work in `feature-dev-workflow:planning-a-feature`. The epic carries solution direction only if it helps frame the problem, and an engineer may flesh it out after conception. Keep the epic project-agnostic in the same way the skill is: it describes a user problem and the value of solving it, not a specific stack.

## Anti-patterns

- **Judging the epic ready by re-reading your own draft.** You wrote it, so it reads clearly to you; that is the one judgment that cannot find a gap. Only a fresh reader with only the text can.
- **Inventing answers and writing them as decided.** A format, a metric, an SLA, or a flow you made up is not a decision the PM made. It is either resolved with the PM or an open confirmation. "Sensible default" is the tell.
- **Making the scope call yourself.** Scope versus usability is the PM's decision. Your job is to surface the tradeoff and the candidates, then record the choice and its reasoning.
- **Stripping the open confirmations to make it look finished.** A clean-looking epic with the unknowns hidden is worse than an honest one with them named — engineering builds against the hidden guesses, and the failure surfaces after launch instead of before design.
- **One-shotting the epic without asking the PM anything.** Filling gaps from your own judgment skips the person who holds the answers. Ask.
- **Designing the implementation.** This skill gets the epic ready to design; it does not design. Detailed implementation is downstream and engineer-owned.

## Red flags

| Thought | Reality |
|---------|---------|
| "It reads clearly to me, it's ready" | You hold the whole idea in your head. Run a fresh engineer on the text alone; your read proves nothing. |
| "I'll fill the gaps with sensible defaults" | A default you invented is not a PM decision. Resolve it with the PM, or mark it an open confirmation. |
| "Engineers hate open questions, I'll just decide" | A named, owned confirmation is honest. A hidden guess makes them build the wrong thing under a deadline. |
| "The narrower scope is obviously right, I'll cut it" | Scope versus usability is the PM's call. Surface the candidates, let them choose, record the why. |
| "We're short on time, just make it ready" | Time pressure does not lower the bar. Readiness is the fresh-reader test, not how finished it looks. |
| "I'll write the implementation so engineering can start faster" | The epic is for designing against, not the design itself. Detailed implementation is the engineer's downstream job. |
