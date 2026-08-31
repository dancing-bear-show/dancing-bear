"""Contract-duplication detector.

Finds test methods that duplicate an assertion already covered by a shared
contract mixin.  This is the defect class that clone detection structurally
cannot see: qlty matches token sequences, and the bodies are rarely textually
similar -- the confirmed phone/schedule case used keyword-argument form while
the contract used positional form.  Two consolidation passes (PRs #320, #329)
cleared the easy cases by counting test methods; they could not identify which
local methods were redundant without reading both sides.

How it works
------------
For each test file that contains AT LEAST ONE class that inherits a contract
mixin, the detector examines every OTHER class in that file (classes that do
not themselves inherit the mixin).  For each method in those other classes, it:

1. Skips the method if it uses ``patch`` / ``patch.object`` / ``mock_open`` --
   mocking indicates branch/conditional testing, which is always app-specific.
2. Collects the set of function names *called* in the method (``_calls``).
3. Compares against the called names in every mixin test method.
4. Keeps only the BEST mixin match (highest similarity) for each local method.
5. Flags the pair when:

       similarity >= 0.45  AND  |shared_calls| >= 3

   Jaccard similarity is over called function/method names.  The two conditions
   together rule out false-positive patterns:

   - Single-helper tests (e.g. ``assertIn("render", build_agentic_capsule())``)
     share only 1--2 calls and fail the ``>= 3`` gate.
   - Conditional-branch tests (using ``patch.object``) are excluded by the
     pre-filter in step 1.

   The combination leaves only methods that (a) call the same domain API
   function as the mixin and (b) make the same class of assertion.

Override detection
------------------
A local method whose name matches a mixin method name is NOT flagged -- it is
an intentional override.

Deduplication
-------------
Each (file, class, local_method) triplet is reported at most once, against its
best-scoring mixin method.  A true duplicate may score above threshold against
several mixin methods (e.g. an emit duplicate matches both
``test_emit_accepts_the_shared_positional_signature`` and
``test_emit_returns_zero_and_writes_the_capsule``); reporting only the top hit
avoids noise.

Threshold derivation
--------------------
Calibrated against three data points:

- Confirmed true positives (phone line 218, schedule line 128):
  {StringIO, assertEqual, emit_agentic_context, redirect_stdout} -- 4 shared
  calls, Jaccard 0.667.
- Confirmed false positive (charts ``test_contains_render_command``):
  {assertIn, build_agentic_capsule} -- 2 shared calls; does not reach 3.
- Calibration case (slides, shape fixed before this branch):
  {build_agentic_capsule, emit_agentic_context, getvalue} -- 3 shared calls,
  Jaccard 0.375.  The fixture in tests/test_detect_contract_duplication.py
  reproduces this shape and confirms it is still flagged.

Scope
-----
Only the four shared contract mixin files are compared:
  tests/agentic_builder_contract.py    AgenticBuilderContractMixin
  tests/agentic_cli_contract.py        AgenticCLIContractMixin
  tests/cli_separator_contract.py      SeparatorContractMixin
  tests/llm_cli_contract.py            LLMCLIContractMixin

Output
------
JSON on stdout, exit 0 regardless of finding count.  Findings are RANKED
SUSPICIONS, not defects; verify each pair by reading both methods before
deleting.  Low yield is expected: the value is regression prevention, not
clearing a backlog.
"""

from __future__ import annotations

import ast
import datetime
import json
import os
import sys

TESTS = "tests"
SKIP_WALK_DIRS = {
    ".git", ".venv", ".claude", "__pycache__", "node_modules",
    ".cache", "out", "_out", "backups", "personal_assistants.egg-info",
}

# Shared contract mixin modules and their class names.
MIXINS: dict[str, str] = {
    "tests/agentic_builder_contract.py": "AgenticBuilderContractMixin",
    "tests/agentic_cli_contract.py": "AgenticCLIContractMixin",
    "tests/cli_separator_contract.py": "SeparatorContractMixin",
    "tests/llm_cli_contract.py": "LLMCLIContractMixin",
}

# Similarity gate: Jaccard over called function/method names.
SIMILARITY_THRESHOLD = 0.45
# Minimum shared calls: single-helper tests (1-2 shared calls) are
# app-specific content assertions, not duplicates.
MIN_SHARED_CALLS = 3

