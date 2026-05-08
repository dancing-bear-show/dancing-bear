import os
import time
import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .utils import expand_paths, parse_size, parse_duration, human_size


@dataclass
class ScanCriteria:
    """Immutable scan thresholds passed through the walk."""

    now: float
    min_bytes: int
    older_secs: Optional[float]
    include_duplicates: bool


@dataclass
class ScanBuckets:
    """Mutable result buckets populated during a scan walk."""

    large: List[Dict] = field(default_factory=list)
    stale: List[Dict] = field(default_factory=list)
    by_dir: Dict[str, int] = field(default_factory=dict)
    files_for_dupes: List[Tuple[str, int]] = field(default_factory=list)


def _stat_file(fp: str):
    """Return os.stat result or None if inaccessible."""
    try:
        return os.stat(fp)
    except (PermissionError, FileNotFoundError):
        return None


def _collect_file(
    fp: str,
    st,
    criteria: ScanCriteria,
    buckets: ScanBuckets,
) -> None:
    """Classify a single file into the appropriate result buckets."""
    size = st.st_size
    mtime = st.st_mtime
    parent = os.path.dirname(fp)
    buckets.by_dir[parent] = buckets.by_dir.get(parent, 0) + size

    if size >= criteria.min_bytes:
        buckets.large.append({
            "path": fp,
            "size": size,
            "size_h": human_size(size),
            "mtime": int(mtime),
        })
    if criteria.older_secs is not None and (criteria.now - mtime) >= criteria.older_secs:
        buckets.stale.append({
            "path": fp,
            "age_days": round((criteria.now - mtime) / 86400, 1),
            "size": size,
            "size_h": human_size(size),
        })
    if criteria.include_duplicates and size >= 1024 * 1024:
        buckets.files_for_dupes.append((fp, size))


def _walk_roots(roots: List[str], criteria: ScanCriteria) -> ScanBuckets:
    """Walk all root paths and collect file data."""
    buckets = ScanBuckets()

    for root in roots:
        if not os.path.exists(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            for name in filenames:
                fp = os.path.join(dirpath, name)
                st = _stat_file(fp)
                if st is None:
                    continue
                _collect_file(fp, st, criteria, buckets)

    return buckets


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

    criteria = ScanCriteria(now, min_bytes, older_secs, include_duplicates)
    buckets = _walk_roots(roots, criteria)

    buckets.large.sort(key=lambda x: x["size"], reverse=True)
    buckets.stale.sort(key=lambda x: (x["age_days"], x["size"]), reverse=True)

    # top directories by size
    top_dirs_list = sorted(
        buckets.by_dir.items(), key=lambda kv: kv[1], reverse=True
    )[:top_dirs]
    top_dirs_report = [
        {"dir": d, "size": s, "size_h": human_size(s)} for d, s in top_dirs_list
    ]

    duplicates: List[List[str]] = []
    if include_duplicates and buckets.files_for_dupes:
        duplicates = find_duplicates(buckets.files_for_dupes)

    return {
        "paths": roots,
        "min_size": min_bytes,
        "older_than": older_secs,
        "generated_at": int(now),
        "large_files": buckets.large,
        "stale_files": buckets.stale,
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
