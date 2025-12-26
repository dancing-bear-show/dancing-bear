"""Secret masking utilities for logs, errors, and URLs.

Ported from cars-sre-utils (stdlib-only, conservative masking).
"""

from __future__ import annotations

import os
import re
import sys
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl, urlsplit, urlunsplit


SENSITIVE_PARAM_KEYS = {
    "token",
    "api_token",
    "access_token",
    "auth",
    "authorization",
    "password",
    "passwd",
    "secret",
    "client_secret",
    "refresh_token",
    "signature",
    "gh_token",
    "github_token",
    "ghp_token",
    "x_api_key",
    "x-api-key",
    "aws_access_key_id",
    "aws_secret_access_key",
    "aws_session_token",
}


def _mask_value(value: str) -> str:
    if not value:
        return value
    s = value.strip().lower()
    if s.startswith("bearer "):
        return "Bearer ***REDACTED***"
    if s.startswith("token "):
        return "Token ***REDACTED***"
    if s.startswith("basic "):
        return "Basic ***REDACTED***"
    return "***REDACTED***"


def mask_headers(headers: Dict[str, str]) -> Dict[str, str]:
    masked: Dict[str, str] = {}
    for k, v in (headers or {}).items():
        lk = (k or "").strip().lower()
        if lk in {"authorization", "proxy-authorization", "x-api-key", "x-auth-token"}:
            masked[k] = _mask_value(v)
        else:
            masked[k] = v
    return masked


def mask_url(url: str) -> str:
    try:
        parts = urlsplit(url or "")
        qs = parse_qsl(parts.query, keep_blank_values=True)
        items = []
        for k, v in qs:
            lk = (k or "").strip().lower()
            if lk in SENSITIVE_PARAM_KEYS:
                items.append(f"{k}=***REDACTED***")
            else:
                items.append(f"{k}={v}")
        query = "&".join(items)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))
    except Exception:
        return url


def mask_text(text: str) -> str:
    s = text or ""
    # Authorization: Scheme token
    s = re.sub(r"(?i)(Authorization\s*:\s*)(Bearer|Basic|Token)\s+[^\s]+", r"\1\2 ***REDACTED***", s)
    # Common header variants
    s = re.sub(r"(?i)(X-API-KEY\s*:\s*)(\S+)", r"\1***REDACTED***", s)
    s = re.sub(r"(?i)(X-Auth-Token\s*:\s*)(\S+)", r"\1***REDACTED***", s)
    # Token=... pairs
    s = re.sub(r"(?i)(token\s*=\s*)([A-Za-z0-9\-\._~+/=]+)", r"\1***REDACTED***", s)
    # JSON fields
    s = re.sub(r"(?i)(\"(?:api[_-]?token|token|access[_-]?token|secret|client_secret|password)\"\s*:\s*\")(.*?)(\")", r"\1***REDACTED***\3", s)
    # GitHub tokens
    s = re.sub(r"gh[pousr]_[A-Za-z0-9]{20,}", "gh_***REDACTED***", s)
    # Atlassian tokens
    s = re.sub(r"AT[A-Za-z0-9]{20,}", "AT***REDACTED***", s)
    # AWS keys in text
    s = re.sub(r"(?i)(aws_secret_access_key\s*[:=]\s*)(\S+)", r"\1***REDACTED***", s)
    s = re.sub(r"(?i)(aws_session_token\s*[:=]\s*)(\S+)", r"\1***REDACTED***", s)
    s = re.sub(r"(?i)(aws_access_key_id\s*[:=]\s*)(\S+)", r"\1***REDACTED***", s)
    # URL query tokens
    s = re.sub(r"(?i)([?&](?:" + "|".join(map(re.escape, SENSITIVE_PARAM_KEYS)) + ")=)([^&\s]+)", r"\1***REDACTED***", s)
    # Basic base64 creds
    s = re.sub(r"(?i)(Authorization\s*:\s*Basic\s+)[A-Za-z0-9+/=]+", r"\1***REDACTED***", s)
    return s


class MaskingWriter:
    def __init__(self, stream, *, enabled: bool = True):
        self._stream = stream
        self._enabled = bool(enabled)
        self._buffer: str = ""

    def write(self, s: str) -> int:
        if not self._enabled:
            return self._stream.write(s)
        text = str(s)
        self._buffer += text
        written = 0
        lines = self._buffer.splitlines(keepends=True)
        complete = lines[:-1] if (lines and not lines[-1].endswith(("\n", "\r"))) else lines
        remainder = "" if complete is lines else (lines[-1] if lines else "")
        masked_chunks = []
        for chunk in complete:
            masked_chunks.append(mask_text(chunk))
        if masked_chunks:
            out = "".join(masked_chunks)
            written += self._stream.write(out)
        self._buffer = remainder
        return written

    def writelines(self, lines) -> None:
        for line in lines:
            self.write(line)

    def flush(self) -> None:
        try:
            if self._enabled and self._buffer:
                masked = mask_text(self._buffer)
                try:
                    self._stream.write(masked)
                except BrokenPipeError:
                    self._buffer = ""
                    return
                self._buffer = ""
            try:
                self._stream.flush()
            except BrokenPipeError:
                return
        except Exception:
            try:
                self._buffer = ""
            except Exception:
                pass  # noqa: S110 - buffer reset failure

    def isatty(self) -> bool:
        try:
            return self._stream.isatty()
        except Exception:
            return False

    @property
    def encoding(self) -> Optional[str]:
        return getattr(self._stream, "encoding", None)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


def install_output_masking_from_env() -> None:
    """Install MaskingWriter on stdout/stderr based on env toggles.

    - SRE_MASK_OUTPUTS: enable when truthy (default 1); disable when 0/false/no/empty
    - SRE_MASK_BYPASS: disable when truthy (wins over MASK_OUTPUTS)
    """
    try:
        bypass = (os.getenv("SRE_MASK_BYPASS") or "").strip().lower()
        if bypass and bypass not in {"0", "false", "no"}:
            return
        val = (os.getenv("SRE_MASK_OUTPUTS", "1") or "").strip().lower()
        if val in {"", "0", "false", "no"}:
            return
        if not isinstance(getattr(sys, "stdout"), MaskingWriter):
            sys.stdout = MaskingWriter(getattr(sys, "stdout"))  # type: ignore[assignment]
        if not isinstance(getattr(sys, "stderr"), MaskingWriter):
            sys.stderr = MaskingWriter(getattr(sys, "stderr"))  # type: ignore[assignment]
    except Exception:
        return

