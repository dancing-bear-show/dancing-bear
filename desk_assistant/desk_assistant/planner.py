import json
import os
from typing import Dict, List, Optional

from personal_core.yamlio import load_config as _load_yaml

from .utils import expand_paths, parse_duration, parse_size


def plan_from_config(config_path: str) -> Dict:
    config_path = os.path.expanduser(config_path)
    if not os.path.exists(config_path):
        raise FileNotFoundError(config_path)
    cfg = _load_yaml(config_path) or {}

    version = int(cfg.get("version", 1))
    rules: List[Dict] = cfg.get("rules", [])
    operations: List[Dict] = []

    for rule in rules:
        match = rule.get("match", {})
        action = rule.get("action", {})
        paths = expand_paths(match.get("paths", ["~"]))
        extensions = [e.lower() for e in match.get("extensions", [])]
        size_gte = match.get("size_gte")
        older_than = match.get("older_than")
        size_threshold = parse_size(size_gte) if size_gte else None
        age_threshold = parse_duration(older_than) if older_than else None

        move_to = action.get("move_to")
        trash = bool(action.get("trash", False))

        for root in paths:
            if not os.path.exists(root):
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                for name in filenames:
                    src = os.path.join(dirpath, name)
                    try:
                        st = os.stat(src)
                    except (PermissionError, FileNotFoundError):
                        continue

                    if extensions and not any(name.lower().endswith(ext) for ext in extensions):
                        continue
                    if size_threshold is not None and st.st_size < size_threshold:
                        continue
                    if age_threshold is not None:
                        import time

                        if (time.time() - st.st_mtime) < age_threshold:
                            continue

                    if move_to:
                        dest_dir = os.path.expanduser(move_to)
                        dest = os.path.join(dest_dir, name)
                        operations.append({
                            "action": "move",
                            "src": src,
                            "dest": dest,
                            "rule": rule.get("name", ""),
                        })
                    elif trash:
                        operations.append({
                            "action": "trash",
                            "src": src,
                            "rule": rule.get("name", ""),
                        })

    return {
        "version": version,
        "generated_from": os.path.abspath(config_path),
        "operations": operations,
    }
