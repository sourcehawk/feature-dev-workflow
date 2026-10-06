---
name: reporting-a-skill-gap
description:
  Use when a feature-dev-workflow skill let the work down, such as when the
  user had to add an instruction by hand that a skill should have carried, a
  skill gave wrong or missing guidance, a skill did not trigger when it
  should have, or the agent repeated or undid work that a skill should have
  prevented, or when asked to report such a gap to the plugin's maintainers.
---

# reporting-a-skill-gap

A gap in one of this plugin's skills shows up in a user's session, in a user's project. The fix happens somewhere else: in the plugin's own repository, by a maintainer who was not in the session. This skill turns what went wrong into an issue that maintainer can act on.

The maintainer fixes a skill under `superpowers:writing-skills`, and that loop starts with a RED baseline: a fresh subagent runs a scenario without the fix and fails in a way someone can check. **The reproduction is the most valuable part of the report.** A story of what happened tells the maintainer that something broke. A scenario with a task prompt and a failure predicate lets them watch it break, then watch the fix work.

## When to invoke

- The user asks to report a skill problem to the plugin, or says a skill should have handled something.
- You notice the gap yourself: you, or the user, had to add an instruction the skill did not carry; you followed a skill and it led you wrong; a skill did not load when the work matched its trigger. Then offer the report to the user once, in one sentence. Do not file it unasked.

This skill covers the skills of `feature-dev-workflow` only. A gap in another plugin's skill goes to that plugin's maintainers; a gap in the user's own project instructions is the user's to fix.

## Step 1: resolve the target repository

The issue goes to the plugin's repository, never to the repository of the current project. `gh` defaults to the repository of the working directory, so a bare `gh issue create` files the report in the user's project, and that can publish their session to their own team or lose it entirely.

1. Read `${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json`. Its `repository` field holds the URL of the plugin's repository. Take `OWNER/REPO` from it (`https://github.com/OWNER/REPO` gives `OWNER/REPO`). Its `version` field is the plugin version for the report.
2. If the file or the field is missing, ask the user for the repository. Do not take it from a README, a marketplace file, or the current remote.
3. Pass `--repo OWNER/REPO` on every `gh issue` command this skill runs. `gh api` takes no `--repo`, so name the repository in the path of every REST call (`repos/OWNER/REPO/...`), and in the query of every GraphQL call (`repository(owner:"OWNER",name:"REPO")`).

## Step 2: locate the gap in the skill

Open the installed skill, `${CLAUDE_PLUGIN_ROOT}/skills/<name>/SKILL.md`, and find the section the agent was following when it went wrong. Copy its heading exactly. If the skill did not trigger, the section is its `description`. Confirm the gap is real in the text: if the skill does cover the case and the agent missed it, say so in the report, because then the fix is to make the guidance easier to find, not to add it.

## Step 3: search for an existing report

```
gh issue list --repo OWNER/REPO --state all --search "<skill-name> <two or three words for the failure>" --limit 20
```

Run a second search with other words if the first finds nothing. The list shows titles only, so open each plausible match with `gh issue view <num> --repo OWNER/REPO --comments` before you pick a branch below. That view shows a closed issue as `CLOSED` but not why it was closed, so for each closed match also run:

```
gh issue view <num> --repo OWNER/REPO --json stateReason --jq .stateReason
```

It prints `COMPLETED`, `NOT_PLANNED`, or `DUPLICATE`. Then:

