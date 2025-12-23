# desk-assistant

A small, dependency-light CLI to help keep your macOS filesystem tidy over time — scan for large/stale/duplicate files, plan moves based on human-readable rules, and apply safe actions.

- Language: Python 3.11
- Philosophy: scan → plan → apply; human-edited YAML rules
- Install: `pip install -e .` (optionally `pip install -e .[yaml]` for YAML IO)

## Quickstart

- Create a venv and install:
  - `python3 -m venv .venv && source .venv/bin/activate`
  - `pip install -e .[yaml]`

- Show help:
  - `./bin/desk-assistant --help`

- Scan common locations for large/stale files:
  - `python3 -m desk_assistant scan --paths ~/Downloads ~/Desktop --min-size 100MB --older-than 30d --duplicates --out out/scan.yaml`

- Generate a starter rules file:
  - `python3 -m desk_assistant rules export --out rules.yaml`

- Produce a plan from rules:
  - `python3 -m desk_assistant plan --config rules.yaml --out plan.yaml`

- Apply a plan (dry-run first):
  - `python3 -m desk_assistant apply --plan plan.yaml --dry-run`
  - `python3 -m desk_assistant apply --plan plan.yaml`
- LLM capsules:
  - `./bin/llm --app desk agentic --stdout`
  - `./bin/llm --app desk domain-map --stdout`
  - `./bin/llm --app desk derive-all --out-dir .llm --include-generated`

## Rules (YAML)

Rules select files using simple matchers (paths, extensions, size/age), then perform a single action (move or trash). See `rules export` for a complete, commented example.

```
version: 1
rules:
  - name: Move DMGs from Downloads to Archives/DMGs
    match:
      paths: ["~/Downloads"]
      extensions: [".dmg"]
      older_than: "7d"
    action:
      move_to: "~/Downloads/Archives/DMGs"
```

## Notes
- Duplicate detection in `scan` is by size + SHA-256 content hash.
- `apply` moves files or sends them to `~/.Trash`. It will not delete permanently.
- YAML IO requires `PyYAML`; JSON is supported without extra deps.

## Development
- Tests: `make test` or `python3 -m unittest tests/test_cli.py -v`
- Dev install: `make dev`

## License
MIT
