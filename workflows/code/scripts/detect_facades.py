"""Facade detector — implements discover-facades from workflows/code/facade-elimination.yaml.

A PURE FACADE is a module whose top level contains only imports, __all__, and
alias assignments: imports > 0 AND defs == 0 AND other == 0.
`if TYPE_CHECKING:` blocks count as "other" (excluded, per the stage spec).
"""

from __future__ import annotations

import ast
import datetime
import json
import os
import re
import sys
from collections import defaultdict

SRC = "src"
SKIP_PARTS = {"maker", "__pycache__", "personal_assistants.egg-info"}
SKIP_WALK_DIRS = {
    ".git", ".venv", ".claude", "__pycache__", ".facade-work",
    "personal_assistants.egg-info", "node_modules", ".cache",
}
INCLUDE_INIT = os.environ.get("INCLUDE_INIT", "false").lower() == "true"
DOMAINS = os.environ.get("DOMAINS", "*")


def iter_py() -> list[str]:
    for dirpath, dirnames, filenames in os.walk(SRC):
        dirnames[:] = [d for d in dirnames if d not in SKIP_PARTS]
        for fn in sorted(filenames):
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def parse_py(path: str) -> ast.Module | None:
    """Parse a Python file, or return None if it cannot be read or parsed.

    Centralises the read so every call site closes its handle deterministically
    rather than relying on refcount finalisation of a bare open(...).read().
    """
    try:
        with open(path, encoding="utf-8") as fh:
            return ast.parse(fh.read())
    except (SyntaxError, UnicodeDecodeError, OSError):
        return None


def _classify_assignment(node: ast.Assign | ast.AnnAssign, names: list[str]) -> int:
    """Return 1 if assignment counts as "other", 0 if it is an alias re-export.

    Also appends re-exported names into `names`.
    Alias re-export: a bare Name or Attribute on the RHS (e.g. ``x = mod.x``).
    """
    tgt = ""
    if isinstance(node, ast.Assign):
        if node.targets and isinstance(node.targets[0], ast.Name):
            tgt = node.targets[0].id
    elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        tgt = node.target.id

    if tgt == "__all__":
        return 0

    if isinstance(node.value, (ast.Name, ast.Attribute)):
        if not tgt:
            # Target is not a simple Name -- tuple unpacking from a single RHS
            # (``a, b = mod.pair``), an attribute (``obj.attr = mod.x``), or a
            # subscript (``a[0] = mod.x``). None of these bind a module-level
            # name that another module could import, so they are not
            # re-exports. Appending the empty ``tgt`` here would put "" into
            # names_reexported and into the symbol map.
            return 1
        names.append(tgt)  # alias re-export
        return 0

    return 1  # counts as "other"


def _is_future_import(node: ast.ImportFrom) -> bool:
    """Return True for ``from __future__ import ...`` (compiler directive, not re-export)."""
    return node.module == "__future__"


def _collect_import_names(node: ast.Import | ast.ImportFrom, names: list[str]) -> None:
    """Append the locally bound names from an import statement into `names`.

    `from __future__ import ...` is filtered by callers before this runs.
    Wildcard imports (``import *``) are skipped — they bind no named symbol.
    """
    for a in node.names:
        if a.name != "*":
            names.append(a.asname or a.name.split(".")[0])


def classify(path: str) -> tuple[int, int, int, list[str]] | None:
    """Return (imports, defs, other, reexported_names) for a module's top level."""
    tree = parse_py(path)
    if tree is None:
        return None

    imports = defs = other = 0
    names: list[str] = []

    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue  # docstring

        if isinstance(node, (ast.Import, ast.ImportFrom)):
            # `from __future__ import annotations` is a compiler directive, not a
            # re-exported symbol. Skip it BEFORE incrementing: counting it would
            # let a module whose only top-level statements are a __future__ import
            # plus __all__ satisfy imports>0/defs==0/other==0 and be reported as a
            # pure facade with zero re-exports — proposing a real module for deletion.
            if isinstance(node, ast.ImportFrom) and _is_future_import(node):
                continue
            imports += 1
            _collect_import_names(node, names)

        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defs += 1

        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            other += _classify_assignment(node, names)

        else:
            other += 1  # includes `if TYPE_CHECKING:` — intentionally not skipped

    return imports, defs, other, names


def module_path(path: str) -> str:
    """Convert a filesystem path under SRC to a dotted module name.

    Uses os.path.relpath + os.sep (not a hard-coded "/") so this works on
    Windows and regardless of the caller's cwd relative to SRC.
    """
    rel = os.path.relpath(path, SRC).removesuffix(".py")
    return ".".join(rel.split(os.sep))


