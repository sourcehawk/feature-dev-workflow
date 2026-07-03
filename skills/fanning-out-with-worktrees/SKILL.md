---
name: fanning-out-with-worktrees
description:
  Use when an orchestrator needs to dispatch parallel subagents into
  per-PR worktrees off a feature branch — typically invoked from
  developing-a-feature for multi-PR features.
---

# fanning-out-with-worktrees

## When to invoke

When you're the orchestrator for multi-PR feature work and these prerequisites are met:

- The `feature/<slug>` integration branch and the main feature worktree exist (set up by `feature-dev-workflow:developing-a-feature` before invoking this skill).
- The plan (`docs/superpowers/plans/<date>-<slug>-plan.md`) has a `## Contracts` section with a Realization strategy per row.
- The plan also has a `## Conventions` block (directory layout, naming scheme, locked vocabulary) — it's mandatory dispatch context for every subagent (Step 2), so the fan-out can't start without it.
- The state file (`docs/superpowers/states/<date>-<slug>-state.md`) has rows for each sub-issue.

Skip for single-PR features — there's no fan-out, just one branch off main.

## Why this exists

Parallel fan-out compounds in complexity quickly: contract handoff, isolation, wave dependencies, propagation, state tracking, per-PR ripening. Wrapping the choreography in one skill keeps `feature-dev-workflow:developing-a-feature` focused on the single-vs-multi decision and the integration-PR endgame, and gives any future use case (parallel migration work, parallel refactor, cross-module sweep) a reusable orchestration entry point.

## Workflow

### 1. Plan the waves

Look at the plan's `## Contracts` table. Sub-PRs that are contract **producers** go in the FOUNDATIONAL wave; sub-PRs that are contract **consumers** go in subsequent waves, keyed by when their contract is realized:

- `data-only` and `pre-merge stub PR` realizations → consumers can start as soon as the producer's stub PR has merged into the feature branch (or the data-only contract is documented).
- `stub-on-producer-branch` → consumers branch from the producer's branch (not the feature branch); dispatch is timed to after the producer's PR is open with the stub in place.

Sub-PRs with no contract dependency → all in one wave.

Record the wave assignments in the state file's `## Phases` section before dispatching.

### 2. Create sub-worktrees and dispatch wave N

For each sub-PR in the wave, the orchestrator creates the worktree first:

```
git worktree add .claude/worktrees/<slug>--<sub-name> -b <sub-branch> <base-ref>
```

When the state file's frontmatter has `sub_pr_target: main`, `<base-ref>` is `origin/main` for every sub-PR in every wave (fetch `origin/main` first so wave N+1 picks up the commits that wave N merged). When `sub_pr_target` is `feature-branch` (the default), `<base-ref>` is `feature/<slug>` for default sub-PRs, `feature/<slug>` after the stub PR merged (for `pre-merge stub PR` consumers), or the producer's branch (for `stub-on-producer-branch` consumers).

Then dispatch one subagent per sub-PR. **REQUIRED SUB-SKILL:** `superpowers:dispatching-parallel-agents`.

Each dispatch prompt MUST include:

