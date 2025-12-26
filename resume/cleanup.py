from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import List, Sequence


@dataclass
class TidyPlan:
    keep: List[Path]
    move: List[Path]
    archive_dir: Path


def _match_files(base_dir: Path, prefix: str | None, suffixes: Sequence[str] | None) -> List[Path]:
    suffix_set = {s.lower() for s in (suffixes or [])}
    out: List[Path] = []
    for p in base_dir.iterdir():
        if not p.is_file():
            continue
        if prefix and not p.name.lower().startswith(prefix.lower()):
            continue
        if suffix_set and p.suffix.lower() not in suffix_set:
            continue
        out.append(p)
    return out


def build_tidy_plan(
    dir_path: str | Path,
    prefix: str | None = None,
    suffixes: Sequence[str] | None = None,
    keep: int = 2,
    archive_dir: str | Path | None = None,
) -> TidyPlan:
    base = Path(dir_path)
    files = _match_files(base, prefix, suffixes)
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    keep_files = files[: max(keep, 0)]
    move_files = files[max(keep, 0) :]
    arch = Path(archive_dir) if archive_dir else (base / "archive")
    return TidyPlan(keep=keep_files, move=move_files, archive_dir=arch)


def execute_archive(plan: TidyPlan, subfolder: str | None = None) -> List[Path]:
    dest = plan.archive_dir
    if subfolder:
        dest = dest / subfolder
    dest.mkdir(parents=True, exist_ok=True)
    moved: List[Path] = []
    for p in plan.move:
        target = dest / p.name
        # Ensure unique filename if exists
        i = 1
        while target.exists():
            target = dest / f"{p.stem}.{i}{p.suffix}"
            i += 1
        shutil.move(str(p), str(target))
        moved.append(target)
    return moved


def execute_delete(plan: TidyPlan) -> List[Path]:
    deleted: List[Path] = []
    for p in plan.move:
        try:
            p.unlink()
            deleted.append(p)
        except Exception:
            pass  # noqa: S110 - file deletion failure
    return deleted


def purge_temp_files(dir_path: str | Path) -> List[Path]:
    base = Path(dir_path)
    removed: List[Path] = []
    for p in base.rglob("*"):
        if not p.is_file():
            continue
        name = p.name
        if name.startswith("~$") or name in {".DS_Store"}:
            try:
                p.unlink()
                removed.append(p)
            except Exception:
                pass  # noqa: S110 - temp file deletion failure
    return removed
