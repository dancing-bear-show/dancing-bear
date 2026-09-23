#!/usr/bin/env bash
# Assert every promise in guard-contract.yaml against block-readonly-role-writes.sh.
#
# This suite is derived from a SPEC, not from history. Its sibling
# block-readonly-role-writes.test.sh grew one case per review finding and so records
# what has already gone wrong; this one records what the guard is supposed to do. A
# promise added to the YAML without an implementation fails here, which is the point.
#
# Usage: bash guard-contract.test.sh [path-to-hook]
# Exit:  0 = all pass, 1 = any failure. Requires jq and python3 (for YAML).

HOOK="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/block-readonly-role-writes.sh}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONTRACT="$HERE/guard-contract.yaml"

# shellcheck source=./_harness.sh
. "$HERE/_harness.sh"

if [ ! -f "$HOOK" ]; then
  echo "hook not found: $HOOK" >&2
  exit 1
fi
if [ ! -f "$CONTRACT" ]; then
  echo "contract not found: $CONTRACT" >&2
  exit 1
fi

REPO_ROOT=$(cd "$(dirname "$HOOK")/../.." && pwd)
echo "testing: $HOOK"
echo "contract: $CONTRACT"
echo

# Flatten the YAML to one tab-separated record per case, so the shell does not have
# to parse YAML. python3 is already required by the repo; PyYAML ships with the venv
# and the stdlib fallback keeps this runnable outside it.
# A scratch directory for the symlink cases. Resolved with `pwd -P` so a platform
# whose tmpdir is itself a symlink (macOS /tmp -> /private/tmp) does not make every
# link case look like it resolves somewhere unexpected.
SCRATCH=$(cd -P "$(mktemp -d)" && pwd -P)
cleanup_scratch() { [ -n "$SCRATCH" ] && rm -rf "$SCRATCH"; }

FLAT=$(python3 - "$CONTRACT" "$REPO_ROOT" "$SCRATCH" <<'PY'
import sys

try:
    import yaml
except ImportError:  # pragma: no cover - venv always has it; CI installs it
    sys.stderr.write("PyYAML not available; cannot read the contract\n")
    sys.exit(3)

path, repo, tmp = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path, encoding="utf-8") as fh:
    doc = yaml.safe_load(fh)

import os

def expand(value):
    text = value or ""
    # Longest placeholder first: {REPO_PARENT} and {REPO_NAME} both contain {REPO}
    # as a prefix, so substituting {REPO} first would corrupt them.
    text = text.replace("{REPO_PARENT}", os.path.dirname(repo))
    text = text.replace("{REPO_NAME}", os.path.basename(repo))
    text = text.replace("{TMP}", tmp)
    return text.replace("{REPO}", repo)

for group in doc.get("promises", []):
    name = group.get("group", "(unnamed)")
    dirs = ",".join(group.get("needs_dirs", []) or [])
    # Symlinks a group needs, as link>target pairs joined by "|".
    links = "|".join(
        f'{expand(item["link"])}>{expand(item["target"])}'
        for item in (group.get("needs_links", []) or [])
    )
    if links:
        dirs = f"{dirs}#LINKS#{links}" if dirs else f"#LINKS#{links}"
    # Every field is emitted with a placeholder for "empty", because a bare empty
    # field between tabs is collapsed by `read -r a b c` in some shells and shifts
    # every later column by one -- which silently moved `expect` out of range and
    # made 110 of 120 cases assert nothing. A visible sentinel fails loudly instead.
    def cell(value):
        text = "" if value is None else str(value)
        # A real newline in a value (the command-separator cases carry one) would
        # split the record across two lines and leave the second half with no
        # `expect` column. Encode it; the shell decodes before running the case.
        text = text.replace("\\", "\\\\").replace("\n", "\\n").replace("\t", "\\t")
        return text if text != "" else "-"

    for case in group.get("cases", []) or []:
        print("\t".join([
            "case", cell(name), cell(dirs),
            cell(case.get("what")),
            cell(case.get("tool", "Write")),
            cell(case.get("role", "researcher")),
            cell(expand(case.get("cwd", repo))),
            cell(expand(case.get("input"))),
            cell(case.get("expect", "block")),
        ]))
    for case in group.get("raw_cases", []) or []:
        print("\t".join([
            "raw", cell(name), cell(dirs),
            cell(case.get("what")),
            "-", "-", "-",
            cell(case.get("payload")),
            cell(case.get("expect", "block")),
        ]))
