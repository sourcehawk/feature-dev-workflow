<!--
Release notes body template. See ${CLAUDE_PLUGIN_ROOT}/skills/drafting-a-release/SKILL.md for the choreography.

This body is the substance of the GitHub release. The reader is someone deciding whether to upgrade and what it costs them. Every section earns its place by answering "why does this matter to me", not just "what changed". A bare list of merged PR titles is a failure of this template — that belongs in the collapsed Changelog at the bottom.

Drop any section that has nothing real to say. Don't ship empty headings.
-->

## Overview

<!--
Two-to-four sentences framing the release as a whole. What is the through-line of this release, who is it for, and why would someone upgrade now? A reader should finish this paragraph knowing whether the release is routine maintenance, a headline feature drop, or a breaking migration they need to plan for. Don't list individual changes here — that's what the sections below are for.
-->

## What's new

<!--
New capabilities and improvements. For EACH entry lead with the why: what could the user not do before, what problem does this solve, and what is now possible. The change itself is the second clause, not the first.

  - **<Short capability name>.** Before, <who> had to <painful workaround> because <the gap>. <The capability> now <does X>, so <the outcome they get>. (#NNN)

Reasoning, not a changelog line. If an entry reads the same as its PR title, it isn't done.
-->

## What's changed

<!--
Behavior changes to things that already existed, including breaking changes. Lead with the reasoning, then state the change, then — if it breaks callers — the migration path in concrete terms.

If a change is breaking, say so loudly and put it FIRST in this section (or pull it into its own "## Breaking changes" heading at the top of the body). A reader skimming must not miss it. Skip the section if nothing existing changed.
-->

## What's removed

<!--
Removals and deprecations. For each: why it's going away, what replaces it, and the concrete migration (old call -> new call). If something is deprecated but not yet removed, say when it will be removed. Skip the section if nothing was removed.
-->

## Fixes

<!--
Notable bug fixes the reader would care about — the kind where someone hit the bug and wants to know it's resolved. State the symptom that's now gone, not just "fixed X". Skip routine internal fixes; they live in the Changelog. Skip the section entirely if there's nothing worth calling out.
-->

<details>
<summary>Changelog</summary>

<!--
The full mechanical list goes here, collapsed so it doesn't drown the curated sections above. One line per merged change with its PR/commit reference. This is where the raw "what" lives — the sections above are the curated "why". A compare link (last tag -> this tag) belongs here too.
-->

</details>
