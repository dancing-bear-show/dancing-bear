import argparse
import json
import sys
from pathlib import Path

from core.assistant import BaseAssistant

from ..io_utils import read_text_any, read_text_raw, read_yaml_or_json, write_yaml_or_json, write_text
from ..parsing import parse_linkedin_text, parse_resume_text, merge_profiles
from ..summarizer import build_summary
from ..templating import load_template, parse_seed_criteria
from ..docx_writer import write_resume_docx
from ..structure import infer_structure_from_docx
from ..job import load_job_config, build_keyword_spec
from ..aligner import align_candidate_to_job, build_tailored_candidate
from ..skills_filter import filter_skills_by_keywords
from ..experience_filter import filter_experience_by_keywords
from ..cleanup import build_tidy_plan, execute_archive, execute_delete, purge_temp_files
from ..experience_summary import build_experience_summary
from ..overlays import apply_profile_overlays
from ..priority import filter_by_min_priority

# Default profile used when --profile is not provided
DEFAULT_PROFILE = "sample"

assistant = BaseAssistant(
    "resume_assistant",
    "agentic: resume_assistant\npurpose: Extract, summarize, and render resumes",
)


def _extend_seed_with_style(seed: dict, style_profile_path) -> dict:
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
    except Exception:
        # Non-fatal; keep seed as-is
        pass
    return seed


def _apply_profile_overlays(data: dict, prof) -> dict:
    # shim retained for backward-compatibility within this module; delegate
    return apply_profile_overlays(data, prof)


def _apply_alignment_filters(data: dict, args: argparse.Namespace) -> dict:
    """Apply optional alignment-based filters to skills and experience.

    When the render CLI provides `--filter-skills-alignment` or
    `--filter-exp-alignment`, this helper trims the corresponding
    sections to matched keywords from the alignment JSON. If a job
    file is also provided, synonyms are included.
    """
    out = dict(data)
    # Build synonyms map from job spec if provided
    synonyms = {}
    try:
        if getattr(args, "filter_skills_job", None):
            spec, syn = build_keyword_spec(load_job_config(args.filter_skills_job))
            synonyms.update(syn or {})
    except Exception:
        pass
    try:
        if getattr(args, "filter_exp_job", None):
            spec, syn = build_keyword_spec(load_job_config(args.filter_exp_job))
            synonyms.update(syn or {})
    except Exception:
        pass

    # Skills filter
    try:
        skills_align = getattr(args, "filter_skills_alignment", None)
        if skills_align:
            al = read_yaml_or_json(skills_align)
            matched = [m.get("skill") for m in (al.get("matched_keywords") or []) if m.get("skill")]
            out = filter_skills_by_keywords(out, matched, synonyms)
    except Exception:
        pass

    # Experience filter
    try:
        exp_align = getattr(args, "filter_exp_alignment", None)
        if exp_align:
            al = read_yaml_or_json(exp_align)
            matched = [m.get("skill") for m in (al.get("matched_keywords") or []) if m.get("skill")]
            out = filter_experience_by_keywords(out, matched_keywords=matched, synonyms=synonyms)
    except Exception:
        pass

    return out


def _add_common_io_args(p: argparse.ArgumentParser):
    p.add_argument("--out", help="Output file path (overrides --profile)")
    p.add_argument("--profile", help="Output prefix (e.g., 'briancorysherwin_general')")
    p.add_argument("--out-dir", default="out", help="Output directory (default: out; pass _out for legacy layouts)")


