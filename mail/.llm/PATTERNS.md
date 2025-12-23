Copy/Paste Patterns

Add a subcommand (argparse)
- Define under `build_parser()` with a focused handler function.
- Keep args small and explicit; preserve existing names/semantics.

Lazy imports for optional deps
- Import Google APIs, YAML, requests only inside the handler methods.
- Wrap in try/except and provide actionable error messages on missing deps.

YAML DSL rules
- Keep YAML human-editable; support brief comments.
- Derive provider configs from unified; never hand-edit derived outputs.

Profiles
- Resolve paths via INI (see `config_resolver.py`).
- Accept `--profile` at top-level and pass through to provider helpers.

Testing
- Use `unittest`; keep tests small/targeted for new CLI surfaces.
- Run: `python3 -m unittest tests/test_cli.py -v`.

