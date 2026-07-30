"""Auto-derived agentic schema from argparse parsers.

Walks a parser's full subcommand tree and emits a JSON-serializable schema.
This is additive to the existing hand-authored capsule system in core/agentic.py
and core/assistant.py — existing behavior is unchanged when new flags are not used.

Public API:
    build_schema_json(parser, *, compact=False, ultra=False, domain=None) -> dict
    build_schema_yaml(parser, *, compact=False, ultra=False, domain=None) -> str
"""
from __future__ import annotations

import argparse
from typing import Any


# ---------------------------------------------------------------------------
# Parser introspection
# ---------------------------------------------------------------------------

def _get_type_name(t: Any) -> str | None:
    if t is None:
        return None
    if t is int:
        return "int"
    if t is float:
        return "float"
    if t is bool:
        return "bool"
    return getattr(t, "__name__", str(t))


def _skip_option_action(action: argparse.Action) -> bool:
    """Return True if this action should be excluded from the schema."""
    if not action.option_strings:
        return True  # positional arg
    return isinstance(action, (argparse._HelpAction, argparse._SubParsersAction))


def _action_to_entry(action: argparse.Action) -> dict:
    """Build a single option descriptor dict from an argparse action."""
    return {
        "name": action.dest,
        "flags": list(action.option_strings),
        "required": bool(getattr(action, "required", False)),
        "type": _get_type_name(getattr(action, "type", None)),
        "choices": list(action.choices) if action.choices else None,
        "nargs": str(action.nargs) if action.nargs is not None else None,
        "default": action.default,
        "help": action.help or "",
        "metavar": str(action.metavar) if action.metavar else None,
        "action": type(action).__name__,
    }


def _extract_options(parser: argparse.ArgumentParser) -> list[dict]:
    """Extract option descriptors from a parser (non-positional actions)."""
    return [
        _action_to_entry(action)
        for action in parser._actions
        if not _skip_option_action(action)
    ]


def _get_subparsers_action(
    parser: argparse.ArgumentParser,
) -> argparse._SubParsersAction | None:
    for act in parser._actions:
        if isinstance(act, argparse._SubParsersAction):
            return act
    return None


def _matches_domain(sub_name: str, domain: str | None, depth: int) -> bool:
    """Return True if a top-level subcommand name should be kept for `domain`."""
    if not domain or depth != 0:
        return True
    return sub_name == domain or sub_name.startswith(domain + "-")


def _build_node_base(parser: argparse.ArgumentParser, name: str) -> dict:
    """Build the non-recursive fields of a schema node."""
    return {
        "prog": getattr(parser, "prog", name) or name,
        "description": (parser.description or "").strip(),
        "usage": (parser.format_usage() or "").strip(),
        "epilog": (parser.epilog or "").strip(),
        "options": _extract_options(parser),
        "subcommands": [],
    }


def _build_subcommand_nodes(
    sub_action: argparse._SubParsersAction, depth: int, domain: str | None
) -> list[dict]:
    """Recursively build schema nodes for every matching subcommand choice."""
    choices: dict = getattr(sub_action, "choices", {}) or {}
    children: list[dict] = []
    for sub_name, sub_parser in sorted(choices.items()):
        if not _matches_domain(sub_name, domain, depth):
            continue
        child = _build_node(sub_parser, sub_name, depth + 1, domain=None)
        child["name"] = sub_name
        children.append(child)
    return children


def _build_node(
    parser: argparse.ArgumentParser,
    name: str,
    depth: int = 0,
    domain: str | None = None,
) -> dict:
    """Recursively build a schema node for a parser."""
    node = _build_node_base(parser, name)
    sub_action = _get_subparsers_action(parser)
    if sub_action is not None:
        node["subcommands"] = _build_subcommand_nodes(sub_action, depth, domain)
    return node


