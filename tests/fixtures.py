import importlib.util
import subprocess
from pathlib import Path
from typing import Optional, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]


def repo_root() -> Path:
    return REPO_ROOT


def repo_path(*parts: str) -> Path:
    return REPO_ROOT.joinpath(*parts)


def bin_path(name: str) -> Path:
    return REPO_ROOT / "bin" / name


def run(cmd: Sequence[str], cwd: Optional[str] = None):
    return subprocess.run(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def has_pyyaml() -> bool:
    try:
        return importlib.util.find_spec("yaml") is not None
    except Exception:
        return False
