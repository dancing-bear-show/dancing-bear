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
./bin/llm domain-map --stdout

# Ensure core .llm files exist (and generate AGENTIC/DOMAIN_MAP)
./bin/llm derive-all --out-dir .llm --include-generated

# Familiarization capsules
./bin/llm familiar --stdout
./bin/llm familiar --verbose

# Flows (curated workflows)
./bin/llm flows --list
./bin/llm flows --id gmail_filters_plan_apply_verify --format md
./bin/llm flows --tags mail,gmail

# Staleness/Dependencies for prioritization
./bin/llm stale --with-status --limit 10
./bin/llm deps --by combined --order desc --limit 10
./bin/llm check --fail-on-stale
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
# ~/.config/credentials.ini (preferred)
# Legacy paths also supported: ~/.config/sre-utils/, ~/.config/sreutils/
[mail.gmail_personal]
credentials = /Users/you/.config/google_credentials.gmail_personal.json
token = /Users/you/.config/token.gmail_personal.json

[mail.outlook_personal]
outlook_client_id = <YOUR_APP_ID>
tenant = consumers
outlook_token = /Users/you/.config/outlook_token.json
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

Pipeline Result Unwrap Pattern
```python
# Use unwrap() instead of assert for safe payload extraction
# Provides clear error messages when result is unexpectedly None

# Bad: assert can be stripped in optimized builds, cryptic errors
def produce(self, envelope):
    assert envelope.result is not None
    payload = envelope.result  # type: ignore

# Good: unwrap() raises with context, works in all builds
def produce(self, envelope):
    payload = envelope.unwrap()  # raises ValueError if None

# Implementation (core/pipeline.py, metals/pipeline.py):
class ResultEnvelope:
    def unwrap(self) -> T:
        """Extract payload or raise ValueError with context."""
        if self.result is None:
            raise ValueError(f"Cannot unwrap: {self.error or 'result is None'}")
        return self.result
```

SafeProcessor Pattern (Automatic Error Handling)
```python
# Modern pattern: SafeProcessor handles errors automatically
# Use this for new pipelines (mail/config_cli, mail/messages_cli migrated Dec 2024)

from core.pipeline import SafeProcessor, BaseProducer, RequestConsumer
from dataclasses import dataclass
from typing import Any, Dict, Optional

# 1. Define request/result types
@dataclass
class CacheStatsRequest:
    cache_path: str

@dataclass
class CacheStatsResult:
    path: str
    files: int
    size_bytes: int

# 2. Use RequestConsumer type alias (no boilerplate consumer class needed)
CacheStatsRequestConsumer = RequestConsumer[CacheStatsRequest]

# 3. Processor: extend SafeProcessor, implement _process_safe()
class CacheStatsProcessor(SafeProcessor[CacheStatsRequest, CacheStatsResult]):
    def _process_safe(self, payload: CacheStatsRequest) -> CacheStatsResult:
        # No try/except needed - SafeProcessor handles errors automatically
        # Just return the result directly, raise exceptions for errors
        from pathlib import Path
        root = Path(payload.cache_path)
        total = 0
        files = 0
        for p in root.rglob("*"):
            if p.is_file():
                files += 1
                total += p.stat().st_size
        return CacheStatsResult(path=str(root), files=files, size_bytes=total)

# 4. Producer: extend BaseProducer, implement _produce_success()
class CacheStatsProducer(BaseProducer):
    def _produce_success(self, payload: CacheStatsResult,
                        diagnostics: Optional[Dict[str, Any]]) -> None:
        # Only handles success case - BaseProducer prints errors automatically
        print(f"Cache: {payload.path} files={payload.files} size={payload.size_bytes} bytes")

# 5. Wire in commands (example)
def run_cache_stats(args):
    request = CacheStatsRequest(cache_path=args.cache)
    envelope = CacheStatsProcessor().process(RequestConsumer(request).consume())
    CacheStatsProducer().produce(envelope)
    return 0 if envelope.ok() else 1
```

