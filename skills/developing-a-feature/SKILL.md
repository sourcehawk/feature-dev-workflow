---
name: developing-a-feature
description:
  Use when starting implementation against a written plan and the
  tracking issue(s) from planning-a-feature, or when handed a plan
  by someone else.
---

# developing-a-feature

## When to invoke

When the plan from `feature-dev-workflow:planning-a-feature` (or equivalent) is committed and you're about to start writing code. Skip for ad-hoc fixes — those go directly through `superpowers:test-driven-development` and `feature-dev-workflow:opening-a-pull-request`.

## Workflow

### 1. Read the state file first, then plan + spec

The orchestration state file (`docs/superpowers/states/<date>-<slug>-state.md`, created by `feature-dev-workflow:planning-a-feature` Step 8) is the entry point — it points at the plan, the spec, the tracking issue, the open PRs, the worktrees, and any bubble-up concerns logged so far. Read it in full before anything else; follow the file's "Resume checklist" section to verify reality against the recorded state.

Then open the plan and spec it references. Note:

- The PR breakdown (one PR or multiple).
- The contract table in the plan's `## Contracts` section (if any).
- The dependency ordering — what must land first.
- Each contract's Realization strategy (pre-merge stub PR / stub-on-producer-branch / data-only).

If the plan is missing, stale, or the state file's recorded state doesn't match reality (a PR's actual status has drifted from the row), STOP and reconcile — re-invoke `feature-dev-workflow:planning-a-feature` Step 7 if the plan needs to change, or update the state file's rows to match reality before continuing.

### 2. Decide: single-PR or multi-PR (feature-branch model)

- **Single PR** → one worktree on the `feature/<slug>` branch `feature-dev-workflow:planning-a-feature` created, one Claude session, one PR from it targeting main. Skip the integration-PR step at the end.
- **Multi-PR** → feature-branch model:
  - `feature-dev-workflow:planning-a-feature` already created `feature/<slug>` (off `origin/main`) and committed the spec + plan + state file onto it. The orchestrator **reuses** that branch — it does not re-create it — attaching the integration worktree at `.claude/worktrees/<slug>` (recorded as `feature_branch` + `feature_worktree` in the state file's frontmatter).
  - Every sub-PR is a real GitHub PR targeting `feature/<slug>`, not main. Each sub-worktree is created off the feature branch with `git worktree add .claude/worktrees/<slug>--<sub-name> -b <sub-branch> feature/<slug>` (raw git is the simplest path here; `EnterWorktree` defaults to branching from origin/main).
  - When a sub-PR is ready, the orchestrator runs a self-review pass, then **self-merges** the sub-PR into `feature/<slug>`. The dispatching agent owns this merge — sub-agents don't merge their own PRs.
  - Sub-issue closure: `Fixes #<sub-issue>` / `Closes #<sub-issue>` only auto-fires on merge to the **default branch**. Sub-PRs into the feature branch therefore use `Towards #<sub-issue>` (the explicit "keep this issue open" keyword); the orchestrator runs `gh issue close <sub-issue>` after each self-merge.
  - When every sub-PR has been self-merged into the feature branch, the orchestrator opens the **integration PR** `feature/<slug>` → `main`, with `Closes #<epic>` in its body, for external review and the final merge.

For sequential single-PR work, skip to Step 4. For multi-PR work, dispatch parallel subagents in Step 3 — but first, ask the user how sub-PR approval should work.

**Sub-PR approval mode (multi-PR only).** Before any sub-worktree work starts, the orchestrator presents the user with a two-option choice via `AskUserQuestion`:

- **Autonomous sub-worktree approval** — the orchestrator reviews each sub-PR with the `review` skill, self-merges it into the feature branch, and closes its sub-issue automatically. Fastest fan-out; the user only sees the integration PR at the end. Suitable when the integration PR's external-review pass is the user's intended inspection point.
- **Manual sub-worktree approval** — the orchestrator still runs the `review` skill on each sub-PR, but then pauses to ask the user for explicit approval before `gh pr merge` runs. One round-trip per sub-PR, but the user inspects every diff before it lands on the feature branch.

Record the choice in the state file's frontmatter as `sub_pr_approval: autonomous` or `sub_pr_approval: manual`. The fan-out skill reads this field at every sub-PR ripening to decide whether to gate on user approval. Default if the field is missing in an older state file: `autonomous` (preserves the original behaviour).

**Sub-PR review-loop (multi-PR only).** Immediately after the approval-mode choice, ask a second `AskUserQuestion`: should each sub-PR run an automated review-loop and come back clean before it is self-merged? This is opt-in and independent of the approval mode.

- **On** — at each sub-PR's ripening, the orchestrator runs `feature-dev-workflow:review-loop` against the open sub-PR before the existing `review`-skill pass and self-merge. A comment the loop wants to push back on does not pause the fan-out; it is logged as a bubble-up concern and surfaced at the wave checkpoint.
- **Off** (default) — ripening is unchanged.

Record the choice as `sub_pr_review_loop: on` or `sub_pr_review_loop: off`. The fan-out skill reads it at every ripening. Default if the field is missing in an older state file: `off` (preserves the original behaviour).

### 3. Set up the implementation environment

- **Multi-PR (feature-branch model)** — `feature/<slug>` already exists, created and pushed by `feature-dev-workflow:planning-a-feature` and carrying the committed spec/plan/state. **Reuse it; never re-create it** off `origin/main` — that errors (`fatal: a branch named 'feature/<slug>' already exists`) and would orphan the planning artifacts. If planning already made the integration worktree at `.claude/worktrees/<slug>`, just `cd` into it. Otherwise attach one to the existing branch:

  ```
  git fetch origin
  git switch main                                       # vacate feature/<slug> if planning left you on it
  git worktree add .claude/worktrees/<slug> feature/<slug>
  cd .claude/worktrees/<slug>
  ```

(Fallback only if planning was skipped and `feature/<slug>` exists nowhere: `git worktree add .claude/worktrees/<slug> -b feature/<slug> origin/main && git -C .claude/worktrees/<slug> push -u origin feature/<slug>`.) Update the state file's `feature_branch` + `feature_worktree` frontmatter fields to point here. Sub-worktrees off this branch are created later by `feature-dev-workflow:fanning-out-with-worktrees`.

- **Single-PR** — `feature-dev-workflow:planning-a-feature` created `feature/<slug>` and committed the planning artifacts onto it; this is the only branch, and the PR opens from it. Reuse it the same way — if planning made a worktree, `cd` in; otherwise attach one to the existing branch:

  ```
  git fetch origin
  git switch main                                       # vacate feature/<slug> if planning left you on it
  git worktree add .claude/worktrees/<slug> feature/<slug>
  cd .claude/worktrees/<slug>
  ```

(Fallback if planning was skipped: `git worktree add .claude/worktrees/<slug> -b feature/<slug> origin/main`.) Skip the integration-PR step at the end; this is the only PR.

### 4. Implement

- **Multi-PR** — **REQUIRED SUB-SKILL:** `feature-dev-workflow:fanning-out-with-worktrees`. The skill owns parallel dispatch, multi-wave ordering, the orchestrator watch loop, per-sub-PR review (via the `review` skill, orchestrator-driven — the worktree subagent does not review its own PR), self-merge into the feature branch, manual sub-issue close, and state-file maintenance. Returns control here when every sub-PR is self-merged and every contract is `locked`.

- **Single-PR** — the build mode depends on the plan's task shape. Read the committed plan's task list and count the tasks that are **independent** (no task depends on another's output — they could, in principle, be built in any order). The integration task that ties them together does not count toward independence; it consumes the others.

  - **2+ independent tasks → drive the build task-by-task with review between tasks.** **REQUIRED SUB-SKILL:** `superpowers:subagent-driven-development`. The orchestrator (this session — the main loop, which *can* dispatch subagents) runs that skill's loop engine: a fresh implementer subagent per task with full task text handed in, then review, fix-loop, and continuous execution across all tasks. Two adaptations keep it consistent with the rest of this plugin:
    - **Per-task review is the `review` skill** (the same mechanism `feature-dev-workflow:fanning-out-with-worktrees` uses for sub-PRs), run by the orchestrator — not the implementer subagent that wrote the task. Run it as two scoped passes, spec-compliance first as a gate, then code quality; route findings back to the implementer and re-run until clean.
    - Each implementer subagent uses **`superpowers:test-driven-development`** + **`feature-dev-workflow:testing-a-feature`** for its task, exactly as the direct path below.

    Why conditional: SDD's premise is independent tasks. Below that threshold the dispatch overhead and context hand-off cost more than they return, so the direct path is correct. This is the in-session analogue of the multi-PR fan-out — same "author and reviewer are different contexts" discipline, one PR instead of many.

  - **Fewer than 2 independent tasks (one cohesive change, or a strictly sequential chain) → the orchestrator implements directly in the worktree from Step 3:**
    - **REQUIRED SUB-SKILL:** `superpowers:test-driven-development` for every code change.
    - **REQUIRED SUB-SKILL:** `feature-dev-workflow:testing-a-feature` for the assertion shape — black-box against the contract, not implementation.

  Either way: commits follow CLAUDE.md conventions (`<type>(<area>): <imperative summary> (#<feature-issue>)`), and you run the project's test and lint commands (and typecheck, if it has one) before claiming work is done. Discover them from the project's CLAUDE.md / AGENTS.md or its build config (Makefile, package.json, etc.).

### 5. Checkpoint review before opening the final PR

- **Single-PR feature** → the implementation is now structurally complete, so this is the point to add whole-flow coverage. If the change introduced a new user- or consumer-visible flow, write the end-to-end coverage now — **REQUIRED SUB-SKILL:** `feature-dev-workflow:testing-end-to-end` for which flows earn one and what each asserts. The behavior is settled now, so this is also the point to write or update the public-facing docs the change touches — **REQUIRED SUB-SKILL:** `feature-dev-workflow:writing-docs` for what earns a doc and how to verify a reader can actually use it. Then **REQUIRED SUB-SKILL:** `superpowers:verification-before-completion`. Run the project's test, lint, and (if it has one) typecheck commands. Paste the output. Forbids claiming "done" without evidence.
- **Multi-PR feature** → **REQUIRED SUB-SKILL:** `feature-dev-workflow:reviewing-feature-progress`. The orchestrator's checkpoint skill re-reads spec + plan + state, walks every self-merged sub-PR against acceptance criteria, checks state-file integrity, and runs end-to-end verification on the main feature worktree (the feature branch as a whole, not just per-sub-PR CI). Catches drift and integration-only failures before the external-review surface opens. If the checkpoint finds gaps, route back through `feature-dev-workflow:developing-a-feature` Step 4 (follow-up sub-PR) or `feature-dev-workflow:planning-a-feature` Steps 6/7 (plan/issue refinement) before continuing.

### 6. Open the PR

**REQUIRED SUB-SKILL:** `feature-dev-workflow:opening-a-pull-request`. Base + body keyword depend on which model is in play:

- **Single-PR feature** → PR targets `main` from `feature/<slug>`. Body opens with `Fixes #<feature-issue>` (bug) or `Closes #<feature-issue>` (feature/task) so the issue auto-closes on merge.
- **Multi-PR integration PR** → PR targets `main` from `feature/<slug>` (`gh pr create --base main --head feature/<slug>`). Body opens with `Closes #<epic>` so the epic auto-closes on merge. This is the PR external reviewers see; the diff is the whole feature.

Sub-PRs into the feature branch are owned by `feature-dev-workflow:fanning-out-with-worktrees`, not this step.

Once the PR to main is open — the single-PR PR, or the multi-PR integration PR — ask the user (via `AskUserQuestion`) whether to run an automated review-loop on it before handing off for external human review. If yes, **OPTIONAL SUB-SKILL:** `feature-dev-workflow:review-loop` against this PR; it drives the PR's automated (Copilot) review to clean. This is the interactive context, so a comment the loop wants to push back on pauses for the user. If no, hand off as-is.

Run the loop on the **final** PR diff. The Step 7 teardown is the last commit on the branch, so a review run before it goes stale against what external reviewers actually see. If the teardown will land after a clean review, defer the loop until after the teardown commit (or re-run it afterward) — and when CI gates the teardown, that means running the loop once the teardown commit is pushed and green, not at PR-open.

### 7. Tear down the planning artifacts

Delete the plan + state file once the work is genuinely done. The spec stays — it's the durable ADR. The plan and state file are scratch; leaving them committed past readiness pollutes the repo with stale operational state that future `grep`s have to wade through.

**The teardown is the last commit on the feature branch; what gates it depends on whether the repo runs CI on the integration PR.** Settle that first by inspecting the repo's CI configuration — is a pipeline wired to run on this PR's branch? Decide from the configuration, not from a momentary `gh pr checks` reading: zero checks *reported* can mean either "no CI exists" or "CI hasn't registered yet," and you can't tell those apart by polling.

**CI is configured to run on the PR →** do NOT tear down until its checks are green. The state file is the resume contract for exactly the case where CI comes back red and you have to fix forward — tear it down before CI confirms and a failed run leaves you fixing forward with no recorded state. Push the teardown only after the checks pass — never as the commit *before opening* the PR, and never on "local green" or "flipped ready" alone (those are not the CI gate).

**No CI is configured to run on the PR →** the full local suite you already pasted via `superpowers:verification-before-completion` is the gate, so proceed. Nothing async can come back red, so there is no resume contract to protect and nothing to wait for — polling for checks the configuration shows will never appear only stalls the workflow.

Single-PR features follow the same two branches. Until you tear down, keep updating the state file as reality moves.

## Anti-patterns

- **Mixing single-PR and multi-PR flows mid-feature.** Once the plan declares multi-PR, the feature-branch model is on. Don't quietly merge "just this small fix" directly to main while the feature branch is live — it skips external review on the integration PR and forks the work.
- **Skipping `verification-before-completion` because "tests passed in my package".** The full test suite runs the whole project because cross-package wiring breaks on edits that look local.
- **Letting the state file drift from reality.** A resumed session reads the state file as ground truth. Update it on every transition (worktree assigned, PR opened, sub-PR self-merged, phase changed, feature shipped).
- **Re-implementing fan-out logic inline.** Parallel dispatch, multi-wave ordering, the watch loop, per-sub-PR self-review and self-merge — all of that is in `feature-dev-workflow:fanning-out-with-worktrees`. Don't paste it into the dispatch prompt or the developing-a-feature flow; reference the sub-skill instead.

## Red flags

| Thought                                                              | Reality                                                                                                |
| -------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| "I'll just open one big PR, the plan is overcomplicating this"       | The PR-shape decision happened during planning. Reopening it here means re-running `feature-dev-workflow:planning-a-feature` Step 4, not skipping the model. |
| "Tests pass, I'll skip lint"                                         | Lint is a CI gate. Running it locally is the cheapest place to catch the failure.                      |
| "The state file is for the planner, I don't need to update it during dev" | The state file is the resume contract. Every transition is your responsibility while dev is in flight. |
| "I'll open the integration PR before the last sub-PR is self-merged" | The integration PR's diff is supposed to be the whole feature. An in-flight sub-PR means the integration PR will be re-pushed mid-review. Wait. |
| "I'll create `feature/<slug>` off `origin/main` in step 3"           | Planning already created it and committed the spec/plan/state onto it. `-b feature/<slug>` errors ("already exists") and re-creating off `origin/main` orphans the planning artifacts. Reuse the existing branch; attach a worktree to it. |
| "Tests pass locally and the PR is ready, so I'll tear down plan/state now" | When CI runs on the PR, local green and "ready" aren't the gate — if it comes back red you fix forward, with no state file if you deleted it. Tear down on the PR's checks going green. (Repo has no CI configured for this branch? Then the local suite *is* the gate — proceed.) |
| "`gh pr checks` reports no checks, so I'll keep polling until CI shows up" | Zero checks reported isn't the same as CI pending. Inspect the repo's CI configuration: if no pipeline runs on this branch, none will ever appear and polling just stalls the workflow. Proceed on the local suite you already pasted. |
| "It's one PR, I'll just implement all the tasks myself in this session" | If the plan has 2+ independent tasks, that skips per-task review — the author and reviewer are the same context, so the bug that slipped into task 1 survives into the PR. Count the independent tasks; at 2+ drive it through `superpowers:subagent-driven-development`. |
| "The tasks are independent, so I'll knock them out back-to-back myself" | Independence is the signal *for* task-by-task dispatch with review between, not against it — it's exactly when SDD pays off. Direct implementation is for one cohesive change or a strictly sequential chain. |
