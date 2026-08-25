#!/usr/bin/env bash
# Pipe-test statusline.sh with the real statusLine stdin shape.
#
# WHY THIS FILE EXISTS: statusline.sh had no tests at all, and its one deliberate
# behaviour change from the reference -- rendering an absent context percentage as a
# dim "--" rather than a confident green "0%" -- is exactly the kind of thing a later
# "simplify this jq" edit reverts without anyone noticing. A statusline that lies
# about a full context window is worse than no statusline, because it is believed.
#
# Assertions are made against the rendered text with ANSI escapes stripped, so a
# colour-code change does not break every case; the two cases that are ABOUT colour
# check the raw escape sequence instead.
#
# Usage: bash statusline.test.sh [path-to-script]
# Exit:  0 = all pass, 1 = at least one failure. Requires jq.

SCRIPT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/statusline.sh}"

# shellcheck source=./_harness.sh
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/_harness.sh"

if [ ! -f "$SCRIPT" ]; then
  echo "statusline not found: $SCRIPT" >&2
  exit 1
fi
echo "testing: $SCRIPT"
echo

GREEN_ESC=$'\033[32m'
YELLOW_ESC=$'\033[33m'
RED_ESC=$'\033[31m'
DIM_ESC=$'\033[2m'
MAGENTA_ESC=$'\033[35m'

_render() { printf '%s' "$1" | bash "$SCRIPT" 2>/dev/null; }
_strip()  { sed -E $'s/\033\\[[0-9;]*m//g'; }

# assert_contains <label> <payload> <expected-substring>
assert_contains() {
  local label="$1" payload="$2" want="$3" out
  out=$(_render "$payload" | _strip)
  if [[ "$out" == *"$want"* ]]; then
    printf 'ok    %s\n' "$label"; pass_count=$((pass_count + 1))
  else
    printf 'FAIL  %s\n      want substring: %s\n      got: %s\n' "$label" "$want" "$out"
    fail=1; fail_count=$((fail_count + 1))
  fi
}

# assert_not_contains <label> <payload> <forbidden-substring>
assert_not_contains() {
  local label="$1" payload="$2" bad="$3" out
  out=$(_render "$payload" | _strip)
  if [[ "$out" != *"$bad"* ]]; then
    printf 'ok    %s\n' "$label"; pass_count=$((pass_count + 1))
  else
    printf 'FAIL  %s\n      must NOT contain: %s\n      got: %s\n' "$label" "$bad" "$out"
    fail=1; fail_count=$((fail_count + 1))
  fi
}

# assert_raw_contains <label> <payload> <expected-raw-substring>
# Used for colour assertions, which are about the escape sequence itself.
assert_raw_contains() {
  local label="$1" payload="$2" want="$3" out
  out=$(_render "$payload")
  if [[ "$out" == *"$want"* ]]; then
    printf 'ok    %s\n' "$label"; pass_count=$((pass_count + 1))
  else
    printf 'FAIL  %s\n      want raw substring (escaped): %q\n      got: %q\n' "$label" "$want" "$out"
    fail=1; fail_count=$((fail_count + 1))
  fi
}

# assert_not_raw_contains <label> <payload> <forbidden-raw-substring>
# The raw counterpart of assert_not_contains, for asserting a colour is ABSENT next to
# a specific piece of text.
assert_not_raw_contains() {
  local label="$1" payload="$2" bad="$3" out
  out=$(_render "$payload")
  if [[ "$out" != *"$bad"* ]]; then
    printf 'ok    %s\n' "$label"; pass_count=$((pass_count + 1))
  else
    printf 'FAIL  %s\n      must NOT contain raw (escaped): %q\n      got: %q\n' "$label" "$bad" "$out"
    fail=1; fail_count=$((fail_count + 1))
  fi
}

FULL='{"model":{"display_name":"Opus 5"},
       "cost":{"total_cost_usd":1.239,"total_lines_added":120,"total_lines_removed":34,
               "total_duration_ms":4500000,"total_api_duration_ms":95000},
       "workspace":{"current_dir":"/Users/me/code/dancing-bear"},
       "context_window":{"used_percentage":63.7},
       "agent":{"name":"tester"},"worktree":{"name":"wt-abc"}}'

