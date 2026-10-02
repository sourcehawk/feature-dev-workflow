<!--
Paste this block into your user CLAUDE.md (~/.claude/CLAUDE.md) after installing the feature-dev-workflow plugin at user scope. It loads in every session on the machine, so the skills trigger in projects whose own CLAUDE.md never mentions them. No placeholders to fill in. Delete this comment after pasting.
-->

## Skills: load before you act

Load the skill in the right column before you do the work in the left column. The skills hold the detail. Do not work from memory when a skill covers the task.

This file applies to every project. A project's own `CLAUDE.md` comes first where it names a different skill for the same work, or a rule that a skill here would contradict. Skip a row whose skill is not installed.

| Before you ... | Load this skill |
| --- | --- |
| Scope a rough product idea into an epic, or judge if an epic is ready for engineering | `feature-dev-workflow:product-epic` |
| Start a feature, plan it, or split it into PRs, before any code, issue, or plan | `feature-dev-workflow:planning-a-feature`, then `feature-dev-workflow:developing-a-feature` |
| Implement a written plan, yours or one someone handed you | `feature-dev-workflow:developing-a-feature` |
| Continue feature work from a state file in `docs/superpowers/states/` | `feature-dev-workflow:resuming-a-feature` |
| Dispatch parallel agents into worktrees for the PRs of one feature | `feature-dev-workflow:fanning-out-with-worktrees` and `feature-dev-workflow:maintaining-architectural-coherence` |
| Split work across PRs, agents, or waves that must read as one author, or act on a structural, interface, naming, or vocabulary inconsistency | `feature-dev-workflow:maintaining-architectural-coherence` |
| Stop at a checkpoint: between fan-out waves, before an integration PR, before you mark it ready | `feature-dev-workflow:reviewing-feature-progress` |
| Base a PR on the branch of another open PR, or create, sync, or merge a stack of PRs | `feature-dev-workflow:stacking-dependent-prs` |
| Write or change a test and decide what it asserts | `feature-dev-workflow:testing-a-feature` |
| Decide if a change needs an end-to-end test, and what it asserts | `feature-dev-workflow:testing-end-to-end` |
| Run a test suite, a linter, a build, a type check, or a command of that weight, or dispatch agents that will; or a command fails on a port in use, a lock, or a machine that swaps | `feature-dev-workflow:bounding-heavy-commands` |
| Write, edit, or delete a comment in code, or review a diff that changes comments | `feature-dev-workflow:writing-code-comments` |
| Write or update public docs: README, usage guide, tutorial, API reference | `feature-dev-workflow:writing-docs` |
| Create, edit, or comment on a GitHub issue | `feature-dev-workflow:writing-github-issues` |
| Open or edit a pull request | `feature-dev-workflow:opening-a-pull-request` |
| Act on review feedback (Copilot, a person, or a local review), and again before every push of a review fix | `feature-dev-workflow:addressing-review-feedback` |
| Run a review loop on a PR until it is clean | `feature-dev-workflow:copilot-review-loop` |
| Cut, draft, tag, or publish a release | `feature-dev-workflow:drafting-a-release` |
| Report a feature-dev-workflow skill that let the work down: an instruction you had to add by hand, wrong or missing guidance, or a skill that did not trigger | `feature-dev-workflow:reporting-a-skill-gap` |
| Write prose that people read: PR and issue bodies, review replies, docs, release notes, commit bodies | `simple-english:simple-english` |
| Say that work is complete, fixed, or passing | `superpowers:verification-before-completion` |
