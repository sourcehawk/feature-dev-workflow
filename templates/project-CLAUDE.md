<!--
Paste this block into your project's CLAUDE.md (or AGENTS.md) after installing the
feature-dev-workflow plugin. It wires the workflow's placeholders to your project's
commands and gives every Claude session the orchestration overview.

Fill in the four placeholders below, then delete this comment.
-->

## Feature-development workflow

This project uses the `feature-dev-workflow` plugin. Invoke `feature-dev-workflow:planning-a-feature`
at feature conception and let the cross-references fan out from there.

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

Invoke `feature-dev-workflow:planning-a-feature` at conception — it and the
`**REQUIRED SUB-SKILL:**` markers inside each skill body drive every box above. Which
skill owns which part of the flow:

| Part of the flow | Skill |
| --- | --- |
| Brainstorm → spec → issues → plan → state file | `feature-dev-workflow:planning-a-feature` (calls `superpowers:brainstorming`, `feature-dev-workflow:writing-github-issues`, `superpowers:writing-plans`) |
| Implement (single or multi-PR) | `feature-dev-workflow:developing-a-feature` (with `superpowers:test-driven-development` + `feature-dev-workflow:testing-a-feature`) |
| The worktree fan-out loop + wave merges | `feature-dev-workflow:fanning-out-with-worktrees` |
| Checkpoints between waves & before the integration PR | `feature-dev-workflow:reviewing-feature-progress` |
| Verify-before-done | `superpowers:verification-before-completion` |
| Open / flip pull requests | `feature-dev-workflow:opening-a-pull-request` |

`superpowers:*` skills come from the [superpowers](https://github.com/obra/superpowers)
plugin (a prerequisite — see below).

### Project commands (fill these in)

The workflow skills reference four placeholders. Set them to your project's real commands:

| Placeholder       | Your command (example)                  |
| ----------------- | --------------------------------------- |
| `<TEST_CMD>`      | e.g. `make test` / `npm test` / `pytest`|
| `<LINT_CMD>`      | e.g. `make lint` / `npm run lint` / `ruff check` |
| `<TYPECHECK_CMD>` | e.g. `npm run typecheck` / `mypy .` — omit if N/A |
| `<OWNER>/<REPO>`  | your GitHub repo slug, e.g. `octocat/hello-world` |

### Operational rules

- **TDD is the standard.** Failing test → watch it fail for the right reason → implement. One commit per task.
- **Before claiming done:** run `<TEST_CMD>` + `<LINT_CMD>` (+ `<TYPECHECK_CMD>` if it applies). These are the cheapest place to catch what CI gates.
- **Commit conventions:** `feat(<area>): ...`, `fix(<area>): ...`, `refactor(<area>): ...`, `test(<area>): ...`, `chore(<area>): ...`, `docs(<area>): ...`. Area mirrors the module path.
- **Never `--no-verify`, never `git add -A` / `git add .`.** Stage by name; pre-commit hooks exist for a reason.
- **No GitHub mutation without a fresh confirmation against the specific body about to land.** Paste the body inline, name the target, wait for an explicit yes.
- **PR titles outlive lifecycle state.** No `wip` / `draft` / `plan` suffixes — GitHub's chip carries lifecycle.
- **Specs in `docs/superpowers/specs/` are durable; plans in `docs/superpowers/plans/` are scratch** (deleted once the plan ships). State files live beside the plan.
