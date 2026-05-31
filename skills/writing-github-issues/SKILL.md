---
name: writing-github-issues
description:
  Use when about to call `gh issue create`, `gh issue edit`, or
  `gh issue comment`, or immediately after concluding a brainstorming
  session that needs an issue to hold the work.
---

# writing-github-issues

## When to invoke

Whenever you're about to file or edit a GitHub issue, **or** immediately after a brainstorming session lands a decision that needs an issue to hold the work.

Four branches:

- **No issue yet**: create one (§Step 2A).
- **Issue exists but is missing context**: update it (§Step 2B).
- **Issue exists and is sufficient**: no GitHub-side action (§Step 2C).
- **A development decision diverged from what the issue states**: record the decision and reconcile the body (§Step 2D).

## Core principle: user-in-the-loop for every GitHub mutation

Don't create, modify, or link an issue without an explicit confirmation **for the specific body about to land**. This applies even if the user said "file an issue" earlier in the conversation; generic intent earlier is not standing consent for the specific body now.

By default, assign the user to any issue created or touched (`--assignee @me`, which `gh` resolves to the authenticated user). Surface the assignment in the same confirmation prompt; if they decline, note it and move on.

Every confirmation shows the user:

- The exact target (the repo, or `#<num>` for updates).
- The full proposed body.
- Which label(s) will be attached.
- Whether you intend to assign them (default: yes).

Wait for an explicit "yes" before any `gh issue create / edit` or sub-issue-linkage call. Treat absence of objection as a no.

GitHub doesn't render HTML comments, so leaving the template guidance in place is harmless — don't burn a step removing it.

## Step 1: pick the template

Three templates live under `templates/`. The choice is a single judgment call — make it explicit; don't default to the smallest shape.

```
Is the work one self-contained change that ships in one PR?
├─ No → It spans several feature-sized chunks ─────────────────→ EPIC
└─ Yes → Is it fixing unintended behaviour (regression, broken contract)?
         ├─ Yes ────────────────────────────────────────────────→ BUG
         └─ No → Is the change user-observable (new flag, UI,
                 API surface)?
                 ├─ Yes ─────────────────────────────────────────→ FEATURE  (label: feature)
                 └─ No  (plumbing, refactor, test work) ─────────→ FEATURE template, label: task
```

For brainstorm output specifically: ask whether the outcome spans multiple feature-sized chunks. If yes, file an **epic** plus one **feature/task/bug** per chunk; link each child as a sub-issue. If no, file a single **feature** (or bug) and break it into PR-sized phases inside the Approach section.

**Tiebreaker for feature vs task** (when work touches user-observable state but reads mostly as plumbing): ask whether the headline change a no-context reader would describe is user-observable. Yes → `feature`. No → `task`. Example: a storage-layout migration that changes the on-disk format is `task` (the headline is "refactor the layout"); the settings UI that lets the user pick a theme is `feature` (the headline is "you can now pick a theme").

| Template          | When                                                                                 | Label              |
| ----------------- | ------------------------------------------------------------------------------------ | ------------------ |
| `epic.md`         | Multi-chunk work; parent of feature/task/bug sub-issues                              | `epic`             |
| `feature.md`      | One self-contained capability or refactor                                            | `feature` or `task`|
| `bug.md`          | Unintended behaviour; broken contract; regression                                    | `bug`              |

## Don't hard-wrap markdown prose

Write each paragraph as a single line and put a blank line between paragraphs. Write each list item as a single line too. This applies to everything you author: the issue/PR body you publish AND markdown source files (these skills, their templates, READMEs, docs). There is no column cap to respect — GitHub and editors soft-wrap on their own, so any newline you insert mid-paragraph just reflows into ragged short lines in the rendered view and in every diff. Let the renderer wrap. Tables, fenced code, and YAML frontmatter keep their own line structure.

## Title hygiene

A title is the one line a no-context reader scans in the issue list. Make it a concise, human-readable headline of the capability or fix. A clean organizing prefix is fine when the work is part of a decomposed set — `Flow 2: investigation session happy path` reads well. What doesn't:

- **A trailing scaffolding parenthetical.** `Assert every launcher boot flag has its documented effect (e2e Flow 1)` buries the headline and tacks the plan's bookkeeping onto a durable artifact. Put the organizing label up front as a prefix, or leave it out — never as a `(… Flow N)` suffix.
- **Decorative Unicode in the title.** Arrows (`→`, `↔`), bullets, and box-drawing characters belong in body prose and diagrams, not in the title the reader scans. Use plain words.
- **A sentence that buries the lede.** If the headline noun-phrase comes after a clause of setup, cut the setup.

