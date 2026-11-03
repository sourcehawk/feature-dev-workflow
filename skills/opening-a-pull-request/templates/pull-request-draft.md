<!--
Draft PR description template. See ${CLAUDE_PLUGIN_ROOT}/skills/opening-a-pull-request/SKILL.md for the choreography.

A draft PR is the stable surface that further commits push onto while work is in flight. Open it with this body; finalize when you're ready for review using the pull-request-ready.md template.
-->

## What lands here

<!--
Open with ONE of these as the FIRST line of this section, depending on what should happen to the linked issue on merge:
  - `Fixes #<num>` — bug-fix issue; GitHub auto-closes on merge to main.
  - `Closes #<num>` — feature/task issue; same auto-close semantics, neutral phrasing.
  - `Towards #<num>` — the PR contributes to the issue but does NOT auto-close it; the issue stays open. Used for sub-PRs into a feature branch and for any other "in progress on this, not finishing it" case.
Omit the line entirely if there is no tracking issue.

Then follow with 1-3 sentences or bullets on the outcomes this PR delivers, or will deliver while the work is still in flight. Treat it as the early-visibility surface for reviewers who might want to flag direction issues now rather than at review time.

Each outcome is a difference that a user, an operator, or a calling system will notice: what they get with this PR and, when it replaces something they had, what that was. Write it from where they stand. The subject is what they see (a request, a record, a status, an alert), not the component or code path that does the work; the diff and the commits already carry which code changed and where. Fit each sentence to its change rather than one pattern for every line: a fix often reads best from the symptom it ends, a new capability from what it lets them do, a changed default from the old value to the new one.
-->

## Related

<!--
Any directly-related PRs or issues OTHER than the tracking issue (which is already linked via Fixes/Closes/Towards in What lands here). Skip the section entirely if there is nothing else to link.
-->
