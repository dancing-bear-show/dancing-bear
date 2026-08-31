"""Mail Assistant CLI using CLIApp framework.

This CLI provides Gmail and Outlook mail management operations including:
- Labels/categories management
- Filters/rules sync
- Messages search, summarize, reply
- Forwarding configuration
- Signatures management
- Multi-account operations
"""

from __future__ import annotations


from core.assistant import BaseAssistant
from ..meta import META
from core.cli_framework import CLIApp

from ..config_resolver import (
    default_gmail_credentials_path,
    default_gmail_token_path,
)
from ..config_cli.commands import run_auth, run_backup
from .cmd_labels import register_labels_commands
from .cmd_filters import register_filters_commands
from .cmd_messages import register_messages_commands
from .cmd_cache import register_cache_commands
from .cmd_auto import register_auto_commands
from .cmd_forwarding import register_forwarding_commands
from .cmd_signatures import register_signatures_commands
from .cmd_config import register_config_commands
from .cmd_workflows import register_workflows_commands
from .cmd_env import register_env_commands
from .cmd_accounts import register_accounts_commands
from .cmd_outlook import register_outlook_commands


assistant = BaseAssistant(META.app_id, META.agentic_fallback)

app = CLIApp(
    "mail-assistant",
    "Mail Assistant CLI for Gmail and Outlook management",
    add_common_args=False,
)

# Default paths for credentials
_default_gmail_credentials = default_gmail_credentials_path()
_default_gmail_token = default_gmail_token_path()

# Repeated help-text strings extracted as module-level constants
HELP_CREDENTIALS = "Path to OAuth credentials.json"
HELP_TOKEN = "Path to token.json"  # nosec B105 - argparse help text, not a credential


def _lazy_emit_agentic():
    from ..agentic import emit_agentic_context
    return emit_agentic_context


# --- auth command ---
@app.command("auth", help="Authenticate with the mail provider")
@app.argument("--credentials", help=f"{HELP_CREDENTIALS} (default: {_default_gmail_credentials})")
@app.argument("--token", help=f"{HELP_TOKEN} (default: {_default_gmail_token})")
@app.argument("--validate", action="store_true", help="Validate existing Gmail token non-interactively")
def cmd_auth(args) -> int:
    return run_auth(args)


# --- backup command ---
@app.command("backup", help="Backup Gmail labels and filters to a timestamped folder")
@app.argument("--credentials", help=HELP_CREDENTIALS)
@app.argument("--token", help=HELP_TOKEN)
@app.argument("--out-dir", help="Output directory (default backups/<timestamp>)")
def cmd_backup(args) -> int:
    return run_backup(args)


# --- labels group ---
labels_group = register_labels_commands(app)

# --- filters group ---
filters_group = register_filters_commands(app)

# --- messages group ---
messages_group = register_messages_commands(app)

# --- cache group ---
cache_group = register_cache_commands(app)

# --- auto group ---
auto_group = register_auto_commands(app)

# --- forwarding group ---
forwarding_group = register_forwarding_commands(app)

# --- signatures group ---
signatures_group = register_signatures_commands(app)

# --- config group ---
config_group = register_config_commands(app)

# --- workflows group ---
workflows_group = register_workflows_commands(app)

# --- env group ---
env_group = register_env_commands(app)

# --- accounts group ---
accounts_group = register_accounts_commands(app)

# --- outlook group ---
outlook_group = register_outlook_commands(app)


def _install_output_masking() -> None:
    """Install output masking for secret shielding."""
    from core.secrets import install_output_masking_from_env
    install_output_masking_from_env()


def _add_common_args(parser) -> None:
    """Add common arguments to parser."""
    parser.add_argument("--profile", help="Credentials profile (INI section suffix)")
    parser.add_argument("--verbose", action="store_true", help="Enable verbose logging")


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the Mail Assistant CLI."""
    return app.run_with_assistant(
        assistant=assistant,
        emit_func=_lazy_emit_agentic(),
        argv=argv,
        pre_run_hook=_install_output_masking,
        post_build_hook=_add_common_args,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