### The naming firewall

Organizing labels — `Flow N`, `Phase N`, `Wave N` — may appear in an issue title prefix or an epic's prose, because that's where humans group the work. They must **never** propagate into the code the issue produces. When the issue's acceptance criteria or approach name concrete artifacts, name them for what they are (`resumable-investigation`, not `flow2-fixture`). The full rule and the allowed-surface table live in `feature-dev-workflow:maintaining-architectural-coherence`.

## Diagrams: visualize architectural changes

When the change is architectural — new components, data or control flow crossing module boundaries, a phase/lifecycle progression, or sequencing between processes — embed a mermaid diagram in the issue body. A diagram earns its place when prose alone forces the reader to reconstruct the topology in their head; skip it when the change is one file with no cross-module shape.

Applies to **feature** and **epic** bodies only (a bug is "what broke", not an architecture). Place it inside the section that already carries the implementation shape: the epic's `## Design overview` or the feature's `## Approach`. GitHub renders fenced `mermaid` blocks natively.

Pick the diagram type that matches what's hard to see in prose:

| Diagram                | Fits                                                                                  |
| ---------------------- | ------------------------------------------------------------------------------------- |
| `flowchart`            | Component/data flow and module seams (which package hands what to which).             |
| `sequenceDiagram`      | Request/handoff ordering between processes (client ↔ server ↔ worker over time).      |
| `stateDiagram-v2`      | Phase or lifecycle progressions (job states, request lifecycle, session state).        |

Keep it honest: the diagram supplements the prose, it does not replace Design overview / Approach. Label nodes with the real component names the prose and code use (the actual file, module, and type names) — a diagram of invented boxes is worse than no diagram. The diagram is part of the body, so it lands in the same confirmation prompt as everything else (§Core principle).

## Step 2A: No issue yet (create)

1. **Draft the issue body** from the chosen template. Each section earns its keep — read the `<!-- -->` guidance in the template for what belongs where. The cross-template common shape:
   - **Title**: human-readable sentence a no-context reader can parse.
   - **Problem**: a few sentences opening with the elevator pitch (the what) and naming the operational reason it matters (the why). No solution; that belongs in the PR description (bug) or in Approach / Design overview (feature / epic).
   - Template-specific sections: see the relevant template file.

2. **Confirm with the user, with the body inline.** Paste the drafted body into chat under a "About to create a `<label>` issue in this repo with the body below, and assign you (`@me`). Confirm?" line. Wait for an explicit yes. If they push back on specific wording, redraft and re-present.

3. **Create the issue** by piping the body through a heredoc:
   ```
   gh issue create --title "<title>" --label <label> --assignee @me --body "$(cat <<'BODY_END'
   <body>
   BODY_END
   )"
   ```
   Drop `--assignee @me` if they declined assignment in step 2. If the body itself contains the line `BODY_END`, pick a less collision-prone sentinel (`ISSUE_BODY`, `EOF_ISSUE_42`, etc.) — the heredoc terminator must not appear inside the body.

4. **Capture the URL** and surface the number to the user.

5. **If this is an epic**, first create a task (`TaskCreate`) for each issue you intend to file — the epic and every sub-issue — so the multi-issue sequence is tracked across turns and confirmations and nothing is dropped halfway. Then file in this order:
   a. **Epic first** (steps 1-4 above) so children can reference its number in their `## Context` section.
   b. **Each sub-issue next** using the feature/task/bug template (steps 1-4 above for each). **Draft, confirm, and create them one at a time** — one issue's body per confirmation prompt, then `gh issue create`, then the next. Do NOT batch several sub-issue bodies into a single "yes to all" prompt: a wall of bodies gets rubber-stamped instead of read, and rewording one mid-batch forces re-pasting the whole set. One issue, one confirmation, one create; mark its task complete before starting the next.
   c. **Linkage last** — once all children have numbers, link each one to the epic via the native sub-issue API (see §Linking sub-issues). Don't try to embed the children in the epic body manually — GitHub renders the progress checklist from the linkage, not from a markdown list.

### Linking sub-issues

GitHub's `gh issue create` does not (yet) expose a `--parent` flag. Use the GraphQL `addSubIssue` mutation, fetching both issue node ids via `gh issue view --json id`.

