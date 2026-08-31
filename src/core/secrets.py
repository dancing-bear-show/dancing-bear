"""Secret masking utilities for logs, errors, and URLs."""

from __future__ import annotations

import os
import re
import sys
from typing import Any, overload
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
    # api_key/apikey are the most common spellings in public API query
    # strings and were absent here, so a masked-looking URL still carried
    # the key. Matching is case-insensitive at the call sites.
    #
    # Every spelling the bare-pair regex in mask_text() recognizes must
    # also appear here: mask_url() consults only this set, so a spelling
    # covered by one and not the other leaks through whichever path the
    # caller happens to take.
    "api_key",
    "apikey",
    "api-key",
    "api_secret",
    "apisecret",
    "api-secret",
    "aws_access_key_id",
    "aws_secret_access_key",
    "aws_session_token",
    # Header and body spellings. These rarely appear as query params, but
    # "rarely" is not "never" -- and keeping them out of the shared set was
    # itself the bug: core.preflight treated them as sensitive while
    # mask_url() did not, so the same credential was redacted on one path
    # and emitted on the other.
    "x_auth_token",
    "proxy_authorization",
    "private_key",
    "session_token",
}

# Canonical redaction marker. Callers that build their own replacement
# string should use this rather than re-typing the literal, so the marker
# can change in one place.
REDACTED = "***REDACTED***"

# SENSITIVE_PARAM_KEYS with -/_ folded together, so header names
# ("X-Auth-Token") and query/body names ("x_auth_token") resolve to the
# same entry. Computed once; every masker compares against this.
def _normalize_key(key: str) -> str:
    """Fold case and the -/./_ separators to one spelling.

    ``.`` is folded alongside ``-`` because the bare-pair regex in
    mask_text() accepts ``api.key``: a spelling one masker recognizes and
    another does not is precisely the drift this module keeps hitting.
    """
    return key.strip().lower().replace("-", "_").replace(".", "_")


_NORMALIZED_SENSITIVE_KEYS = {_normalize_key(k) for k in SENSITIVE_PARAM_KEYS}

# Suffixes that mark a key as a credential regardless of its prefix, so
# vendor-specific names are covered without enumerating every service.
# Deliberately narrow: "key" alone is not here, because "sort_key" and
# "primary_key" are not secrets and redacting them would make logs worse.
_SENSITIVE_KEY_SUFFIXES = (
    "_token",
    "_secret",
    "_password",
    "_api_key",
    "_apikey",
    "_credential",
    "_credentials",
)


def is_sensitive_key(key: object) -> bool:
    """Return True when a key name marks its value as a credential.

    The single place that answers "is this name sensitive?". Header
    masking, URL masking, and structured-sample masking all route through
    it, so a key added to SENSITIVE_PARAM_KEYS takes effect everywhere at
    once. Keeping separate lists per masker was a real bug: a name present
    in one and absent from another was redacted on one path and emitted on
    the other.

    Case and ``-``/``_`` are folded, so ``X-Auth-Token``, ``x_auth_token``
    and ``X_AUTH_TOKEN`` all match.
    """
    if not isinstance(key, str):
        return False
    normalized = _normalize_key(key)
    if normalized in _NORMALIZED_SENSITIVE_KEYS:
        return True
    # Vendor headers are open-ended -- "Music-User-Token", "X-Shopify-
    # Access-Token" -- so an exact list will always trail the services
    # actually called. A name ending in one of these words is a credential
    # by convention, and treating it as one costs a redacted log line at
    # worst. (Apple Music's Music-User-Token leaked past the old exact
    # list while being sent on every request in apple_music/client.py.)
    return any(normalized.endswith(suffix) for suffix in _SENSITIVE_KEY_SUFFIXES)


@overload
def _mask_value(value: str) -> str:
    # Overload declaration: typing-only, never executed.
    pass


@overload
def _mask_value(value: None) -> None:
    # Overload declaration: typing-only, never executed.
    pass


def _mask_value(value: str | None) -> str | None:
    """Mask a header value, passing a falsy input straight back.

    Overloaded rather than widened to `str | None` unconditionally: the falsy
    branch returns its own argument, so `str` in really does mean `str` out.
    A single `str | None` return made `mask_headers`' `dict[str, str]`
    unprovable even though it only ever passes `str`. Coercing None to "" would
    have satisfied the checker by changing behaviour -- a masking helper that
    silently turns a missing value into an empty string hides the distinction
    between "absent" and "blank", so the overload states the real contract
    instead.
    """
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


def mask_headers(headers: dict[str, str] | None) -> dict[str, str]:
    masked: dict[str, str] = {}
    for k, v in (headers or {}).items():
        lk = (k or "").strip().lower()
        # Normalized against the shared key set rather than a private list:
        # a header name absent here but present in SENSITIVE_PARAM_KEYS was
        # redacted in URLs and emitted in headers.
        if is_sensitive_key(lk):
            masked[k] = _mask_value(v)
        else:
            masked[k] = v
    return masked


