# feature-dev-workflow

A Claude Code plugin that turns feature development into a visible, reviewable process. It packages an end-to-end workflow as a set of composable skills that an agent follows from a feature's conception through to merge.

You invoke one skill at feature conception (`feature-dev-workflow:planning-a-feature`), and the `REQUIRED SUB-SKILL` markers inside each skill body walk the agent to the next step. The [How it works](#how-it-works) diagram below shows the full flow.

## Why this exists

Real-world software development has a shape. You plan a feature, then break it into smaller tasks so the work stays coherent and each piece is reviewable in a small batch. That discipline is what keeps a codebase legible: every change has an intent, a reviewer, and a trail back to the decision that motivated it.

AI lets you skip all of that. You can hand a model the whole feature and have it one-shot the implementation in a single sweep. It looks like the fast path, but you lose the visibility and the review discipline, and you are left with one opaque diff that has no plan behind it and nothing a reviewer can follow. Reviewability is the missing link in AI-driven development: teams have long treated review as a discipline, but one-shotting discards it exactly when the volume of machine-written code makes it matter most. It is not even the fast path: a single sweep is serial, so the whole feature waits on one long session.

This plugin keeps the engineering discipline while still using the agent to move fast. It makes agent-driven development follow the same standard a senior team already uses:

- **Design before code.** A brainstorm produces a spec, plus an ADR when the decision is cross-cutting, that a human approves before any implementation starts.
- **Work is tracked.** Every change maps to a GitHub issue, or an epic with sub-issues, so the plan is visible to the whole team and not just the agent.
- **Changes ship in reviewable batches.** A single self-contained change is one PR. A larger feature becomes a set of PRs on a feature branch, each independently reviewable.
- **Quality gates are explicit.** Tests come first, verification runs before anything is called done, and a human reviews the integration before it merges.

The result is agent speed without the output becoming a black box: legible artifacts (specs, issues, plans, PRs), incremental review, and a clear audit trail.

It is also the faster path. Breaking the feature into independent PRs lets the multi-PR flow fan the work out across parallel subagents, each in its own worktree, so independent pieces are built concurrently rather than waiting in one serial sweep. That wins on wall-clock time and on tokens, because each subagent holds only its own slice of context instead of the whole feature at once.

## Skills

| Skill | Use when |
| --- | --- |
| `planning-a-feature` | At feature conception, before any code, issue, or plan. Sequences brainstorm, spec, issues, and plan. |
| `writing-github-issues` | About to `gh issue create`/`edit`, or right after a brainstorm that needs an issue. Templates for bug, feature, and epic. |
| `developing-a-feature` | Starting implementation against a committed plan. Routes single-PR vs multi-PR. |
| `fanning-out-with-worktrees` | An orchestrator dispatching parallel subagents into per-PR worktrees off a feature branch. |
| `reviewing-feature-progress` | Orchestration checkpoints: between fan-out waves, and before the integration PR. |
| `testing-a-feature` | Writing tests for any non-trivial change. Decides the assertion shape (black-box against the contract). |
| `opening-a-pull-request` | About to `gh pr create`/`edit`. Draft and ready body templates, issue-linking keywords. |
| `maintaining-architectural-coherence` | Work split across PRs/agents/waves must read as one author. Invoked when agreeing conventions before parallel work, and when reviewing the merged union for structural, interface, naming, and vocabulary drift. |
| `drafting-a-release` | Standalone (not part of the feature flow). About to cut a release: drafts curated release notes that explain the why, proposes the version, and gates `gh release create` on the user. |

## How it works

The flow forks once, on whether the work ships as **one PR** or **many**, and rejoins at the merge. A single PR runs straight through. A multi-PR feature opens a long-lived feature branch and fans the sub-PRs out across isolated worktrees, one wave at a time, with an alignment checkpoint between waves.

```mermaid
flowchart TD
    Start([Feature idea]) --> BS[Brainstorm<br/>intent · scope · design choices]
    BS --> Spec[Write the spec<br/>+ an ADR if the decision is cross-cutting]
    Spec --> Approve{User approves<br/>the spec?}
    Approve -->|revise| BS
    Approve -->|yes| Shape{One PR<br/>or many?}

    Shape -->|single PR| IssueOne[File one issue<br/>feature or bug]
    IssueOne --> PlanS[Write the plan<br/>ordered tasks · dependencies]
    PlanS --> Build[Implement directly<br/>test-first · one commit per task]
    Build --> VerifyS[Verify green<br/>tests · lint · typecheck]
    VerifyS --> PR1[Open PR → main<br/>Fixes / Closes the issue]

    Shape -->|many PRs| Epic[File an epic<br/>+ one sub-issue per PR, linked]
    Epic --> PlanM[Write the plan<br/>+ contracts between parallel PRs]
    PlanM --> Branch[Open the feature branch<br/>+ a worktree to orchestrate from]
    Branch --> Wave[Fan out a wave<br/>one worktree + subagent per sub-PR]
    Wave --> Merge[Orchestrator reviews each sub-PR,<br/>merges it, closes its sub-issue]
    Merge --> Done{All sub-PRs<br/>merged?}
    Done -->|next wave| Wave
    Done -->|yes| VerifyM[Verify the integrated branch<br/>green end to end]
    VerifyM --> PR2[Open the integration PR<br/>feature → main · Closes the epic]

    PR1 --> Ship([External review → merge<br/>plan + state torn down in the same diff])
    PR2 --> Ship
```

You invoke `feature-dev-workflow:planning-a-feature` at conception. It, and the `REQUIRED SUB-SKILL` markers inside each skill body, walk the agent through the rest. The [`templates/project-CLAUDE.md`](templates/project-CLAUDE.md) paste-in maps each part of the flow to the skill that owns it.

## Prerequisites

This plugin depends on the [superpowers](https://github.com/obra/superpowers) plugin and references its skills directly: `superpowers:brainstorming`, `superpowers:writing-plans`, `superpowers:test-driven-development`, `superpowers:verification-before-completion`, and `superpowers:dispatching-parallel-agents`. It also uses superpowers' `docs/superpowers/{specs,plans}/` path convention, adding a sibling `docs/superpowers/states/` directory for orchestration state files. Install superpowers first.

The skills also assume the [`gh`](https://cli.github.com/) CLI is installed and authenticated.

## Install

This repo is both a plugin and its own single-plugin marketplace:

```
/plugin marketplace add sourcehawk/feature-dev-workflow
/plugin install feature-dev-workflow@feature-dev-workflow
```

A local path also works for development: `/plugin marketplace add /path/to/feature-dev-workflow`.

No further setup is required; the skills derive your repo and build commands from context. Optionally, paste [`templates/project-CLAUDE.md`](templates/project-CLAUDE.md) into your project's `CLAUDE.md` to give every session the workflow overview and the operational rules (commit conventions, safe git staging, GitHub-mutation confirmation).

## Notes

- Intra-plugin skill references are namespaced as `feature-dev-workflow:<name>`.
- Skill bodies reference their own templates via `${CLAUDE_PLUGIN_ROOT}` so paths resolve after the plugin is copied into the install cache.

## License

MIT. See [LICENSE](LICENSE).
