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
# after the watermark, newest first. The bot's author login in /reviews is
# copilot-pull-request-reviewer[bot]; the broad test() guards against the
# identity surfacing under a variant login. The watermark is interpolated as a
# jq string literal — safe because an ISO-8601 timestamp has no jq metacharacters.
#
# The `submitted_at > $SINCE` comparison is a plain string comparison. That is
# correct here because the GitHub REST API always returns timestamps as UTC
# ISO-8601 with a `Z` suffix (e.g. 2026-05-30T22:47:51Z), a fixed-width format
# whose lexical order matches chronological order. Capture SINCE in the same
# format (`date -u +%Y-%m-%dT%H:%M:%SZ`) and the comparison holds.
filter="[.[]
  | select((.user.login==\"$BOT\") or (.user.login|test(\"[Cc]opilot\")))
  | select(.submitted_at > \"$SINCE\")
  | {id, state, submitted_at, body}]
  | sort_by(.submitted_at) | reverse"

while :; do
  # Tolerate transient gh/network failures: `|| true` keeps a blip or a rate-limit
  # from killing the poller under `set -e`. A failed poll yields empty output, so
  # the loop simply tries again next interval — only a genuine timeout exits 124,
  # keeping the exit code unambiguous for the caller (0 found / 124 timed out).
  found=$(gh api "repos/$REPO/pulls/$PR/reviews" --paginate --jq "$filter" 2>/dev/null || true)
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