PY
) || { echo "failed to read the contract" >&2; exit 1; }

if [ -z "$FLAT" ]; then
  echo "contract produced no cases -- refusing to report a pass" >&2
  exit 1
fi

# Create any directory a group needs, remembering only what we made so a real
# workspace is left alone. Round 7's bug hid behind an absent directory: the ALLOW
# case passed because `outputs/` did not exist, not because the guard was right.
MADE_DIRS=""
# Symlinks are tracked too, and removed on exit. The round-14 rows link REPO-ROOT names
# (analysis, context, stages, ...) at src/, so leaving them behind would litter the
# working tree with links into source that a later `git status` reports as untracked.
MADE_LINKS=""
# ...and so is every directory `mkdir -p` creates to hold one. The link is removed on
# exit, but its parent (`analysis/` for `analysis/srclink`) was never recorded, so each
# run left eight empty directories (analysis/, out/, stages/, ...) at the repo root.
# `git status` cannot see an empty directory; mid-run each held a `srclink` that a
# concurrent changed-files scan picked up and handed to qlty, which then failed on a
# path that no longer existed.
MADE_LINK_PARENTS=""
ensure_dirs() {
  local spec="$1" csv="$spec" linkspec="" d pair
  # The flattener appends "#LINKS#a>b|c>d" when a group needs symlinks.
  case "$spec" in
    *"#LINKS#"*)
      csv="${spec%%#LINKS#*}"
      linkspec="${spec#*#LINKS#}"
      ;;
  esac

  if [ -n "$csv" ]; then
    local IFS=','
    for d in $csv; do
      [ -n "$d" ] || continue
      if [ ! -d "$REPO_ROOT/$d" ]; then
        # A FAILED mkdir must abort, not be skipped. Silently ignoring it lets a
        # workspace-root ALLOW row run against an absent directory and pass because
        # nothing was there -- which is round 7's bug exactly, reintroduced one level
        # up in the code that exists to prevent it. A setup failure is not a result.
        if ! mkdir -p "$REPO_ROOT/$d"; then
          echo "FATAL: could not create required directory '$d' for group setup." >&2
          echo "Aborting rather than running rows against an absent directory." >&2
          exit 1
        fi
        MADE_DIRS="$MADE_DIRS $d"
      fi
    done
  fi

  if [ -n "$linkspec" ]; then
    local IFS='|'
    for pair in $linkspec; do
      [ -n "$pair" ] || continue
      local link="${pair%%>*}" target="${pair#*>}"
      # `ln -sfn` over an existing REAL directory creates the link INSIDE it rather
      # than replacing it, so the case would then exercise a path that does not exist
      # and pass for the wrong reason. Anything already at the name that is not our
      # own symlink is a setup failure.
      if [ -e "$link" ] && [ ! -L "$link" ]; then
        echo "FATAL: '$link' already exists and is not a symlink." >&2
        echo "Refusing to run link rows against it." >&2
        exit 1
      fi
      # Record only ancestors that do not exist yet, so a real workspace is left
      # alone. Walked deepest first, and PREPENDED to the running list, so cleanup
      # removes a later link's directories before an earlier link's shared ancestor.
      local parent missing=""
      parent=$(dirname "$link")
      while [ ! -e "$parent" ] && [ ! -L "$parent" ]; do
        missing="$missing $parent"
        parent=$(dirname "$parent")
      done
      # Record BEFORE creating, never after: a mkdir that creates `analysis/` then
      # fails, or a signal between creation and bookkeeping, would otherwise leave
      # an untracked directory or link. Cleanup tolerates entries never created --
      # rmdir of a missing directory fails quietly, and a link is removed only if
      # [ -L ] -- so over-recording is harmless and under-recording leaks.
      MADE_LINK_PARENTS="$missing $MADE_LINK_PARENTS"
      MADE_LINKS="$MADE_LINKS $link"
      if ! mkdir -p "$(dirname "$link")"; then
        echo "FATAL: could not create the parent directory for link '$link'." >&2
        exit 1
      fi
      if ! ln -sfn "$target" "$link"; then
        echo "FATAL: could not create the symlink '$link' -> '$target'." >&2
        echo "Aborting rather than running link rows against a missing link." >&2
        exit 1
      fi
    done
  fi
}
cleanup_dirs() {
  # Pin IFS. bash scopes `local` dynamically, and ensure_dirs sets IFS to '|' or
  # ',' while it loops -- so any exit taken INSIDE it (every FATAL setup branch,
  # or a signal mid-setup) ran this trap with that IFS, the space-joined lists
  # below never split, and nothing was removed. Measured: 10 of 10 mid-setup
  # signals left the link-group directories behind.
  local IFS=$' \t\n'
  local d l
  # Links first: one may sit inside a directory we also have to remove.
  for l in $MADE_LINKS; do [ -L "$l" ] && rm -f "$l"; done
  # rmdir, not rm -rf: it removes only an EMPTY directory, so anything a case wrote
  # into one survives to be noticed rather than being deleted with it.
  for d in $MADE_LINK_PARENTS; do rmdir "$d" 2>/dev/null; done
  for d in $MADE_DIRS; do rmdir "$REPO_ROOT/$d" 2>/dev/null; done
  cleanup_scratch
}
trap cleanup_dirs EXIT
# A signal must become an exit, or the EXIT trap may not run: measured, a SIGHUP
# mid-run left srclink symlinks and five empty directories at the repo root.
trap 'exit 1' INT TERM HUP

