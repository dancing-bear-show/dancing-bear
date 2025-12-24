"""Universal assistant dispatcher.

Allows a single entry point (`assistant`) to invoke the existing assistant CLIs
by app name, e.g. `assistant resume --help` or `assistant calendar outlook list`.
"""

from __future__ import annotations

import sys
from importlib import import_module
from typing import Callable, Dict, List

# Map shorthand app names to their CLI modules (each exposes a main() entry).
APP_MODULES: Dict[str, str] = {
    "mail": "mail.__main__",
    "calendar": "calendars.__main__",
    "schedule": "schedule.__main__",
    "resume": "resume.__main__",
    "phone": "phone.__main__",
    "whatsapp": "whatsapp.__main__",
    "maker": "maker.__main__",
    "metals": "metals.__main__",
    "music": "apple_music.__main__",
    "apple-music": "apple_music.__main__",
    "wifi": "wifi.__main__",
}


def _load_app_main(app: str) -> Callable[[List[str]], int]:
    module_path = APP_MODULES.get(app)
    if not module_path:
        raise KeyError(app)
    try:
        module = import_module(module_path)
    except Exception as exc:  # pragma: no cover - surfaced to caller
        raise RuntimeError(f"Failed to load app '{app}': {exc}") from exc
    main = getattr(module, "main", None)
    if not callable(main):
        raise RuntimeError(f"App '{app}' missing main()")
    return main


def main(argv: List[str] | None = None) -> int:
    args = list(argv) if argv is not None else sys.argv[1:]
    if not args or args[0] in {"-h", "--help"}:
        apps = ", ".join(sorted(APP_MODULES))
        print("Usage: assistant <app> [args]\nApps:", apps)
        return 0 if args and args[0] in {"-h", "--help"} else 2

    app, app_args = args[0], args[1:]
    try:
        app_main = _load_app_main(app)
    except KeyError:
        print(f"Unknown app '{app}'. Known apps: {', '.join(sorted(APP_MODULES))}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2

    return int(app_main(app_args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
