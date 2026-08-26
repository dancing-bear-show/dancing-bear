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

import argparse
from pathlib import Path
from typing import Callable

from core.assistant import BaseAssistant
from core.cli_errors import CLIError, ExitCode
from core.cli_framework import CLIApp
from core.paths import ENV_DATA_HOME, output_dir

from core.textio import write_text

from ..io_utils import read_text_any, read_text_raw, read_yaml_or_json, write_yaml_or_json
from ..model import CandidateData
from ..parsing_linkedin import parse_linkedin_text
from ..parsing_experience_text import parse_resume_text, merge_profiles
from ..summarizer import build_summary
from ..templating import load_template, parse_seed_criteria
from ..docx_writer import write_resume_docx
from ..structure import infer_structure_from_docx
from ..job import load_job_config, build_keyword_spec
from ..aligner import align_candidate_to_job, build_tailored_candidate
from ..cleanup import build_tidy_plan, execute_archive, execute_delete, purge_temp_files
from ..experience_summary import build_experience_summary
from ..overlays import apply_profile_overlays
from ..pipeline import FilterPipeline

# Default profile used when --profile is not provided
DEFAULT_PROFILE = "sample"

# Domain subdirectory under the data root; also the --out-dir help text, which
# names the resolved default so `--help` does not claim a path that moved.
OUT_DIR_DOMAIN = "resume"
OUT_DIR_HELP = (
    "Output directory (default: <data-home>/resume, "
    f"overridable with ${ENV_DATA_HOME})"
)

# Common extension constants
EXT_JSON = ".json"
EXT_YAML = ".yaml"

assistant = BaseAssistant(
    "resume",
    "agentic: resume\npurpose: Extract, summarize, and render resumes",
)

app = CLIApp(
    "resume-assistant",
    "Extract, summarize, and render resumes from LinkedIn profiles and existing resumes.",
    add_common_args=False,
)


def _emit_agentic(fmt: str, compact: bool) -> int:
    from ..agentic import emit_agentic_context
    return emit_agentic_context(fmt, compact)


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