run_case() { # run_case <tool> <role> <cwd> <input> <expect> <label>
  local tool="$1" role="$2" cwd="$3" input="$4" expect="$5" label="$6" payload rc
  if [ "$tool" = "Bash" ]; then
    payload=$(jq -n --arg a "$role" --arg c "$cwd" --arg x "$input" \
      '{agent_type:$a,cwd:$c,tool_name:"Bash",tool_input:{command:$x}}')
  elif [ "$tool" = "Edit" ]; then
    payload=$(jq -n --arg a "$role" --arg c "$cwd" --arg p "$input" \
      '{agent_type:$a,cwd:$c,tool_name:"Edit",tool_input:{file_path:$p,old_string:"a",new_string:"b"}}')
  else
    payload=$(jq -n --arg a "$role" --arg c "$cwd" --arg p "$input" \
      '{agent_type:$a,cwd:$c,tool_name:"Write",tool_input:{file_path:$p,content:"x"}}')
  fi
  printf '%s' "$payload" | bash "$HOOK" >/dev/null 2>&1
  rc=$?
  _record "$(printf '%s' "$expect" | tr '[:lower:]' '[:upper:]')" "$(_classify "$rc")" "$label"
}

run_raw() { # run_raw <payload> <expect> <label>
  local rc
  printf '%s' "$1" | bash "$HOOK" >/dev/null 2>&1
  rc=$?
  _record "$(printf '%s' "$2" | tr '[:lower:]' '[:upper:]')" "$(_classify "$rc")" "$3"
}

current_group=""
while IFS=$'\t' read -r kind group dirs what tool role cwd input expect; do
  [ -n "$kind" ] || continue
  # Undo the "-" sentinel the flattener uses for empty cells.
  [ "$dirs"  = "-" ] && dirs=""
  [ "$cwd"   = "-" ] && cwd=""
  [ "$input" = "-" ] && input=""
  [ "$role"  = "-" ] && role=""
  # A record that lost its expect column is a flattener bug, not a passing case.
  case "$expect" in
    block|allow) ;;
    *)
      echo "FAIL  malformed contract record (expect=${expect:-<empty>}): $what" >&2
      fail=1; fail_count=$((fail_count + 1))
      continue
      ;;
  esac
  if [ "$group" != "$current_group" ]; then
    [ -n "$current_group" ] && echo
    echo "--- $group ---"
    current_group="$group"
    ensure_dirs "$dirs"
  fi
  # Decode what the flattener escaped, in the reverse order it was applied.
  input=${input//\\t/$'\t'}
  input=${input//\\n/$'\n'}
  input=${input//\\\\/\\}
  if [ "$kind" = "raw" ]; then
    run_raw "$input" "$expect" "$what"
  else
    run_case "$tool" "$role" "$cwd" "$input" "$expect" "$what"
  fi
done <<< "$FLAT"

_summary "guard-contract"
