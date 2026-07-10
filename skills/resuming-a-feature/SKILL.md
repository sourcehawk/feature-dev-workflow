---
name: resuming-a-feature
description:
  Use when a session starts with a request to resume, continue, or
  pick up in-flight feature work recorded in an orchestration state
  file (docs/superpowers/states/), or when handed a state-file path.
---

# resuming-a-feature

## When to invoke

First action of a fresh session when the user asks to resume, continue, or pick up a planned feature — at any phase: mid-development, mid-review, merge staging, or wrap-up. Skip when no state file exists; there is nothing to resume, so ask what the work is or enter `feature-dev-workflow:planning-a-feature`.

## Why this exists

The state file is the resume contract, but a cold session that only knows "read the state file" still has to derive the rest: which recorded facts to trust versus re-verify, which skill owns each remaining action, and how to re-enter at a phase the development skills' triggers don't name (a feature past active development matches no skill description). Left underivable, the user compensates with a hand-written resume prompt reconstructing what the state file already records. This skill is the protocol; the state file's `## Pending snapshot` section is its input.

## Workflow

### 1. Locate the state file

A user-provided path wins. Otherwise search every checkout — state files live on feature branches, so the main checkout usually has none: `ls docs/superpowers/states/` in the current directory, then in each worktree listed by `git worktree list`. Multiple candidates → ask which feature.

### 2. Read it in full, then the plan and spec

Everything: frontmatter (`status`, the `sub_pr_*` configuration, branch/worktree/artifact paths), `## Phases`, the `## PRs / worktrees` table, `## Contracts`, `## Bubble-up log`, `## Pending snapshot`, the resume checklist. Then the plan and spec at the recorded paths (they may already be torn down late in the lifecycle; that is normal, not drift).

### 3. Verify before trusting

The state file is authoritative for intent, decisions, pointers, and recorded user configuration; live git/GitHub/filesystem are authoritative for every mutable fact. On disagreement, reality wins — reconcile the state file first (commit and push it) before proposing any mutation.

| Trust from the file | Verify against live sources |
| ------------------- | --------------------------- |
| Plan/spec paths, slug, issue and PR numbers, branch names, worktree paths | Each PR's actual state: `gh pr view <num> --json state,isDraft,baseRefName,headRefOid,mergedAt` vs the recorded row |
| `sub_pr_approval` / `sub_pr_review_loop` / `sub_pr_target` — explicit user answers; don't re-ask | Each issue's open/closed state (`gh issue view <num> --json state`) |
| Bubble-up resolutions and their propagation records | Each worktree: exists, clean, no unpushed commits (`git -C <path> status --porcelain`; `git -C <path> log --oneline @{u}..`) |
| The `## Pending snapshot`'s intent and ordering | Branch existence (`git rev-parse --verify <branch>`), CI state (`gh pr checks <num>`) |

### 4. Treat the bubble-up log as settled

Its entries record adjudicated decisions with their why. A fresh session's fresh eyes are not new evidence — don't reopen or silently redo them. If one looks genuinely wrong, raise it with the user; never relitigate it unprompted.

### 5. Route by recorded phase

| `status:` | Re-enter |
| --------- | -------- |
| `planning` | `feature-dev-workflow:planning-a-feature`, at the step the snapshot names |
| `foundational-wave` / `consumer-wave` | `feature-dev-workflow:developing-a-feature` Step 4 → `feature-dev-workflow:fanning-out-with-worktrees`, continuing the recorded wave |
| `review` | The `## Pending snapshot`'s actions, each through the skill that owns it: retargets, body reconciliation, and ready-flips via `feature-dev-workflow:opening-a-pull-request`; pre-flip checkpoints via `feature-dev-workflow:reviewing-feature-progress`; issue closure and reconciliation via `feature-dev-workflow:writing-github-issues`; teardown via `feature-dev-workflow:developing-a-feature` Step 7 |
| `merged` | Remaining wrap-up items from the snapshot only (epic closure verification, worktree deletion after the unpushed-commit check, teardown) |

Resuming changes who is at the keyboard, not who holds the merge button: `feature-dev-workflow:developing-a-feature`'s merge guard still governs, and no `gh pr merge` runs beyond what `sub_pr_approval` / `sub_pr_target` already configured.

### 6. Report before mutating

One reconciled summary to the user: the feature, the phase, per-PR reality against the recorded rows, every divergence found and fixed, and the next actions from the snapshot. Then confirm the first mutation — resuming is not standing consent for the backlog.

## The Pending snapshot contract (producing side)

Resume quality is determined before a session ends, not after the next one starts. At the end of every work burst — and always when the user signals a pause or a session end — refresh the state file's `## Pending snapshot`: the ordered next actions, each carrying what, where, which skill owns it, and what gates it, with enough context that a cold session could execute from the file alone. If the user has to hand-write a resume prompt reconstructing the state, the snapshot failed its job.

## Red flags

| Thought | Reality |
| ------- | ------- |
| "The row says draft, so it's a draft" | Rows record the past; `gh pr view` is the present. Verify every mutable fact before acting on it. |
| "The user's resume prompt describes the state, that's enough" | Prompts go stale exactly like rows. Read the file, verify live, reconcile — then act. |
| "This bubble-up decision looks wrong, I'll redo it properly" | It records an adjudication with its why. Raise it with the user if genuinely suspect; don't silently reopen it. |
| "Development is done, so developing-a-feature doesn't apply anymore" | Its merge guard, state-file contract, and Step 7 teardown still govern. Route each remaining atom through the skill that owns it. |
| "I'll work through the snapshot, no need to check GitHub first" | The snapshot was true when written. A human may have merged, retargeted, or commented since. Verify, reconcile, then execute. |
