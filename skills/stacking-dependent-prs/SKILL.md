---
name: stacking-dependent-prs
description:
  Use when a PR's branch is based on another open PR's branch, such as a
  stub-on-producer-branch consumer or a sequential chain of PRs opened
  before their parents merge, or when creating, adopting, fixing, syncing,
  or merging a linear stack of dependent PRs with `gh stack`.
---

# stacking-dependent-prs

## When to invoke

A **stack** is a linear chain of open PRs where each PR's branch is based on the branch of the PR below it, so each diff shows only its own commits and the chain merges bottom first. A consumer branched from its producer's branch (`stub-on-producer-branch`) is a stack, and so is a strictly sequential run of sub-PRs opened before their parents merge. Parallel, independent sub-PRs in a fan-out wave are **not** a stack: each is based on the feature branch or `main` directly, and that model stays as it is. `gh stack` stacks are strictly linear (one parent, at most one child), so never force a wave into one.

Invoked from `feature-dev-workflow:fanning-out-with-worktrees` when it classifies a sub-PR as a stack layer, from `feature-dev-workflow:developing-a-feature` when a review fix lands in a stack, and from `feature-dev-workflow:resuming-a-feature` when a recorded stack must be verified or adopted.

The stack's mechanics (branch creation, PR bases, propagation, merges) go through GitHub's `gh stack` extension, never by hand. Hand-propagated stacks (manual `gh pr edit --base` retargets, per-layer merge-forward, `gh pr merge` on a layer) are how a layer ends up on a stale base or a child keeps the parent's pre-squash commits.

## Check availability first; ask, never install

Before creating, adopting, or changing a stack, run `gh stack --version` (or look for `github/gh-stack` in `gh extension list`). If it is missing, STOP and ask the user to install it with `gh extension install github/gh-stack`, and suggest the companion agent skill: `gh skill install github/gh-stack gh-stack --agent claude-code --scope user`. Do not install either yourself, and do not fall back to building the stack by hand while you wait. Then check that the repository has stacked PRs enabled: `gh api "repos/{owner}/{repo}/stacks?per_page=1" --silent`. A 404 (or exit code 9 from any `gh stack` command) means they are not enabled. STOP and ask the user to enable stacked PRs for the repository, with the same rule: no stack built by hand while you wait.

**Setup, once per repo:** `git config rerere.enabled true`, and `git config remote.pushDefault <remote>` when the repo has more than one remote.

## One dedicated worktree per stack

`gh stack` checks the stack's branches out in turn, and git refuses a branch that is checked out in another worktree, so a stack cannot be split into one worktree per layer. Give each stack its own worktree in the repo's usual worktree location (for example `git worktree add --detach .claude/worktrees/<slug>--stack origin/<trunk>`; detached, because the trunk is usually checked out elsewhere), and record it as the worktree path of every layer's row in the state file. When you create or adopt a stack, also add it to the state file's `## Stacks` section: its worktree, its trunk, and its layers bottom to top. A cold resume reads the stack's identity and order from there. Never drive a stack from the main checkout, and never switch branches in the user's working copy: `gh stack` moves `HEAD` between layers, and doing that anywhere the user or another session works blocks their development. The consequences:

- Work inside the stack's worktree happens one layer at a time.
- A layer that is still being built may live in a temporary worktree of its own while it is built in parallel (see §Parallel layers). That worktree is removed before the layer joins the stack.
- Separate stacks each get their own worktree.
- A stack that exists only as a link on GitHub (built with `gh stack link`, its branches managed elsewhere, or no local tracking) is adopted first: follow §Adopting a stack that was built by hand, in a dedicated worktree, before anything is propagated or merged through it. After that it is a local stack like any other. `gh stack link` itself is used only to join PRs opened with `gh pr create` (see §Opening the stack's PRs) and to correct a stale base.

## Parallel layers

Build layers in parallel where it is feasible, and join them to the stack afterwards. Feasibility is the orchestrator's call, made per layer:

- **Parallel** when the layer depends only on its parent's contract: an interface or shape that is already agreed and recorded (a `## Contracts` row, or a stub committed on the parent's branch as in `stub-on-producer-branch`).
- **Sequential** when the layer needs the parent's real behaviour to be written or tested, or when no contract for the parent is recorded. It waits until the parent is code-complete.

Record each layer's decision and its reason in the stack's `## Stacks` entry. A parallel layer's row carries its temporary worktree path while that worktree exists, and the stack's worktree after it joins. A parallel layer is built like this:

