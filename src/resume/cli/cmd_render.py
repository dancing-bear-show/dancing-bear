"""Render and structure command registration for the Resume Assistant CLI.

render and structure share the structure-loading helpers, so they live together.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Callable

from core.cli_errors import CLIError, ExitCode
from core.cli_framework import CLIApp
from core.paths import output_dir

from ..io_utils import read_yaml_or_json, write_yaml_or_json
from ..templating import load_template, parse_seed_criteria
from ..docx_writer import write_resume_docx
from ..structure import infer_structure_from_docx
from .args import PROFILE_HELP_DATA, PROFILE_HELP_OUT, OUT_DIR_HELP, DATA_HELP, EXT_JSON, EXT_YAML, OUT_DIR_DOMAIN
from .helpers import _load_candidate_data, _apply_filter_pipeline, _extend_seed_with_style, _resolve_out


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


def cmd_render(args: argparse.Namespace) -> int:
    data = _load_candidate_data(args)
    template = load_template(args.template)
    seed = parse_seed_criteria(args.seed) if args.seed else {}
    seed = _extend_seed_with_style(seed, getattr(args, "style_profile", None))

    # Apply all filters via pipeline. The result stays typed all the way into
    # the writer -- this is the only path that no longer lowers to a dict.
    min_prio = getattr(args, "min_priority", None)
    resume = _apply_filter_pipeline(
        data, args, float(min_prio) if isinstance(min_prio, (int, float)) else None
    )

    structure = _load_structure(args)
    out_docx = _resolve_out(args, ".docx", kind="resume")
    out_suf = out_docx.suffix.lower()
    if out_suf == ".pdf":
        raise CLIError("render writes .docx only; use 'resume export-pdf --docx <path>' to convert.", ExitCode.USAGE)
    # default to docx
    # Ensure parent directory exists for nested profile layout
    try:
        out_docx.parent.mkdir(parents=True, exist_ok=True)
    except Exception:  # nosec B110 - mkdir failure
        pass
    write_resume_docx(
        resume=resume,
        template=template,
        out_path=str(out_docx),
        seed=seed,
        structure=structure,
    )
    return 0


def cmd_structure(args: argparse.Namespace) -> int:
    struct = infer_structure_from_docx(args.source)
    out = _resolve_out(args, EXT_JSON, kind="structure")
    write_yaml_or_json(struct, out)
    return 0


def register_render_commands(app: CLIApp) -> None:
    """Register the render and structure commands on app."""
    _RENDER_ARGS: list[tuple[tuple[str, ...], dict[str, Any]]] = [
        (("--data",), {"help": DATA_HELP}),
        (("--template",), {"help": "Template config (YAML/JSON); defaults to summary/skills/experience/education"}),
        (("--seed",), {"help": "Seed criteria as JSON string or KEY=VALUE pairs (comma-separated)"}),
        (("--style-profile",), {"help": "Style profile JSON from 'style build' (optional)"}),
        (("--filter-skills-alignment",), {"help": "Alignment JSON to filter Skills to matched keywords"}),
        (("--filter-skills-job",), {"help": "Job YAML/JSON to supplement synonyms for filtering"}),
        (("--filter-exp-alignment",), {"help": "Alignment JSON to filter Experience to matched keywords"}),
        (("--filter-exp-job",), {"help": "Job YAML/JSON to supplement synonyms for experience filter"}),
        (("--structure-from",), {"help": "Reference DOCX resume to mimic section order and headings"}),
        (("--min-priority",), {"type": float, "help": "Filter Skills/Technologies items by priority (keep >= cutoff)"}),
        (("--out",), {"help": "Output file path (overrides --profile)"}),
        (("--profile",), {"help": PROFILE_HELP_DATA}),
        (("--out-dir",), {"help": OUT_DIR_HELP}),
    ]
    app.add_arguments(_RENDER_ARGS)
    app.command("render", help="Render a DOCX resume from unified data with a YAML/JSON template")(cmd_render)

    _STRUCTURE_ARGS: list[tuple[tuple[str, ...], dict[str, Any]]] = [
        (("--source",), {"required": True, "help": "Reference .docx file"}),
        (("--out",), {"help": "Output file path (overrides --profile)"}),
        (("--profile",), {"help": PROFILE_HELP_OUT}),
        (("--out-dir",), {"help": OUT_DIR_HELP}),
    ]
    app.add_arguments(_STRUCTURE_ARGS)
    app.command("structure", help="Infer section order and headings from a reference DOCX resume")(cmd_structure)