def _resolve_out(args: argparse.Namespace, default_ext: str, kind: str) -> Path:
    """Resolve output path.

    New scheme: nest by profile under out-dir for clearer segregation:
      out/<profile>/<kind><ext>

    Backward compatibility is preserved elsewhere when reading (e.g., structure).
    """
    if getattr(args, "out", None):
        return Path(args.out)
    prefix = getattr(args, "profile", None) or DEFAULT_PROFILE
    out_dir = Path(getattr(args, "out_dir", "out") or "out") / prefix
    name = f"{kind}{default_ext}" if kind else f"{default_ext.lstrip('.')}"
    path = out_dir / name
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _cmd_extract(args: argparse.Namespace) -> int:
    linkedin_text = ""
    if args.linkedin:
        if str(args.linkedin).lower().endswith((".html", ".htm")):
            linkedin_text = read_text_raw(args.linkedin)
        else:
            linkedin_text = read_text_any(args.linkedin)
    resume_text = read_text_any(args.resume) if args.resume else ""
    li = parse_linkedin_text(linkedin_text) if linkedin_text else {}
    rs = {}
    if args.resume:
        if str(args.resume).lower().endswith('.docx'):
            from ..parsing import parse_resume_docx
            rs = parse_resume_docx(args.resume)
        else:
            rs = parse_resume_text(resume_text) if resume_text else {}
    data = merge_profiles(li, rs)
    out_path = _resolve_out(args, ".json", kind="data")
    write_yaml_or_json(data, out_path)
    return 0


def _cmd_summarize(args: argparse.Namespace) -> int:
    data = read_yaml_or_json(args.data)
    # Optional: overlay profile data when --profile is provided
    prof = getattr(args, "profile", None)
    if prof:
        data = _apply_profile_overlays(data, prof)
    seed = parse_seed_criteria(args.seed) if args.seed else {}
    seed = _extend_seed_with_style(seed, getattr(args, "style_profile", None))
    # Optional: filter skills to matched keywords
    if getattr(args, "filter_skills_alignment", None):
        try:
            al = read_yaml_or_json(args.filter_skills_alignment)
            matched = [m.get("skill") for m in (al.get("matched_keywords") or []) if m.get("skill")]
            synonyms = {}
            if getattr(args, "filter_skills_job", None):
                spec, syn = build_keyword_spec(load_job_config(args.filter_skills_job))
                synonyms = syn or {}
            data = filter_skills_by_keywords(data, matched, synonyms)
        except Exception:
            pass
    # Optional: filter experience to matched keywords
    if getattr(args, "filter_exp_alignment", None):
        try:
            al = read_yaml_or_json(args.filter_exp_alignment)
            matched = [m.get("skill") for m in (al.get("matched_keywords") or []) if m.get("skill")]
            synonyms = {}
            if getattr(args, "filter_exp_job", None):
                spec, syn = build_keyword_spec(load_job_config(args.filter_exp_job))
                synonyms = syn or {}
            data = filter_experience_by_keywords(
                data,
                matched_keywords=matched,
                synonyms=synonyms,
            )
        except Exception:
            pass
    # (skills already optionally filtered above)
    summary = build_summary(data, seed)
    out = _resolve_out(args, ".md", kind="summary")
    if out.suffix.lower() in {".yaml", ".yml", ".json"}:
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
        write_text("\n".join(lines), out)
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    data = read_yaml_or_json(args.data)
    template = load_template(args.template) if args.template else {}
    seed = parse_seed_criteria(args.seed) if args.seed else {}
    seed = _extend_seed_with_style(seed, getattr(args, "style_profile", None))
    # Overlay profile config if present (e.g., config/profile.<profile>.yaml)
    prof = getattr(args, "profile", None)
    if prof:
        data = _apply_profile_overlays(data, prof)
    # Optional: filter skills/experience via alignment report (+ optional job synonyms)
    data = _apply_alignment_filters(data, args)
    # Optional: filter grouped skills/technologies/summary/experience by priority/usefulness cutoff
    min_prio = getattr(args, "min_priority", None)
    if isinstance(min_prio, (int, float)):
        data = filter_by_min_priority(data, float(min_prio))

    structure = None
    if args.structure_from:
        sf = str(args.structure_from)
        if sf.lower().endswith((".json", ".yaml", ".yml")):
            try:
                structure = read_yaml_or_json(sf)
            except Exception:
                structure = None
        else:
            structure = infer_structure_from_docx(sf)
    else:
        # If no structure explicitly provided, attempt to reuse saved structure for this profile
        prof = getattr(args, "profile", None)
        base_out_dir = Path(getattr(args, "out_dir", "out") or "out")
        candidate_out_dirs = [base_out_dir]
        legacy_out_dir = Path("_out")
        if legacy_out_dir not in candidate_out_dirs:
            candidate_out_dirs.append(legacy_out_dir)
        if prof:
            # New nested location first
            for out_dir in candidate_out_dirs:
                for ext in (".json", ".yaml", ".yml"):
                    sfile_new = out_dir / prof / f"structure{ext}"
                    if sfile_new.exists():
                        try:
                            structure = read_yaml_or_json(str(sfile_new))
                            break
                        except Exception:
                            structure = None
                if structure is not None:
                    break
            # Fallback to legacy flat naming
            if structure is None:
                for out_dir in candidate_out_dirs:
                    for ext in (".json", ".yaml", ".yml"):
                        sfile_old = out_dir / f"{prof}.structure{ext}"
                        if sfile_old.exists():
                            try:
                                structure = read_yaml_or_json(str(sfile_old))
                                break
                            except Exception:
                                structure = None
                    if structure is not None:
                        break
            # Also consider a config-provided structure file in the profile folder
            if structure is None:
                for ext in (".json", ".yaml", ".yml"):
                    sfile_cfg = Path("config") / "profiles" / prof / f"structure{ext}"
                    if sfile_cfg.exists():
                        try:
                            structure = read_yaml_or_json(str(sfile_cfg))
                            break
                        except Exception:
                            structure = None
    out_docx = _resolve_out(args, ".docx", kind="resume")
    out_suf = out_docx.suffix.lower()
    if out_suf == ".pdf":
        raise RuntimeError("PDF rendering planned for future; use .docx output.")
    # default to docx
    # Ensure parent directory exists for nested profile layout
    try:
        out_docx.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    write_resume_docx(
        data=data,
        template=template,
        out_path=str(out_docx),
        seed=seed,
        structure=structure,
    )
    return 0