def _collect_leaf_options(node: dict) -> list[frozenset]:
    """Collect option flag-sets from all leaf subcommand nodes."""
    if not node.get("subcommands"):
        return [frozenset(o["name"] for o in node.get("options", []))]
    result: list[frozenset] = []
    for child in node["subcommands"]:
        result.extend(_collect_leaf_options(child))
    return result


def _hoist_inherited_options(node: dict) -> list[str]:
    """Find options present in every leaf; remove from leaves, return names.

    Returns the list of hoisted option names.
    """
    leaves = _collect_leaf_options(node)
    if not leaves:
        return []
    common = set.intersection(*[set(s) for s in leaves]) if leaves else set()
    if not common:
        return []

    def _remove_common(n: dict) -> None:
        n["options"] = [o for o in n.get("options", []) if o["name"] not in common]
        for child in n.get("subcommands", []):
            _remove_common(child)

    _remove_common(node)
    return sorted(common)


def _strip_compact_fields(node: dict) -> None:
    """Remove help/metavar/action/usage/epilog from node (compact mode)."""
    for opt in node.get("options", []):
        opt.pop("help", None)
        opt.pop("metavar", None)
        opt.pop("action", None)
    node.pop("usage", None)
    node.pop("epilog", None)
    for child in node.get("subcommands", []):
        _strip_compact_fields(child)


_ULTRA_KEY_MAP = {
    "prog": "p",
    "description": "d",
    "options": "o",
    "subcommands": "sc",
    "inherited_options": "io",
}
_ULTRA_OPT_KEY_MAP = {
    "name": "n",
    "flags": "f",
    "required": "r",
    "type": "t",
    "choices": "c",
    "nargs": "g",
}
def _ultra_remap_scalars(node: dict) -> dict:
    """Remap simple (non-list/dict) node fields to short keys, dropping empties."""
    out: dict = {}
    for long_k, short_k in _ULTRA_KEY_MAP.items():
        if long_k not in node:
            continue
        val = node[long_k]
        if val or val == 0:  # keep 0 but drop empty/None
            out[short_k] = val
    return out


def _ultra_compress_option(opt: dict) -> dict:
    """Remap a single option dict to short keys, dropping empty/False values."""
    new_opt: dict = {}
    for long_k, short_k in _ULTRA_OPT_KEY_MAP.items():
        if long_k not in opt:
            continue
        val = opt[long_k]
        if val is not None and val != "" and val is not False:
            new_opt[short_k] = val
    return new_opt


def _ultra_compress_options(options: list[dict]) -> list[dict]:
    """Compress a list of option dicts, dropping any that end up empty."""
    return [c for opt in options if (c := _ultra_compress_option(opt))]


def _ultra_compress_subcommands(subcommands: list[dict]) -> list[dict]:
    """Recursively compress child nodes, re-attaching their name field."""
    compressed_subs: list[dict] = []
    for child in subcommands:
        compressed_child = _apply_ultra(child)
        if "name" in child:
            compressed_child["n"] = child["name"]
        if compressed_child:
            compressed_subs.append(compressed_child)
    return compressed_subs


def _apply_ultra(node: dict) -> dict:
    """Remap node keys to 1-2 char short forms and drop low-value fields."""
    out = _ultra_remap_scalars(node)

    if "options" in node:
        compressed_opts = _ultra_compress_options(node["options"])
        if compressed_opts:
            out["o"] = compressed_opts

    if "subcommands" in node:
        compressed_subs = _ultra_compress_subcommands(node["subcommands"])
        if compressed_subs:
            out["sc"] = compressed_subs
    return out


# ---------------------------------------------------------------------------
# Public schema builders
# ---------------------------------------------------------------------------

