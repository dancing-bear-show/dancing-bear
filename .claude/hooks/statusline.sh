#!/usr/bin/env bash
# Claude Code statusLine renderer.
#
# Reads the statusline JSON payload on stdin and prints one line:
#   [agent|wt:name] branch │ dir │ context-bar % │ +added/-removed │ model │ $cost │ duration (api wait)
#
# Wire it up with the statusLine block in settings.json -- see hooks/README.md.

input=$(cat)

RESET='\033[0m'
CYAN='\033[36m'
GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'
MAGENTA='\033[35m'
BLUE='\033[34m'
DIM='\033[2m'

# One jq call, newline-delimited. Deliberately not ten calls: the statusline renders
# on every turn, and each jq process is a fork -- ten of them is a visible hitch.
#
# CHANGED FROM THE REFERENCE: context percentage no longer defaults to 0.
#
# The original used `(.context_window.used_percentage // 0)`, so an absent
# .context_window rendered a full green bar reading "0%" -- indistinguishable from a
# genuinely empty context window. That is the worst kind of wrong reading: confident,
# plausible, and pointing the opposite direction from the truth. A session at 85%
# looked like a session at 0%, which is precisely when you most need the number.
#
# Absent now yields the sentinel "?" and renders as a dim "--" bar. Unknown looks
# unknown. The same reasoning applies to the model name, which keeps the original's
# "?" fallback.
#
# The `if type == "object"` guard is what rejects a top-level scalar.
#
# A literal `null` payload is VALID JSON, and `null.model.display_name` is `null` in jq
# rather than an error -- so every `// fallback` below fired, jq exited 0, and the
# unreadable-payload branch was never reached. The result was a fully plausible status
# line: a real branch name, a real directory, "?" for the model, "$0.00", "0m (0s api)".
# Nothing about it looked wrong, which is the entire problem -- the same "confident and
# false" failure the `// 0` removal above was made to prevent, arriving through the one
# door that check does not watch. `3`, `"hello"`, and `[1,2,3]` behave the same way
# (the array errors on field access, but only by luck of jq's typing rules, not by
# design). A payload that is not an object has no fields to fall back FROM, so it is
# unreadable by definition and must say so.
#
# `printf '%s'` rather than `echo`: echo is unspecified for a leading `-` (bash's
# builtin eats `-n`/`-e`/`-E` as flags) and for backslash escapes, and it appends a
# newline the payload did not contain. A statusline payload is arbitrary JSON arriving
# from outside this script, so none of those are hypothetical -- `printf '%s'` passes
# the bytes through unchanged.
#
# The `if !` capture is what makes a PARTIAL jq failure readable. jq streams its outputs
# as it produces them, so a payload like `{"context_window":"bad"}` prints the first
# three values and THEN errors on the type comparison. VALUES came back non-empty, the
# emptiness check below was skipped, and the script rendered a line with an empty
# PERCENT -- which is not a number, so `[ "$PERCENT" -ge 80 ]` printed
# `[: : integer expected` to the terminal and the bar rendered with a blank percentage.
# A half-filled VALUES is exactly as unreadable as an empty one; the difference is that
# the empty case announced itself and the partial case emitted a broken status line plus
# shell errors. Testing jq's EXIT STATUS covers both, where testing its output covered
# only one.
if ! VALUES=$(printf '%s' "$input" | jq -r '
  if type != "object" then error("not an object") else . end |
  (.model.display_name // "?"),
  (.cost.total_cost_usd // 0),
  (.workspace.current_dir // "."),
  (if (.context_window.used_percentage | type) == "number"
     then (.context_window.used_percentage | floor) else "?" end),
  (.cost.total_lines_added // 0),
  (.cost.total_lines_removed // 0),
  (.cost.total_duration_ms // 0),
  (.cost.total_api_duration_ms // 0),
  (.agent.name // ""),
  (.worktree.name // "")
' 2>/dev/null); then
  echo -e "${DIM}(statusline: unreadable payload)${RESET}"
  exit 0
fi

# A payload that is not JSON at all leaves VALUES empty even when jq exits 0 (an empty
# input produces no output and no error). Still checked separately from the exit status
# above: the two failures are different and neither implies the other.
if [ -z "$VALUES" ]; then
  echo -e "${DIM}(statusline: unreadable payload)${RESET}"
  exit 0
fi

MODEL=$(sed -n '1p' <<< "$VALUES")
COST=$(sed -n '2p' <<< "$VALUES")
DIR=$(sed -n '3p' <<< "$VALUES")
PERCENT=$(sed -n '4p' <<< "$VALUES")
LINES_ADD=$(sed -n '5p' <<< "$VALUES")
LINES_REM=$(sed -n '6p' <<< "$VALUES")
DURATION_MS=$(sed -n '7p' <<< "$VALUES")
API_MS=$(sed -n '8p' <<< "$VALUES")
AGENT=$(sed -n '9p' <<< "$VALUES")
WORKTREE=$(sed -n '10p' <<< "$VALUES")

BRANCH=""
if git rev-parse --git-dir > /dev/null 2>&1; then
    BRANCH=$(git branch --show-current 2>/dev/null)
fi
BRANCH=${BRANCH:-"no-repo"}

DIR_NAME=${DIR##*/}

# Repeat a (possibly multi-byte) string N times.
#
# NOT `printf '%*s' N '' | tr ' ' '<char>'`, which is the obvious spelling and is
# wrong: tr translates BYTES, so under a non-UTF-8 locale (LANG unset on a CI
# runner, LC_ALL=C) it maps each space to only the FIRST byte of the character.
# '·' is c2b7, so a 10-wide bar came out as ten 0xc2 bytes -- invalid UTF-8 that
# renders as mojibake locally and crashed the Python test wrapper's decode in CI.
# Bash string ops carry the whole character regardless of locale.
_repeat() {
    local out='' i
    for ((i = 0; i < $2; i++)); do out+="$1"; done
    printf '%s' "$out"
}

# Context bar. Green under 50%, yellow at 50%, red at 80% -- thresholds unchanged
# from the reference. The "?" branch is the new unknown state.
BAR_WIDTH=10
if [ "$PERCENT" = "?" ]; then
    BAR_COLOR="$DIM"
    BAR=$(_repeat '·' "$BAR_WIDTH")
    PERCENT_FMT="--"
else
    FILLED=$((PERCENT * BAR_WIDTH / 100))
    EMPTY=$((BAR_WIDTH - FILLED))
    if [ "$PERCENT" -ge 80 ]; then
        BAR_COLOR="$RED"
    elif [ "$PERCENT" -ge 50 ]; then
        BAR_COLOR="$YELLOW"
    else
        BAR_COLOR="$GREEN"
    fi
    BAR="$(_repeat '█' "$FILLED")$(_repeat '░' "$EMPTY")"
    PERCENT_FMT="${PERCENT}%"
fi

COST_FMT=$(printf "%.2f" "$COST" 2>/dev/null || echo "?")

DURATION_MIN=$((DURATION_MS / 60000))
if [ "$DURATION_MIN" -ge 60 ]; then
    DURATION_FMT="$((DURATION_MIN / 60))h$((DURATION_MIN % 60))m"
else
    DURATION_FMT="${DURATION_MIN}m"
fi

API_SEC=$((API_MS / 1000))
if [ "$API_SEC" -ge 60 ]; then
    API_FMT="$((API_SEC / 60))m$((API_SEC % 60))s"
else
    API_FMT="${API_SEC}s"
fi

LINES_CHANGED="${GREEN}+${LINES_ADD}${RESET}/${RED}-${LINES_REM}${RESET}"

# Agent / worktree prefix.
#
# This matters more in dancing-bear than in the original repo: sessions run under
# .claude/worktrees/ by default (`claude -w`), subagents get their own isolated
# worktrees, and the directory name alone does not tell you which branch's worktree
# you are looking at. Committing to the wrong worktree is the mistake this prefix is
# here to prevent.
PREFIX=""
if [ -n "$AGENT" ]; then
    PREFIX="${MAGENTA}${AGENT}${RESET} ${DIM}│${RESET} "
elif [ -n "$WORKTREE" ]; then
    PREFIX="${MAGENTA}wt:${WORKTREE}${RESET} ${DIM}│${RESET} "
fi

LEFT="${PREFIX}${CYAN}${BRANCH}${RESET} ${DIM}│${RESET} ${BLUE}${DIR_NAME}${RESET} ${DIM}│${RESET} ${BAR_COLOR}${BAR}${RESET} ${PERCENT_FMT}"
RIGHT="${LINES_CHANGED} ${DIM}│${RESET} ${MAGENTA}${MODEL}${RESET} ${DIM}│${RESET} ${GREEN}\$${COST_FMT}${RESET} ${DIM}│${RESET} ${DIM}${DURATION_FMT} (${API_FMT} api)${RESET}"

echo -e "${LEFT} ${DIM}│${RESET} ${RIGHT}"