def _mask_netloc(netloc: str) -> str:
    """Redact the password in a raw ``user:pass@host`` netloc.

    Operates on the string rather than urlsplit's ``password``/``port``
    properties, which raise ValueError on a malformed port and would push
    the caller into an except branch that returns the unmasked original.
    """
    if "@" not in netloc:
        return netloc
    userinfo, _, host = netloc.rpartition("@")
    if ":" not in userinfo:
        return netloc  # user with no password; nothing to hide
    user, _, _pw = userinfo.partition(":")
    return f"{user}:{REDACTED}@{host}"


def _mask_query_pairs(query: str) -> str:
    """Redact sensitive values in a raw ``a=1&b=2`` query string.

    String-only, for the path where urlsplit/parse_qsl already failed.
    """
    out = []
    for pair in query.split("&"):
        key, sep, _value = pair.partition("=")
        out.append(f"{key}={REDACTED}" if sep and is_sensitive_key(key) else pair)
    return "&".join(out)


def _strip_userinfo(url: str) -> str:
    """Mask credentials in a URL by pure string surgery.

    The fallback for when urlsplit fails outright -- a malformed IPv6
    literal raises ValueError, for instance. Emitting a slightly mangled
    URL is always better than emitting a live credential.

    Handles the query string as well as the userinfo: masking only the
    password meant a malformed host with "?api_key=..." still leaked, so
    mask_url leaked precisely on its own error path.
    """
    scheme, sep, rest = url.partition("://")
    if not sep:
        return _mask_query_pairs_in_tail(url)
    authority, slash, tail = rest.partition("/")
    masked_authority = _mask_netloc(authority) if "@" in authority else authority
    rebuilt = f"{scheme}://{masked_authority}"
    if slash:
        rebuilt += "/" + _mask_query_pairs_in_tail(tail)
    return rebuilt


def _mask_query_pairs_in_tail(tail: str) -> str:
    """Mask the query portion of a ``path?query#fragment`` tail."""
    path, qmark, remainder = tail.partition("?")
    if not qmark:
        return tail
    query, hashmark, fragment = remainder.partition("#")
    rebuilt = f"{path}?{_mask_query_pairs(query)}"
    return rebuilt + (f"#{fragment}" if hashmark else "")


def mask_url(url: str | None) -> str:
    # Normalized once here rather than at each use. The happy path already did
    # `url or ""`, but the except path passed the raw argument to
    # _strip_userinfo(url: str) -- so a None reaching the fallback was both a
    # type error and, on the one path whose entire job is "never emit a live
    # credential", an AttributeError instead of a masked string.
    url = url or ""
    try:
        parts = urlsplit(url)
        qs = parse_qsl(parts.query, keep_blank_values=True)
        items = []
        for k, v in qs:
            lk = (k or "").strip().lower()
            if is_sensitive_key(lk):
                items.append(f"{k}=***REDACTED***")
            else:
                items.append(f"{k}={v}")
        query = "&".join(items)
        # A password in the netloc (https://user:pw@host) survived here:
        # only the query string was inspected, and urlunsplit reassembled
        # the netloc verbatim.
        #
        # Rebuilt by splitting the raw netloc rather than reading
        # parts.password/parts.port: those properties raise ValueError on a
        # malformed port ("host:bad"), and the except below would then
        # return the ORIGINAL url -- password intact. A masking function
        # whose failure mode is emitting the secret is worse than no
        # masking at all, so the parse must not be able to raise here.
        netloc = _mask_netloc(parts.netloc)
        return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))
    except Exception:
        # Last-resort: never return a URL still carrying userinfo.
        return _strip_userinfo(url)


_REDACTED = r"\1***REDACTED***"

# Key names recognized inside a mapping literal. Shared by the JSON and
# Python-repr forms so the two spellings cannot drift apart.
_MAPPING_KEY_ALTERNATION = (
    r"api[_.-]?token|api[_.-]?key|api[_.-]?secret|token"
    r"|access[_.-]?token|refresh[_.-]?token|secret|client[_.-]?secret"
    r"|private[_.-]?key|password|passwd"
)

# Group 1 spans the opening quote, key, separator and opening value quote.
# Group 2 is the key quote and group 3 the value quote; \3 closes the value
# with the same character that opened it, so a single-quoted value cannot be
# terminated by a stray double quote inside it.
_MAPPING_FIELD_RE = re.compile(
    r"(?i)((['\"])(?:" + _MAPPING_KEY_ALTERNATION + r")\2\s*:\s*(['\"]))"
    # (?:\\.|(?!\3).)* consumes an escape sequence as one unit, so a
    # backslash-escaped quote inside the value cannot end the match. A
    # plain .*? stopped at the first quote character and redacted only the
    # head -- "abc\"def_SECRET" became ***REDACTED***"def_SECRET, which
    # reads as masked while leaving the tail in the log.
    r"(?:\\.|(?!\3).)*\3"
)


