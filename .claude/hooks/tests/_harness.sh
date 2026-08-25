#!/usr/bin/env bash
# Shared assertion harness for the guard-hook suites. Sourced, not executed.
#
# WHY THIS IS NOT `[ "$rc" -eq 2 ] && got=BLOCK || got=ALLOW`
# -----------------------------------------------------------
# Both suites used to classify with exactly that line, which folds EVERY non-2 exit
# code into ALLOW. A hook that dies on `set -u` referencing an unset variable exits 1;
# a hook whose jq is missing exits 127; a hook killed by a signal exits 130+. Under
# the old classifier all three were reported as `ok ALLOW` on any case expecting
# ALLOW -- so a hook that had stopped running at all still printed ALL PASS across the
# whole allow half of the suite.
#
# That is the same fail-open shape the hooks themselves were fixed for: the failure of
# the inspecting step read as approval. A test suite that cannot tell "allowed" from
# "crashed" cannot detect a fail-closed regression, which is the only regression that
# matters here.
#
# So: 0 is ALLOW, 2 is BLOCK, and anything else is a TEST FAILURE reported by its
# actual exit code and failing the suite regardless of what the case expected.

fail=0
pass_count=0
fail_count=0

# _classify <rc> -> prints ALLOW, BLOCK, or ERROR:<rc>
_classify() {
  case "$1" in
    0) printf 'ALLOW' ;;
    2) printf 'BLOCK' ;;
    *) printf 'ERROR:%s' "$1" ;;
  esac
}

# _record <expect> <got> <label>
_record() {
  local expect="$1" got="$2" label="$3"
  case "$got" in
    ERROR:*)
      printf 'FAIL  want=%-5s got=%s  %s\n' "$expect" "$got" "$label"
      printf '      ^ the hook exited with an unexpected code. That is a hook crash,\n'
      printf '        not an allow decision -- see the note in tests/_harness.sh.\n'
      fail=1; fail_count=$((fail_count + 1))
      return
      ;;
  esac
  if [ "$got" = "$expect" ]; then
    printf 'ok    %-5s  %s\n' "$got" "$label"
    pass_count=$((pass_count + 1))
  else
    printf 'FAIL  want=%-5s got=%s  %s\n' "$expect" "$got" "$label"
    fail=1; fail_count=$((fail_count + 1))
  fi
}

# _summary <suite-name>
_summary() {
  echo
  printf '%s: %d passed, %d failed, %d total\n' \
    "$1" "$pass_count" "$fail_count" "$((pass_count + fail_count))"
  if [ "$fail" -eq 0 ]; then
    echo "ALL PASS"
  else
    echo "FAILURES PRESENT"
  fi
  return "$fail"
}