1. The orchestrator creates a temporary worktree for it on a new layer branch, `git worktree add .claude/worktrees/<slug>--<sub-name> -b <layer> <source>`, and dispatches its own subagent there. The source is the parent layer's current tip, or the parent's stub commit. The bottom layer's parent is the trunk, so its source is `origin/<trunk>`. When the parent's branch does not exist yet, the source is the nearest existing layer below it, or `origin/<trunk>` when no layer below exists. That subagent pushes its branch with plain `git push` and never runs `gh stack` commands; layers built inside the stack's worktree are pushed by the orchestrator's `gh stack push`.
2. When the layer is done and pushed, the orchestrator removes the temporary worktree.
3. In the stack's worktree, the orchestrator joins the layer on top. If the worktree already tracks the stack, it runs `gh stack unstack --local` first; for the first join there is no local stack yet, so it skips that. Then `gh stack init --base <trunk> <bottom> ... <new-top>` (`init` adopts branches that already exist), then `gh stack view --json` to confirm the order.
4. It replays the layer onto the parent's final tip: `gh stack checkout <parent>`, `gh stack rebase --upstack`, then `gh stack push`. A conflict at join time is resolved there, in the stack's worktree.
5. Once the layer has joined, it opens the layer's PR and links it as §Opening the stack's PRs says.

Two ordering rules hold throughout. Layers join bottom-up: a layer cannot join above a parent that has not joined yet. And never run `gh stack sync`, `gh stack rebase`, or `gh stack checkout` while any layer branch of the stack is checked out in another worktree (the trunk does not count); the orchestrator sequences joins and syncs so that never happens.

## Non-interactive invocations only

An agent has no TTY, and the bare forms of several commands open a prompt or a full-screen UI and block. Use these forms:

| Run | Never run |
| --- | --- |
| `gh stack view --json` | bare `gh stack view` |
| `gh stack init --base <trunk> <bottom> ... <top>` | bare `gh stack init` |
| `gh stack add <branch>` (from the top branch) | bare `gh stack add` |
| `gh pr create --draft ...` per layer, then `gh stack link --base <trunk> <bottom-PR-URL> ... <top-PR-URL>` | `gh stack submit` in any form to open PRs (it creates any missing PR with a generated title and body); `--open` on `link` or `submit` (it marks the PRs ready, and the user reviews drafts first) |
| `gh stack checkout <branch-or-pr>`, `gh stack up` / `down` / `top` / `bottom` | bare `gh stack checkout`, `gh stack switch` |
| `gh stack merge <pr> --yes --<method>` | `gh pr merge` on a layer; `gh stack modify` (UI only) |

`gh stack <command> --help` is authoritative for flags. The stack's trunk is the branch the bottom PR targets: `main` when `sub_pr_target: main`, `<type>/<slug>` in the feature-branch model.

## Building a new stack

In the stack's worktree: `gh stack init --base <trunk> <bottom>` (it creates a missing branch from the trunk), commit that layer, then `gh stack add <next>` from the top for each following layer, then open the PRs as §Opening the stack's PRs says.

## Opening the stack's PRs

A stack PR never appears on GitHub with generated text, so the agent creates every PR itself and `gh stack` only links them. Open each layer's PR as soon as that layer is ready, bottom to top, not all at once at the end: a `stub-on-producer-branch` consumer is dispatched only after its producer's PR is open (`feature-dev-workflow:fanning-out-with-worktrees` Step 1), so the producer's PR must exist before its consumer's layer is even started. For each layer that is ready:

1. `gh stack push` from the stack's worktree, so the layer branch is on the remote.
2. Compose the title and body through `feature-dev-workflow:opening-a-pull-request` (under a standing grant, or after a fresh confirmation), then run `gh pr create --draft --base <parent-branch> --head <layer> --title <title> --body-file <file>`. The bottom layer's base is the trunk.
3. Link the stack once two or more layers have PRs: `gh stack link --base <trunk> <bottom-PR-URL> ... <top-PR-URL>`, listing every layer's PR bottom to top. `gh stack link` takes at least two arguments, so a stack with only its bottom PR open is not linked yet; the bottom PR stays an ordinary draft against the trunk until the next layer's PR exists. Each time a further layer's PR opens, run the same command again with the full list; `link` adds the new PR to the existing stack. Pass PR URLs, never branch names or bare numbers: a URL always resolves to an existing PR, while a branch without a PR makes `link` create one with a generated title and body. `link` leaves the existing PRs' titles and bodies untouched; it only corrects bases and builds the stack on GitHub.
4. Check the result: `gh stack view --json` shows each layer with its PR (once the stack is linked), and `gh pr view <num> --json title,body,isDraft,baseRefName` matches what you created.

## Adopting a stack that was built by hand

This covers a stack whose branches and PRs already exist, including a stack that exists only as a `gh stack link` link on GitHub. A hand-made chain is still a stack, so adopt it before propagating anything through it. If human review has already started, ask the user first, because the adoption rebases the layers under that review.