def mask_text(text: str | None) -> str:
    s = text or ""
    # Authorization: Scheme token
    s = re.sub(r"(?i)(Authorization\s*:\s*)(Bearer|Basic|Token)\s+[^\s]+", r"\1\2 ***REDACTED***", s)
    # Common header variants
    s = re.sub(r"(?i)(X-API-KEY\s*:\s*)(\S+)", _REDACTED, s)
    s = re.sub(r"(?i)(X-Auth-Token\s*:\s*)(\S+)", _REDACTED, s)
    # Bare key=value pairs, with no ? or & to mark them as query params.
    # Exception and log text routinely reads "api_key=abc123" or
    # "connection failed (apikey=abc123)", which the query-param and JSON
    # rules below both miss.
    s = re.sub(
        # The value class is "everything up to whitespace or a delimiter"
        # rather than an allow-list: a percent-encoded value (api_key=%2Fabc)
        # fell outside [\w.~+/=-] and was left whole, and abc%2Fdef was
        # worse -- redacted up to the % and the tail emitted.
        r"(?i)((?:api[_.-]?key|api[_.-]?secret|token|password|passwd"
        r"|client[_.-]?secret|private[_.-]?key|secret)\s*=\s*)([^\s&;,\"')\]}]+)",
        _REDACTED,
        s,
    )
    # Credentials embedded in a URI netloc: postgres://user:pw@host/db.
    # Database drivers and HTTP clients quote the whole URI when auth
    # fails, so this is one of the likeliest shapes to reach a log. The
    # username is kept -- it identifies which account failed.
    s = re.sub(
        # The password group is greedy up to the LAST '@' before the host,
        # not the first: an unescaped '@' in a password ("u:p@ssw0rd@host")
        # otherwise ended the match early and left "ssw0rd@host" in the
        # output. mask_url gets this right via rpartition; this is the text
        # path saying the same thing.
        r"(?i)([a-z][a-z0-9+.-]*://)([^:@/\s]+):([^/\s]+)@",
        r"\1\2:" + REDACTED + "@",
        s,
    )
    # Mapping fields, in both JSON ("k": "v") and Python repr ('k': 'v')
    # form. An exception carrying a dict stringifies as repr, so a
    # double-quote-only rule left RuntimeError({'api_key': ...}) unmasked
    # in the RetryExhaustedError message built from it. The quote style is
    # captured and backreferenced so the two forms cannot be mixed.
    s = _MAPPING_FIELD_RE.sub(r"\1***REDACTED***\3", s)
    # GitHub tokens
    s = re.sub(r"gh[pousr]_[A-Za-z0-9]{20,}", "gh_***REDACTED***", s)
    # Vendor tokens recognizable by shape alone, so they are caught even
    # with no key= context around them.
    s = re.sub(r"\bxox[bpaso]-[A-Za-z0-9-]{10,}", "xox-" + REDACTED, s)
    s = re.sub(r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{10,}", "sk_" + REDACTED, s)
    s = re.sub(r"\bsk-[A-Za-z0-9_-]{32,}", "sk-" + REDACTED, s)
    # PEM blocks. DOTALL via [\s\S] so the body spans lines.
    s = re.sub(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----",
        "-----BEGIN PRIVATE KEY-----" + REDACTED + "-----END PRIVATE KEY-----",
        s,
    )
    # Atlassian tokens
    s = re.sub(r"AT[A-Za-z0-9]{20,}", "AT***REDACTED***", s)
    # AWS keys in text
    s = re.sub(r"(?i)(aws_secret_access_key\s*[:=]\s*)(\S+)", _REDACTED, s)
    s = re.sub(r"(?i)(aws_session_token\s*[:=]\s*)(\S+)", _REDACTED, s)
    s = re.sub(r"(?i)(aws_access_key_id\s*[:=]\s*)(\S+)", _REDACTED, s)
    # URL query tokens
    s = re.sub(r"(?i)([?&](?:" + "|".join(map(re.escape, SENSITIVE_PARAM_KEYS)) + ")=)([^&\s]+)", _REDACTED, s)
    # Basic base64 creds
    s = re.sub(r"(?i)(Authorization\s*:\s*Basic\s+)[\w+/=]+", _REDACTED, s)
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
        has_incomplete = lines and not lines[-1].endswith(("\n", "\r"))
        complete = lines[:-1] if has_incomplete else lines
        if complete is lines:
            remainder = ""
        else:
            remainder = lines[-1] if lines else ""
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

    def _flush_pending_buffer(self) -> bool:
        """Write and clear any buffered content. Returns False on a broken pipe."""
        if not (self._enabled and self._buffer):
            return True
        masked = mask_text(self._buffer)
        try:
            self._stream.write(masked)
        except BrokenPipeError:
            self._buffer = ""
            return False
        self._buffer = ""
        return True

    def flush(self) -> None:
        try:
            if not self._flush_pending_buffer():
                return
            try:
                self._stream.flush()
            except BrokenPipeError:
                return
        except Exception:
            try:
                self._buffer = ""
            except Exception:  # nosec B110 - buffer reset failure
                pass

    def isatty(self) -> bool:
        try:
            return self._stream.isatty()
        except Exception:
            return False

    @property
    def encoding(self) -> str | None:
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

