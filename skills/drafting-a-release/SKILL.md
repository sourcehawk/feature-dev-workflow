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

Work the steps in order. Steps 2, 4, and 5 are gates — do not run ahead of the user on any of them.

1. **Establish the baseline.** Find the last release and what shipped since: `gh release list` (or `git describe --tags --abbrev=0`) for the last tag, then `git log <last-tag>..` and the merged PRs in that range. This range is the raw material for both the curated sections and the changelog.

2. **Propose the version — never pick it silently.** Read the change types in the range and propose a semver bump with one line of reasoning (a breaking change forces a major; new capability is a minor; fixes-only is a patch — adjust for a pre-1.0 `0.x` line, where breaking bumps the minor). State your proposal and the reasoning, then let the user confirm or override. The version is the user's call; your job is the recommendation.

3. **Draft the body from the template, reasoning about the why.** This is the work the merge list can't do for you. For each entry, lead with what the user couldn't do before and what it solves — not the PR title reworded. The raw "what" belongs in the collapsed changelog; the sections above it are the curated "why". Put any breaking change first and call it out loudly.

4. **Present the full body and proposed tag, and let the user refine.** Paste the complete drafted body and the tag in chat. Invite edits and iterate until they're happy. Do not move to publishing off a body they haven't seen in full.

5. **Ask whether it's a draft or a published release.** This is the user's choice — ask it explicitly, don't default. A draft (`--draft`) stages the notes on GitHub for a final human look without going live; omitting the flag publishes immediately. If they're unsure, recommend draft (it's the reversible option) but let them decide.

6. **Confirmation gate, then create.** See below.

## Core principle: user-in-the-loop for the publish

Don't run `gh release create` without an explicit confirmation **for the exact release about to land**. A "yes, cut a release" at the start of the task is intent to begin, not approval of this tag, this body, and this draft/published state.

The confirmation you show the user spells out all four:

- The **tag / version** (and target ref if not the default branch).
- **Draft or published.**
- The **full notes body**.
- The **repo**, if there's any chance of ambiguity about which one.

Phrase it as: "About to create release `<tag>` on `<repo>` as **<draft|published>** with the body below. Confirm?" — then paste the body and wait for an explicit yes. Treat absence of objection as a no.

Once confirmed:

```bash
gh release create <tag> \
  --title "<tag>" \
  --notes-file <body-file> \
  [--target <ref>] \
  [--draft]
```

## Anti-patterns

- **A changelog masquerading as release notes.** Grouped PR titles under Features / Fixes headings, with no reasoning, is a changelog. The curated sections must answer *why it matters*; the bare list lives in the collapsed `<details>`.
- **No overview.** Skipping straight to bullets robs the reader of the through-line — is this routine, a headline feature, or a migration?
- **Burying a breaking change** in the middle of a list. It goes first, flagged.
- **Picking the version yourself** and moving on. Propose, then let the user decide.
- **Defaulting draft-vs-published** instead of asking. The user owns that call.
- **Running `gh release create` on inferred consent.** Every release is a fresh confirmation against the specific tag, body, and draft state.

## Red flags: STOP before running `gh release create`

These thoughts mean the release isn't ready to publish:

| Thought                                                       | Reality                                                                                    |
| ------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| "The PR titles are descriptive enough as the notes"           | PR titles are the *what*. Release notes are the *why*. Curate, then collapse the raw list. |
| "I'll default to a published release since they want it live" | Draft-vs-published is the user's choice. Ask, don't assume.                                |
| "I'll just default to draft to be safe and publish later"     | Still the user's call. Recommend draft if unsure, but ask.                                 |
| "Breaking change is in there, the reader will see it"         | They skim. Put it first, flag it loudly, give the migration.                               |
| "They said cut a release a minute ago, that's a yes"          | That's intent to start. Confirm the exact tag, body, and draft state now.                  |
| "Semver is obvious, I'll just tag it"                         | Propose the bump with reasoning; the version is the user's to confirm.                     |

All of these mean: finish the curated body, present tag + body + draft state, and wait for an explicit yes.