1. Verify every layer is clean and pushed: no dirty files, and the local head equals the remote head (`git status --porcelain --branch`, `git ls-remote <remote> <branch>`).
2. Take a local backup outside the repo before anything moves: a `git bundle create` of every layer branch, checked with `git bundle verify`; a local backup tag at each branch head; and an archive of any per-layer worktree directories. Record each layer's old parent and old head SHA. Keep the backup local; never push backup refs.
3. Remove the per-layer worktrees, and create or keep the stack's one dedicated worktree (never the main checkout).
4. `gh stack init --base <trunk> <bottom> ... <top>`. It adopts the existing branches and detects their PRs.
5. Read `gh stack view --json` before syncing: the layer order, each layer's PR number, and `needsRebase`. Stop if any of them is wrong.
6. `gh stack sync`. It rebases onto the trunk, force-pushes with lease, and links the PRs into a Stack on GitHub. On a conflict it restores every branch and exits 3: run `gh stack rebase`, resolve the files, `git add` them, then `gh stack rebase --continue`.
7. Verify: for each layer, `git range-diff <oldParent>..<oldHead> <newParent>..<newHead>` shows `=` for every commit; each PR's draft state and base are unchanged; then run the project's full test and lint gates on the top branch, because the trunk moved under every layer.

## Propagation is a rebase

`gh stack` keeps a stack consistent by rebasing each layer onto its parent and force-pushing. That rewrites SHAs under review and outdates the review comments anchored to them; it is the price of automatic propagation. The trade is worth it mainly because of squash merges: after a parent squash-merges, a child still carries the parent's original commits, and `gh stack sync` / `gh stack rebase` replay the child with `--onto` so they drop out. The best moment to create or adopt a stack is therefore before human review starts. After `gh stack push` or `gh stack sync`, record each layer's head SHA from the remote, not from memory.

**Propagating a fix through the stack.** Commit the fix on the layer that owns the code (ownership is decided by `feature-dev-workflow:developing-a-feature` §Review-driven changes while several open PRs share history). In the stack's worktree, check out the owning layer (`gh stack checkout <branch>`), commit the fix, run `gh stack rebase --upstack`, then `gh stack push`, and record the new head SHAs from the remote. A stack that exists only as a link on GitHub is adopted into its dedicated worktree first (§Adopting a stack that was built by hand).

## After a parent merges

Run `gh stack sync`. Then check the next PR: `gh pr view <num> --json baseRefName,closingIssuesReferences`. If its base still names the merged branch, correct it with `gh stack link --base <trunk> <PR-URL> ... <top-PR-URL>`, listing the open layers bottom to top by PR URL. Never use `gh stack submit` for this: it also creates a PR with a generated title and body for any layer that has none. Once the base is the default branch, `closingIssuesReferences` must list its sub-issue (see the stacked-PR keyword rule in `feature-dev-workflow:opening-a-pull-request`). The sync rebased every layer above, so check whether their gates still hold: for each one, record its head before the sync and compare its own commits with `git range-diff <oldParent>..<oldHead> <newParent>..<newHead>`. A layer whose commits all show `=` keeps the gates it passed. A layer with any changed commit (for example, a conflict was resolved during the rebase) goes back through its review gates and approval gate before it merges.

## Merges stay under the merge guard

`gh stack merge <pr> --yes` merges that PR and every unmerged PR below it, all or nothing. Pass the project's merge method (`--merge`, `--squash`, or `--rebase`): without one, `--yes` uses whatever method was used last. When the base branch uses a merge queue, the PRs are queued instead, and the queue picks the method. A queued merge has not happened yet: wait until `gh pr view <num> --json mergedAt` shows it merged before `gh stack sync`, the sub-issue close, or the state-file update. `gh stack merge` never bypasses required reviews or other merge requirements. Run it only for the sub-PR merges the state file's `sub_pr_approval` / `sub_pr_target` configuration already covers (see the merge guard in `feature-dev-workflow:developing-a-feature` Step 6); a stack does not widen what this workflow may merge. Because the merge set includes every unmerged layer below, merge bottom-up: name only the lowest unmerged layer, after that layer has passed its own gates. A higher layer that is ready first waits. `gh stack merge` also refuses a draft, and every layer was opened as one, so flip the layer ready first (`feature-dev-workflow:fanning-out-with-worktrees` Step 5, item 4).

## Red flags

| Thought | Reality |
| --- | --- |
| "`gh stack` isn't installed, I'll chain the bases by hand for now" | A hand-made stack is the thing `gh stack` replaces: stale bases after a parent merges, children still carrying a squashed parent's commits. Stop and ask the user to install it; never install it yourself. |
| "I'll keep one worktree per layer, it's tidier" / "I'll just run the stack in the main checkout" | `gh stack` checks every layer out in turn, and git refuses a branch held by another worktree. It also moves `HEAD`, so the main checkout or the user's working copy would be blocked. One dedicated worktree per stack. A per-layer worktree is right only while that layer is built in parallel, and it must be gone before the layer joins. |
