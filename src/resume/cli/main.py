"""Resume assistant CLI using CLIApp framework.

Commands:
  extract       - Parse LinkedIn and resume sources
  summarize     - Build summary output
  render        - Render DOCX resume
  structure     - Infer section order from reference DOCX
  align         - Align candidate data with job posting
  candidate-init - Generate candidate skills YAML
  style build   - Build style profile from corpus
  files tidy    - Archive or delete old files
  experience export - Export job history summary
"""

from __future__ import annotations

from core.assistant import BaseAssistant
from ..meta import META
from core.cli_framework import CLIApp


from .cmd_extract import register_extract_commands
from .cmd_summarize import register_summarize_commands
from .cmd_render import register_render_commands
from .cmd_align import register_align_commands
from .cmd_style import register_style_commands
from .cmd_files import register_files_commands
from .cmd_experience import register_experience_commands
from .cmd_docx import register_docx_commands

assistant = BaseAssistant(META.app_id, META.agentic_fallback)

app = CLIApp(
    "resume-assistant",
    "Extract, summarize, and render resumes from LinkedIn profiles and existing resumes.",
    add_common_args=False,
)


def _emit_agentic(fmt: str, compact: bool) -> int:
    from ..agentic import emit_agentic_context
    return emit_agentic_context(fmt, compact)


# --- register all commands ---
register_extract_commands(app)
register_summarize_commands(app)
register_render_commands(app)
register_align_commands(app)
register_style_commands(app)
register_files_commands(app)
register_experience_commands(app)
register_docx_commands(app)


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the Resume Assistant CLI."""
    return app.run_with_assistant(
        assistant=assistant,
        emit_func=_emit_agentic,
        argv=argv,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
