"""Shared private helpers for the Resume Assistant CLI.

These helpers are used by two or more command modules.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from core.cli_errors import CLIError, ExitCode
from core.paths import config_home, output_dir

from ..io_utils import read_text_any, read_text_raw, read_yaml_or_json
from ..schema import Resume
from ..parsing_experience_text import parse_resume_text
from ..pipeline import FilterPipeline

from .args import DEFAULT_PROFILE, OUT_DIR_DOMAIN


def _extend_seed_with_style(seed: dict, style_profile_path: str | None) -> dict:
    if not style_profile_path:
        return seed
    try:
        sp = read_yaml_or_json(style_profile_path)
        from ..style import extract_style_keywords

        style_kws = extract_style_keywords(sp, limit=10)
        if style_kws:
            cur = seed.get("keywords", [])
            if isinstance(cur, str):
                cur = [cur]
            seed["keywords"] = list(dict.fromkeys(list(cur) + style_kws))
    except Exception:  # nosec B110 - non-fatal seed extension
        pass
    return seed


def _load_candidate_data(args: argparse.Namespace) -> dict:
    """Load candidate data and normalize its shape once, at the document boundary.

    Candidate data reaches this CLI in several shapes: ``bullets`` may be
    ``list[str]`` or ``list[dict]``, section items may use ``text``/``line``/
    ``name``. Those are all mainstream producer output, not legacy leftovers --
    ``parsing_experience_text._extract_bullets`` returns ``list[str]``.

    Normalizing here rather than deeper in the pipeline is the point. When the
    conversion sat at the filter call site instead, the shape changed *midway*
    through the run, so a consumer saw ``list[str]`` or ``list[dict]`` depending
    on whether a filter had run -- which is how ``summarize`` came to raise
    ``TypeError`` on filtered data while working on unfiltered data. Converting
    once, on load, gives every consumer the same shape.

    Returns a plain dict, not a ``Resume``. The remaining consumers downstream
    of here (``build_summary``, ``align_candidate_to_job``,
    ``apply_profile_overlays``, ``build_experience_summary``) all take a dict,
    so returning the typed object would only add a ``.to_dict()`` at each of
    them. The render path is the exception: it re-enters the schema through
    ``_apply_filter_pipeline``, which now returns the ``Resume`` that
    ``write_resume_docx`` requires. Converting the rest is a later step.

    Only candidate data goes through here. Style profiles and alignment reports
    are different documents with different shapes and are loaded directly.

    A data file that does not parse to a dict -- a truncated YAML that reads
    as a bare list or string -- makes ``Resume.from_dict`` raise. That is a user
    error, not a programming error, so it is reported as a ``CLIError`` naming
    the file rather than escaping as a traceback. Previously ``from_dict``
    returned an empty ``Resume`` for these inputs and the run rendered a blank
    document with nothing reporting a failure.

    The check is ``isinstance(raw, dict)``, matching ``Resume.from_dict``
    exactly. Both say "dict" rather than "mapping" so the message cannot be
    read as promising that any :class:`collections.abc.Mapping` is accepted.

    Raises:
        CLIError: If the data file's top level is not a dict.
    """
    path = _resolve_data(args)
    raw = read_yaml_or_json(path)
    if not isinstance(raw, dict):
        raise CLIError(
            f"{path}: candidate data must be a dict of resume sections, got "
            f"{type(raw).__name__}. Check the file is complete and not truncated.",
            ExitCode.USAGE,
        )
    return Resume.from_dict(raw).to_dict()


def _apply_filter_pipeline(
    data: dict, args: argparse.Namespace, min_priority: float | None = None
) -> Resume:
    """Apply profile overlay, skill filter, experience filter, and priority filter.

    Returns the ``Resume`` that ``FilterPipeline`` produces, rather than
    lowering it back to a dict. ``render`` hands that object straight to
    ``write_resume_docx``, so the typed value now survives from the filters to
    the writer instead of being flattened in between.

    The input is still a dict because ``_load_candidate_data`` feeds several
    dict-only consumers (``build_summary``, ``align_candidate_to_job``,
    ``apply_profile_overlays``); callers that need a dict from here call
    ``.to_dict()`` themselves.
    """
    return (
        FilterPipeline(Resume.from_dict(data))
        .with_profile_overlays(getattr(args, "profile", None))
        .with_skill_filter(
            getattr(args, "filter_skills_alignment", None),
            getattr(args, "filter_skills_job", None),
        )
        .with_experience_filter(
            getattr(args, "filter_exp_alignment", None),
            getattr(args, "filter_exp_job", None),
        )
        .with_priority_filter(min_priority)
        .execute()
    )


def _resolve_data(args: argparse.Namespace) -> str:
    """Return the candidate data path, falling back to the profile's config.

    ``--data`` wins when given — a user who names a path means it. Otherwise
    the file is read from the profile directory under the config root:

        <config-home>/resume/<profile>/data.{json,yaml,yml}

    This mirrors how mail resolves its unified filter config, and how
    ``--profile`` already selects credentials elsewhere. Without it, every
    invocation had to repeat an absolute path to data that lives at a
    predictable location, and ``--profile`` confusingly affected only the
    OUTPUT filename while the input still had to be spelled out.

    Config, not data-home: this file is user-authored source, and a resume
    carries a name, phone number, and address, so it stays outside the
    checkout for the same reason mail's filter rules do.
    """
    explicit = getattr(args, "data", None)
    if explicit:
        return str(explicit)

    profile = getattr(args, "profile", None) or DEFAULT_PROFILE
    base = config_home() / OUT_DIR_DOMAIN / profile
    # is_file(), not exists(): a directory named data.json would otherwise
    # satisfy the lookup and fail later inside the reader with a confusing
    # IsADirectoryError instead of the actionable message below.
    for name in ("data.json", "data.yaml", "data.yml"):
        candidate = base / name
        if candidate.is_file():
            return str(candidate)

    raise CLIError(
        f"No --data given and no data file found for profile '{profile}'. "
        f"Looked for data.json, data.yaml, data.yml under {base}. "
        f"Pass --data <path>, or create {base / 'data.json'}.",
        ExitCode.USAGE,
    )


def _resolve_out(args: argparse.Namespace, default_ext: str, kind: str) -> Path:
    """Resolve output path.

    Nests by profile under the resolved out-dir for clearer segregation:
      <out-dir>/<profile>/<kind><ext>

    ``<out-dir>`` is ``--out-dir`` when given, else ``core.paths.output_dir()``
    for this domain (``<data-home>/resume``).

    Backward compatibility is preserved elsewhere when reading (e.g., structure).
    """
    if getattr(args, "out", None):
        return Path(args.out)
    prefix = getattr(args, "profile", None) or DEFAULT_PROFILE
    out_dir = output_dir(OUT_DIR_DOMAIN, getattr(args, "out_dir", None)) / prefix
    name = f"{kind}{default_ext}" if kind else f"{default_ext.lstrip('.')}"
    path = out_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _read_linkedin_text(linkedin_path: str) -> str:
    """Read LinkedIn source text, using raw read for HTML sources."""
    if str(linkedin_path).lower().endswith((".html", ".htm")):
        return read_text_raw(linkedin_path)
    return read_text_any(linkedin_path)


def _parse_resume_source(resume_path: str, resume_text: str) -> dict:
    """Parse a resume source, dispatching by file extension."""
    resume_lower = str(resume_path).lower()
    if resume_lower.endswith('.docx'):
        from ..parsing_experience_docx import parse_resume_docx
        return parse_resume_docx(resume_path)
    if resume_lower.endswith('.pdf'):
        from ..parsing_experience_pdf import parse_resume_pdf
        return parse_resume_pdf(resume_path)
    return parse_resume_text(resume_text) if resume_text else {}