**Confirm the linkage set before running any mutation.** Sub-issue linking is a GitHub mutation; the user-in-the-loop rule from §Core principle applies. Once every child issue is filed (so every number is known), present the full linkage set to the user in one prompt:

> About to link the following sub-issues to epic `#<epic-num>`:
> - `#<child-1>` (<one-line title>)
> - `#<child-2>` (<one-line title>)
> - ...
>
> Confirm?

Wait for an explicit yes. On push-back, drop or amend specific links before running anything.

Then run the mutation once per sub-issue:

```
PARENT_ID=$(gh issue view <epic-num> --json id --jq .id)
CHILD_ID=$(gh issue view <child-num> --json id --jq .id)
gh api graphql -f query="mutation { addSubIssue(input: {issueId: \"$PARENT_ID\", subIssueId: \"$CHILD_ID\"}) { subIssue { number } } }"
```

The epic's body's `## Sub-issues` section auto-renders as a checklist with progress — no manual list maintenance needed.

## Step 2B: Issue exists but is missing context (update)

1. **Read the existing issue:**
   ```
   gh issue view <num> --json title,body,labels,assignees
   ```
2. **Identify the gaps.** Compare the existing body against the matching template's section list. State each gap in one sentence. Pre-existing tickets are most often missing concrete acceptance criteria, verification steps, or labels; flag those first.
3. **Draft the updated body.** Preserve content from the existing issue that the user wants to keep; merge in what's missing. Use the template for sections that need them.
4. **Confirm with the user, surfacing both the gap list and the proposed body.** Paste the drafted body into chat under a "The issue at `#<num>` is missing: <one-line gap list>. About to update its body to the version below, and assign you (`@me`) if you're not already. Confirm?" line. Wait for an explicit yes. On push-back, redraft and re-present.

5. **Update the issue** by piping the body through a heredoc:
   ```
   gh issue edit <num> --add-label <label> --add-assignee @me --body "$(cat <<'BODY_END'
   <body>
   BODY_END
   )"
   ```
   Drop `--add-assignee @me` if declined. Drop `--add-label` if the label is already attached.

## Step 2C: Issue exists and is sufficient (no body change)

1. **Surface the link to the user**.
2. **Ask about assignment** if the user isn't listed in `assignees`:

   > You're not currently assigned to `#<num>`. Want me to add you (`@me`)?

   On yes: `gh issue edit <num> --add-assignee @me`. On no: leave it.

3. **No body changes.**

## Step 2D: A development decision changed what the issue states (record + reconcile)

When implementation diverges from what the tracking issue currently states — an acceptance criterion changes, the stated approach no longer matches what's being built, scope expands or contracts, or a described contract ships in a different shape — the issue must be brought back into truth *and* the decision recorded. A bare body edit reconciles the *what* but destroys the *why*; doing nothing leaves the issue stale and the divergence lost to history. Both are failures. This branch does both, as one confirmed change, before the feature merges.

**The materiality test.** Would a reader of the issue, as it stands, be misled by what is now true on the branch? If yes, it is material — run this branch. If the change is an implementation detail the issue never claimed, or pure wording, it is not material — do nothing.

**This is not the "design belongs in the PR, not the issue" case.** You are not adding fresh line-level design to the issue (§Anti-patterns still forbids that). You are recording that a decision already made changed the issue's *durable content* — its problem, stated approach, or acceptance criteria — and restoring the body to match. Keeping that content true is the issue's own job; the PR still carries the line-level design.

**Which issue.** Single-PR feature → the one tracking issue. Multi-PR → the **sub-issue** when the change is scoped to that sub-PR's work; the **epic** when the change is to the design-overview-level shape the epic carries.

**Commit it first.** The record links the commit that embodies the change, so the change must be committed and pushed before this branch runs. In a multi-PR feature that commit is on `feature/<slug>`, which is pushed and linkable on GitHub before the feature merges.

The record and the reconcile are one logical change, confirmed together:

1. **Draft the decision comment.** It states three things and nothing else:
   - **What the issue said before** — the prior approach / criterion / scope.
   - **What it is now** — the decision that replaced it.
   - **Why it changed** — the operational reason the prior shape didn't hold.

   It links the commit, and nothing else: `owner/repo@<sha>` (GitHub renders it) or the full commit URL. It references **no** spec path, plan path, state file, or other scratch/agent artifact — the same rule as the §Anti-patterns "Referencing the design spec ... from an issue" entry. The commit is the only pointer; the issue's own thread carries the rest.

