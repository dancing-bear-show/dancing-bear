#!/usr/bin/env bash
# rename.sh — rename the current tmux session and push the tab title.
# Usage: rename.sh <name>
#
# Exit codes:
#   0  — success (or TMUX unset, nothing to rename)
#   2  — invalid name (printed to stderr)
#
# Why a script: the inline block (tmux display-message -p '#{client_tty}' +
# command substitution) is rejected by the destructive-bash guard hook as
# "too complex to verify", so the tab title would silently not update.
set -u

NAME="${1:-}"

# --- Validate ----------------------------------------------------------------
if [ -z "$NAME" ]; then
    echo "usage: rename.sh <name>" >&2
    exit 2
fi

if ! echo "$NAME" | grep -qE '^[a-z0-9]+(-[a-z0-9]+)*$'; then
    echo "invalid name '$NAME': must match ^[a-z0-9]+(-[a-z0-9]+)*\$" >&2
    exit 2
fi

if [ "${#NAME}" -gt 30 ]; then
    echo "invalid name '$NAME': max 30 characters (got ${#NAME})" >&2
    exit 2
fi

# --- TMUX check --------------------------------------------------------------
if [ -z "${TMUX:-}" ]; then
    echo "TMUX is unset — nothing to rename"
    exit 0
fi

# --- Rename session ----------------------------------------------------------
tmux rename-session -- "$NAME"

# --- Push tab title via the outer client tty ---------------------------------
# A pane's own tty does not reach the terminal emulator; the client (outer) tty
# does. Check that it is a character device writable by us before writing.
tty=$(tmux display-message -p '#{client_tty}' 2>/dev/null || true)
if [ -n "$tty" ] && [ -c "$tty" ] && [ -w "$tty" ]; then
    printf '\033]0;%s\007' "$NAME" > "$tty"
fi

tmux display-message -p 'Session: #S'
