from __future__ import annotations

import sqlite3
import plistlib
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple, Dict, Any


@dataclass
class IconStateFile:
    path: Path
    desc: str


def find_latest_backup_dir(mobilesync_dir: Optional[Path] = None) -> Optional[Path]:
    """Return the most recently modified Finder backup directory under MobileSync/Backup.

    On macOS, Finder stores device backups in:
      ~/Library/Application Support/MobileSync/Backup/<UDID>/
    """
    if mobilesync_dir is None:
        mobilesync_dir = Path.home() / "Library" / "Application Support" / "MobileSync" / "Backup"
    if not mobilesync_dir.exists():
        return None
    # Choose by most recent Manifest.db mtime when present, else dir mtime.
    candidates = []
    for child in mobilesync_dir.iterdir():
        if not child.is_dir():
            continue
        manifest = child / "Manifest.db"
        mtime = manifest.stat().st_mtime if manifest.exists() else child.stat().st_mtime
        candidates.append((mtime, child))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _manifest_select(db_path: Path, sql: str, params: Tuple[Any, ...]) -> list[sqlite3.Row]:
    con = sqlite3.connect(str(db_path))
    try:
        con.row_factory = sqlite3.Row
        cur = con.execute(sql, params)
        rows = cur.fetchall()
        return rows
    finally:
        con.close()


def find_iconstate_file(backup_dir: Path) -> Optional[IconStateFile]:
    """Locate an IconState plist file in the backup manifest and return its hashed path.

    We look for files in domain 'HomeDomain' with relativePath like 'Library/SpringBoard/IconState%'.
    Prefer IconState.plist over DesiredIconState variants.
    """
    manifest_db = backup_dir / "Manifest.db"
    result: Optional[IconStateFile] = None
    if manifest_db.exists():
        rows = _manifest_select(
            manifest_db,
            """
            SELECT fileID, relativePath
            FROM Files
            WHERE domain='HomeDomain'
              AND relativePath LIKE 'Library/SpringBoard/IconState%'
            ORDER BY relativePath ASC
            """,
            tuple(),
        )
        if rows:
            # Choose best candidate: prefer IconState~ipad.plist or IconState.plist; otherwise first.
            _suffix_scores = {
                "iconstate~ipad.plist": 3,
                "iconstate.plist": 2,
                "desirediconstate.plist": 1,
            }

            def score(path: str) -> int:
                p = path.lower()
                return next(
                    (v for suffix, v in _suffix_scores.items() if p.endswith(suffix)),
                    0,
                )

            best = max(rows, key=lambda r: score(r["relativePath"]))
            file_id = best["fileID"]
            rel = best["relativePath"]
            hashed = backup_dir / file_id[:2] / file_id
            if hashed.exists():
                result = IconStateFile(path=hashed, desc=rel)
    return result


def load_plist(path: Path) -> Dict[str, Any]:
    with path.open("rb") as f:
        return plistlib.load(f)