2. **Draft the reconciled body** — the existing body with the now-false content corrected to match the decision, following §Step 2B's body-drafting rules (preserve what's still true; the naming firewall still applies).

3. **Confirm both together, inline.** Paste the full comment body and the full reconciled body into chat under an "About to comment on `#<num>` recording this decision, then update its body to match — both shown below. Confirm?" line. Wait for an explicit yes; the user-in-the-loop rule (§Core principle) governs both mutations — a comment is as public as an edit. On push-back, redraft and re-present.

4. **Post the comment, then update the body** — comment first, so the prior state is preserved verbatim in the thread before the edit overwrites it:
   ```
   gh issue comment <num> --body "$(cat <<'BODY_END'
   <comment>
   BODY_END
   )"
   gh issue edit <num> --body "$(cat <<'BODY_END'
   <reconciled body>
   BODY_END
   )"
   ```
   If either body contains the line `BODY_END`, pick a less collision-prone sentinel.

## Labels

The skill assumes these labels exist in the repo:

| Label     | Used for                                                                  |
| --------- | ------------------------------------------------------------------------- |
| `epic`    | Parent issue grouping feature/task/bug sub-issues                         |
| `feature` | User-observable capability or surface (flag, UI, API, behaviour)          |
| `task`    | Plumbing, refactor, test work with no direct user-visible change          |
| `bug`     | Unintended behaviour; regression; broken contract                         |

`bug` already exists on the repo from GitHub's default set. If `epic`, `feature`, or `task` is missing, surface that to the user and offer to create them with `gh label create <name> --description "<one-line>"` — that's a GitHub mutation, gate it on confirmation like any other.

## Implementation workflow

When working a sub-issue (or a single-feature/bug issue):

- **Commits carry the sub-issue ref** as a suffix on the subject line: `fix(cache): handle empty entry dir (#23)`. The issue page surfaces the commit history automatically; an epic doesn't need its own ref because GitHub's parent→sub-issue linkage already threads them.
- **PR linkage depends on which branch the PR targets** (see `feature-dev-workflow:opening-a-pull-request`):
  - **Sub-PR into the feature branch** (multi-PR features) — body uses `Towards #<sub-issue>`. `Fixes` / `Closes` don't auto-trigger on non-default branches; `Towards` is explicit about keeping the issue open until the orchestrator closes it manually after the self-merge: `gh issue close <sub-issue>`. The close is bodyless (no `--comment`) — GitHub already auto-cross-references the merge commit through the sub-PR's `Towards` keyword, so the closing trail is preserved without a custom comment body that would itself need confirmation against the user-in-the-loop rule.
  - **Integration PR into main** (multi-PR features) — body uses `Closes #<epic>` so the epic auto-closes when the feature lands.
  - **Single-PR feature → main** — body uses `Fixes #<feature-issue>` or `Closes #<feature-issue>`.
- **Don't bundle work across sub-issues** in one commit. One sub-issue per commit (or per logical commit chain) keeps the cross-link signal honest.

## Anti-patterns