def _cmd_structure(args: argparse.Namespace) -> int:
    struct = infer_structure_from_docx(args.source)
    out = _resolve_out(args, ".json", kind="structure")
    write_yaml_or_json(struct, out)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="resume-assistant",
        description=(
            "Extract, summarize, and render resumes from LinkedIn profiles and existing resumes."
        ),
    )
    assistant.add_agentic_flags(p)
    sub = p.add_subparsers(dest="command", required=True)

    # extract
    p_ext = sub.add_parser(
        "extract",
        help="Parse LinkedIn and resume sources and produce unified data (YAML/JSON).",
    )
    p_ext.add_argument("--linkedin", help="Path to LinkedIn profile (txt/md/html/docx/pdf)")
    p_ext.add_argument("--resume", help="Path to resume (txt/md/html/docx/pdf)")
    _add_common_io_args(p_ext)
    p_ext.set_defaults(func=_cmd_extract)

    # summarize
    p_sum = sub.add_parser("summarize", help="Build heuristically-derived summary output.")
    p_sum.add_argument("--data", required=True, help="Unified data file (YAML/JSON)")
    p_sum.add_argument(
        "--seed",
        help="Seed criteria as JSON string or KEY=VALUE pairs (comma-separated).",
    )
    p_sum.add_argument("--style-profile", help="Style profile JSON from 'style build' (optional)")
    _add_common_io_args(p_sum)
    p_sum.set_defaults(func=_cmd_summarize)

    # render
    p_r = sub.add_parser(
        "render",
        help=(
            "Render a DOCX resume from unified data with a YAML/JSON template."
        ),
    )
    p_r.add_argument("--data", required=True, help="Unified data file (YAML/JSON)")
    p_r.add_argument("--template", help="Template config (YAML/JSON)")
    p_r.add_argument(
        "--seed",
        help="Seed criteria as JSON string or KEY=VALUE pairs (comma-separated).",
    )
    p_r.add_argument("--style-profile", help="Style profile JSON from 'style build' (optional)")
    p_r.add_argument("--filter-skills-alignment", help="Alignment JSON to filter Skills to matched keywords")
    p_r.add_argument("--filter-skills-job", help="Job YAML/JSON to supplement synonyms for filtering")
    p_r.add_argument("--filter-exp-alignment", help="Alignment JSON to filter Experience to matched keywords")
    p_r.add_argument("--filter-exp-job", help="Job YAML/JSON to supplement synonyms for experience filter")
    p_r.add_argument(
        "--structure-from",
        help="Reference DOCX resume to mimic section order and headings.",
    )
    p_r.add_argument(
        "--min-priority", type=float, help="Filter Skills/Technologies items by priority/usefulness (keep items >= cutoff)")
    _add_common_io_args(p_r)
    p_r.set_defaults(func=_cmd_render)

    # structure
    p_s = sub.add_parser(
        "structure",
        help="Infer section order and headings from a reference DOCX resume.",
    )
    p_s.add_argument("--source", required=True, help="Reference .docx file")
    _add_common_io_args(p_s)
    p_s.set_defaults(func=_cmd_structure)

    # align
    p_a = sub.add_parser(
        "align",
        help="Align unified candidate data with a job posting YAML/JSON and output alignment report.",
    )
    p_a.add_argument("--data", required=True, help="Unified candidate data (YAML/JSON)")
    p_a.add_argument("--job", required=True, help="Job posting config (YAML/JSON)")
    p_a.add_argument("--out", help="Alignment report (YAML/JSON); overrides --profile")
    p_a.add_argument(
        "--tailored",
        help="Optional path to write tailored candidate data focused on matched keywords (YAML/JSON)",
    )
    p_a.add_argument("--profile", help="Output prefix (e.g., 'briancorysherwin_general')")
    p_a.add_argument("--out-dir", default="out", help="Output directory (default: out; pass _out for legacy layouts)")
    p_a.add_argument("--max-bullets", type=int, default=6, help="Max bullets per role in tailored output")
    p_a.add_argument("--min-exp-score", type=int, default=1, help="Minimum experience score to keep a role")
    p_a.set_defaults(func=_cmd_align)

    # candidate-init
    p_ci = sub.add_parser(
        "candidate-init",
        help="Generate a candidate skills YAML from unified data for manual curation.",
    )
    p_ci.add_argument("--data", required=True, help="Unified candidate data (YAML/JSON)")
    p_ci.add_argument("--out", help="Output candidate YAML path; overrides --profile")
    p_ci.add_argument("--profile", help="Output prefix (e.g., 'briancorysherwin_general')")
    p_ci.add_argument("--out-dir", default="out", help="Output directory (default: out; pass _out for legacy layouts)")
    p_ci.add_argument("--include-experience", action="store_true", help="Include experience items and bullets")
    p_ci.add_argument("--max-bullets", type=int, default=3, help="Max bullets per role if including experience")
    p_ci.set_defaults(func=_cmd_candidate_init)

    # style
    p_style = sub.add_parser(
        "style",
        help="Build or manage style profiles from a prose corpus.",
    )
    style_sub = p_style.add_subparsers(dest="style_cmd", required=True)
    p_style_build = style_sub.add_parser("build", help="Build style profile JSON from a corpus directory")
    p_style_build.add_argument("--corpus-dir", required=True, help="Directory of prose samples (.txt/.md/.docx)")
    _add_common_io_args(p_style_build)
    p_style_build.set_defaults(func=_cmd_style_build)

    # files
    p_files = sub.add_parser("files", help="File utilities for organizing outputs and data")
    files_sub = p_files.add_subparsers(dest="files_cmd", required=True)
    p_tidy = files_sub.add_parser("tidy", help="Archive or delete old files to reduce noise")
    p_tidy.add_argument("--dir", default="_data", help="Directory to tidy (default: _data)")
    p_tidy.add_argument("--prefix", help="Only match files starting with this prefix")
    p_tidy.add_argument("--suffixes", default=".json,.docx", help="Comma-separated suffix list (e.g., .json,.docx)")
    p_tidy.add_argument("--keep", type=int, default=2, help="Keep most-recent N matches (default: 2)")
    p_tidy.add_argument("--archive-dir", help="Archive destination directory (default: <dir>/archive)")
    p_tidy.add_argument("--delete", action="store_true", help="Delete old files instead of archiving")
    p_tidy.add_argument("--purge-temp", action="store_true", help="Remove temporary files (e.g., '~$*.docx', .DS_Store)")
    p_tidy.add_argument("--subfolder", help="Subfolder under archive for moved files (e.g., profile name)")
    p_tidy.set_defaults(func=_cmd_files_tidy)

    # experience
    p_exp = sub.add_parser("experience", help="Experience tools")
    exp_sub = p_exp.add_subparsers(dest="exp_cmd", required=True)
    p_exp_export = exp_sub.add_parser(
        "export",
        help="Export a YAML/JSON summary of job history from data or a resume file",
    )
    p_exp_export.add_argument("--data", help="Unified data file (YAML/JSON)")
    p_exp_export.add_argument("--resume", help="Resume file to parse (txt/md/html/docx/pdf)")
    p_exp_export.add_argument("--max-bullets", type=int, default=None, help="Limit bullets per role in summary")
    _add_common_io_args(p_exp_export)
    p_exp_export.set_defaults(func=_cmd_experience_export)

    return p