# Call names that indicate mocking / conditional-branch testing.  A method
# that patches implementation details is testing app-specific behaviour, not
# duplicating a contract invariant.
_MOCK_INDICATORS = frozenset({"patch", "mock_open", "MagicMock", "AsyncMock", "Mock"})


# ---------------------------------------------------------------------------
# AST helpers
# ---------------------------------------------------------------------------

def _parse(path: str) -> ast.Module | None:
    try:
        with open(path, encoding="utf-8") as fh:
            return ast.parse(fh.read(), filename=path)
    except (OSError, SyntaxError, ValueError):
        return None  # nosec B112 - skip unreadable/unparseable files silently


def _calls(node: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    """Return the set of bare function/method names called in a method body.

    For a bare call ``foo()``: adds ``foo``.
    For a method call ``obj.method()``: adds ``method``.
    Self-references (``self``) are excluded -- they inflate every method's
    score identically and do not discriminate between duplicates and originals.
    """
    names: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            func = n.func
            if isinstance(func, ast.Name):
                if func.id != "self":
                    names.add(func.id)
            elif isinstance(func, ast.Attribute):
                names.add(func.attr)
    return frozenset(names)


def _all_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> frozenset[str]:
    """Return ALL Name ids appearing anywhere in the method body.

    Used by ``_uses_mocking`` to detect ``patch.object(...)`` where the
    ``ast.Call.func`` attribute is ``object`` (not ``patch``), but ``patch``
    still appears as a ``Name`` node in the call expression's value chain.
    """
    names: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Name):
            names.add(n.id)
    return frozenset(names)


