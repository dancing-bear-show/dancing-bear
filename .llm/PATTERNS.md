LLM Agent Code Patterns
Copy-paste templates aligned to current architecture

Project Goal (Reminder)
- Unified CLIs to manage Gmail/Outlook labels, filters, signatures, rules.
- One human‑editable YAML source of truth with safe plan→apply flows.
- Persisted, profile‑based credentials for repeatable operations.

Use Existing Commands First
```
# Prefer wrappers over python -m
./bin/mail-assistant --help
./bin/calendar-assistant --help

# Token‑efficient schemas
./bin/mail-assistant --agentic --agentic-format yaml --agentic-compact
./bin/llm agentic --stdout
```

Agentic Shortcuts (LLM CLI)
```
# Compact agentic capsule to stdout
./bin/llm agentic --stdout

# Generate domain map (CLI tree + flows)
./bin/llm domain-map --write .llm/DOMAIN_MAP.md

# Ensure core .llm files exist (and generate AGENTIC/DOMAIN_MAP)
./bin/llm derive-all --out-dir .llm --include-generated --stdout

# Familiarization capsules
./bin/llm familiar --stdout
./bin/llm familiar --verbose --write .llm/familiarize.yaml

# Staleness/Dependencies for prioritization
./bin/llm stale --by area --limit 10 --with-status --format table
./bin/llm deps --by combined --order desc --format table --limit 10
./bin/llm check --limit 50 --agg max --with-status --fail-on-stale
```

Familiarization: Reading Order
```
1) .llm/CONTEXT.md, .llm/DOMAIN_MAP.md, README.md
2) bin/mail-assistant → mail/__main__.py
3) mail/dsl.py, mail/config_resolver.py, mail/utils/filters.py
4) mail/providers/*.py, mail/gmail_api.py, mail/outlook_api.py
5) tests/test_cli.py, tests/test_cli_filters.py, tests/test_workflows*.py
```

Familiarization: Ripgrep Quick Searches (exclude heavy dirs)
```
rg -n "(def main\(|argparse|click)" mail/ bin/ \
  -g '!{.venv,.git,.cache,_disasm,out,_out,maker,backups}/**'

rg -n "filters (plan|sync|export)|labels (plan|sync|export)" mail/ bin/ \
  -g '!{.venv,.git,.cache,_disasm,out,_out,maker,backups}/**'

rg -n "filters_unified.yaml|derive|audit|optimize" mail/ README.md \
  -g '!{.venv,.git,.cache,_disasm,out,_out,maker,backups}/**'
```

Familiarization: Large YAML/JSON Policy
```
- Only open large YAML/JSON when auditing derived vs canonical.
- Canonical: config/filters_unified.yaml
- Derived/ephemeral: out/** (legacy _out/**), backups/**, exports (open only for audits)
```

CLI Entry Pattern
```
# bin/mail-assistant (preferred)
./bin/mail-assistant labels export --out labels.yaml
./bin/mail-assistant filters export --out filters.yaml
```

Schedule Planning/Apply
```
# bin/schedule-assistant (plan then apply; apply requires --apply)
# Prefer writing outputs to out/ (tracked as needed)
./bin/schedule-assistant plan --source schedules/classes.csv --out out/schedule.plan.yaml
./bin/schedule-assistant apply --plan out/schedule.plan.yaml --dry-run
./bin/schedule-assistant apply --plan out/schedule.plan.yaml --apply --calendar "Your Family"
```

Profile-Based Credentials
```
# ~/.config/sre-utils/credentials.ini
[mail.gmail_personal]
credentials = /Users/you/.config/sre-utils/google_credentials.gmail_personal.json
token = /Users/you/.config/sre-utils/token.gmail_personal.json

[mail.outlook_personal]
outlook_client_id = <YOUR_APP_ID>
tenant = consumers
outlook_token = /Users/you/.config/sre-utils/outlook_token.json
```

Lazy Imports for Optional Deps
```
def export_labels(...):
    import yaml  # lazy, optional
    from googleapiclient.discovery import build  # lazy
    ...
```

YAML IO Wrapper
```
def read_yaml(path):
    import yaml
    with open(path, 'r') as f:
        return yaml.safe_load(f) or {}

def write_yaml(path, data):
    import yaml
    with open(path, 'w') as f:
        yaml.safe_dump(data, f, sort_keys=False)
```

Provider Capability Gate
```
if not provider.capabilities().get("signatures"):
    raise SystemExit("Signatures not supported by this provider")
```

Plan/Apply Flow
```
# plan
python3 -m mail filters plan --config filters.yaml --out plan.json
# apply (dry-run by default; require --apply to write)
python3 -m mail filters sync --config filters.yaml --dry-run
```

Minimal Test (unittest)
```
import unittest, subprocess

class TestCLI(unittest.TestCase):
    def test_help(self):
        out = subprocess.check_output(["./bin/mail-assistant", "--help"], text=True)
        self.assertIn("labels", out)

if __name__ == "__main__":
    unittest.main()
```

Code Quality (qlty)
```bash
# Check a specific file for issues
~/.qlty/bin/qlty check path/to/file.py

# Check entire module
~/.qlty/bin/qlty check schedule/

# Common issue types:
# - ruff:E402 - imports not at top of file (fix: move docstring before imports)
# - python:S3776 - cognitive complexity too high (fix: extract helper functions)

# Extract metrics for a file
~/.qlty/bin/qlty metrics path/to/file.py

# Show all available linters
~/.qlty/bin/qlty plugins

# Fix auto-fixable issues
~/.qlty/bin/qlty check --fix path/to/file.py
```