def _scan_file_lines(p: str, regex: re.Pattern[str]) -> list[str]:
    """Return "path:lineno" strings for every matching line in a single file."""
    try:
        with open(p, encoding="utf-8") as fh:
            lines = fh.readlines()
    except (OSError, UnicodeDecodeError):
        return []  # nosec B112 - skip unreadable/binary files silently

    return [
        f"{p}:{lineno}"
        for lineno, line in enumerate(lines, start=1)
        if regex.search(line)
    ]


def scan_lines(pattern: str, roots: list[str]) -> list[str]:
    """Pure-Python replacement for shelling out to `grep -rnE`.

    Returns "path:lineno" strings for every line matching `pattern` under the
    given root directories. Unreadable/binary files are skipped explicitly —
    a missing external grep binary previously failed silently (empty stdout),
    which this makes impossible since there's no external process to be absent.
    """
    regex = re.compile(pattern)
    hits: list[str] = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                if fn.endswith(".py"):
                    hits.extend(_scan_file_lines(os.path.join(dirpath, fn), regex))
    return hits


def _resolve_relative_import(level: int, module: str | None, pkg: str) -> str:
    """Resolve a relative import's dotted module path from a package base.

    ``level`` is the number of dots (1 = current package, 2 = parent, …).
    ``module`` is the name after the dots, or None for a bare ``from . import``.
    ``pkg`` is the dotted package path of the file containing the import.
    """
    base = pkg
    for _ in range(level - 1):
        base = base.rsplit(".", 1)[0] if "." in base else ""
    return f"{base}.{module}" if module else base


def imports_of(path: str) -> list[str]:
    """Modules this file imports from (absolute dotted, resolving relatives)."""
    tree = parse_py(path)
    if tree is None:
        return []
    mp = module_path(path)
    pkg = mp.rsplit(".", 1)[0] if "." in mp else ""
    found: list[str] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            if node.level:
                found.append(_resolve_relative_import(node.level, node.module, pkg))
            elif node.module:
                found.append(node.module)
        elif isinstance(node, ast.Import):
            found.extend(a.name for a in node.names)
    return found


# ---- Step 1-2: find pure facades -------------------------------------------
facades: dict[str, dict] = {}
for path in iter_py():
    if not INCLUDE_INIT and os.path.basename(path) == "__init__.py":
        continue
    res = classify(path)
    if res is None:
        continue
    imports, defs, other, names = res
    if imports > 0 and defs == 0 and other == 0:
        mod = module_path(path)
        domain = mod.split(".")[0]
        if DOMAINS != "*" and domain not in {d.strip() for d in DOMAINS.split(",")}:
            continue
        facades[mod] = {
            "module": mod, "path": path, "domain": domain,
            "names_reexported": len(names), "_names": names,
        }


# ---- Step 3-4: callers and patch targets -----------------------------------

def _file_pkg(p: str) -> str:
    """Return the dotted package path of a source file, or "" if not under SRC."""
    if not p.startswith(SRC + os.sep):
        return ""
    mp = module_path(p)
    return mp.rsplit(".", 1)[0] if "." in mp else ""


def _record_import_node(n: ast.Import, p: str, found: defaultdict) -> None:
    """Record plain ``import x`` nodes that reference a facade module."""
    for a in n.names:
        if a.name in facades:
            found[a.name].add(p)


def _record_import_from_node(
    n: ast.ImportFrom, p: str, pkg: str, found: defaultdict
) -> None:
    """Record ``from x import y`` nodes that reference a facade module.

    A string grep for `from <dotted.module> import` is relative-import-blind:
    `from .text_utils import x` inside src/calendars/importer/ targets
    calendars.importer.text_utils but shares no substring with it. It also
    misses lazy imports nested in function bodies, hence ast.walk over
    tree.body. Both forms are common in this repo and undercounting them makes
    a live facade look dead.
    """
    if n.level:
        tgt = _resolve_relative_import(n.level, n.module, pkg)
    else:
        tgt = n.module

    if tgt in facades:
        found[tgt].add(p)

    # `from worker import queue as q` binds a SUBMODULE, not a symbol:
    # node.module is the parent package ("worker"), so comparing
    # node.module alone never matches the facade ("worker.queue").
    # Callers then use it as `q.enqueue(...)`, and the alias also
    # shows up in patch strings as "worker.job_runtime.q.counts".
    if tgt:
        for a in n.names:
            cand = f"{tgt}.{a.name}"
            if cand in facades:
                found[cand].add(p)


