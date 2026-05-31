<!--
product-epic template. Fill each section per its guidance, then hand the body to
feature-dev-workflow:writing-github-issues to file it (label: epic).

Two rules govern everything below:
1. Every line is either something the PM decided or something the team/codebase
   confirmed. Anything else goes in "Open confirmations" — never written here as fact.
2. The epic is ready when a fresh engineer, given only this text, hits no blocker
   that isn't already named in "Open confirmations", and a fresh stakeholder
   understands the problem and why it matters.

GitHub doesn't render HTML comments, so leaving this guidance in place is harmless.
-->

# <Title: a human-readable headline of the user value, not a slug>

## Value proposition

<!-- One short paragraph: who this is for, what they can do once it ships that they
can't today, and why that matters. This is the line the wider team reads to understand
why the work is worth doing. No solution detail here. -->

## Problem

<!-- The user problem and why it matters now. What is broken, missing, or costly for
the user today, and what signal says it's worth solving (demand, churn, an obligation).
State the problem, not the solution. -->

## Target users

<!-- Who specifically has this problem. If more than one type of user is affected and
they need different things, name each — conflating them is how scope drifts. -->

## User stories and acceptance criteria

<!-- One or more "As a <user>, I <goal> so that <value>" statements. Under each, list
acceptance criteria as verifiable yes/no conditions a reviewer could check at done-time
("X is visible when Y", not "the experience is great"). Criteria you can't yet write
because a decision is open belong in Open confirmations, not invented here. -->

## Success metrics

<!-- How we'll know it worked, measurably. Each metric is a number or an observable
state, not an aspiration. If the target value isn't decided, say so and add it to Open
confirmations rather than guessing one. -->

## Scope and the scope decision

<!-- What the first version includes. Then the decision: name the cut you chose and WHY
you chose it over the alternatives. If a narrower scope and a more usable/valuable cut
pulled apart, this is the PM's recorded decision and its reasoning, so a later reader
knows the boundary was deliberate. -->

## Non-goals

<!-- What this explicitly does NOT cover, so it doesn't creep in silently. Each non-goal
is a thing a reader might reasonably assume is included; call it out and, where useful,
say whether it's a deliberate "never" or a "not yet". -->

## Constraints and dependencies

<!-- Known constraints this must respect, and anything outside this work it depends on
(another team, a system, an external input). A dependency that's only assumed available
is an Open confirmation, not a stated fact. -->

## Risks

<!-- What could go wrong — for users, for the business, technically — and the severity.
A risk that needs a mitigation decision before design is also an Open confirmation. -->

## Solution direction (optional)

<!-- High-level direction ONLY if it helps frame the problem or bound the scope. The
detailed implementation is the engineer's downstream job (feature-dev-workflow:planning-a-feature)
and is deliberately not required here. An engineer may fill this in after conception.
Do not invent a technical design to make the epic look complete. -->

## Open confirmations

<!-- The checklist of everything that must be confirmed before this epic is ready for an
engineer to design against. Every unknown surfaced during refinement lives here rather
than as an invented answer above. Each item names what must be confirmed and who owns it.
The epic is "coherent" when this list is honest and complete; it is "ready to design"
when this list is empty. -->

- [ ] <Confirm X is feasible at the engineering level> — owner: <who>
- [ ] <Confirm whether this needs design / specialist input> — owner: <who>
- [ ] <Confirm the open decision: ...> — owner: <who>