def _apply_filter_pipeline(data: dict, args: argparse.Namespace, min_priority: float | None = None) -> dict:
    """Apply profile overlay, skill filter, and experience filter (and optionally priority) via FilterPipeline."""
    return (
        FilterPipeline(data)
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


# --- extract command ---
@app.command("extract", help="Parse LinkedIn and resume sources and produce unified data (YAML/JSON)")
@app.argument("--linkedin", help="Path to LinkedIn profile (txt/md/html/docx/pdf)")
@app.argument("--resume", help="Path to resume (txt/md/html/docx/pdf)")
@app.argument("--out", help="Output file path (overrides --profile)")
@app.argument("--profile", help="Output prefix (e.g., 'briancorysherwin_general')")
@app.argument("--out-dir", help=OUT_DIR_HELP)
def cmd_extract(args: argparse.Namespace) -> int:
    linkedin_text = _read_linkedin_text(args.linkedin) if args.linkedin else ""
    resume_text = read_text_any(args.resume) if args.resume else ""
    li = parse_linkedin_text(linkedin_text) if linkedin_text else {}
    rs = _parse_resume_source(args.resume, resume_text) if args.resume else {}
    data: CandidateData = merge_profiles(li, rs)
    out_path = _resolve_out(args, EXT_JSON, kind="data")
    write_yaml_or_json(data, out_path)
    return 0


# --- summarize command ---
@app.command("summarize", help="Build heuristically-derived summary output")
@app.argument("--data", required=True, help="Unified data file (YAML/JSON)")
@app.argument("--seed", help="Seed criteria as JSON string or KEY=VALUE pairs (comma-separated)")
@app.argument("--style-profile", help="Style profile JSON from 'style build' (optional)")
@app.argument("--filter-skills-alignment", help="Alignment JSON to filter Skills")
@app.argument("--filter-skills-job", help="Job YAML/JSON to supplement synonyms")
@app.argument("--filter-exp-alignment", help="Alignment JSON to filter Experience")
@app.argument("--filter-exp-job", help="Job YAML/JSON for experience filter")
@app.argument("--out", help="Output file path (overrides --profile)")
@app.argument("--profile", help="Output prefix (e.g., 'briancorysherwin_general')")
@app.argument("--out-dir", help=OUT_DIR_HELP)
def cmd_summarize(args: argparse.Namespace) -> int:
    data = read_yaml_or_json(args.data)
    data = _apply_filter_pipeline(data, args)

    seed = parse_seed_criteria(args.seed) if args.seed else {}
    seed = _extend_seed_with_style(seed, getattr(args, "style_profile", None))
    summary = build_summary(data, seed)
    out = _resolve_out(args, ".md", kind="summary")
    if out.suffix.lower() in {EXT_YAML, ".yml", EXT_JSON}:
        write_yaml_or_json(summary, out)
    else:
        # Default to markdown/text
        lines = ["# Resume Summary"]
        if summary.get("headline"):
            lines.append(f"\n## Headline\n{summary['headline']}")
        if summary.get("top_skills"):
            skills = ", ".join(summary["top_skills"]) or ""
            lines.append(f"\n## Top Skills\n{skills}")
        if summary.get("experience_highlights"):
            lines.append("\n## Experience Highlights")
            for item in summary["experience_highlights"]:
                lines.append(f"- {item}")
        write_text(out, "\n".join(lines))
    return 0


# --- render helpers ---


def _try_load_structure(path: Path) -> dict | None:
    """Try to load structure from a file, return None on failure."""
    if not path.exists():
        return None
    try:
        return read_yaml_or_json(str(path))
    except Exception:  # nosec B110 - best-effort structure load; returns None on any failure
        return None


def _find_first_structure(
    out_dirs: list[Path], extensions: tuple, path_for: Callable[[Path, str], Path]
) -> dict | None:
    """Try each (out_dir, extension) combination via path_for until a structure loads."""
    for out_dir in out_dirs:
        for ext in extensions:
            if (structure := _try_load_structure(path_for(out_dir, ext))):
                return structure
    return None


def _find_structure_in_dirs(
    profile: str, out_dirs: list[Path], extensions: tuple = (EXT_JSON, EXT_YAML, ".yml")
) -> dict | None:
    """Search for structure file in output directories (nested and legacy flat)."""
    # Try nested location first: out_dir/profile/structure.ext
    nested = _find_first_structure(
        out_dirs, extensions, lambda out_dir, ext: out_dir / profile / f"structure{ext}"
    )
    if nested:
        return nested
    # Fallback to legacy flat naming: out_dir/profile.structure.ext
    return _find_first_structure(
        out_dirs, extensions, lambda out_dir, ext: out_dir / f"{profile}.structure{ext}"
    )


def _find_structure_in_config(
    profile: str, extensions: tuple = (EXT_JSON, EXT_YAML, ".yml")
) -> dict | None:
    """Search for structure file in config folder."""
    config_dir = Path("config") / "profiles" / profile
    return _find_first_structure(
        [config_dir], extensions, lambda out_dir, ext: out_dir / f"structure{ext}"
    )


def _load_structure(args: argparse.Namespace) -> dict | None:
    """Load structure from explicit path or auto-discover for profile."""
    if args.structure_from:
        sf = str(args.structure_from)
        if sf.lower().endswith((EXT_JSON, EXT_YAML, ".yml")):
            return _try_load_structure(Path(sf))
        return infer_structure_from_docx(sf)

    profile = getattr(args, "profile", None)
    if not profile:
        return None

    # Build list of output directories to search. This path READS existing
    # files, so the in-repo locations stay in the search order even though
    # nothing writes there any more — a structure file left by an earlier run
    # must keep resolving instead of silently disappearing.
    base_out_dir = output_dir(OUT_DIR_DOMAIN, getattr(args, "out_dir", None))
    out_dirs = [base_out_dir]
    for legacy in (Path("out"), Path("_out")):
        if legacy not in out_dirs:
            out_dirs.append(legacy)

    return _find_structure_in_dirs(profile, out_dirs) or _find_structure_in_config(profile)


# --- render command ---
@app.command("render", help="Render a DOCX resume from unified data with a YAML/JSON template")
@app.argument("--data", required=True, help="Unified data file (YAML/JSON)")
@app.argument("--template", help="Template config (YAML/JSON); defaults to summary/skills/experience/education")
@app.argument("--seed", help="Seed criteria as JSON string or KEY=VALUE pairs (comma-separated)")
@app.argument("--style-profile", help="Style profile JSON from 'style build' (optional)")
@app.argument("--filter-skills-alignment", help="Alignment JSON to filter Skills to matched keywords")
@app.argument("--filter-skills-job", help="Job YAML/JSON to supplement synonyms for filtering")
@app.argument("--filter-exp-alignment", help="Alignment JSON to filter Experience to matched keywords")
@app.argument("--filter-exp-job", help="Job YAML/JSON to supplement synonyms for experience filter")
@app.argument("--structure-from", help="Reference DOCX resume to mimic section order and headings")
@app.argument("--min-priority", type=float, help="Filter Skills/Technologies items by priority (keep >= cutoff)")
@app.argument("--out", help="Output file path (overrides --profile)")
@app.argument("--profile", help="Output prefix (e.g., 'briancorysherwin_general')")
@app.argument("--out-dir", help=OUT_DIR_HELP)
def cmd_render(args: argparse.Namespace) -> int:
    data = read_yaml_or_json(args.data)
    template = load_template(args.template)
    seed = parse_seed_criteria(args.seed) if args.seed else {}
    seed = _extend_seed_with_style(seed, getattr(args, "style_profile", None))

    # Apply all filters via pipeline
    min_prio = getattr(args, "min_priority", None)
    data = _apply_filter_pipeline(
        data, args, float(min_prio) if isinstance(min_prio, (int, float)) else None
    )

    structure = _load_structure(args)
    out_docx = _resolve_out(args, ".docx", kind="resume")
    out_suf = out_docx.suffix.lower()
    if out_suf == ".pdf":
        raise CLIError("PDF rendering planned for future; use .docx output.", ExitCode.USAGE)
    # default to docx
    # Ensure parent directory exists for nested profile layout
    try:
        out_docx.parent.mkdir(parents=True, exist_ok=True)
    except Exception:  # nosec B110 - mkdir failure
        pass
    write_resume_docx(
        data=data,
        template=template,
        out_path=str(out_docx),
        seed=seed,
        structure=structure,
    )
    return 0


# --- structure command ---
@app.command("structure", help="Infer section order and headings from a reference DOCX resume")
@app.argument("--source", required=True, help="Reference .docx file")
@app.argument("--out", help="Output file path (overrides --profile)")
@app.argument("--profile", help="Output prefix (e.g., 'briancorysherwin_general')")
@app.argument("--out-dir", help=OUT_DIR_HELP)
def cmd_structure(args: argparse.Namespace) -> int:
    struct = infer_structure_from_docx(args.source)
    out = _resolve_out(args, EXT_JSON, kind="structure")
    write_yaml_or_json(struct, out)
    return 0


# --- align command ---
@app.command("align", help="Align unified candidate data with a job posting YAML/JSON")
@app.argument("--data", required=True, help="Unified candidate data (YAML/JSON)")
@app.argument("--job", required=True, help="Job posting config (YAML/JSON)")
@app.argument("--tailored", help="Optional path to write tailored candidate data (YAML/JSON)")
@app.argument("--max-bullets", type=int, default=6, help="Max bullets per role in tailored output")
@app.argument("--min-exp-score", type=int, default=1, help="Minimum experience score to keep a role")
@app.argument("--out", help="Alignment report path (overrides --profile)")
@app.argument("--profile", help="Output prefix (e.g., 'briancorysherwin_general')")
@app.argument("--out-dir", help=OUT_DIR_HELP)
def cmd_align(args: argparse.Namespace) -> int:
    candidate = read_yaml_or_json(args.data)
    prof = getattr(args, "profile", None)
    if prof:
        candidate = apply_profile_overlays(candidate, prof)
    job_cfg = load_job_config(args.job)
    kw_spec, synonyms = build_keyword_spec(job_cfg)
    al = align_candidate_to_job(candidate, kw_spec, synonyms)
    out = _resolve_out(args, EXT_JSON, kind="alignment")
    write_yaml_or_json(al, out)
    if args.tailored:
        tailored = build_tailored_candidate(
            candidate, al, max_bullets_per_role=args.max_bullets, min_exp_score=args.min_exp_score
        )
        write_yaml_or_json(tailored, Path(args.tailored))
    return 0


# --- candidate-init command ---
@app.command("candidate-init", help="Generate a candidate skills YAML from unified data")
@app.argument("--data", required=True, help="Unified candidate data (YAML/JSON)")
@app.argument("--include-experience", action="store_true", help="Include experience items and bullets")
@app.argument("--max-bullets", type=int, default=3, help="Max bullets per role if including experience")
@app.argument("--out", help="Output candidate YAML path (overrides --profile)")
@app.argument("--profile", help="Output prefix (e.g., 'briancorysherwin_general')")
@app.argument("--out-dir", help=OUT_DIR_HELP)
def cmd_candidate_init(args: argparse.Namespace) -> int:
    data = read_yaml_or_json(args.data)
    # Overlay profile data onto candidate if profile is provided
    prof = getattr(args, "profile", None)
    if prof:
        data = apply_profile_overlays(data, prof)
    out = _resolve_out(args, EXT_YAML, kind="candidate")
    # Build skeleton candidate skills YAML
    skills = [str(s) for s in (data.get("skills") or [])]
    candidate = {
        "name": data.get("name", ""),
        "headline": data.get("headline", ""),
        "contact": {
            "email": data.get("email", ""),
            "phone": data.get("phone", ""),
            "location": data.get("location", ""),
        },
        "summary_keywords": [],
        "skills": {
            "soft_skills": [],
            "tech_skills": skills,
            "technologies": [],
        },
    }
    if args.include_experience:
        items = []
        for e in (data.get("experience") or []):
            items.append({
                "title": e.get("title", ""),
                "company": e.get("company", ""),
                "start": e.get("start", ""),
                "end": e.get("end", ""),
                "location": e.get("location", ""),
                "bullets": (e.get("bullets") or [])[: args.max_bullets],
            })
        candidate["experience"] = items
    write_yaml_or_json(candidate, out)
    return 0


# --- style group ---
style_group = app.group("style", help="Build or manage style profiles from a prose corpus")


@style_group.command("build", help="Build style profile JSON from a corpus directory")
@style_group.argument("--corpus-dir", required=True, help="Directory of prose samples (.txt/.md/.docx)")
@style_group.argument("--out", help="Output file path (overrides --profile)")
@style_group.argument("--profile", help="Output prefix (e.g., 'briancorysherwin_general')")
@style_group.argument("--out-dir", help=OUT_DIR_HELP)
def cmd_style_build(args: argparse.Namespace) -> int:
    from ..style import build_style_profile
    prof = build_style_profile(args.corpus_dir)
    out = _resolve_out(args, EXT_JSON, kind="style")
    write_yaml_or_json(prof, out)
    return 0


# --- files group ---
files_group = app.group("files", help="File utilities for organizing outputs and data")


@files_group.command("tidy", help="Archive or delete old files to reduce noise")
@files_group.argument("--dir", default="_data", help="Directory to tidy (default: _data)")
@files_group.argument("--prefix", help="Only match files starting with this prefix")
@files_group.argument("--suffixes", default=".json,.docx", help="Comma-separated suffix list (e.g., .json,.docx)")
@files_group.argument("--keep", type=int, default=2, help="Keep most-recent N matches (default: 2)")
@files_group.argument("--archive-dir", help="Archive destination directory (default: <dir>/archive)")
@files_group.argument("--delete", action="store_true", help="Delete old files instead of archiving")
@files_group.argument("--purge-temp", action="store_true", help="Remove temporary files (e.g., '~$*.docx', .DS_Store)")
@files_group.argument("--subfolder", help="Subfolder under archive for moved files (e.g., profile name)")
def cmd_files_tidy(args: argparse.Namespace) -> int:
    suffixes = [s.strip() for s in (args.suffixes or "").split(",") if s.strip()]
    plan = build_tidy_plan(
        dir_path=args.dir,
        prefix=args.prefix,
        suffixes=suffixes,
        keep=args.keep,
        archive_dir=args.archive_dir,
    )
    # Archive/delete old files
    if plan.move:
        if args.delete:
            execute_delete(plan)
        else:
            execute_archive(plan, subfolder=args.subfolder or args.prefix)
    # Purge temp files if requested
    if args.purge_temp:
        purge_temp_files(args.dir)
    return 0


# --- experience group ---
experience_group = app.group("experience", help="Experience tools")


@experience_group.command("export", help="Export a YAML/JSON summary of job history from data or resume")
@experience_group.argument("--data", help="Unified data file (YAML/JSON)")
@experience_group.argument("--resume", help="Resume file to parse (txt/md/html/docx/pdf)")
@experience_group.argument("--max-bullets", type=int, default=None, help="Limit bullets per role in summary")
@experience_group.argument("--out", help="Output file path (overrides --profile)")
@experience_group.argument("--profile", help="Output prefix (e.g., 'briancorysherwin_general')")
@experience_group.argument("--out-dir", help=OUT_DIR_HELP)
def cmd_experience_export(args: argparse.Namespace) -> int:
    if not args.data and not args.resume:
        raise SystemExit("Provide --data or --resume")
    if args.data:
        data = read_yaml_or_json(args.data)
        prof = getattr(args, "profile", None)
        if prof:
            data = apply_profile_overlays(data, prof)
    else:
        # parse from resume file
        resume_text = read_text_any(args.resume)
        if str(args.resume).lower().endswith(".docx"):
            from ..parsing_experience_docx import parse_resume_docx

            data = parse_resume_docx(args.resume)
        else:
            data = parse_resume_text(resume_text)
    summary = build_experience_summary(data, max_bullets=args.max_bullets)
    out = _resolve_out(args, EXT_YAML, kind="experience")
    write_yaml_or_json(summary, out)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Main entry point for the Resume Assistant CLI."""
    return app.run_with_assistant(
        assistant=assistant,
        emit_func=_emit_agentic,
        argv=argv,
    )


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