def _collect_py_callers(p: str, found: defaultdict[str, set[str]]) -> None:
    """Walk all AST import nodes in file `p` and record facade references into `found`.

    Uses ast.walk (not tree.body) so lazy imports nested inside function bodies
    are also discovered — a body-only walk misses them, undercounting live callers.
    """
    tree = parse_py(p)
    if tree is None:
        return
    pkg = _file_pkg(p)
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            _record_import_node(n, p, found)
        elif isinstance(n, ast.ImportFrom):
            _record_import_from_node(n, p, pkg, found)


def ast_callers() -> defaultdict[str, set[str]]:
    """Map facade module -> set of files importing it, resolved via AST.

    A string grep for `from <dotted.module> import` is relative-import-blind:
    `from .text_utils import x` inside src/calendars/importer/ targets
    calendars.importer.text_utils but shares no substring with it. It also
    misses lazy imports nested in function bodies, hence ast.walk over
    tree.body. Both forms are common in this repo and undercounting them makes
    a live facade look dead.
    """
    found: defaultdict[str, set[str]] = defaultdict(set)
    for root, dirs, files_ in os.walk("."):
        dirs[:] = [d for d in dirs if d not in SKIP_WALK_DIRS]
        for fn in files_:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(root, fn).lstrip("./")
            _collect_py_callers(p, found)
    return found


_ast_hits = ast_callers()

for mod, f in facades.items():
    esc = re.escape(mod)
    files = sorted(_ast_hits.get(mod, set()) - {f["path"]})
    f["src_callers"] = sum(1 for x in files if x.startswith(SRC + os.sep))
    f["test_callers"] = sum(1 for x in files if x.startswith("tests" + os.sep))
    f["bin_callers"] = sum(1 for x in files if x.startswith("bin" + os.sep))
    f["caller_files"] = files
    # re.escape(mod) so "worker.queue" doesn't match the unrelated literal
    # "worker_queue" — that trap produced 20 indistinguishable false positives
    # during this sweep.
    patches = scan_lines(rf"(patch|patch\.object)\([\"']{esc}\.", ["tests", SRC])
    f["patch_targets"] = [h.split(":")[0] + ":" + h.split(":")[1] for h in patches]

# ---- Step 5: chains ---------------------------------------------------------
for mod, f in facades.items():
    f["chain_children"] = sorted({m for m in imports_of(f["path"]) if m in facades})


def depth(mod: str, seen: set[str] | None = None) -> int:
    seen = seen or set()
    if mod in seen:
        return 0  # cycle guard
    kids = facades[mod]["chain_children"]
    return 0 if not kids else 1 + max(depth(k, seen | {mod}) for k in kids)


for mod, f in facades.items():
    f["chain_depth"] = depth(mod)

# ---- Step 6: symbol -> terminal real module --------------------------------

def _module_file(mod: str) -> str | None:
    parts = mod.split(".")
    p = os.path.join(SRC, *parts) + ".py"
    if os.path.exists(p):
        return p
    p = os.path.join(SRC, *parts, "__init__.py")
    return p if os.path.exists(p) else None


def _binding_nodes(body: list[ast.stmt]):
    """Yield top-level nodes, descending into try/except/else and if bodies.

    Module-level constants are commonly assigned inside a try/except ImportError
    fallback (e.g. worker.queue_ops.QUEUE_ROOT), so a body-only walk misses them.
    """
    for n in body:
        yield n
        if isinstance(n, ast.Try):
            yield from _binding_nodes(n.body)
            for h in n.handlers:
                yield from _binding_nodes(h.body)
            yield from _binding_nodes(n.orelse)
            yield from _binding_nodes(n.finalbody)
        elif isinstance(n, ast.If):
            yield from _binding_nodes(n.body)
            yield from _binding_nodes(n.orelse)


def _node_defines_sym(n: ast.stmt, sym: str) -> bool:
    """Return True if AST node `n` defines the symbol `sym`."""
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return n.name == sym

    if isinstance(n, ast.Assign):
        return any(
            isinstance(t, ast.Name) and t.id == sym
            for t in n.targets
        )

    if isinstance(n, ast.AnnAssign):
        # e.g. ALL_VENDORS: List[VendorParser] = [...]
        return (
            isinstance(n.target, ast.Name)
            and n.target.id == sym
            and n.value is not None
        )

    return False


def defines(mod: str, sym: str) -> bool:
    """Return True if module `mod` directly defines symbol `sym`."""
    p = _module_file(mod)
    if not p:
        return False
    tree = parse_py(p)
    if tree is None:
        return False
    return any(_node_defines_sym(n, sym) for n in _binding_nodes(tree.body))


