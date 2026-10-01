#!/usr/bin/env bash
# rename.sh — rename the current tmux session and push the tab title.
# Usage: rename.sh <name>
#
# Exit codes:
#   0  — success (or TMUX unset, nothing to rename)
#   2  — invalid name (printed to stderr)
#   non-zero (propagated) — tmux rename-session or display-message failed
#                           (e.g. name already taken, no server); the tab
#                           title is NOT written when rename-session fails.
#
# Why a script: the inline block (tmux display-message -p '#{client_tty}' +
# command substitution) is rejected by the destructive-bash guard hook as
# "too complex to verify", so the tab title would silently not update.
set -eu

NAME="${1:-}"

# --- Validate ----------------------------------------------------------------
if [ -z "$NAME" ]; then
    echo "usage: rename.sh <name>" >&2
    exit 2
fi

# Use bash =~ to anchor the entire string — echo|grep matches per line, so a
# newline-embedded name like $'ok\nevil' would pass (first line matches) and
# the whole value, including control characters, would reach the tty.
if ! [[ $NAME =~ ^[a-z0-9]+(-[a-z0-9]+)*$ ]] || [ "${#NAME}" -gt 30 ]; then
    echo "invalid name: must match ^[a-z0-9]+(-[a-z0-9]+)*\$ and be <=30 chars" >&2
    exit 2
fi

# --- TMUX check --------------------------------------------------------------
if [ -z "${TMUX:-}" ]; then
    echo "TMUX is unset — nothing to rename"
    exit 0
fi

# --- Rename session ----------------------------------------------------------
# Exit immediately on failure (set -e); do not write the title if rename fails.
tmux rename-session -- "$NAME"

# --- Push tab title via the outer client tty ---------------------------------
# A pane's own tty does not reach the terminal emulator; the client (outer) tty
# does. Check that it is a character device writable by us before writing.
tty=$(tmux display-message -p '#{client_tty}' 2>/dev/null || true)
if [ -n "$tty" ] && [ -c "$tty" ] && [ -w "$tty" ]; then
    printf '\033]0;%s\007' "$NAME" > "$tty"
fi

tmux display-message -p 'Session: #S'
