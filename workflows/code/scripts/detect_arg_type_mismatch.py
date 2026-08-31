"""Argument-type mismatch detector — static heuristic for S5655 candidates.

Finds call sites where a literal constant (None, a str, an int, …) is passed
positionally to a parameter whose annotation clearly excludes that type.

Implementation note: the detector is split across sibling modules prefixed
``_argtype_`` to keep per-file complexity manageable.  This file is the entry
point and the public API surface; the logic lives in:
- ``_argtype_common.py``     -- shared state (_STATS, _AMBIGUOUS), walk helpers
- ``_argtype_signatures.py`` -- signature collection pass
- ``_argtype_types.py``      -- type-compatibility predicates
- ``_argtype_scan.py``       -- call-site scanning pass

WHY THIS EXISTS
---------------
qlty's ``radarlint-python:python:S5655`` ("Change this argument; Function X
expects a different type") is nondeterministically capped per run.  Measured on
this repo: a single run finds 0–4 findings, different ones each time; a 28-run
union still found only 2; a static AST pass found 14 — a strict superset.  That
gap is why a repo-internal detector is worth having.

KNOWN LIMITATIONS
-----------------
- Only *literal* constants are inspected (``None``, string/int/float literals).
  Variables and expressions are not resolved.
- Only calls whose callee name was explicitly imported via ``from X import Y``
  are resolved.  Attribute calls (``obj.method()``) are genuinely skipped: the
  receiver carries the type, and matching on the bare attribute name made
  ``a.foo()``, ``b.foo()`` and ``self.foo()`` indistinguishable.
- Only positional arguments are inspected.  Keyword arguments, ``*args`` /
  ``**kwargs``, and default values are not, and a signature rewritten by a
  decorator is read as written.  ``@overload`` resolves to whichever ``def``
  is parsed last.
- The signature table is keyed by ``(module_stem, funcname)``, which cannot
  distinguish sibling classes in one file -- ``consumers.consume`` is defined
  37 times in a single module.  Ambiguous keys are DROPPED, not guessed (122 on
  this repo); ``stats.signatures_ambiguous_dropped`` reports how many, so the
  blind spot is visible rather than silent.
- Nested and inner functions are not collected: only module-level ``def`` and
  class bodies are walked.
- The resolver is heuristic, not a type-checker.  Verify each finding before
  acting on it.
- Annotations are compared as PARSED syntax, not resolved types.  The None
  check inspects top-level union members, so ``dict[str, Any]`` is correctly
  None-hostile (a substring test accepted it -- 270 parameters on this repo,
  the single most common annotation).  What remains unresolved is anything
  requiring name resolution: a bare ``TypeVar`` (``T``) or an alias such as
  ``JsonValue`` is reported even when it permits None, because the name alone
  does not say so.

CONFIDENCE
----------
Findings are CANDIDATES, not proven defects.  The note field in the JSON output
says so explicitly.  Follow ``detect_unadopted.py``'s precedent: "Read before
acting."

USAGE
-----
Run from the repo root (the script discovers ``src/`` and ``tests/`` relative
to ``cwd``):

    python3 workflows/code/scripts/detect_arg_type_mismatch.py

Optional env vars:
    SRC_ROOT   — directory to scan for signatures (default: ``src``)
    TEST_ROOT  — directory to scan for call sites (default: ``tests``)
"""

from __future__ import annotations

import json
import os
import sys

# Bootstrap: add our own directory to sys.path so the sibling _argtype_*
# modules can be found via plain absolute imports regardless of how this file
# is invoked (subprocess by absolute path, importlib.util.spec_from_file_location
# with no package context, or direct `python3 <path>`).
_SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from _argtype_common import _STATS  # noqa: E402
from _argtype_signatures import (  # noqa: E402
    _collect_class_sigs,
    _collect_params,
    _has_staticmethod_decorator,
    collect_signatures,
)
from _argtype_scan import scan_test_files  # noqa: E402
from _argtype_types import _is_mismatch  # noqa: E402

# ---------------------------------------------------------------------------
# Re-export the public API for importlib-loaded tests.
# tests/test_detect_arg_type_mismatch.py loads this file via
# importlib.util.spec_from_file_location and then accesses these names as
# attributes of the loaded module object.  The imports above make them
# available; the explicit list below documents the contract.
# ---------------------------------------------------------------------------
__all__ = [
    "collect_signatures",
    "scan_test_files",
    "_collect_params",
    "_is_mismatch",
    # Also accessed by tests via _dm.<name>:
    "_collect_class_sigs",
    "_has_staticmethod_decorator",
    "main",
]

SRC_ROOT = os.environ.get("SRC_ROOT", "src")
TEST_ROOT = os.environ.get("TEST_ROOT", "tests")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    src_root = argv[1] if len(argv) > 1 else SRC_ROOT
    test_root = argv[2] if len(argv) > 2 else TEST_ROOT

    sigs = collect_signatures(src_root)
    findings = scan_test_files(test_root, sigs)

    # An empty scan is a tooling failure, not a clean result, so it exits
    # non-zero rather than printing a reassuring "0 findings". A wrong root, a
    # rename, or a tree that failed to parse would otherwise be byte-identical
    # to a genuinely clean run -- which is the false-clean class this detector
    # exists to work around, and would be embarrassing to reproduce in it.
    scanned_nothing = (
        _STATS["src_files_scanned"] == 0
        or _STATS["test_files_scanned"] == 0
        or _STATS["signatures_collected"] == 0
    )

    json.dump(
        {
            "src_root": src_root,
            "test_root": test_root,
            "total_findings": len(findings),
            "stats": dict(_STATS),
            "scanned_nothing": scanned_nothing,
            "note": (
                "Candidates only — not proven defects.  The resolver is heuristic: "
                "import-based, positional, literal-only.  A same-named function in "
                "an unrelated module can produce a false positive.  Read each finding "
                "before acting.  Check `stats` before trusting a zero: 0 findings with "
                "0 files scanned is a broken run, not a clean tree."
            ),
            "findings": findings,
        },
        sys.stdout,
        indent=2,
    )
    print()

    if scanned_nothing:
        print(
            f"ERROR: scanned nothing (src={src_root!r} test={test_root!r}); "
            "0 findings here means the run is broken, not that the tree is clean",
            file=sys.stderr,
        )
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
