"""Rules engine — loads, validates, and merges classification rules."""

import json
import logging
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_SCHEMA_PATH = Path(__file__).parent / "schema" / "rules-schema.json"

DEFAULT_RULES: dict[str, Any] = {
    "avoidable": {
        "bash-as-grep": {
            "enabled": True,
            "patterns": [r"grep\b", r"\brg\b", r"ripgrep\b"],
            "exclude": [],
        },
        "bash-as-read": {
            "enabled": True,
            "patterns": [r"\bcat\b", r"\bhead\b", r"\btail\b"],
            "exclude": [],
        },
        "bash-as-glob": {
            "enabled": True,
            "patterns": [r"\bfind\b", r"\bls\b"],
            "exclude": [],
        },
        "bash-as-write": {
            "enabled": True,
            "patterns": [r"\becho\b\s*>", r"\btee\b\s", r"cat\s*<<"],
            "exclude": [],
        },
        "redundant-read": {
            "enabled": True,
            "window_seconds": 60,
            "lookback_events": 10,
        },
        "rapid-re-edit": {
            "enabled": True,
            "window_seconds": 30,
            "lookback_events": 5,
        },
    },
    "review": {
        "abandoned-search": {
            "enabled": True,
            "consecutive_reads": 3,
        },
        "fruitless-agent": {
            "enabled": True,
            "window_seconds": 300,
            "lookforward_events": 10,
        },
    },
    "tools": {
        "productive": ["Edit", "Write", "MultiEdit", "NotebookEdit"],
        "neutral": [
            "Read",
            "Grep",
            "Glob",
            "Skill",
            "TaskCreate",
            "TaskUpdate",
            "TaskGet",
            "TaskList",
            "TaskStop",
            "TodoRead",
            "TodoWrite",
            "ToolSearch",
            "WebSearch",
            "WebFetch",
            "AskUserQuestion",
        ],
    },
    "tip_filters": {
        "exclude_blame_patterns": ["superpowers:*"],
        "min_cost_impact": 0.01,
    },
    "custom_rules": [],
    "fix_hints": {
        "bash-as-grep": {
            "skill": "Skill {name}: use the Grep tool instead of running grep/rg in Bash.",
            "agent": "Agent {name}: use Grep tool instead of Bash grep/rg calls.",
            "session": (
                "Session: replace Bash grep/rg calls with the Grep tool."
                " Add a rule to CLAUDE.md to reinforce this."
            ),
        },
        "bash-as-read": {
            "skill": "Skill {name}: use the Read tool instead of cat/head/tail in Bash.",
            "agent": "Agent {name}: use Read tool instead of Bash cat/head/tail.",
            "session": "Session: replace Bash cat/head/tail calls with the Read tool.",
        },
        "bash-as-glob": {
            "skill": "Use the Glob tool instead of find/ls in Bash.",
            "agent": "Agent {name}: use Glob tool instead of Bash find/ls calls.",
            "session": "Session: replace Bash find/ls calls with the Glob tool.",
        },
        "bash-as-write": {
            "skill": "Use the Write tool instead of echo/tee redirects in Bash.",
            "agent": "Agent {name}: use Write tool instead of Bash echo/tee redirects.",
            "session": "Session: replace Bash write redirects with the Write tool.",
        },
        "redundant-read": {
            "skill": (
                "Skill {name} read the same file multiple times"
                " — cache contents in a variable."
            ),
            "agent": "Agent {name}: avoid re-reading the same file; store content for reuse.",
            "session": "Session: the same file was read repeatedly — read once and reuse.",
        },
        "rapid-re-edit": {
            "skill": "Skill {name} edited the same file multiple times rapidly — batch edits.",
            "agent": "Agent {name}: consolidate rapid re-edits into a single edit operation.",
            "session": "Session: rapid re-edits detected — plan all changes before editing.",
        },
        "abandoned-search": {
            "skill": "Skill {name} ran many reads without writing — verify search strategy.",
            "agent": (
                "Agent {name}: consecutive reads without progress"
                " — reconsider search approach."
            ),
            "session": "Session: many reads without writes suggest abandoned search patterns.",
        },
        "fruitless-agent": {
            "skill": "Skill {name} spawned agents that produced no output — review agent prompts.",
            "agent": "Agent {name}: sub-agents returned no useful results — refine prompts.",
            "session": "Session: agent invocations led to no productive output.",
        },
    },
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def validate_rules(rules: dict) -> list[str]:
    """Validate rules dict against the JSON schema.

    Returns a list of error strings (empty list means valid).
    Requires jsonschema — returns a warning string if not installed.
    """
    try:
        import jsonschema  # noqa: PLC0415 - lazy import; jsonschema is optional
    except ImportError:
        return []  # jsonschema not installed — skip validation

    try:
        schema = json.loads(_SCHEMA_PATH.read_text())
    except Exception as exc:  # nosec B110 - schema load failure surfaces as error string
        return [f"Could not load rules schema: {exc}"]

    validator = jsonschema.Draft7Validator(schema)
    errors = sorted(validator.iter_errors(rules), key=lambda e: list(e.path))
    return [f"{'.'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors]


def load_rules(path: str | Path | None = None) -> dict[str, Any]:
    """Load rules from a YAML file and deep-merge with DEFAULT_RULES."""
    if path is None:
        config_path = Path.home() / ".telemetry-transcripts" / "rules.yaml"
    else:
        config_path = Path(path)

    if not config_path.exists():
        return deepcopy(DEFAULT_RULES)

    try:
        raw = yaml.safe_load(config_path.read_text())
    except yaml.YAMLError as exc:
        logger.warning("Warning: invalid YAML in %s: %s", config_path, exc)
        return deepcopy(DEFAULT_RULES)

    if not isinstance(raw, dict):
        logger.warning("Warning: rules file %s did not parse to a mapping; using defaults.", config_path)
        return deepcopy(DEFAULT_RULES)

    merged = _deep_merge(DEFAULT_RULES, raw)

    errors = validate_rules(merged)
    real_errors = [e for e in errors if not e.startswith("jsonschema not installed")]
    if real_errors:
        logger.warning("Warning: rules file %s failed schema validation; using defaults.", config_path)
        for err in real_errors:
            logger.warning("  - %s", err)
        return deepcopy(DEFAULT_RULES)

    return merged