def build_schema_json(
    parser: argparse.ArgumentParser,
    *,
    compact: bool = False,
    ultra: bool = False,
    domain: str | None = None,
) -> dict:
    """Build a JSON-serializable schema dict from a parser.

    Args:
        parser: The root ArgumentParser to introspect.
        compact: Strip help/metavar/action/usage/epilog; hoist common options.
        ultra: Remap keys to 1-2 char short forms; drop empty/low-value fields.
               Implies compact.
        domain: If set, only include top-level subcommands matching this name
                or starting with this prefix followed by '-'.

    Returns:
        Dict representing the full CLI schema tree.
    """
    node = _build_node(parser, getattr(parser, "prog", ""), domain=domain)

    if compact or ultra:
        _strip_compact_fields(node)
        inherited = _hoist_inherited_options(node)
        if inherited:
            node["inherited_options"] = inherited

    if ultra:
        node = _apply_ultra(node)

    return node


def build_schema_yaml(
    parser: argparse.ArgumentParser,
    *,
    compact: bool = False,
    ultra: bool = False,
    domain: str | None = None,
) -> str:
    """Build a YAML string schema from a parser.

    Dependency-free: does not import PyYAML. Uses a minimal recursive emitter
    that handles dict/list/scalar/bool/None and properly quotes strings
    containing special characters.

    Args:
        parser: The root ArgumentParser to introspect.
        compact: Strip low-value fields; hoist common inherited options.
        ultra: Remap keys to short forms; drop empty fields. Implies compact.
        domain: Top-level subcommand prefix filter.

    Returns:
        YAML string.
    """
    schema = build_schema_json(parser, compact=compact, ultra=ultra, domain=domain)
    return _dict_to_yaml(schema, indent=0)


# ---------------------------------------------------------------------------
# Minimal dependency-free YAML emitter
# ---------------------------------------------------------------------------

_YAML_NEEDS_QUOTE_CHARS = frozenset(": #-\n\t")


def _needs_quoting(s: str) -> bool:
    """Return True if the string requires YAML quoting."""
    if not s:
        return True  # empty string must be quoted as ''
    if s in ("true", "false", "null", "yes", "no", "on", "off"):
        return True
    if s[0] in (" ", "\t") or s[-1] in (" ", "\t"):
        return True
    for ch in _YAML_NEEDS_QUOTE_CHARS:
        if ch in s:
            return True
    return False


def _yaml_scalar(val: Any) -> str:
    """Render a scalar value as a YAML token."""
    if val is None:
        return "null"
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    s = str(val)
    if _needs_quoting(s):
        escaped = s.replace("\\", "\\\\").replace("'", "''")
        return f"'{escaped}'"
    return s


def _yaml_dict_lines(data: dict, indent: int, pad: str) -> list[str]:
    """Render a dict's entries as YAML lines."""
    lines: list[str] = []
    for key, value in data.items():
        k = _yaml_scalar(str(key))
        if isinstance(value, (dict, list)) and value:
            lines.append(f"{pad}{k}:")
            lines.append(_dict_to_yaml(value, indent + 1))
        else:
            lines.append(f"{pad}{k}: {_yaml_scalar(value)}")
    return lines


def _yaml_list_item_lines(item: Any, indent: int, pad: str) -> list[str]:
    """Render a single list item as YAML lines, nesting complex items."""
    if not (isinstance(item, (dict, list)) and item):
        return [f"{pad}- {_yaml_scalar(item)}"]

    lines: list[str] = []
    for i, line in enumerate(_dict_to_yaml(item, indent + 1).splitlines()):
        lines.append(f"{pad}- {line.lstrip()}" if i == 0 else line)
    return lines


def _yaml_list_lines(data: list, indent: int, pad: str) -> list[str]:
    """Render a list's items as YAML lines."""
    lines: list[str] = []
    for item in data:
        lines.extend(_yaml_list_item_lines(item, indent, pad))
    return lines


def _dict_to_yaml(data: Any, indent: int) -> str:
    """Recursively render data as YAML lines."""
    pad = "  " * indent

    if isinstance(data, dict):
        lines = _yaml_dict_lines(data, indent, pad)
    elif isinstance(data, list):
        lines = _yaml_list_lines(data, indent, pad)
    else:
        lines = [f"{pad}{_yaml_scalar(data)}"]

    return "\n".join(lines)