- **Forcing multi-chunk work into a single feature/bug issue.** If the brainstorm decision is "build X with three feature-sized pieces", an epic + three children beats one bloated issue with a checklist body. Sub-issues give you GitHub's progress bar, independent assignees, independent close-on-merge.
- **Inventing a feature-id-style slug as the title.** Issue titles are human-readable sentences. Slugs belong on branches and PR titles, not in the issue heading a reviewer reads first.
- **Tacking the plan's bookkeeping onto the title as a suffix.** `… (e2e Flow 1)` buries the headline; decorative arrows (`→`) and box characters add noise. A clean `Flow 1:` prefix is fine — a trailing parenthetical is not (see §Title hygiene).
- **Letting an organizing label leak into code names.** `Flow N` / `Phase N` is navigational only. The fixtures, ids, functions, and markers the issue produces are named for what they are, never `flow2-…` / `…_FLOW2_…` (see §The naming firewall).
- **Putting design into a feature or bug issue.** The issue is "problem + how we'll know it's done." Design belongs in the PR description that lands the work (or in `docs/superpowers/specs/` for spec-worthy work). The epic's `## Design overview` is the exception — it captures the brainstorm output, not the line-level design.
- **Referencing the design spec (or any scratch doc) from an issue.** Issues are durable GitHub artifacts; the spec and plan are repo files that move, get renamed, or — in the plan's case — get deleted once the work ships. A sub-issue references **only its parent epic** (GitHub's native sub-issue linkage threads it); the epic captures the design context **inline** in its `## Design overview`, it does not link the spec file either. The spec is referenced from the *plan*, not from any issue. A `docs/superpowers/specs/...` or `docs/superpowers/plans/...` path in an issue body is the smell.
- **Hard-wrapping prose to a column width.** There is no column cap; GitHub and editors soft-wrap on their own, and the breaks you insert reflow into ragged short lines. One line per paragraph, one line per bullet, blank line between — in bodies and source files alike (see §Don't hard-wrap markdown prose).
- **Describing a multi-component flow in prose only.** When a feature/epic narrates data or control crossing several modules (client → API → queue → worker → store) or a phase progression, a five-node mermaid diagram makes the seams legible at a glance. Prose-only forces every reader to rebuild the topology in their head. Add the diagram in `## Design overview` / `## Approach` (see §Diagrams).
- **Acceptance criteria written as aspirations.** Each bullet has to be a verifiable condition a reviewer can answer "yes / no" against at done-time. "the service is more reliable" is not checkable; "`get_session` returns the saved record after a restart" is.
- **Inferring consent from earlier intent.** "The user said 'file an issue' two turns ago" is not standing consent for the specific body you now want to publish. Re-confirm with the actual proposed body, every time.
- **Updating an issue silently because the diff is small.** Even a one-line addition to a public issue is a public action the user didn't approve. Show the diff first.
- **Reconciling a changed issue with a bare body edit.** When a development decision made the issue's stated approach or criteria false, a lone `gh issue edit` restores the *what* and erases the *why*. A material divergence gets a decision comment (before / now / why + commit link) **and** the body update, together (§Step 2D). The thread is the durable record of why the shipped thing differs from the plan.
- **Letting "design belongs in the PR" leave the issue stale.** That rule bars dumping new line-level design into the issue; it does not excuse an issue whose stated approach or acceptance criteria are now false. Reconcile the durable content and record the decision (§Step 2D) — the PR still carries the design.
- **Proceeding on absence of objection.** "I'll go ahead unless they stop me" is not consent. Wait for an explicit yes; the cost of waiting is low, the cost of an unwanted public mutation is high.
- **Skipping the assignee question.** Default is to assign the user. If they decline once, note it and move on; don't keep asking on later edits.
- **Skipping the label.** Every issue gets exactly one of `epic`, `feature`, `task`, `bug`. The label is how the issue list is navigable; an unlabeled issue is invisible to filters.

## Red flags: STOP and re-confirm

These thoughts mean you're about to mutate GitHub without a fresh confirm:

| Thought                                                      | Reality                                                                                      |
| ------------------------------------------------------------ | -------------------------------------------------------------------------------------------- |
| "The user already said they want this issue"                 | Generic intent earlier ≠ consent for the specific body now. Re-confirm with the body inline. |
| "I'm just updating, the diff is small"                       | Public action on a public surface. Show the diff first.                                      |
| "They said yes a turn ago, this is the same thing"           | Bodies change between turns. Confirm what you're about to send.                              |
| "They didn't object to the assignment line, so they want it" | Absence of objection ≠ consent. Ask, then act.                                               |
| "I'll just append and they can edit later if needed"         | They shouldn't have to clean up after the agent. Confirm first.                              |
| "An epic feels heavy; I'll fold the children into one issue" | The brainstorm says it's multi-chunk. Don't compress it just because the template feels new. |
| "I'll link the spec in the issue's Context so readers find the design" | Issues are durable; spec/plan files move and get deleted. Sub-issues reference the epic only; the epic carries design inline. The spec is linked from the plan, not the issue. |
| "I'll paste all the sub-issue bodies in one prompt for a single yes" | Batched bodies get rubber-stamped, not read. One sub-issue per confirmation, per create. |
| "This change is architectural but the prose already explains the flow" | If the flow crosses modules or moves through phases, a mermaid diagram makes the seams legible at a glance. Add it (§Diagrams). |
| "I'll append `(e2e Flow 1)` so readers know which flow this is" | Put the label up front as a `Flow 1:` prefix, or leave it out. A trailing parenthetical buries the headline (§Title hygiene). |
| "`flow2-fixture` is the obvious name, the issue is literally Flow 2" | The label is navigational, not an identifier. Name the artifact for what it is; the firewall is one-way (§The naming firewall). |

All of these mean: paste the proposed body and the assignment intent into chat, wait for an explicit yes, then act.
