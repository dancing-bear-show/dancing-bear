#!/usr/bin/env python3
"""Generate bin/ wrappers from _wrappers.yaml.

Usage:
    python3 bin/_gen_wrappers.py [--check] [--verbose]

Options:
    --check    Dry-run: report what would change without writing
    --verbose  Show all files, not just changes
"""
from __future__ import annotations

import argparse
import stat
import sys
from pathlib import Path

# Lazy import PyYAML (optional dep)
try:
    import yaml
except ImportError:
    yaml = None  # type: ignore[assignment]

BIN_DIR = Path(__file__).resolve().parent
CONFIG_FILE = BIN_DIR / "_wrappers.yaml"

# Templates
BASH_TEMPLATE = """\
#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
exec "$SCRIPT_DIR/{base}" {args} "$@"
"""

PYTHON_TEMPLATE = '''\
#!/usr/bin/env python3
"""{doc}"""
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from {module}.__main__ import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
'''

# For modules that aren't packages with __main__
PYTHON_TEMPLATE_CORE = '''\
#!/usr/bin/env python3
"""{doc}"""
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from {module} import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
'''


def load_config() -> dict:
    """Load _wrappers.yaml."""
    if yaml is None:
        # Fallback: simple YAML parser for our constrained format
        return _parse_simple_yaml(CONFIG_FILE.read_text())
    return yaml.safe_load(CONFIG_FILE.read_text())


def _parse_kv_section_line(line: str, section_data: dict) -> None:
    """Parse a 'name: {key: val, ...}' line into section_data."""
    import re

    m = re.match(r"\s+(\S+):\s+\{(.+)\}", line)
    if m:
        name = m.group(1)
        fields = {}
        for kv in m.group(2).split(", "):
            k, v = kv.split(": ", 1)
            fields[k] = v.strip('"')
        section_data[name] = fields


def _parse_simple_yaml(text: str) -> dict:
    """Minimal YAML parser for our config format."""
    import re

    result: dict = {"python": {}, "bash": {}, "manual": []}
    current_section = None
    for line in text.split("\n"):
        line = line.rstrip()
        if not line or line.startswith("#"):
            continue
        if line in ("python:", "bash:", "manual:"):
            current_section = line[:-1]
            continue
        if current_section == "manual":
            m = re.match(r"\s+-\s+(\S+)", line)
            if m:
                result["manual"].append(m.group(1))
        elif current_section in ("python", "bash"):
            _parse_kv_section_line(line, result[current_section])
    return result


def generate_bash(_name: str, spec: dict) -> str:
    """Generate bash wrapper content."""
    return BASH_TEMPLATE.format(base=spec["base"], args=spec["args"])


def generate_python(_name: str, spec: dict) -> str:
    """Generate Python wrapper content."""
    module = spec["module"]
    doc = spec.get("doc", f"Thin wrapper for {module}.")
    # Use different template for core.* modules
    if "." in module:
        return PYTHON_TEMPLATE_CORE.format(module=module, doc=doc)
    return PYTHON_TEMPLATE.format(module=module, doc=doc)


def _process_wrapper_section(specs: dict, generate_fn, check: bool, verbose: bool) -> tuple:
    """Process one section of wrappers; returns (changed_count, unchanged_count)."""
    changed = 0
    unchanged = 0
    for name, spec in specs.items():
        path = BIN_DIR / name
        content = generate_fn(name, spec)
        status = _update_file(path, content, check)
        if status == "changed":
            changed += 1
            print(f"{'Would update' if check else 'Updated'}: {name}")
        elif status == "created":
            changed += 1
            print(f"{'Would create' if check else 'Created'}: {name}")
        else:
            unchanged += 1
            if verbose:
                print(f"Unchanged: {name}")
    return changed, unchanged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Dry-run mode")
    parser.add_argument("--verbose", action="store_true", help="Show all files")
    args = parser.parse_args()

    config = load_config()
    c1, u1 = _process_wrapper_section(config.get("python", {}), generate_python, args.check, args.verbose)
    c2, u2 = _process_wrapper_section(config.get("bash", {}), generate_bash, args.check, args.verbose)
    changed = c1 + c2
    unchanged = u1 + u2

    print(f"\nTotal: {changed} changed, {unchanged} unchanged")
    return 1 if args.check and changed > 0 else 0


def _update_file(path: Path, content: str, check: bool) -> str:
    """Update file if content differs. Returns 'created', 'changed', or 'unchanged'."""
    if path.exists():
        existing = path.read_text()
        if existing == content:
            return "unchanged"
        if not check:
            path.write_text(content)
            _make_executable(path)
        return "changed"
    else:
        if not check:
            path.write_text(content)
            _make_executable(path)
        return "created"


def _make_executable(path: Path) -> None:
    """Add executable permission."""
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


if __name__ == "__main__":
    sys.exit(main())
