---
name: reviewing-feature-progress
description:
  Use at feature-development orchestration checkpoints — between
  fan-out waves, before opening the integration PR, and before
  flipping the integration PR ready.
---

# reviewing-feature-progress

## When to invoke

Three checkpoints during a feature in flight:

1. **Between fan-out waves.** After wave N is fully self-merged and before wave N+1 dispatches — catches drift while it's still cheap to fix.
2. **Before opening the integration PR.** The integration PR is the external-review surface; its first impression has to be right.
3. **Before flipping a draft integration PR to ready.** Any feedback addressed since the draft opened needs to be re-aligned against the spec/plan.

Skip for ad-hoc fixes that didn't go through `feature-dev-workflow:planning-a-feature`.

## Why this exists

Per-sub-PR review (`review` skill, run by the orchestrator inside `feature-dev-workflow:fanning-out-with-worktrees`) checks one diff at one moment. It doesn't check whether all sub-PRs together still implement what the spec promised, whether they *cohere with each other* (naming, structure, vocabulary — drift that's invisible to any single diff or contract), whether the acceptance criteria are covered, or whether the feature branch as a whole compiles and tests cleanly. Drift accumulates silently across waves; this skill catches it at the boundary.

## Workflow

### 1. Re-read the artifacts

Open these in order:

- The state file (`docs/superpowers/states/<date>-<slug>-state.md`).
- The plan (`docs/superpowers/plans/<date>-<slug>-plan.md`), with focus on the `## Contracts` section and the PR-by-PR breakdown.
- The spec (`docs/superpowers/specs/<date>-<slug>-design.md`), with focus on goals + non-goals.
- Each closed sub-issue's `## Acceptance criteria` section (`gh issue view <num>`).

### 2. Walk each self-merged sub-PR against the plan

For every row in the state file's `## PRs / worktrees` table with status `self-merged`:

- **Diff vs plan.** Use the `review` skill against the sub-PR number to walk the diff with full context. Cross-check against the sub-issue's acceptance criteria — does the diff cover every bullet?
- **Contract realization.** If the sub-PR was a contract producer, inspect the symbol / wire / data layout that actually shipped against what the contract row in the plan documented. The contract row's `Status` should be `locked` and `Realized in` should point at the merged sub-PR.

### 3. Cross-PR coherence sweep

Steps 1-2 check each sub-PR against an *external* reference (plan, contract, acceptance criteria). This step checks the sub-PRs against *each other* — the drift that's invisible to every per-PR check because each divergent choice is individually contract-satisfying.

**REQUIRED SUB-SKILL:** `feature-dev-workflow:maintaining-architectural-coherence`. Apply it to the union of the self-merged sub-PRs (against the plan's `## Conventions` block and against each other) across every dimension it names — structure, interfaces, layering, naming + the firewall, vocabulary, idiom. Classify each finding **align now** (a convergence follow-up sub-PR before the integration PR — the cheap fix) or **deliberate, justified** (record the one-line why in the plan so the reviewer doesn't re-litigate it). Don't carry unexplained drift into the integration PR.

### 4. Acceptance-criteria coverage

For every sub-issue (whether `self-merged` or still open):

- Is every bullet in the issue's `## Acceptance criteria` section now testable / observable in the feature branch?
- If a criterion isn't covered, classify:
  - **Missing implementation** — file or surface a follow-up sub-PR; do not open the integration PR yet.
  - **De-scoped** — removing a criterion changes what the issue promises: a material change. Record it and reconcile the body via `feature-dev-workflow:writing-github-issues` Step 2D (decision comment + body update, linking the commit that de-scoped it); do not silently drop it.
  - **Rephrased / equivalent** — if the implementation genuinely satisfies the criterion under different language, update the wording to match (`feature-dev-workflow:writing-github-issues` Step 2B). If the criterion's substance changed, that is material — use Step 2D.

### 5. GitHub-surface sweep

