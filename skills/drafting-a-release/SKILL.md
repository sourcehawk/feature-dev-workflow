---
name: drafting-a-release
description:
  Use when the user asks to cut, draft, create, publish, or tag a new release — drafting release notes / a changelog and running `gh release create`.
---

# drafting-a-release

A release is a public, hard-to-retract artifact, and its notes are read by people deciding whether to upgrade and what it costs them. This skill turns "what merged since last time" into curated notes that explain **why** each change matters, proposes the version, and gates the publish on the user.

This skill is standalone. Nothing in the feature-development flow routes into it, and it routes into nothing. Invoke it whenever a release is asked for.

## Template

One template carries the shape and the per-section guidance:

- `${CLAUDE_PLUGIN_ROOT}/skills/drafting-a-release/templates/release-notes.md`

Copy it, fill each section per its `<!-- -->` guidance, then pass the body to `gh release create` via `--notes-file` (write the body to a file — it avoids shell-escaping the markdown). The collapsed `<details>` changelog renders as a fold on GitHub; leaving the comment guidance in the file is harmless since GitHub doesn't render HTML comments, so don't burn a step stripping it.

## Choreography

Work the steps in order. Steps 1, 3, 5, and 6 are gates — do not run ahead of the user on any of them.

1. **Establish the release point — ask, don't assume HEAD.** Before anything else, ask whether to cut from the current tip of the default branch or from a specific commit. Ask this on every release: even when the branch tip looks obviously fine, and even when an unfinished commit sitting on top looks obviously skippable. Where the tag lands is the user's call, not an inference you make from how the commits read.

   If they choose a specific commit, accept whatever form they give it — a commit SHA, any resolvable ref (a tag or a branch), or a description of intent ("the commit where the X landed", "everything up to PR #N"). Resolve a description to one concrete commit from `git log` and the merged-PR history, then echo back the short SHA, subject, and date and wait for an explicit yes before using it. Confirm the resolved commit even when they hand you a literal SHA — show its subject so they can catch a typo or a stale paste.

   The resolved commit (or the branch tip, if that's what they chose) is `<target>` for the rest of the run: it sets the upper bound of the next step's range and the `--target` of the publish. The short SHA you echo here is for the human-readable confirmation only — when `<target>` reaches `--target`, pass the full 40-char SHA (`git rev-parse <target>`) or the branch name, never the abbreviated form. The publish step says why.

2. **Establish the baseline.** Find the last release and what shipped between it and the release point: `gh release list` (or `git describe --tags --abbrev=0`) for the last tag, then `git log <last-tag>..<target>` and the merged PRs in that range. Bounding the range at `<target>` rather than HEAD keeps anything past the release point out of the notes. This range is the raw material for both the curated sections and the changelog.

3. **Propose the version — never pick it silently.** Read the change types in the range and propose a semver bump with one line of reasoning (a breaking change forces a major; new capability is a minor; fixes-only is a patch — adjust for a pre-1.0 `0.x` line, where breaking bumps the minor). State your proposal and the reasoning, then let the user confirm or override. The version is the user's call; your job is the recommendation.

4. **Draft the body from the template, reasoning about the why.** This is the work the merge list can't do for you. For each entry, lead with what the user couldn't do before and what it solves — not the PR title reworded. The raw "what" belongs in the collapsed changelog; the sections above it are the curated "why". Put any breaking change first and call it out loudly.

5. **Present the full body and proposed tag, and let the user refine.** Paste the complete drafted body and the tag in chat. Invite edits and iterate until they're happy. Do not move to publishing off a body they haven't seen in full.

6. **Publish gate — draft or published, and that choice is the go-ahead.** With the full body already shown in step 5, ask the one question that both picks the mode and authorizes the publish: draft or published? A draft (`--draft`) stages the notes on GitHub for a final human look without going live; omitting the flag publishes immediately. If they're unsure, recommend draft (it's the reversible option) but let them decide. Their answer — made against this exact tag, body, and commit — is the explicit consent to create, so run `gh release create` on it. Do not stack a second "Confirm?" prompt on top of a publish-mode choice they just made. See below for what this single gate must put in front of them.

## Core principle: user-in-the-loop for the publish

Don't run `gh release create` on inferred consent. A "yes, cut a release" at the start of the task is intent to begin, not approval of this tag, this body, and this draft/published state. The explicit consent is the user's draft-or-published choice (step 6) made against the exact release you've laid out. That single choice is the go-ahead: once they've made it, create — don't stack a separate "Confirm?" prompt on top of it.

