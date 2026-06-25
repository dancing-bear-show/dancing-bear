"""File utilities — thin re-exports from core.fileutil."""
from core.fileutil import atomic_write_json, safe_load_json

__all__ = ["atomic_write_json", "safe_load_json"]