1. **Isolation verification as the first action.** `cd <worktree-path> && pwd && git branch --show-current` — the subagent confirms it's on the sub-branch in the right worktree before any edit. Commits land on the wrong branch otherwise.
2. **Context handoff.** State file path, plan path, spec path, the issue number it's working, the relevant contract row(s) (Name + Producer + Consumer + Shape + Realization), **and the plan's `## Conventions` block**. The subagent implements **against the contract and the conventions** — it does not re-discover or re-design either, and it does not invent its own directory layout or naming scheme. A subagent handed contracts but not conventions will name and structure locally, and the merged feature reads as written by a committee (see `feature-dev-workflow:maintaining-architectural-coherence`).
3. **Implementation skills.** `superpowers:test-driven-development` + `feature-dev-workflow:testing-a-feature` for every change.
4. **PR completion.** When the implementation is done and verified, the subagent invokes `feature-dev-workflow:opening-a-pull-request`. The base and body keyword depend on `sub_pr_target` in the state file: when `feature-branch`, use `--base feature/<slug>` and `Towards #<sub-issue>` in the body (`Fixes`/`Closes` don't fire on non-default-branch merges; `Towards` keeps the issue open until the orchestrator closes it manually after the merge); when `main`, use `--base main` and the type-appropriate closing keyword in the body — `Fixes #<sub-issue>` for a bug sub-issue, `Closes #<sub-issue>` otherwise; either fires automatically on merge to the default branch (see `feature-dev-workflow:opening-a-pull-request` for the distinction). Epic closure in main mode is not handled by sub-PR keywords — the orchestrator closes the epic manually in Step 7. The subagent reports the PR URL back to the orchestrator.

### 3. Update the state file as subagents start work

As each subagent surfaces its worktree path and branch, the orchestrator fills in the row in the state file's `## PRs / worktrees` table. When a subagent opens its draft PR, the orchestrator fills in the PR column with the base ref (`#<num> → feature/<slug>` or `#<num> → main`, per the `sub_pr_target` setting) and flips status to `draft`.

A stale row is worse than no row — a resumed session reads the state file as ground truth.

### 4. Watch loop

While subagents run, the orchestrator is the integration point — not an idle waiter. Watch for concerns that bubble up from any subagent and propagate the resolution across every subagent the concern touches. Silent divergence is the failure mode this watch loop exists to prevent.

Categories of concerns to watch for:

- **Contract drift.** A row in the `## Contracts` table needs to shift (reviewer feedback, an edge case the producer hit). Pause every affected consumer, update the plan's row, propagate.
- **Naming / layout divergence.** A subagent introduces a path, package, file-naming scheme, identifier pattern, or fixture name that doesn't match the `## Conventions` block or what a sibling PR already shipped. Reconcile before the merge — pick the convention (update the block if the new choice is better), and propagate to every subagent on the divergent pattern. Naming drift is invisible to contract checks; catching it here is far cheaper than at the integration PR.
- **Spec ambiguity surfaced mid-implementation.** A subagent hits a case the spec didn't cover. Surface to the user, get a decision, amend the spec (or add a note to the plan), and propagate to every subagent whose scope touches the same surface.
- **Discovered cross-PR dependency.** A subagent finds it needs a helper, type, or behaviour from another PR that the plan didn't enumerate. Decide whether the helper becomes a new contract (file an issue, add a contract row), inlines into the current PR, or is something one of the other subagents is already producing.
- **Test failure in shared infrastructure.** One subagent breaks a test that another subagent's PR relies on. Coordinate the fix into the right PR; don't let both subagents fix it independently.
- **External dependency change.** A dependency version bump, a library update, an API shift — affects every running subagent.
- **Resource conflict.** Two subagents both editing the same file or symbol. Re-scope one to avoid the collision, or serialize the work.

How to propagate the resolution:

- **Subagent still running** → `SendMessage` with the subagent's id to push the resolution with full context. The subagent resumes with the update applied.
- **Subagent finished, PR still open** → re-dispatch a focused follow-up with the PR number and the specific change.
- **Subagent not yet dispatched (later wave)** → update its dispatch prompt's context block before launching.

Append a dated entry to the state file's `## Bubble-up log` (newest at top) naming the concern, the resolution, and the propagation path used. The orchestrator owns propagation; a concern raised by one subagent and not propagated to the others is how this whole pattern fails.

### 5. Per-sub-PR ripening — all orchestrator-driven

When a sub-PR is ready (subagent reports `ready` and the relevant verification commands pass), the **orchestrator** takes over for the rest of the lifecycle. Every action below — review, merge, sub-issue close, state-file update — is the orchestrator's, not the worktree subagent's. Three reasons this is the right division of labour:

- **Review independence.** The subagent that wrote the code is the wrong reviewer for the same code; the orchestrator's distance from the implementation is the whole point.
- **Global view.** Only the orchestrator holds the merge-order context (which contract rows are `locked`, which sibling PRs are still in flight, which wave we're in). A subagent merging on its own would commit to ordering it can't see.
- **Worktree topology.** Subagents live in their per-sub-PR worktrees; only the orchestrator's main feature worktree has `feature/<slug>` checked out, so the merge naturally happens on the orchestrator's side.

Per sub-PR, in order:

1. **Automated review-loop, if the state file's `sub_pr_review_loop` is `on`.** **OPTIONAL SUB-SKILL:** `feature-dev-workflow:copilot-review-loop` against the sub-PR number, in fan-out mode — it requests the automated (Copilot) review, waits for it in the background, and drives the PR to review-clean. In fan-out mode a comment the loop wants to push back on does **not** pause the fan-out: log it as a bubble-up concern in the `## Bubble-up log` (surfaced at the wave checkpoint by `feature-dev-workflow:reviewing-feature-progress`) and continue. Skip this step when `sub_pr_review_loop` is `off` or missing. It runs before the orchestrator's own review so the diff reviewed below is the post-automated-review diff that will actually merge.
2. **Two-stage review — spec-compliance first, then code quality.** Both stages are the `review` skill, run against the sub-PR number with full PR context, scoped differently. This review is weaker than external review (which lands at the integration PR) but stronger than nothing; it catches issues that would otherwise pile onto the integration PR reviewer. The order is a gate, not a preference: a PR that doesn't yet implement its sub-issue is going back regardless, so quality findings on code about to change are wasted effort and noise. One blended "looks good" pass is the failure this split exists to prevent.
   1. **Spec-compliance pass (the gate).** **REQUIRED SUB-SKILL:** the `review` skill, scoped to *intent*: walk the sub-issue's acceptance criteria one by one and map each to real code in the diff **and** a test that exercises it. Confirm nothing is missing and nothing extra was built — unrequested scope is a finding, not a bonus (it may collide with a sibling PR or belong elsewhere). This pass must come back clean before the quality pass starts.
   2. **Code-quality pass.** **REQUIRED SUB-SKILL:** the `review` skill, scoped to *craft*: bugs the criteria didn't name, edge cases, error handling, test quality, simplification/reuse. Beyond bugs, check the diff against the `## Conventions` block — does its layout, naming, and vocabulary match the block and the sibling PRs already merged? A convention violation caught here is one the integration reviewer never sees.
   - **Fix-loop.** When either pass returns findings, the orchestrator does **not** fix them in place — it routes them back to the worktree subagent via `SendMessage` (the author has the context, and silent orchestrator fixes rob the parallel agents of shared understanding), then re-runs the *same* pass against the changed surface. Spec-compliance findings re-run the spec pass; only once it is clean does the quality pass run. Repeat until both passes are clean. The worktree subagent fixes; the orchestrator reviews — never the reverse.
3. **Approval gate, per the state file's `sub_pr_approval` mode.** Every gate covers the **bundle**: merge + sub-issue close + state-file update. The close is bodyless (no `--comment` flag) — GitHub automatically cross-references the sub-issue from the merge commit via the sub-PR's body keyword, so no custom comment is needed and there's no "specific body about to land" for the close mutation.
   - **`autonomous`** (default) — proceed straight through the bundle in steps 4-6. The user opted into the mechanical bundle (review → merge → bodyless close → state update) in `feature-dev-workflow:developing-a-feature` Step 2.
   - **`manual`** — pause and ask the user for explicit approval before the bundle. The prompt MUST surface: a one-line summary of the review findings ("review clean" / "<N> findings, none blocking" / specific concerns), the PR's title and diff size, and a note that closing sub-issue `#<sub-issue>` follows the merge. Wait for an explicit yes. On push-back, route the concern back to the worktree subagent via `SendMessage` instead of merging.
4. **Merge.** Run `gh pr merge <num> --merge` (or `--squash` / `--rebase` per project preference). Before merging, push any local state-file commits to their remote — for `feature-branch` that is `origin/feature/<slug>`; for `main` that is `origin/feature/<slug>` as well (the orchestrator stays on the feature branch for state management). The merge itself lands on GitHub's remote, and the pull-back differs by target:
   - **`sub_pr_target: feature-branch`**: after the merge, `git -C <feature_worktree> fetch origin && git merge --ff-only origin/feature/<slug>` to bring the merge commit back into the feature worktree. Keep local == origin at every merge boundary (unpushed local commits cause a "Not possible to fast-forward" failure; recover with `git rebase origin/feature/<slug>`).
   - **`sub_pr_target: main`**: the merge lands on `main`. The orchestrator remains on `feature/<slug>` for state file management; no pull-back into the feature worktree is needed. Before dispatching wave N+1, run `git fetch origin` so the next wave's worktrees branch from the freshly updated `origin/main`.
5. **Close the sub-issue.**
   - **`sub_pr_target: feature-branch`**: `gh issue close <sub-issue>`. Sub-PRs into a non-default branch don't trigger `Fixes`/`Closes` — manual close is the workaround. The body's `Towards #<sub-issue>` keyword left the issue open precisely so the orchestrator can close it here; the cross-reference from the merge commit (which references `#<sub-pr>`, which references `#<sub-issue>`) is preserved automatically without a custom comment.
   - **`sub_pr_target: main`**: no manual close needed. The closing keyword in the PR body (`Fixes`/`Closes`) fires on merge to the default branch and auto-closes the sub-issue. Confirm it closed before marking the state-file row `self-merged`.
6. **Update the state file.** Flip the row's status to `self-merged`. If the sub-PR was the realization of a contract (e.g. a pre-merge stub PR), flip the contract row's status to `locked` and fill in the `Realized in` pointer.

### 6. Checkpoint review, then dispatch wave N+1

When every sub-PR in wave N is `self-merged` AND every contract tied to wave N's producers is `locked`:

1. **REQUIRED SUB-SKILL:** `feature-dev-workflow:reviewing-feature-progress` — run the alignment checkpoint at the wave boundary. Drift accumulated across wave N is cheapest to fix here, not at the integration PR. If the checkpoint surfaces gaps, address them (follow-up sub-PR in wave N, plan/issue refinement, or both) before moving on.
2. Once the checkpoint is clean, dispatch wave N+1. Wave N+1's subagents pick up the realized contracts because the orchestrator updated the state file's `## Contracts` table.

Repeat Steps 2 → 6 for each wave.

### 7. All waves complete → hand back

When every wave is complete (every sub-issue closed, every row `self-merged`, every contract `locked`), update the state file's frontmatter `status:` to `review` and return control to `feature-dev-workflow:developing-a-feature`.
- **`sub_pr_target: feature-branch`**: the next step is the integration PR (`feature/<slug>` → `main` with `Closes #<epic>`), which `feature-dev-workflow:developing-a-feature` Step 6 owns — opening and review-looping only; the merge to main itself is the user's (see that skill's merge guard).
- **`sub_pr_target: main`**: the sub-PRs were already the deliverables to main; there is no integration PR. `feature-dev-workflow:developing-a-feature` passes through Step 6 (verification only — no PR to open) and proceeds to Step 7 (teardown). Close the epic manually with `gh issue close <epic>` before handing back — sub-PR closing keywords (`Fixes`/`Closes`) only close sub-issues, so the epic does not auto-close.

## Anti-patterns

- **Dispatching parallel agents without contracts.** "Two subagents on these two PRs" with no contract = divergent implementations that block at integration. If the plan didn't define a contract, don't dispatch — go back to `feature-dev-workflow:planning-a-feature` Step 6 and add one.
- **Dispatching without the conventions block.** Contracts make the work compile; conventions make it cohere. Hand a subagent contracts but no `## Conventions` and it invents its own layout and names — the drift surfaces at the integration PR when it's expensive. If the plan has no conventions block, go back to `planning-a-feature` Step 6.
- **Skipping wave dependencies.** Consumers dispatched before producers' contracts are realized produce code against an imagined shape. Dispatch wave N+1 only after wave N is fully self-merged and contracts locked.
- **Self-merging without orchestrator review.** The integration PR is where external review lands, but sub-PRs still need a review pass before going into the feature branch. Skipping it dumps issues onto the integration PR reviewer.
- **Collapsing the two stages into one "looks good" pass.** Spec-compliance and code-quality answer different questions — "does it do the job" vs "is it well-built". Reviewing them together lets a momentum-driven skim pass a PR that quietly misses an acceptance criterion or builds unrequested scope. Run the spec gate to clean first, then quality.
- **Quality-reviewing before spec-compliance is clean.** Polishing code that's about to change because it doesn't meet the spec wastes the pass and buries the real finding in nits. The spec pass is a gate; the quality pass waits behind it.
- **Orchestrator fixing review findings in place.** The worktree subagent wrote the code and holds the context; it fixes, then the orchestrator re-reviews. A silent orchestrator fix skips the author and erodes the shared understanding the parallel agents run on.
- **Letting the worktree subagent review its own PR.** A subagent reviewing the code it just wrote has the same blind spots in review that it had in implementation. The orchestrator owns sub-PR review precisely because it didn't write the code.
- **Letting a bubble-up concern die in one subagent.** Propagation is the whole point of the watch loop.
- **Forgetting to manually close the sub-issue when `sub_pr_target: feature-branch`.** The keyword doesn't fire on non-default-branch merges; the issue page silently shows "open" even though the work shipped.
- **Using `Towards #<sub-issue>` when `sub_pr_target: main`.** `Closes` fires on merge to the default branch; `Towards` intentionally blocks auto-close. Using the wrong keyword silently leaves sub-issues open after they merge to main and forces a manual cleanup pass.
- **Letting the state file go stale.** A resumed session reads it as ground truth. Update every row as reality moves; commit **and push** the state-file diff per phase transition — an unpushed local commit diverges the feature branch the moment the next sub-PR squash-merges on GitHub (see Step 5.4).

## Red flags

| Thought                                                              | Reality                                                                                                |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| "The plan says parallel but I don't see contracts — I'll just guess" | Plan is incomplete. Stop and define the contract, or sequence the work.                                |
| "I'll dispatch wave 2 now, wave 1 is almost done"                    | Almost-done producers haven't `locked` their contract rows. Wave 2 will diverge. Wait.                 |
| "The subagent will figure out the worktree on its own"               | Create the worktree yourself and embed `cd <path> && pwd && git branch --show-current` in the dispatch. |
| "Self-review feels redundant, the integration PR catches everything" | Integration PR reviewer can't catch every issue across 5 sub-PRs in one sitting. Catch them per PR.    |
| "The subagent already verified the diff, no need for the orchestrator to review again" | Verification (tests pass) is not review (does the diff express intent cleanly). Different signals. |
| "Tests pass and the diff looks clean — one review pass is enough" | Spec-compliance and quality are different questions. The spec gate runs to clean first, then quality; one blended pass skims past a missed acceptance criterion. |
| "The spec pass found a gap but I'll quality-review now to save a round-trip" | Quality findings on code about to change are noise. Send the gap back, re-run the spec pass to clean, then quality. |
| "Both sub-PRs pass CI, so the naming difference between them is fine" | Contract checks don't see naming. Two schemes for one kind of thing is drift — reconcile it at the wave, not the integration PR. |
| "I'll close the sub-issue once the integration PR merges"            | Issues that read "open" while their work has shipped clutter the triage view. Close manually at self-merge (feature-branch mode) or confirm auto-close fired (main mode). |
| "`Towards` is always the safe keyword for sub-PRs"                  | `Towards` intentionally blocks auto-close. In `sub_pr_target: main` mode use `Closes` — it fires on merge to the default branch and removes the manual close step. |
