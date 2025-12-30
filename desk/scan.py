import os
import time
import hashlib
from typing import Dict, List, Optional, Tuple

from .utils import expand_paths, parse_size, parse_duration, human_size


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

    large: List[Dict] = []
    stale: List[Dict] = []
    by_dir: Dict[str, int] = {}
    files_for_dupes: List[Tuple[str, int]] = []

    for root in roots:
        if not os.path.exists(root):
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            for name in filenames:
                fp = os.path.join(dirpath, name)
                try:
                    st = os.stat(fp)
                except (PermissionError, FileNotFoundError):
                    continue
                size = st.st_size
                mtime = st.st_mtime
                parent = os.path.dirname(fp)
                by_dir[parent] = by_dir.get(parent, 0) + size

                if size >= min_bytes:
                    large.append({
                        "path": fp,
                        "size": size,
                        "size_h": human_size(size),
                        "mtime": int(mtime),
                    })
                if older_secs is not None and (now - mtime) >= older_secs:
                    stale.append({
                        "path": fp,
                        "age_days": round((now - mtime) / 86400, 1),
                        "size": size,
                        "size_h": human_size(size),
                    })
                if include_duplicates and size >= 1024 * 1024:
                    files_for_dupes.append((fp, size))

    large.sort(key=lambda x: x["size"], reverse=True)
    stale.sort(key=lambda x: (x["age_days"], x["size"]), reverse=True)

    # top directories by size
    top_dirs_list = sorted(by_dir.items(), key=lambda kv: kv[1], reverse=True)[:top_dirs]
    top_dirs_report = [
        {"dir": d, "size": s, "size_h": human_size(s)} for d, s in top_dirs_list
    ]

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

