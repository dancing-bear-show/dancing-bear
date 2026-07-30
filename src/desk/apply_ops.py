import os
import shutil
from typing import Dict, List

from core.yamlio import load_config as _load_yaml


def apply_plan_file(plan_path: str, dry_run: bool = False) -> None:
    plan_path = os.path.expanduser(plan_path)
    data = _load_data(plan_path)
    ops: List[Dict] = data.get("operations", [])
    for op in ops:
        action = op.get("action")
        if action == "move":
            _do_move(op["src"], op["dest"], dry_run=dry_run)
        elif action == "trash":
            _do_trash(op["src"], dry_run=dry_run)
        else:
            print(f"? unknown action: {action}")


def _load_data(path: str) -> Dict:
    import json

    if path.lower().endswith((".yaml", ".yml")):
        return _load_yaml(path) or {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _do_move(src: str, dest: str, dry_run: bool = False) -> None:
    dest_dir = os.path.dirname(dest)
    if dry_run:
        print(f"DRY-RUN move: {src} -> {dest}")
        return
    os.makedirs(dest_dir, exist_ok=True)
    try:
        shutil.move(src, dest)
        print(f"moved: {src} -> {dest}")
    except Exception as e:
        print(f"ERROR moving {src} -> {dest}: {e}")


def _do_trash(src: str, dry_run: bool = False) -> None:
    trash_dir = os.path.expanduser("~/.Trash")
    dest = os.path.join(trash_dir, os.path.basename(src))
    if dry_run:
        print(f"DRY-RUN trash: {src} -> {dest}")
        return
    try:
        shutil.move(src, dest)
        print(f"trashed: {src}")
    except Exception as e:
        print(f"ERROR trashing {src}: {e}")