echo "--- every field present renders every field ---"
assert_contains "model name rendered"        "$FULL" "Opus 5"
assert_contains "cost rounded to 2dp"        "$FULL" '$1.24'
assert_contains "dir basename only"          "$FULL" "dancing-bear"
assert_contains "percentage floored to int"  "$FULL" "63%"
assert_contains "lines added"                "$FULL" "+120"
assert_contains "lines removed"              "$FULL" "-34"
assert_contains "duration in h/m"            "$FULL" "1h15m"
assert_contains "api duration in m/s"        "$FULL" "1m35s api"
# The floor must not round up: 63.7 is 63, not 64.
assert_not_contains "percentage is floored, not rounded" "$FULL" "64%"
# A full path in the statusline wastes the width the bar needs.
assert_not_contains "full dir path not rendered" "$FULL" "/Users/me/code"

echo
echo "--- absent context window renders UNKNOWN, never 0% ---"
# This is the whole reason the reference's `// 0` was dropped. A session at 85% that
# renders as a confident green 0% is the worst kind of wrong reading: plausible, and
# pointing the opposite direction from the truth.
NO_CTX='{"model":{"display_name":"Opus 5"},"cost":{"total_cost_usd":0}}'
assert_contains     "unknown percent renders --" "$NO_CTX" "--"
assert_not_contains "unknown percent is NOT 0%"  "$NO_CTX" "0%"
RESET_ESC=$'\033[0m'
DOT_BAR='··········'
# The exact ${DIM}${bar}${RESET} fragment, not a bare search for DIM_ESC anywhere in the
# line. DIM is emitted for every separator regardless, so searching the whole line
# proved only that separators exist -- it passed even when the unknown bar rendered
# GREEN, which is precisely the confident-and-false reading this case was written to
# catch. Asserting the colour is adjacent to the bar is the only form that tests it.
assert_raw_contains "unknown bar is dim"         "$NO_CTX" "${DIM_ESC}${DOT_BAR}${RESET_ESC}"
assert_raw_contains "null-percent bar is dim" \
  '{"context_window":{"used_percentage":null},"cost":{"total_cost_usd":0}}' \
  "${DIM_ESC}${DOT_BAR}${RESET_ESC}"
# And the inverse: the unknown bar must not be coloured as if the value were known.
assert_not_raw_contains "unknown bar is not green"  "$NO_CTX" "${GREEN_ESC}${DOT_BAR}"
assert_not_raw_contains "unknown bar is not red"    "$NO_CTX" "${RED_ESC}${DOT_BAR}"
assert_contains     "unknown bar uses dots"      "$NO_CTX" "··········"
assert_not_contains "unknown bar has no fill"    "$NO_CTX" "█"

NULL_CTX='{"context_window":{"used_percentage":null},"cost":{"total_cost_usd":0}}'
assert_contains     "null percent renders --"    "$NULL_CTX" "--"
assert_not_contains "null percent is NOT 0%"     "$NULL_CTX" "0%"

STR_CTX='{"context_window":{"used_percentage":"63"},"cost":{"total_cost_usd":0}}'
assert_contains     "string percent renders --"  "$STR_CTX" "--"
assert_not_contains "string percent is NOT 63%"  "$STR_CTX" "63%"

echo
echo "--- context bar colour thresholds ---"
# Boundaries are inclusive on the upper colour: >=50 is yellow, >=80 is red. Each is
# tested at the boundary AND one below it, because an off-by-one here is invisible.
assert_raw_contains "0%  is green"   '{"context_window":{"used_percentage":0}}'  "$GREEN_ESC"
assert_raw_contains "49% is green"   '{"context_window":{"used_percentage":49}}' "$GREEN_ESC"
assert_raw_contains "50% is yellow"  '{"context_window":{"used_percentage":50}}' "$YELLOW_ESC"
assert_raw_contains "79% is yellow"  '{"context_window":{"used_percentage":79}}' "$YELLOW_ESC"
assert_raw_contains "80% is red"     '{"context_window":{"used_percentage":80}}' "$RED_ESC"
assert_raw_contains "100% is red"    '{"context_window":{"used_percentage":100}}' "$RED_ESC"
# A green bar at 80% would be the same class of lie as the 0% default.
assert_contains "80% renders its number" '{"context_window":{"used_percentage":80}}' "80%"
assert_contains "50% renders its number" '{"context_window":{"used_percentage":50}}' "50%"

