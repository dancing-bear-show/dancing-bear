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
INCLUDE_INIT = os.environ.get("INCLUDE_INIT", "false").lower() == "true"
DOMAINS = os.environ.get("DOMAINS", "*")


def iter_py():
    for dirpath, dirnames, filenames in os.walk(SRC):
        dirnames[:] = [d for d in dirnames if d not in SKIP_PARTS]
        for fn in sorted(filenames):
            if fn.endswith(".py"):
                yield os.path.join(dirpath, fn)


def parse_py(path):
    """Parse a Python file, or return None if it cannot be read or parsed.

    Centralises the read so every call site closes its handle deterministically
    rather than relying on refcount finalisation of a bare open(...).read().
    """
    try:
        with open(path, encoding="utf-8") as fh:
            return ast.parse(fh.read())
    except (SyntaxError, UnicodeDecodeError, OSError):
        return None


def classify(path):
    """Return (imports, defs, other, reexported_names) for a module's top level."""
    tree = parse_py(path)
    if tree is None:
        return None
    imports = defs = other = 0
    names = []
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue  # docstring
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            imports += 1
            # `from __future__ import annotations` is a compiler directive, not a
            # re-exported symbol — counting it inflates the unresolved tally.
            if isinstance(node, ast.ImportFrom) and node.module == "__future__":
                continue
            for a in node.names:
                if a.name != "*":
                    names.append(a.asname or a.name.split(".")[0])
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defs += 1
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            tgt = ""
            if isinstance(node, ast.Assign) and node.targets and isinstance(node.targets[0], ast.Name):
                tgt = node.targets[0].id
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                tgt = node.target.id
            if tgt == "__all__":
                continue
            if isinstance(node.value, (ast.Name, ast.Attribute)):
                names.append(tgt)  # alias re-export
            else:
                other += 1
        else:
            other += 1  # includes `if TYPE_CHECKING:` — intentionally not skipped
    return imports, defs, other, names


def module_path(path):
    """Convert a filesystem path under SRC to a dotted module name.

    Uses os.path.relpath + os.sep (not a hard-coded "/") so this works on
    Windows and regardless of the caller's cwd relative to SRC.
    """
    rel = os.path.relpath(path, SRC).removesuffix(".py")
    return ".".join(rel.split(os.sep))


def scan_lines(pattern, roots):
    """Pure-Python replacement for shelling out to `grep -rnE`.

    Returns "path:lineno" strings for every line matching `pattern` under the
    given root directories. Unreadable/binary files are skipped explicitly —
    a missing external grep binary previously failed silently (empty stdout),
    which this makes impossible since there's no external process to be absent.
    """
    regex = re.compile(pattern)
    hits = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                if not fn.endswith(".py"):
                    continue
                p = os.path.join(dirpath, fn)
                try:
                    with open(p, encoding="utf-8") as fh:
                        lines = fh.readlines()
                except (OSError, UnicodeDecodeError):
                    continue  # nosec B112 - skip unreadable/binary files silently
                for lineno, line in enumerate(lines, start=1):
                    if regex.search(line):
                        hits.append(f"{p}:{lineno}")
    return hits


def imports_of(path):
    """Modules this file imports from (absolute dotted, resolving relatives)."""
    tree = parse_py(path)
    if tree is None:
        return []
    pkg = module_path(path).rsplit(".", 1)[0] if "." in module_path(path) else ""
    found = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            if node.level:  # relative
                base = pkg
                for _ in range(node.level - 1):
                    base = base.rsplit(".", 1)[0] if "." in base else ""
                found.append(f"{base}.{node.module}" if node.module else base)
            elif node.module:
                found.append(node.module)
        elif isinstance(node, ast.Import):
            found.extend(a.name for a in node.names)
    return found


