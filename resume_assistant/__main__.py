"""Executable shim so `python -m resume_assistant` runs the CLI."""

from __future__ import annotations

from importlib import import_module
import sys


def _load_cli_main():
    try:
        module = import_module("resume_assistant.resume_assistant.cli.main")
        return getattr(module, "main")
    except ModuleNotFoundError as exc:
        missing = str(exc).split("'")[1]
        print(f"Missing optional dependency '{missing}'. Install resume requirements or run in the venv before using this CLI.", file=sys.stderr)
        raise SystemExit(99)


def main() -> int:
    return _load_cli_main()()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