- **An open issue covers the same gap:** comment on it instead of filing a new one. The comment adds your reproduction and evidence (see the template's comment form). If the issue already has a reproduction of the same case, tell the user and stop.
- **A closed issue covers it, closed as `DUPLICATE`:** follow it to the issue it duplicates and pick the branch for that issue instead. Do not comment on the duplicate. Get the number with `gh api graphql -f query='query{repository(owner:"OWNER",name:"REPO"){issue(number:<num>){duplicateOf{number}}}}' --jq '.data.repository.issue.duplicateOf.number'`. If it prints an empty line, take the number from the closing comment.
- **A closed issue covers it, closed as `NOT_PLANNED`:** the maintainers declined this gap. Tell the user, with the reason from the thread, and file nothing: no new issue, and no comment on the closed one. This holds under a standing grant too, because a grant lets a report land without a prompt and does not decide whether one is due. A reproduction that the closed issue lacks is not a difference. File a new issue only when your case differs from the closed one in a way the maintainers' reason does not cover, such as another section or another failure. The new issue names the closed one and the difference in `## Evidence`.
- **A closed issue covers it, closed as `COMPLETED` and fixed in a version newer than the installed one:** tell the user to update the plugin. File nothing.
- **A closed issue covers it, closed as `COMPLETED`, and the installed version has the fix:** it is a regression. File a new issue and name the closed one in `## Evidence`.
- **No match:** file a new issue.

## Step 4: draft the body from the template

Fill `${CLAUDE_PLUGIN_ROOT}/skills/reporting-a-skill-gap/templates/skill-gap.md`, each section per its `<!-- -->` guidance.

**Sanitize everything.** The plugin's repository is public; the user's project usually is not. The report keeps the generic shape of the failure and drops everything else:

| From the session | In the report |
| --- | --- |
| Project, company, product, or repository name | A role: `a service repository`, `the project` |
| A person's name, including the user's | `the user` |
| Paths, branch names, issue or PR numbers in the user's repository | Neutral stand-ins: `<scratch-dir>`, `<feature-branch>`, or nothing |
| A secret, key, token, or credential, even a test one | Nothing. Not the value, not a masked form. |
| Domain details of the feature (what the code is for) | Only what the failure depends on |
| Session ids, logs | Described in `## Evidence`, not pasted, unless the user says to include them |

Read the draft once against this table before you show it. A quoted instruction the user typed by hand is quoted, but with the same reductions.

**Write the reproduction to be replayed.** Check each part before you move on:

- The situation and environment facts hold every fact the agent needs, so a fresh subagent with only this text can play the scenario.
- The task prompt is the message the agent under test receives. It does not mention the fix. It asks for a neutral change ("I changed a function", "check the change"), not the user's feature, because the sanitizing table applies to the reproduction too.
- The failure predicate is something to grep or check in the agent's output, with a pass condition beside it. "The agent handles it badly" is not a predicate; "no dispatch prompt names a per-subagent scratch path" is.

**OPTIONAL SUB-SKILL:** `simple-english:simple-english` for the prose of the issue body or comment. If it is available, load it before you draft and write the sentences under it. Where its formatting rules (headings, bold, lists, or its register for chat replies) differ from the host skill or its template, the host skill and its template win. It sets sentence style only: the template still decides the sections, their order, and their length, and the task prompt and failure predicate keep their exact wording. If the skill is not available, do not stop or wait for it. If you have not already done so in this session, tell the user once that it can be installed with `/plugin marketplace add AminBlg/SimpleEnglish` and then `/plugin install simple-english@simple-english`. Then write short, plain, active sentences without it.

## Step 5: land it

**REQUIRED SUB-SKILL:** `feature-dev-workflow:writing-github-issues` to create the issue (its Step 2A) or post the comment. That skill owns the confirmation gate. It has no step that only comments, so post a comment on an existing issue with `gh issue comment <num> --repo OWNER/REPO --body-file <file>`, under the same gate, and do not edit the issue's body: a second occurrence adds evidence, it does not change what the issue states. Three points apply on top of it:

- The confirmation names the target as the plugin's `OWNER/REPO` from Step 1, so the user sees that the report leaves their project.
- Say which sanitizing reductions you made, in one line, so the user can check that nothing private is left.
- Set the label `bug` and the assignee only when the user can push to the plugin's repository (`gh api repos/OWNER/REPO --jq .permissions.push` prints `true`). Otherwise pass neither: GitHub drops both for a user without push access, and the triage is the maintainers' work.

Do not edit the installed copy of the skill under `${CLAUDE_PLUGIN_ROOT}`: the plugin cache is replaced on update. Until the fix ships, keep any instruction the user added by hand in the session's own prompts.

## Red flags

| Thought | Reality |
| --- | --- |
| "`gh` is set up for this repo, I'll just run `gh issue create`" | That files the report in the user's project. Pass `--repo` with the plugin's repository from `plugin.json`. |
| "What happened explains it, the maintainer can work out a test" | The maintainer was not there. Without a task prompt and a failure predicate they will test a scenario that may not fail. Write the reproduction. |
| "The skill name is enough, they can find the section" | Name the skill as `feature-dev-workflow:<name>` and copy the heading. A report that points at a whole skill gets a fix in the wrong place. |
| "I'll mention the project so they see it was a real case" | The repository is public. The generic shape is the real case; the names add only risk. |
| "It's only a test key, I'll mask it" | Leave it out. A masked key still tells a reader what kind of secret leaked and where. |
| "This is probably new, I'll skip the search" | A second issue splits the thread. Search first; a reproduction is worth more on the existing issue. |
| "It was closed as not planned, but it had no reproduction, and the user asked me to report" | The maintainers declined the gap, not the report's form. Tell the user and file nothing. A new issue needs a difference that their reason does not cover. |
| "I'll fix the installed skill file so it works now" | The cache is overwritten on update, and the fix needs the maintainer's RED baseline. Report it and keep the hand-added instruction in your prompts. |