Old-Style vs SafeProcessor Migration
```python
# OLD: Manual error handling (before migration)
class OldProcessor(Processor[Request, ResultEnvelope[Result]]):
    def process(self, payload: Request) -> ResultEnvelope[Result]:
        try:
            # ... do work ...
            return ResultEnvelope(status="success", payload=Result(...))
        except Exception as e:
            return ResultEnvelope(status="error", diagnostics={"message": str(e)})

class OldProducer(Producer[ResultEnvelope[Result]]):
    def produce(self, result: ResultEnvelope[Result]) -> None:
        if not result.ok():
            print(f"Error: {(result.diagnostics or {}).get('message', 'Failed')}")
            return
        p = result.unwrap()
        print(f"Success: {p.value}")

# NEW: Automatic error handling (after migration)
class NewProcessor(SafeProcessor[Request, Result]):
    def _process_safe(self, payload: Request) -> Result:
        # No try/except - SafeProcessor wraps this automatically
        # Just raise exceptions for errors
        return Result(...)

class NewProducer(BaseProducer):
    def _produce_success(self, payload: Result, diagnostics: Optional[Dict[str, Any]]) -> None:
        # Only success path - BaseProducer handles errors
        print(f"Success: {payload.value}")
```

Plan/Apply Flow (Safe by Default)
```
# Always: plan → dry-run → apply
# Mail filters
./bin/mail-assistant filters plan --config filters.yaml
./bin/mail-assistant filters sync --config filters.yaml --dry-run
./bin/mail-assistant filters sync --config filters.yaml

# Mail labels
./bin/mail-assistant labels plan --config labels.yaml --delete-missing
./bin/mail-assistant labels sync --config labels.yaml --dry-run
./bin/mail-assistant labels sync --config labels.yaml

# Outlook rules
./bin/mail-assistant outlook rules plan --config filters.outlook.yaml
./bin/mail-assistant outlook rules sync --config filters.outlook.yaml --dry-run
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

Constants Abstraction
```python
# Extract constants into module-level or dedicated files for:
# - Maintainability: single source of truth, easy to update
# - Testability: constants can be imported and verified
# - Reduced complexity: moves magic values out of function bodies

# Bad: constants buried in functions
def process_file(path):
    TEMP_PREFIXES = ("~$", ".~", "._")  # buried, hard to find
    DS_STORE = ".DS_Store"
    ...

# Good: module-level constants
TEMP_PREFIXES = ("~$", ".~", "._")
DS_STORE = ".DS_Store"
TEMP_PATTERNS = (*TEMP_PREFIXES, DS_STORE)

def process_file(path):
    ...

# Better for large constant sets: dedicated constants file
# module/constants.py
TEMP_PREFIXES = ("~$", ".~", "._")
SECTION_PATTERNS = {...}
DEFAULT_CONFIG = {...}

# module/processor.py
from .constants import TEMP_PREFIXES, SECTION_PATTERNS
```

Phone/iOS Patterns
```
# Export → Plan → Checklist → Profile
./bin/phone-assistant export --out out/ios.IconState.yaml
./bin/phone-assistant plan --layout out/ios.IconState.yaml --out out/ios.plan.yaml
./bin/phone-assistant checklist --plan out/ios.plan.yaml --layout out/ios.IconState.yaml
./bin/phone-assistant profile build --plan out/ios.plan.yaml --out out/ios.mobileconfig

# Analyze and prune unused apps
./bin/phone-assistant analyze --layout out/ios.IconState.yaml
./bin/phone-assistant unused --layout out/ios.IconState.yaml --limit 50
./bin/phone-assistant prune --layout out/ios.IconState.yaml --mode offload
```

Calendar Patterns
```
# Outlook calendar operations
./bin/calendar --profile outlook_personal outlook verify-from-config --config out/plan.yaml
./bin/calendar --profile outlook_personal outlook add-from-config --config out/plan.yaml
./bin/calendar --profile outlook_personal outlook update-locations --config out/plan.yaml

# Dedup series
./bin/calendar --profile outlook_personal outlook dedup --calendar "Family" \
  --from 2025-01-01 --to 2025-12-31 --prefer-delete-nonstandard --keep-newest
```

Metals Patterns
```
# Extract and build summaries
./bin/extract-metals --profile gmail_personal --out out/metals.json
./bin/build-metals-summaries --in out/metals.json --out out/metals-summary.xlsx
./bin/metals-premium --in out/metals.json
./bin/metals-spot-series --days 30
```

WiFi Patterns
```
# Diagnostics
./bin/wifi-assistant scan
./bin/wifi-assistant diagnose
```
