<!--
Ready-for-review PR description template. See ${CLAUDE_PLUGIN_ROOT}/skills/opening-a-pull-request/SKILL.md for the choreography.

This replaces the draft body when marking the PR ready (or is the opening body for PRs that go straight to ready).
-->

## Description

<!--
Open with ONE of these as the FIRST line of this section, depending on what should happen to the linked issue on merge:
  - `Fixes #<num>` — bug-fix issue; GitHub auto-closes on merge to main.
  - `Closes #<num>` — feature/task issue; same auto-close semantics, neutral phrasing.
  - `Towards #<num>` — the PR contributes to the issue but does NOT auto-close it; the issue stays open. Used for sub-PRs into a feature branch (where the orchestrator closes the sub-issue manually after self-merge) and for any other "in progress on this, not finishing it" case.
Omit the line entirely if there is no tracking issue.

Then the summary, at most four sentences, in this order:
  1. The effect, or the cause — the same one the title leads with. A reader who knows the codebase but not this work should be able to stop after this sentence and know whether the PR concerns them.
  2. What this PR does about it.
  3. The consequence, when this PR leaves one behind — a new failure mode, an alert that will start firing, a case it deliberately does not fix, work deferred to a follow-up. One sentence, and it belongs HERE, not further down: it is the part a reviewer most needs before approving, and the Description is the only section they are guaranteed to read.

Write it for a dev arriving without context. Lean on Changes (below) for the "what specifically" — everything a reviewer needs that doesn't fit those three parts has a section of its own further down.
-->

## Changes

<!--
Over-arching changes that affect behavior or user-visible surface. Don't list "renamed foo to bar" or file-level diffs unless they are genuinely the headline change. Bullets, one line each, lead with the biggest.
-->

## Challenges

<!--
Optional, and absent more often than present. Delete the heading unless a paragraph passes this test:

  It states a non-obvious fact about the SYSTEM that a reviewer cannot get from the diff, and knowing it changes how they read the code.

One paragraph, two if the diff really hides two such facts. Three kinds of content fail that test and are what bloats this section — each has a home elsewhere:
  - A consequence of the change (a new failure mode, a tradeoff, an alert that will now fire, work left for later). That is the Description's third part, or a Related follow-up.
  - The history of how the work got here (a review comment, a wrong turn, a test that needed adjusting, what an earlier commit tried). The commits and the review threads already hold it, and a reviewer reading for system facts does not want the changelog of your session.
  - A fact the diff states plainly. If a reviewer learns it by reading the code, writing it here spends their attention twice.

A heading present but thinly filled is worse than no heading: it teaches the reader that this body's sections are decoration, and they stop trusting the ones that matter.
-->

## Related

<!--
Two things live here, and nothing else:
  - Directly-related PRs or issues OTHER than the tracking issue (which is already linked via Fixes/Closes in the Description) — siblings, prior art, a PR this one stacks on.
  - Follow-up work this PR knowingly leaves undone, one line each, whether or not an issue exists for it yet. This is where the deferred fix goes once the Description has named its consequence in a sentence.

Skip the section entirely if there is neither.
-->

## Testing

<!--
Freeform prose. What was tested, how, anything reviewers should poke at themselves. Describe what gives you confidence this is shippable. No checklists.
-->
