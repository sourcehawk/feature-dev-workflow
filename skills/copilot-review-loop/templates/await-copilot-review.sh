#!/usr/bin/env bash
# Poll an open PR until GitHub Copilot posts a review newer than a watermark,
# then print that review as JSON and exit. Designed to be launched in the
# background so the agent session is never blocked waiting.
#
# Dependencies: gh (with `gh api --jq`, which uses gh's built-in jq engine) and
# shell builtins only. No jq binary, no gh extension.
#
# Usage:
#   await-copilot-review.sh <pr-number> <since-iso8601> [interval-seconds] [timeout-seconds]
#
# <since-iso8601> is the watermark: capture it BEFORE requesting the review, e.g.
#   SINCE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
# so a review left over from a previous round can't be mistaken for the new one.
#
# Exit status:
#   0   a Copilot review newer than the watermark was found (printed to stdout)
#   124 timed out before one appeared
#   2   bad arguments

set -euo pipefail

PR="${1:-}"
SINCE="${2:-}"
INTERVAL="${3:-30}"
TIMEOUT="${4:-900}"

if [ -z "$PR" ] || [ -z "$SINCE" ]; then
  echo "usage: await-copilot-review.sh <pr-number> <since-iso8601> [interval] [timeout]" >&2
  exit 2
fi

REPO=$(gh repo view --json nameWithOwner --jq .nameWithOwner)
BOT="copilot-pull-request-reviewer[bot]"
DEADLINE=$(( $(date +%s) + TIMEOUT ))

# jq filter (run by gh's built-in engine): Copilot-authored reviews submitted
# after the watermark. The bot's author login in /reviews is
# copilot-pull-request-reviewer[bot]; the broad test() guards against the
# identity surfacing under a variant login. The watermark is interpolated as a
# jq string literal — safe because an ISO-8601 timestamp has no jq metacharacters.
#
# The filter emits each matching review as a bare object, NOT wrapped in an outer
# array. This is deliberate: gh runs the --jq filter once per page under
# --paginate and concatenates the outputs (and --slurp is rejected together with
# --jq). An array-wrapped filter would emit an empty array for every page with no
# match, so a multi-page no-match would print several empty arrays in a row —
# non-empty output, which the loop would misread as "review found". Emitting bare
# objects means a no-match prints nothing on every page, so the output is
# genuinely empty and the -n test below is correct.
#
# submitted_at > SINCE is a plain string comparison, which is correct here: the
# GitHub REST API always returns UTC ISO-8601 with a Z suffix (fixed-width, so
# lexical order == chronological order). Capture SINCE the same way
# (date -u +%Y-%m-%dT%H:%M:%SZ) and the comparison holds.
filter=".[]
  | select((.user.login==\"$BOT\") or (.user.login|test(\"[Cc]opilot\")))
  | select(.submitted_at > \"$SINCE\")
  | {id, state, submitted_at, body}"

while :; do
  # Capture output ONLY when gh succeeds. On an HTTP error (404, rate-limit, a
  # network blip) gh prints the error body to stdout AND exits non-zero; the
  # if-guard discards that body and leaves found empty, so an error is never
  # mistaken for a review. This also tolerates transient failures under set -e:
  # a failed poll just retries next interval, and only a genuine timeout exits
  # 124 — keeping the exit code unambiguous for the caller (0 found / 124 timed).
  found=""
  if out=$(gh api "repos/$REPO/pulls/$PR/reviews" --paginate --jq "$filter" 2>/dev/null); then
    found="$out"
  fi
  if [ -n "$found" ]; then
    printf '%s\n' "$found"
    exit 0
  fi
  if [ "$(date +%s)" -ge "$DEADLINE" ]; then
    echo "timed out after ${TIMEOUT}s waiting for a Copilot review on #$PR" >&2
    exit 124
  fi
  sleep "$INTERVAL"
done
