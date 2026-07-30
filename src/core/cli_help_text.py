"""Help text constants for commonly repeated CLI argument strings.

Import these instead of repeating the same string literal across domain CLIs.
Only constants for strings that appear multiple times in the codebase are included.

Usage:
    from core.cli_help_text import HELP_DRY_RUN, HELP_VERBOSE, HELP_PROFILE
    parser.add_argument("--dry-run", action="store_true", help=HELP_DRY_RUN)
"""
from __future__ import annotations

# Matches core/cli_framework.py CLIApp._add_common_arguments
HELP_VERBOSE = "Enable verbose output"
HELP_QUIET = "Suppress non-essential output"
HELP_DRY_RUN = "Preview changes without applying them"
HELP_PROFILE = "Credentials profile name"
HELP_OUTPUT = "Output format (default: text)"

# Repeated across domain CLIs (grep-verified)
HELP_DAYS = "Look back N days"
HELP_OUT_DIR = "Output directory"
HELP_OUT_PATH = "Output file path"
HELP_PAGE_SIZE = "Page size"
HELP_MAX_PAGES = "Max pages"
HELP_ACCOUNTS = "Accounts YAML"
HELP_ACCOUNTS_LIST = "Comma-separated list of accounts"
HELP_CACHE_DIR = "Cache directory"
HELP_PRETTY_JSON = "Pretty-print JSON"
HELP_JSON_OUT = "Path to write JSON output (default stdout)"
HELP_YAML_OUT = "Output YAML path"
HELP_START_DATE = "Start date YYYY-MM-DD"
HELP_DAYS_BACK = "Restrict query to last N days"
