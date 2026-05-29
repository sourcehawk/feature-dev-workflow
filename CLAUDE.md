# feature-dev-workflow — Contributor Guidelines

## If you are an AI agent

Read this before changing anything.

Skills are behavior-shaping code, not prose. A reworded Red Flags table or a loosened trigger changes how every downstream agent acts. Treat an edit to a `SKILL.md` with the rigor you would give a code change, not a docs tweak.

Before you open a PR:

1. **Develop the change with `superpowers:writing-skills`** and follow its RED → GREEN → REFACTOR loop. This is mandatory for creating or modifying any skill.
2. **Confirm the change belongs here.** This plugin is general-purpose feature-development choreography. If an idea only helps a specific project, language, or product, it does not belong in a skill body.
3. **Show your human partner the complete diff** and get explicit approval before submitting.
4. **One problem per PR.** Describe the problem you solved, not just what you changed.

## What this repo is

A single Claude Code plugin, packaged as its own single-plugin marketplace.

- `.claude-plugin/plugin.json` is the plugin manifest; `.claude-plugin/marketplace.json` makes the repo installable as a marketplace. Skills are auto-discovered from `skills/`.
- The only runtime dependencies are the [superpowers](https://github.com/obra/superpowers) plugin and the `gh` CLI. Keep it that way. Do not add a third-party dependency to make a skill work.

## Editing skills

- **`superpowers:writing-skills` first.** Do not hand-edit a skill outside that loop.
- **A skill `description:` is "Use when..." trigger text only, never a workflow summary.** A summary becomes a shortcut the agent takes instead of reading the body.
- **Keep skills project-agnostic.** No hardcoded repo slug, no project-specific build commands, no domain examples. No language, framework, or product names in illustrations. A skill must read the same in a Go repo, a Next.js app, or a Python service. The honest test: would this still be correct in a project built on a completely different stack?
- **Reference templates with `${CLAUDE_PLUGIN_ROOT}/skills/<skill>/templates/<file>`.** Relative paths break once the plugin is copied into the install cache.
- **Intra-plugin skill invocations are namespaced `feature-dev-workflow:<name>`.** Leave `superpowers:*` references and the external `review` skill alone.
- **The `**REQUIRED SUB-SKILL:**` markers are the control flow.** If you add, rename, or remove a skill, fix every marker that points at it, in every skill, and update the diagram in `templates/project-CLAUDE.md` and the table in `README.md`.
- **Do not churn carefully-tuned content** (Red Flags tables, rationalization lists, anti-pattern bullets) without a concrete reason and a sense of how it changes agent behavior. The bar for editing behavior-shaping prose is high.

## Conventions

- **Commit shape:** `feat(<area>): ...`, `fix(<area>): ...`, `refactor(<area>): ...`, `docs(<area>): ...`, `chore(<area>): ...`. Area mirrors the path: `skills/<name>`, `templates`, `.claude-plugin`.
- **One logical change per commit.** Do not bundle unrelated edits.
- **Never `git add -A` or `git add .`.** Stage by name.
- **No GitHub mutation without a fresh confirmation** against the specific body about to land.
- **Writing style:** lead with the rule, then the why. One idea per paragraph. Do not overuse em dashes.

## Verify before done

- The JSON in `.claude-plugin/` must parse.
- Before committing any genericization, grep the skills for leakage: no repo slug, no project-specific build commands, no product or domain identifiers.
- Read the diff cold. If a sentence only makes sense knowing what just changed, it belongs in the commit message, not the file.