echo
echo "--- numeric formatting ---"
assert_contains "cost 0 renders \$0.00"      '{"cost":{"total_cost_usd":0}}' '$0.00'
assert_contains "cost rounds, not truncates" '{"cost":{"total_cost_usd":12.3456}}' '$12.35'
assert_contains "sub-hour duration is m"     '{"cost":{"total_duration_ms":300000}}' "5m"
assert_contains "exactly 60m becomes 1h0m"   '{"cost":{"total_duration_ms":3600000}}' "1h0m"
assert_contains "sub-minute api is s"        '{"cost":{"total_api_duration_ms":45000}}' "45s"
assert_contains "exactly 60s api is 1m0s"    '{"cost":{"total_api_duration_ms":60000}}' "1m0s"
assert_contains "absent cost defaults to 0"  '{}' '$0.00'
assert_contains "absent model renders ?"     '{}' "?"

echo
echo "--- malformed payloads render a marker, not a plausible line ---"
# A line of blanks and zeroes reads like a real status. It must not.
assert_contains "non-JSON payload"      'not json at all'  "unreadable payload"
assert_contains "empty payload"         ''                 "unreadable payload"
assert_contains "truncated JSON"        '{"model":{"disp'  "unreadable payload"
assert_contains "JSON array payload"    '[1,2,3]'          "unreadable payload"
# A bare scalar is valid JSON but has no fields; it must not render a fake status.
assert_not_contains "scalar payload shows no fake cost" '"hello"' '$0.00'

# REGRESSION: a top-level `null` is VALID JSON, and `null.model.display_name` is `null`
# in jq rather than an error -- so every `// fallback` fired, jq exited 0, and the
# unreadable-payload branch was never reached. The result was a completely plausible
# status line: a real branch, a real directory, "?" for the model, "$0.00", "0m (0s
# api)". Nothing about it looked wrong, which is the whole problem. Same confident-and-
# false failure as the `// 0` percentage the reference was fixed for, arriving through
# the one door that check does not watch.
assert_contains     "null payload is unreadable"        'null' "unreadable payload"
assert_not_contains "null payload shows no fake cost"   'null' '$0.00'
assert_not_contains "null payload shows no fake model"  'null' "?"
assert_contains     "number payload is unreadable"      '3'    "unreadable payload"
assert_contains     "true payload is unreadable"        'true' "unreadable payload"
assert_contains     "string payload is unreadable"      '"hello"' "unreadable payload"
assert_contains     "array payload is unreadable"       '[1,2,3]' "unreadable payload"
# An object with no known fields is still an object: fallbacks are the right answer
# there, and it must NOT be reported as unreadable.
assert_not_contains "empty object is not unreadable"    '{}' "unreadable payload"

echo
echo "--- agent / worktree prefix precedence ---"
# Agent wins over worktree when both are present: inside a subagent, WHICH subagent is
# the more specific fact, and the worktree name is derivable from it.
BOTH='{"agent":{"name":"tester"},"worktree":{"name":"wt-abc"},"cost":{"total_cost_usd":0}}'
assert_contains     "agent name shown when both present"   "$BOTH" "tester"
assert_not_contains "worktree hidden when agent present"   "$BOTH" "wt:wt-abc"

WT_ONLY='{"worktree":{"name":"wt-abc"},"cost":{"total_cost_usd":0}}'
assert_contains     "worktree shown with wt: prefix"       "$WT_ONLY" "wt:wt-abc"

AGENT_ONLY='{"agent":{"name":"tester"},"cost":{"total_cost_usd":0}}'
assert_contains     "agent shown without wt: prefix"       "$AGENT_ONLY" "tester"
assert_not_contains "agent is not prefixed with wt:"       "$AGENT_ONLY" "wt:tester"

NEITHER='{"cost":{"total_cost_usd":0}}'
assert_not_contains "no prefix when neither present"       "$NEITHER" "wt:"

# Empty-string names are absent, not present-and-blank -- otherwise the line opens
# with a stray separator.
EMPTY_NAMES='{"agent":{"name":""},"worktree":{"name":""},"cost":{"total_cost_usd":0}}'
assert_not_contains "empty agent/worktree names add no prefix" "$EMPTY_NAMES" "wt:"

echo
echo "--- exit code is always 0 (a statusline must never break the prompt) ---"
for p in "$FULL" 'not json' '' '{}'; do
  _render "$p" >/dev/null 2>&1
  rc=$?
  _record ALLOW "$(_classify "$rc")" "statusline exits 0 for payload: ${p:0:24}"
done

echo
_summary "statusline"
exit $?