For that choice to count as consent, the gate must put the whole release in front of them at once:

- The **tag / version**, and the **commit it lands on** — the short SHA for readability when a specific commit was chosen, or the default branch tip.
- The **full notes body** — shown in full in step 5; restate it or point to it directly above, so they're choosing against what they can see.
- The **repo**, if there's any chance of ambiguity about which one.
- The **draft-or-published choice itself** — the action they take to consent.

Phrase it as: "Release `<tag>` on `<repo>`, landing on `<commit>`, body above — publish it live now, or stage it as a draft?" Their answer is the consent; act on it. Treat silence or a non-answer as a no.

Then create:

```bash
gh release create <tag> \
  --title "<tag>" \
  --notes-file <body-file> \
  [--target <full-sha-or-branch>] \
  [--draft]
```

`--target` takes a **branch name or the full 40-char commit SHA — never an abbreviated SHA.** GitHub's release API rejects an abbreviated `target_commitish` and reports it as `tag_name is not a valid tag` / `Release.target_commitish is invalid`, which reads like a tag problem but is the short SHA. Resolve it with `git rev-parse <target>`. Omit `--target` entirely only when cutting from the default branch's current tip (the API's default).

## Anti-patterns

- **Tagging the branch tip because no commit was named.** Where the release is cut from is a gate, like the version. Ask whether it's the branch tip or a specific commit; don't read silence as HEAD.
- **Picking the release point yourself from how the commits read.** A trailing "WIP" commit doesn't authorize you to silently target the one below it. Surface the choice, then confirm the resolved commit with the user.
- **A changelog masquerading as release notes.** Grouped PR titles under Features / Fixes headings, with no reasoning, is a changelog. The curated sections must answer *why it matters*; the bare list lives in the collapsed `<details>`.
- **No overview.** Skipping straight to bullets robs the reader of the through-line — is this routine, a headline feature, or a migration?
- **Burying a breaking change** in the middle of a list. It goes first, flagged.
- **Picking the version yourself** and moving on. Propose, then let the user decide.
- **Defaulting draft-vs-published** instead of asking. The user owns that call.
- **Running `gh release create` on inferred consent.** A start-of-task "cut a release" is not approval of this tag, body, and state. The user's draft-or-published choice against the shown body is that approval — get it before creating.
- **Re-confirming after the user already chose.** Once they've picked draft or published against the body you showed, that *is* the consent. A second "Confirm?" prompt on top of it is friction, not safety — create.
- **Passing an abbreviated SHA to `--target`.** GitHub rejects it as an invalid `target_commitish`, surfacing as "tag_name is not a valid tag". Use the full 40-char SHA (`git rev-parse`) or a branch name.

## Red flags: STOP before running `gh release create`

These thoughts mean the release isn't ready to publish:

| Thought                                                       | Reality                                                                                    |
| ------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| "The PR titles are descriptive enough as the notes"           | PR titles are the *what*. Release notes are the *why*. Curate, then collapse the raw list. |
| "I'll default to a published release since they want it live" | Draft-vs-published is the user's choice. Ask, don't assume.                                |
| "I'll just default to draft to be safe and publish later"     | Still the user's call. Recommend draft if unsure, but ask.                                 |
| "Breaking change is in there, the reader will see it"         | They skim. Put it first, flag it loudly, give the migration.                               |
| "They said cut a release a minute ago, that's a yes"          | That's intent to start. The go-ahead is their draft-vs-published choice made against the body you've shown. |
| "Semver is obvious, I'll just tag it"                         | Propose the bump with reasoning; the version is the user's to confirm.                     |
| "They didn't name a commit, so cutting from HEAD is fine"     | Where the tag lands is a gate. Ask: the branch tip, or a specific commit?                  |
| "The top commit is obviously WIP — I'll target the one below" | Don't infer the release point. Ask, then confirm the resolved commit before using it.      |
| "They gave me a SHA, so I don't need to confirm it"           | Echo its subject and date — a typo or stale paste tags the wrong commit.                    |
| "I'll pass the short SHA I echoed back as `--target`"         | GitHub rejects an abbreviated `target_commitish` ("tag_name is not a valid tag" is the misleading symptom). Pass the full 40-char SHA or a branch name. |

All of these mean: finish the curated body, present tag + body + commit, and let the user's draft-or-published choice against it be the explicit go-ahead.