from typing import List, Optional


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    def _emit_agentic(fmt: str, compact: bool) -> int:
        from ..agentic import emit_agentic_context

        return emit_agentic_context(fmt, compact)

    agentic_result = assistant.maybe_emit_agentic(args, emit_func=_emit_agentic)
    if agentic_result is not None:
        return int(agentic_result)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        return 2
    except Exception as exc:  # keep CLI stable: report and non-zero
        print(f"Error: {exc}", file=sys.stderr)
        return 1


def _cmd_align(args: argparse.Namespace) -> int:
    candidate = read_yaml_or_json(args.data)
    prof = getattr(args, "profile", None)
    if prof:
        candidate = _apply_profile_overlays(candidate, prof)
    job_cfg = load_job_config(args.job)
    kw_spec, synonyms = build_keyword_spec(job_cfg)
    al = align_candidate_to_job(candidate, kw_spec, synonyms)
    out = _resolve_out(args, ".json", kind="alignment")
    write_yaml_or_json(al, out)
    if args.tailored:
        tailored = build_tailored_candidate(
            candidate, al, max_bullets_per_role=args.max_bullets, min_exp_score=args.min_exp_score
        )
        write_yaml_or_json(tailored, Path(args.tailored))
    return 0


def _cmd_candidate_init(args: argparse.Namespace) -> int:
    data = read_yaml_or_json(args.data)
    # Overlay profile data onto candidate if profile is provided
    prof = getattr(args, "profile", None)
    if prof:
        data = _apply_profile_overlays(data, prof)
    out = _resolve_out(args, ".yaml", kind="candidate")
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


def _cmd_style_build(args: argparse.Namespace) -> int:
    from ..style import build_style_profile
    prof = build_style_profile(args.corpus_dir)
    out = _resolve_out(args, ".json", kind="style")
    write_yaml_or_json(prof, out)
    return 0


def _cmd_files_tidy(args: argparse.Namespace) -> int:
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


def _cmd_experience_export(args: argparse.Namespace) -> int:
    if not args.data and not args.resume:
        raise SystemExit("Provide --data or --resume")
    if args.data:
        data = read_yaml_or_json(args.data)
        prof = getattr(args, "profile", None)
        if prof:
            data = _apply_profile_overlays(data, prof)
    else:
        # parse from resume file
        resume_text = read_text_any(args.resume)
        if str(args.resume).lower().endswith(".docx"):
            from ..parsing import parse_resume_docx

            data = parse_resume_docx(args.resume)
        else:
            data = parse_resume_text(resume_text)
    summary = build_experience_summary(data, max_bullets=args.max_bullets)
    out = _resolve_out(args, ".yaml", kind="experience")
    write_yaml_or_json(summary, out)
    return 0
