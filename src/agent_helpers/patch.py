"""analyze-patch: extract structured data from a unified diff."""

from __future__ import annotations

import ast
import re
from pathlib import Path

EXTRACT_CHOICES = ("dispatch-map", "all-list", "imports", "added-functions")

_DISPATCH_NAMES = frozenset({"dispatch", "forward_map", "DISPATCH"})
_IMPORT_LINE = re.compile(r"[+-]\s*(import |from )")
_ADDED_DEF = re.compile(r"\+def ([A-Za-z_]\w*)\s*\(", re.ASCII)


def reconstruct_post_image(patch_text: str) -> str:
    """Build the post-patch file image from added and context lines.

    Headers (``+++``/``---``), hunk markers (``@@``), no-newline markers and
    removed lines are dropped; blank context lines are kept as empty lines.
    """
    kept: list[str] = []
    for line in patch_text.splitlines():
        if line.startswith(("+++", "---", "@@", "\\")):
            continue
        if line.startswith(("+", " ")):
            kept.append(line[1:])
        elif line == "":
            kept.append("")
    return "\n".join(kept)


def extract_imports(patch_text: str) -> list[dict[str, str]]:
    """Collect added/removed import lines from the diff."""
    results: list[dict[str, str]] = []
    for line in patch_text.splitlines():
        if line.startswith(("+++", "---")) or not _IMPORT_LINE.match(line):
            continue
        results.append({"op": "added" if line[0] == "+" else "removed", "line": line[1:].strip()})
    return results


def extract_added_functions(patch_text: str) -> list[str]:
    """Collect top-level function names from ``+def`` lines."""
    names: list[str] = []
    for line in patch_text.splitlines():
        match = None if line.startswith("+++") else _ADDED_DEF.match(line)
        if match:
            names.append(match.group(1))
    return names


def _assigned_values(tree: ast.AST, names: frozenset[str]) -> list[ast.expr]:
    """Right-hand sides of assignments targeting one of ``names``."""
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id in names for t in node.targets)
    ]


def extract_all_list(patch_text: str) -> list[str]:
    """Extract ``__all__`` items from the post-image (AST first, regex fallback)."""
    image = reconstruct_post_image(patch_text)
    try:
        for value in _assigned_values(ast.parse(image), frozenset({"__all__"})):
            if isinstance(value, ast.List):
                return [e.value for e in value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    except SyntaxError:  # partial-file patches rarely parse; the regex fallback below handles them
        pass  # nosec B110 - intentional fall-through to regex extraction
    match = re.search(r"__all__\s*=\s*\[([^\]]*)\]", image, re.DOTALL)
    return re.findall(r'["\']([^"\']+)["\']', match.group(1)) if match else []


def _dict_literal(node: ast.Dict) -> dict[str, object]:
    out: dict[str, object] = {}
    for key, value in zip(node.keys, node.values):
        if not isinstance(key, ast.Constant):
            continue
        try:
            out[str(key.value)] = ast.literal_eval(value)
        except (ValueError, TypeError):
            out[str(key.value)] = ast.unparse(value)  # non-literal RHS, e.g. a callable reference
    return out


def extract_dispatch_map(patch_text: str) -> dict[str, object]:
    """Extract a ``dispatch``/``forward_map`` dict from the post-image (AST first, regex fallback)."""
    image = reconstruct_post_image(patch_text)
    try:
        for value in _assigned_values(ast.parse(image), _DISPATCH_NAMES):
            result = _dict_literal(value) if isinstance(value, ast.Dict) else {}
            if result:
                return result
    except SyntaxError:  # partial-file patches rarely parse; the regex fallback below handles them
        pass  # nosec B110 - intentional fall-through to regex extraction
    match = re.search(r"dispatch\s*=\s*\{([^}]*)\}", image, re.DOTALL)
    if not match:
        return {}
    pairs = re.findall(r'["\']([^"\']+)["\']\s*:\s*["\']([^"\']+)["\']', match.group(1))
    return dict(pairs)


_EXTRACTORS = {
    "imports": extract_imports,
    "added-functions": extract_added_functions,
    "all-list": extract_all_list,
    "dispatch-map": extract_dispatch_map,
}


def analyze_patch(patch: str, extract: str) -> dict:
    """Read ``patch`` and run the named extractor; read errors land in ``error``."""
    try:
        text = Path(patch).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return {"patch": patch, "extract": extract, "results": [], "error": str(exc)}
    return {"patch": patch, "extract": extract, "results": _EXTRACTORS[extract](text)}