def _aliases_from_import(node: ast.Import) -> dict[str, str]:
    """Return alias->module entries from a plain ``import x`` or ``import x as y``."""
    return {a.asname or a.name.split(".")[0]: a.name for a in node.names}


def _aliases_from_import_from(node: ast.ImportFrom) -> dict[str, str]:
    """Return alias->module entries from ``from pkg import name`` where ``name`` is a submodule.

    Only absolute imports (``node.level == 0``) and named modules are considered.
    Names that resolve to symbols (not submodule files) are excluded so that
    only real submodule bindings end up in the alias map.
    """
    if not node.module or node.level:
        return {}
    result: dict[str, str] = {}
    for a in node.names:
        cand = f"{node.module}.{a.name}"
        if _module_file(cand):  # only when the name is a module, not a symbol
            result[a.asname or a.name] = cand
    return result


def _build_alias_to_mod(body: list[ast.stmt]) -> dict[str, str]:
    """Build a local-alias -> dotted-module map from a module's top-level body.

    Covers both binding forms:
      import core.llm_cli as _x        (ast.Import)
      from core import llm_cli as _x   (ast.ImportFrom binding a submodule)
    """
    alias_to_mod: dict[str, str] = {}
    for node in body:
        if isinstance(node, ast.Import):
            alias_to_mod.update(_aliases_from_import(node))
        elif isinstance(node, ast.ImportFrom):
            alias_to_mod.update(_aliases_from_import_from(node))
    return alias_to_mod


def _resolve_import_from(
    node: ast.ImportFrom, sym: str, pkg: str, hops: int
) -> str | None:
    """Resolve Form 1: ``from <mod> import <sym>``.

    Returns the module that defines sym, or None if not found via this node.
    """
    target = next(
        (a.name for a in node.names if (a.asname or a.name) == sym), None
    )
    if target is None:
        return None

    if node.level:
        src_mod = _resolve_relative_import(node.level, node.module, pkg)
    else:
        src_mod = node.module

    if defines(src_mod, target):
        return src_mod
    return resolve(src_mod, target, hops + 1)


def _resolve_alias_assign(
    node: ast.Assign, sym: str, alias_to_mod: dict[str, str], hops: int
) -> str | None:
    """Resolve Form 2: ``<sym> = <alias>.<attr>`` (attribute alias re-export).

    Returns the module that defines the attribute, or None if not applicable.
    """
    if not isinstance(node.value, ast.Attribute):
        return None
    tgt = node.targets[0] if node.targets else None
    if not (isinstance(tgt, ast.Name) and tgt.id == sym):
        return None
    base_node, attr = node.value.value, node.value.attr
    if not isinstance(base_node, ast.Name):
        return None
    src_mod = alias_to_mod.get(base_node.id)
    if not src_mod:
        return None
    if defines(src_mod, attr):
        return src_mod
    return resolve(src_mod, attr, hops + 1)


def resolve(mod: str, sym: str, hops: int = 0) -> str | None:
    """Follow re-export hops to the module that actually defines sym."""
    if hops > 10:
        return None
    p = facades.get(mod, {}).get("path") or os.path.join(SRC, *mod.split(".")) + ".py"
    if not os.path.exists(p):
        return None
    tree = parse_py(p)
    if tree is None:
        return None
    pkg = mod.rsplit(".", 1)[0] if "." in mod else ""

    alias_to_mod = _build_alias_to_mod(tree.body)

    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            result = _resolve_import_from(node, sym, pkg, hops)
            if result is not None:
                return result

        elif isinstance(node, ast.Assign):
            result = _resolve_alias_assign(node, sym, alias_to_mod, hops)
            if result is not None:
                return result

    return None


for mod, f in facades.items():
    smap: dict[str, str] = {}
    unresolved: list[str] = []
    for sym in f.pop("_names"):
        r = resolve(mod, sym)
        if r:
            smap[sym] = r
        elif not sym.startswith("_"):
            # Leading-underscore names here are private module aliases from a bare
            # `import x as _x` used only to hang attribute re-exports off — the
            # public names they feed are resolved separately.
            unresolved.append(sym)
    f["symbol_map"] = smap
    f["unresolved_symbols"] = unresolved
    f["symbols_unresolved"] = len(unresolved)

out = {
    "scanned_at": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "include_init": INCLUDE_INIT,
    "total_facades": len(facades),
    "facades": sorted(facades.values(),
                      key=lambda f: (f["domain"], f["chain_depth"], f["module"])),
}
json.dump(out, sys.stdout, indent=1)
print()