Steps 1-4 verify the code against the plan and the criteria; this step verifies the prose an external reviewer reads first. A long review cycle changes decisions faster than bodies get reconciled: the per-decision mechanisms (`feature-dev-workflow:writing-github-issues` Step 2D, `feature-dev-workflow:opening-a-pull-request`'s body reconciliation) each cover the surface where the decision was made, and under momentum some surface is always missed. This sweep is the backstop. Walk every GitHub surface the feature owns and read each against the final shape of the branch:

- **The epic body** — design overview, any mermaid diagrams, the framing of each sub-issue.
- **Every sub-issue body** — the approach and context prose, not just the `## Acceptance criteria` sections Step 4 already covered.
- **Every open PR body** — draft or ready, including the integration PR.

A body that names a mechanism the review cycle replaced (a removed field, a renamed method, a dropped phase, a diagram showing a state that no longer exists) misleads the reader in the first ten seconds. Fix through the matching mechanism: issue bodies via `feature-dev-workflow:writing-github-issues` Step 2B (wording) or Step 2D (material change), PR bodies via `feature-dev-workflow:opening-a-pull-request`'s reconciliation (body only, no comment). Sweep all surfaces, not only the ones you remember touching — the misleading body is precisely the one whose divergence went unnoticed at the decision.

### 6. State-file integrity check

Walk the state file and verify reality against record:

- Every `self-merged` row's PR has actually merged into the feature branch (`gh pr view <num> --json mergedAt --jq .mergedAt`).
- Every `locked` contract row's `Realized in` PR is in fact merged.
- Every `## Bubble-up log` entry has a propagation path recorded — no concerns left unresolved.
- The `feature_branch` and `feature_worktree` frontmatter still point at real things on disk (`git rev-parse --verify feature/<slug>` + `ls <feature_worktree>`).

If anything is out of sync, fix the state file before continuing — the resumed-session contract depends on it.

### 7. End-to-end verification on the feature branch

The structure is now settled — every sub-PR merged, the coherence sweep run. This is the first point at which a whole-flow test is safe to write against real seams rather than interfaces still in motion. If the feature introduced a new user- or consumer-visible flow, write or extend the end-to-end coverage now, before running the suite. **REQUIRED SUB-SKILL:** `feature-dev-workflow:testing-end-to-end` for which flows earn an end-to-end test and what each one asserts. A feature that only extends a flow an existing test already covers may need none.

With the feature whole and its behavior settled, write or update the public-facing docs the feature touches before the integration PR opens — the integration PR is the external-review surface, and its docs are part of the first impression. **REQUIRED SUB-SKILL:** `feature-dev-workflow:writing-docs` for what earns a doc and how to verify a reader can actually use it.

**REQUIRED SUB-SKILL:** `superpowers:verification-before-completion`. Run the project-wide checks on the main feature worktree (which holds the integration state — sub-worktrees only hold their own sub-branch):

```
cd <feature_worktree>
git pull origin feature/<slug>
# then run the project's full test + lint suite (and typecheck, if it has one),
# discovered from the project's CLAUDE.md / AGENTS.md or build config
```

Paste the output. The feature branch must be green end to end before the integration PR opens — a sub-PR's isolated CI passing doesn't guarantee the integration compiles, since each sub-PR's tests ran against its own branch state, not the post-merge state.

### 8. Synthesize the gap list

Produce a short summary for the orchestrator (and the user, if this is a pre-integration-PR or pre-ready checkpoint):

- **Drift found** — one bullet per discrepancy between spec/plan and what the diffs actually do.
- **Coherence findings** — one bullet per cross-PR inconsistency from Step 3 (naming, structure, API shape, vocabulary), each marked `align now` or `deliberate, justified`.
- **Acceptance criteria uncovered** — one bullet per missing or rephrased criterion, with the classification from Step 4.
- **Body-sweep fixes** — one bullet per stale GitHub body reconciled in Step 5 (epic, sub-issue, or PR).
- **State-file fixes** — one bullet per row corrected.
- **Verification status** — test / lint / typecheck pass/fail.

Decide:

- **All clean** → open the integration PR (or flip ready) per `feature-dev-workflow:developing-a-feature`.
- **Coverable by a follow-up sub-PR** → re-enter `feature-dev-workflow:developing-a-feature` Step 4 and dispatch a follow-up subagent into a new sub-worktree. Update the state file with the new row.
- **Needs spec/plan refinement** → re-invoke `feature-dev-workflow:planning-a-feature` Steps 6/7 (write/update the plan, refine the issues), surface the changes to the user, then continue.

## Anti-patterns

- **Skipping the check at phase transitions.** Each wave's drift compounds; surfacing it at the boundary is the cheapest place to fix it.
- **Running verification on a sub-worktree instead of the main feature worktree.** Sub-worktrees only have their own sub-branch checked out. The feature branch — where the integration shows up — lives in the main feature worktree.
- **Marking the integration PR ready without re-running this checkpoint after external feedback.** Reviewer-requested changes can re-introduce drift the original review missed.
- **Calling it "all clean" on contract + acceptance + verification alone.** Those are external-reference checks; they pass while the merged surface drifts. Run the Step 3 coherence sweep before any "all clean".
- **Treating the acceptance-criteria gap as a docs problem.** A missing criterion is either missing implementation or a planning oversight. Don't silently delete it; classify and act.
- **Reconciling a de-scoped criterion with a bare body edit.** Dropping a criterion changes what the issue promises; the *why* and the commit that decided it belong in the issue's thread, not just trimmed out of the body. Use `feature-dev-workflow:writing-github-issues` Step 2D — comment, then edit.

## Red flags

| Thought                                                            | Reality                                                                                                            |
| ------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------ |
| "The sub-PRs all passed CI, the integration PR will too"           | Per-sub-PR CI runs against the sub-branch, not the feature branch. The integration is new state.                   |
| "The spec is old, no point checking against it"                    | Spec is the durable ADR. If it's stale, fix the spec — don't ignore it.                                            |
| "Acceptance criteria mismatch is fine, the spirit is the same"     | Acceptance criteria are checkable conditions. Either they're met or they're not. Update the issue if the criterion changed. |
| "I'll skip the state-file walk, I've been keeping it current"      | The resumed-session contract is what the state file SAYS — verify it; don't trust your memory.                     |
| "Lint passed in my sub-worktree, no need to re-run on feature"      | Lint can be scoped to changed files; project-wide issues only surface on the integrated branch.                    |
| "Contracts, criteria, and CI are all green — all clean"             | Those never see cross-PR coherence. Run the Step 3 sweep before declaring clean.                                   |
| "Everyone agreed to drop it verbally, I'll just trim the body"      | A verbal agreement isn't the durable record; the issue is. A de-scoped criterion gets a decision comment + commit link, then the body edit (`feature-dev-workflow:writing-github-issues` Step 2D). |
| "The issues and PRs were reconciled at each decision, no need to re-read them" | Per-decision reconciliation covers the surface where the decision was made; the Step 5 sweep exists for the surfaces it missed. Re-read every body against the final shape — the stale diagram or claim hides exactly where you didn't look. |
