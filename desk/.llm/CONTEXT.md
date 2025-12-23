desk-assistant: LLM context

Overview
- This project provides a CLI to keep a macOS filesystem tidy over time. The model tasks are: scan (inspect filesystem), plan (produce move/trash plan from human-defined YAML rules), apply (execute the plan safely).
- Keep dependencies minimal. YAML IO is optional via PyYAML.

Principles
- Scan → Plan → Apply. Do not perform destructive actions without a plan step or `--dry-run`.
- Favor explicit, human-readable rules over complex heuristics.
- Preserve stable CLI flags and subcommands.

Paths
- CLI wrapper: `bin/desk-assistant`
- Entrypoint: `desk_assistant/cli.py` and module `desk_assistant/__main__.py`
- Helpers: `desk_assistant/utils.py`

Common Commands
- `python3 -m desk_assistant scan --paths ~/Downloads ~/Desktop --min-size 100MB --older-than 30d --duplicates --out out/scan.yaml`
- `python3 -m desk_assistant rules export --out rules.yaml`
- `python3 -m desk_assistant plan --config rules.yaml --out plan.yaml`
- `python3 -m desk_assistant apply --plan plan.yaml --dry-run`

Testing
- Use `unittest`. Run `make test`.