# ---- Step 1-2: find pure facades -------------------------------------------
facades = {}
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
def ast_callers():
    """Map facade module -> set of files importing it, resolved via AST.

    A string grep for `from <dotted.module> import` is relative-import-blind:
    `from .text_utils import x` inside src/calendars/importer/ targets
    calendars.importer.text_utils but shares no substring with it. It also
    misses lazy imports nested in function bodies, hence ast.walk over
    tree.body. Both forms are common in this repo and undercounting them makes
    a live facade look dead.
    """
    found = defaultdict(set)
    for root, dirs, files_ in os.walk("."):
        dirs[:] = [d for d in dirs if d not in {
            ".git", ".venv", ".claude", "__pycache__", ".facade-work",
            "personal_assistants.egg-info", "node_modules", ".cache",
        }]
        for fn in files_:
            if not fn.endswith(".py"):
                continue
            p = os.path.join(root, fn).lstrip("./")
            tree = parse_py(p)
            if tree is None:
                continue
            pkg = ""
            if p.startswith(SRC + os.sep):
                mp = module_path(p)
                pkg = mp.rsplit(".", 1)[0] if "." in mp else ""
            for n in ast.walk(tree):
                if isinstance(n, ast.Import):
                    for a in n.names:
                        if a.name in facades:
                            found[a.name].add(p)
                    continue
                if not isinstance(n, ast.ImportFrom):
                    continue
                if n.level:
                    base = pkg
                    for _ in range(n.level - 1):
                        base = base.rsplit(".", 1)[0] if "." in base else ""
                    tgt = f"{base}.{n.module}" if n.module else base
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

def depth(mod, seen=None):
    seen = seen or set()
    if mod in seen:
        return 0  # cycle guard
    kids = facades[mod]["chain_children"]
    return 0 if not kids else 1 + max(depth(k, seen | {mod}) for k in kids)

for mod, f in facades.items():
    f["chain_depth"] = depth(mod)

# ---- Step 6: symbol -> terminal real module --------------------------------
def _module_file(mod):
    parts = mod.split(".")
    p = os.path.join(SRC, *parts) + ".py"
    if os.path.exists(p):
        return p
    p = os.path.join(SRC, *parts, "__init__.py")
    return p if os.path.exists(p) else None


def _binding_nodes(body):
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


def defines(mod, sym):
    p = _module_file(mod)
    if not p:
        return False
    tree = parse_py(p)
    if tree is None:
        return False
    for n in _binding_nodes(tree.body):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == sym:
            return True
        if isinstance(n, ast.Assign):
            for t in n.targets:
                if isinstance(t, ast.Name) and t.id == sym:
                    return True
        elif isinstance(n, ast.AnnAssign):
            # e.g. ALL_VENDORS: List[VendorParser] = [...]
            if isinstance(n.target, ast.Name) and n.target.id == sym and n.value is not None:
                return True
    return False


def resolve(mod, sym, hops=0):
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

    # Local alias -> module, for both binding forms:
    #   import core.llm_cli as _x        (ast.Import)
    #   from core import llm_cli as _x   (ast.ImportFrom binding a submodule)
    alias_to_mod = {}
    for node in tree.body:
        if isinstance(node, ast.Import):
            for a in node.names:
                alias_to_mod[a.asname or a.name.split(".")[0]] = a.name
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for a in node.names:
                cand = f"{node.module}.{a.name}"
                if _module_file(cand):  # only when the name is a module, not a symbol
                    alias_to_mod[a.asname or a.name] = cand

    for node in tree.body:
        # Form 1: from <mod> import <sym>
        if isinstance(node, ast.ImportFrom):
            target = None
            for a in node.names:
                if (a.asname or a.name) == sym:
                    target = a.name
            if target is None:
                continue
            if node.level:
                base = pkg
                for _ in range(node.level - 1):
                    base = base.rsplit(".", 1)[0] if "." in base else ""
                src_mod = f"{base}.{node.module}" if node.module else base
            else:
                src_mod = node.module
            if defines(src_mod, target):
                return src_mod
            return resolve(src_mod, target, hops + 1)

        # Form 2: <sym> = <alias>.<attr>   (attribute alias re-export)
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Attribute):
            tgt = node.targets[0] if node.targets else None
            if not (isinstance(tgt, ast.Name) and tgt.id == sym):
                continue
            base_node, attr = node.value.value, node.value.attr
            if not isinstance(base_node, ast.Name):
                continue
            src_mod = alias_to_mod.get(base_node.id)
            if not src_mod:
                continue
            if defines(src_mod, attr):
                return src_mod
            return resolve(src_mod, attr, hops + 1)
    return None


for mod, f in facades.items():
    smap = {}
    unresolved = []
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