def _uses_mocking(method_node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return True if the method uses patch / MagicMock / etc.

    Methods that mock implementation details test conditional branches, which
    is always app-specific -- never a duplicate of a contract invariant.
    Checks all Name ids in the method body (not just call names) so that
    ``patch.object(...)`` -- where the call attr is ``object`` -- is still
    detected via the ``patch`` Name in the value chain.
    """
    return bool(_all_names(method_node) & _MOCK_INDICATORS)


def _test_methods(
    cls_node: ast.ClassDef,
) -> dict[str, tuple[frozenset[str], int, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """Return {name: (called_names, lineno, node)} for test_* methods in the class."""
    result: dict[str, tuple[frozenset[str], int, ast.FunctionDef | ast.AsyncFunctionDef]] = {}
    for node in cls_node.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("test_"):
                result[node.name] = (_calls(node), node.lineno, node)
    return result


def _base_names(cls_node: ast.ClassDef) -> list[str]:
    """Return the simple base-class names for a class (no module resolution)."""
    bases: list[str] = []
    for base in cls_node.bases:
        if isinstance(base, ast.Name):
            bases.append(base.id)
        elif isinstance(base, ast.Attribute):
            bases.append(base.attr)
    return bases


# ---------------------------------------------------------------------------
# Mixin method index
# ---------------------------------------------------------------------------

def _load_mixin_methods(
    mixin_file: str, mixin_class: str,
) -> dict[str, frozenset[str]]:
    """Return {method_name: called_names} for all test methods in the mixin."""
    tree = _parse(mixin_file)
    if tree is None:
        return {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == mixin_class:
            return {
                name: calls
                for name, (calls, _lineno, _node) in _test_methods(node).items()
            }
    return {}


# ---------------------------------------------------------------------------
# Similarity
# ---------------------------------------------------------------------------

def _jaccard(a: frozenset[str], b: frozenset[str]) -> float:
    union = len(a | b)
    if union == 0:
        return 0.0
    return len(a & b) / union


# ---------------------------------------------------------------------------
# Scanner
# ---------------------------------------------------------------------------

def _iter_test_files() -> list[str]:
    for dirpath, dirnames, filenames in os.walk(TESTS):
        dirnames[:] = [d for d in dirnames if d not in SKIP_WALK_DIRS]
        for fn in sorted(filenames):
            if fn.endswith(".py") and fn.startswith("test_"):
                yield os.path.join(dirpath, fn)


def _adopted_mixins_in_file(
    classes: list[ast.ClassDef],
    mixin_index: dict[str, dict[str, frozenset[str]]],
) -> set[str]:
    """Return the set of mixin class names adopted by any class in the file."""
    adopted: set[str] = set()
    for cls_node in classes:
        for base in _base_names(cls_node):
            if base in mixin_index:
                adopted.add(base)
    return adopted


def _best_match_for_method(
    local_name: str,
    local_calls: frozenset[str],
    local_line: int,
    local_node: ast.FunctionDef | ast.AsyncFunctionDef,
    mixin_class: str,
    mixin_methods: dict[str, frozenset[str]],
    test_file: str,
    class_name: str,
) -> dict | None:
    """Return the finding dict for the best mixin match, or None if no match."""
    if _uses_mocking(local_node):
        return None
    best_sim = -1.0
    best: dict | None = None
    for mixin_name, mixin_calls in mixin_methods.items():
        shared = local_calls & mixin_calls
        sim = _jaccard(local_calls, mixin_calls)
        if sim < SIMILARITY_THRESHOLD or len(shared) < MIN_SHARED_CALLS:
            continue
        if sim > best_sim:
            best_sim = sim
            best = {
                "kind": "contract-duplication",
                "file": test_file,
                "class": class_name,
                "local_method": local_name,
                "local_line": local_line,
                "mixin": mixin_class,
                "mixin_method": mixin_name,
                "similarity": round(sim, 3),
                "shared_calls": sorted(shared),
                "shared_call_count": len(shared),
            }
    return best


def _scan_class(
    cls_node: ast.ClassDef,
    adopted_mixins: set[str],
    mixin_index: dict[str, dict[str, frozenset[str]]],
    test_file: str,
    best: dict[tuple[str, str, str], dict],
) -> None:
    """Update ``best`` with the top-scoring finding for each local method."""
    if set(_base_names(cls_node)) & adopted_mixins:
        return  # adopter class -- skip

    local_methods = _test_methods(cls_node)
    if not local_methods:
        return

    for mixin_class in adopted_mixins:
        mixin_methods = mixin_index[mixin_class]
        mixin_names = set(mixin_methods.keys())
        for local_name, (local_calls, local_line, local_node) in local_methods.items():
            if local_name in mixin_names:
                continue  # intentional override -- skip
            candidate = _best_match_for_method(
                local_name, local_calls, local_line, local_node,
                mixin_class, mixin_methods, test_file, cls_node.name,
            )
            if candidate is None:
                continue
            key = (test_file, cls_node.name, local_name)
            existing = best.get(key)
            if existing is None or candidate["similarity"] > existing["similarity"]:
                best[key] = candidate


def scan() -> list[dict]:
    """Scan the tests/ tree and return ranked contract-duplication findings."""
    mixin_index: dict[str, dict[str, frozenset[str]]] = {
        mixin_class: _load_mixin_methods(mixin_file, mixin_class)
        for mixin_file, mixin_class in MIXINS.items()
        if os.path.isfile(mixin_file)
    }

    # One finding per (file, class, local_method) -- the best mixin match wins.
    best: dict[tuple[str, str, str], dict] = {}

    for test_file in _iter_test_files():
        tree = _parse(test_file)
        if tree is None:
            continue
        classes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        adopted_mixins = _adopted_mixins_in_file(classes, mixin_index)
        if not adopted_mixins:
            continue
        for cls_node in classes:
            _scan_class(cls_node, adopted_mixins, mixin_index, test_file, best)

    findings = list(best.values())
    findings.sort(
        key=lambda f: (
            -f["similarity"],
            -f["shared_call_count"],
            f["file"],
            f["class"],
            f["local_method"],
        )
    )
    return findings


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main(_argv: list[str]) -> int:
    findings = scan()

    json.dump(
        {
            "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "similarity_threshold": SIMILARITY_THRESHOLD,
            "min_shared_calls": MIN_SHARED_CALLS,
            "finding_count": len(findings),
            "note": (
                "Ranked suspicions, not defects. Verify each pair by reading "
                "both the local method and the mixin method before deleting. "
                "Low yield is expected and intentional: the value is regression "
                "prevention, not clearing a backlog."
            ),
            "findings": findings,
        },
        sys.stdout,
        indent=2,
    )
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
