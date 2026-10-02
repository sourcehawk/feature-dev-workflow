<!--
Skill-gap issue body template. See ${CLAUDE_PLUGIN_ROOT}/skills/reporting-a-skill-gap/SKILL.md for the choreography.

The reader is a maintainer of this plugin who was not in the session. They will fix the skill under superpowers:writing-skills, which starts with a RED baseline: a subagent runs a scenario without the fix and must fail in a way they can see. The `## Reproduction` section is that baseline. Without it, the maintainer must invent a scenario and may test the wrong thing.

Everything in this body is public. Describe the generic shape of the failure. Do not name the user's project, company, repository, people, paths, issue numbers, or any secret. Use neutral stand-ins instead (`a service repository`, `<scratch-dir>`, `the user`).

Label: `bug`.

When you comment on an existing issue instead of filing a new one, the comment holds `## What happened`, `## Instruction added by hand` (when there is one), `## Reproduction`, and `## Evidence`, under the heading `## Another occurrence`. Leave out the sections the issue already states.
-->

# <plain-english-title>

<!-- Title rule: a human-readable sentence that names the skill and the failure. Example: "fanning-out-with-worktrees: parallel subagents overwrite each other's files in the shared scratch directory". -->

## What happened

<!-- A few sentences. What the agent did while it followed the skill, and what went wrong as a result: lost work, repeated work, a wrong commit, a stall. State the cost (time lost, a wrong change, a manual cleanup). No fix here. -->

## Expected

<!-- One or two sentences. What the skill should have made the agent do instead. -->

## Where in the plugin

<!--
Exactly these three lines:

- Skill: `feature-dev-workflow:<name>`
- Section: `<the heading, copied from the installed SKILL.md, with its # marks>`
- Plugin version: `<version from .claude-plugin/plugin.json>`

When the failure is that a skill did not trigger, the section is `description` (the frontmatter trigger text). When more than one skill is involved, repeat the Skill and Section lines for each.
-->

<!-- optional -->

## Instruction added by hand

<!-- Include when the user, or the agent, had to add an instruction that the skill should have carried. Quote it word for word in a blockquote, then say in one sentence what changed after it was added. Omit the section when nobody added one. -->

## Reproduction

<!-- Required. A self-contained scenario that a maintainer can hand to a fresh subagent as a RED baseline. It must run without access to this session or the user's project: every fact the agent needs is written here, in generic terms. -->

### Situation

<!-- A few sentences in the second person ("You are the orchestrator of ..."). What the agent is doing, which skill it follows, and where it is in that skill. -->

### Environment facts

<!-- A bulleted list of the facts the agent saw that matter to the failure: directory layout, what other agents are doing, tool output, file contents. Use neutral stand-ins for names and paths. -->

### Task prompt

<!-- The message the agent under test receives, in a fenced block, written as the user would type it. Do not hint at the fix in it. Ask for a neutral change ("check the change I made"), not the user's feature. -->

### Failure predicate

<!-- One to three bullets. What to grep for or check in the agent's output that shows the failure, and what shows a pass. Each bullet is checkable without judgment. Example: "Fail: the dispatch prompts contain no per-subagent scratch path. Pass: every dispatch prompt names a scratch subfolder unique to its subagent." -->

## Suggested fix location

<!-- The file and section to change (`skills/<name>/SKILL.md`, `### <heading>`, or a template path), and one sentence on the shape of the change. Not a patch: the maintainer writes the wording under superpowers:writing-skills. Say so if you are not sure which skill should own the fix. -->

<!-- optional -->

## Evidence

<!-- Public references only: issues or PRs in this plugin's repository, a related upstream issue, a public commit. A reference into a private repository or a session is described, not linked ("a session log is available from the reporter"). Omit the section when there is nothing public to point at. -->
