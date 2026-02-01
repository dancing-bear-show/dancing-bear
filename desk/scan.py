import os
import time
import hashlib
from typing import Dict, List, Optional, Tuple

from .utils import expand_paths, parse_size, parse_duration, human_size


def _process_file(
    filepath: str,
    min_bytes: int,
    older_secs: Optional[int],
    include_duplicates: bool,
    now: float,
) -> Tuple[Optional[int], Optional[int], Optional[Dict], Optional[Dict], Optional[Tuple[str, int]]]:
    """Process a single file and return metrics.

    Returns: (size, parent_idx, large_entry, stale_entry, dupe_tuple)
    """
    try:
        st = os.stat(filepath)
    except (PermissionError, FileNotFoundError):
        return (None, None, None, None, None)

    size = st.st_size
    mtime = st.st_mtime

    large_entry = None
    if size >= min_bytes:
        large_entry = {
            "path": filepath,
            "size": size,
            "size_h": human_size(size),
            "mtime": int(mtime),
        }

    stale_entry = None
    if older_secs is not None and (now - mtime) >= older_secs:
        stale_entry = {
            "path": filepath,
            "age_days": round((now - mtime) / 86400, 1),
            "size": size,
            "size_h": human_size(size),
        }

    dupe_tuple = None
    if include_duplicates and size >= 1024 * 1024:
        dupe_tuple = (filepath, size)

    return (size, None, large_entry, stale_entry, dupe_tuple)


def _process_directory(
    dirpath: str,
    filenames: List[str],
    min_bytes: int,
    older_secs: Optional[int],
    include_duplicates: bool,
    now: float,
    large: List[Dict],
    stale: List[Dict],
    by_dir: Dict[str, int],
    files_for_dupes: List[Tuple[str, int]],
) -> None:
    """Process all files in a directory and update collections."""
    for name in filenames:
        fp = os.path.join(dirpath, name)
        size, _, large_entry, stale_entry, dupe_tuple = _process_file(
            fp, min_bytes, older_secs, include_duplicates, now
        )

        if size is not None:
            parent = os.path.dirname(fp)
            by_dir[parent] = by_dir.get(parent, 0) + size

        if large_entry is not None:
            large.append(large_entry)
        if stale_entry is not None:
            stale.append(stale_entry)
        if dupe_tuple is not None:
            files_for_dupes.append(dupe_tuple)


def _collect_file_stats(
    roots: List[str],
    min_bytes: int,
    older_secs: Optional[int],
    include_duplicates: bool,
    now: float,
) -> Tuple[List[Dict], List[Dict], Dict[str, int], List[Tuple[str, int]]]:
    """Walk directory trees and collect file statistics."""
    large: List[Dict] = []
    stale: List[Dict] = []
    by_dir: Dict[str, int] = {}
    files_for_dupes: List[Tuple[str, int]] = []

    for root in roots:
        if not os.path.exists(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            _process_directory(
                dirpath, filenames, min_bytes, older_secs, include_duplicates,
                now, large, stale, by_dir, files_for_dupes
            )

    return (large, stale, by_dir, files_for_dupes)


def _build_top_dirs_report(by_dir: Dict[str, int], top_dirs: int) -> List[Dict]:
    """Build sorted report of top directories by size."""
    top_dirs_list = sorted(by_dir.items(), key=lambda kv: kv[1], reverse=True)[:top_dirs]
    return [
        {"dir": d, "size": s, "size_h": human_size(s)} for d, s in top_dirs_list
    ]


def run_scan(
    paths: List[str],
    min_size: str = "50MB",
    older_than: Optional[str] = None,
    include_duplicates: bool = False,
    top_dirs: int = 10,
) -> Dict:
    roots = expand_paths(paths)
    min_bytes = parse_size(min_size)
    older_secs = parse_duration(older_than) if older_than else None
    now = time.time()

    large, stale, by_dir, files_for_dupes = _collect_file_stats(
        roots, min_bytes, older_secs, include_duplicates, now
    )

    large.sort(key=lambda x: x["size"], reverse=True)
    stale.sort(key=lambda x: (x["age_days"], x["size"]), reverse=True)

    top_dirs_report = _build_top_dirs_report(by_dir, top_dirs)

    duplicates: List[List[str]] = []
    if include_duplicates and files_for_dupes:
        duplicates = find_duplicates(files_for_dupes)

    return {
        "paths": roots,
        "min_size": min_bytes,
        "older_than": older_secs,
        "generated_at": int(now),
        "large_files": large,
        "stale_files": stale,
        "top_dirs": top_dirs_report,
        "duplicates": duplicates,
    }


def find_duplicates(files: List[Tuple[str, int]]) -> List[List[str]]:
    # bucket by size first
    by_size: Dict[int, List[str]] = {}
    for fp, size in files:
        by_size.setdefault(size, []).append(fp)

    dupe_groups: List[List[str]] = []
    for size, paths in by_size.items():
        if len(paths) < 2:
            continue
        by_hash: Dict[str, List[str]] = {}
        for p in paths:
            try:
                h = _sha256_of(p)
            except (PermissionError, FileNotFoundError, IsADirectoryError):
                continue
            by_hash.setdefault(h, []).append(p)
        for group in by_hash.values():
            if len(group) > 1:
                dupe_groups.append(sorted(group))
    return dupe_groups


def _sha256_of(path: str, chunk: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

