from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Optional

from personal_core.yamlio import dump_config as _dump_yaml, load_config as _load_yaml


def safe_import(name: str) -> Optional[Any]:
    try:
        return __import__(name)
    except Exception:
        return None


def read_text_any(path: str | os.PathLike[str]) -> str:
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix in {".txt", ".md"}:
        return p.read_text(encoding="utf-8")
    if suffix in {".html", ".htm"}:
        text = p.read_text(encoding="utf-8", errors="ignore")
        # naive HTML strip for generic resumes, but callers parsing LinkedIn may
        # want raw HTML. Use read_text_raw for that path.
        return re.sub(r"<[^>]+>", " ", text)
    if suffix == ".docx":
        docx = safe_import("docx")
        if not docx:
            raise RuntimeError(
                "Reading .docx requires python-docx. Install it or provide .txt/.md."
            )
        from docx import Document  # type: ignore

        doc = Document(str(p))
        return "\n".join(par.text for par in doc.paragraphs)
    if suffix == ".pdf":
        # Optional dependency
        pdfminer = safe_import("pdfminer.high_level")
        if not pdfminer:
            raise RuntimeError(
                "Reading .pdf requires pdfminer.six. Install it or provide .txt/.md."
            )
        from pdfminer.high_level import extract_text  # type: ignore

        return extract_text(str(p))
    # Fallback treat as text
    return p.read_text(encoding="utf-8")


def read_text_raw(path: str | os.PathLike[str]) -> str:
    """Read file as raw text without any stripping or transformation."""
    return Path(path).read_text(encoding="utf-8", errors="ignore")


def read_yaml_or_json(path: str | os.PathLike[str]) -> Any:
    p = Path(path)
    suffix = p.suffix.lower()
    if not p.exists():
        raise FileNotFoundError(p)
    if suffix in {".yaml", ".yml"}:
        return _load_yaml(str(p))
    text = p.read_text(encoding="utf-8")
    return json.loads(text)


def write_yaml_or_json(data: Any, path: str | os.PathLike[str]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    suffix = p.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        _dump_yaml(str(p), data)
        return
    with p.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def write_text(text: str, path: str | os.PathLike[str]) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
