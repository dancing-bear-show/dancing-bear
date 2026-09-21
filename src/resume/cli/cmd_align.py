"""Align and candidate-init command registration for the Resume Assistant CLI."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from core.cli_framework import CLIApp
from core.cli_framework_types import Argument

from ..io_utils import write_yaml_or_json
from ..job import load_job_config, build_keyword_spec
from ..aligner import align_candidate_to_job, build_tailored_candidate
from ..overlays import apply_profile_overlays
from ..keyword_normalize import item_text
from .args import PROFILE_HELP_DATA, OUT_DIR_HELP, DATA_HELP, EXT_JSON, EXT_YAML
from .helpers import _load_candidate_data, _resolve_out


def cmd_align(args: argparse.Namespace) -> int:
    candidate = _load_candidate_data(args)
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


def cmd_candidate_init(args: argparse.Namespace) -> int:
    data = _load_candidate_data(args)
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
                # Flattened to prose: this file is a hand-editable skills
                # skeleton, so bullets are written as plain strings regardless
                # of whether they arrived as strings or as priority dicts.
                "bullets": [
                    t
                    for b in (e.get("bullets") or [])[: args.max_bullets]
                    if (t := item_text(b))
                ],
            })
        candidate["experience"] = items
    write_yaml_or_json(candidate, out)
    return 0


def register_align_commands(app: CLIApp) -> None:
    """Register the align and candidate-init commands on app."""
    _ALIGN_ARGS: list[tuple[tuple[str, ...], dict[str, Any]]] = [
        (("--data",), {"help": DATA_HELP}),
        (("--job",), {"required": True, "help": "Job posting config (YAML/JSON)"}),
        (("--tailored",), {"help": "Optional path to write tailored candidate data (YAML/JSON)"}),
        (("--max-bullets",), {"type": int, "default": 6, "help": "Max bullets per role in tailored output"}),
        (("--min-exp-score",), {"type": int, "default": 1, "help": "Minimum experience score to keep a role"}),
        (("--out",), {"help": "Alignment report path (overrides --profile)"}),
        (("--profile",), {"help": PROFILE_HELP_DATA}),
        (("--out-dir",), {"help": OUT_DIR_HELP}),
    ]
    for flags, kwargs in reversed(_ALIGN_ARGS):
        app._pending_arguments.append(Argument(flags, kwargs))
    app.command("align", help="Align unified candidate data with a job posting YAML/JSON")(cmd_align)

    _CANDIDATE_INIT_ARGS: list[tuple[tuple[str, ...], dict[str, Any]]] = [
        (("--data",), {"help": DATA_HELP}),
        (("--include-experience",), {"action": "store_true", "help": "Include experience items and bullets"}),
        (("--max-bullets",), {"type": int, "default": 3, "help": "Max bullets per role if including experience"}),
        (("--out",), {"help": "Output candidate YAML path (overrides --profile)"}),
        (("--profile",), {"help": PROFILE_HELP_DATA}),
        (("--out-dir",), {"help": OUT_DIR_HELP}),
    ]
    for flags, kwargs in reversed(_CANDIDATE_INIT_ARGS):
        app._pending_arguments.append(Argument(flags, kwargs))
    app.command("candidate-init", help="Generate a candidate skills YAML from unified data")(cmd_candidate_init)
