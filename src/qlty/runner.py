"""Single choke point for every qlty subprocess invocation.

Why this module exists (plan section 2, F4): ``--json`` is absent from every
``qlty --help`` output as of CLI v0.640.0 but works and is already depended on
by ``workflows/code/qlty-complexity-sweep.yaml``. If a future release drops it,
degrading to an empty finding set would read as "clean repo" -- the same silent
failure this wrapper exists to prevent. So JSON is attempted first, SARIF is the
fallback, and the degradation is surfaced rather than swallowed.

The single most important invariant: **an empty finding list from a parse error
and an empty finding list from a clean repo must never be the same value.**
A parse failure raises ``QltyInvocationError``; a clean repo returns ``[]``.

Verified exit-code contract (qlty 0.640.0, 2026-08-14):

===========  ======  ==================================
exit code    stdout  meaning
===========  ======  ==================================
0            ``[]``  scan ran, no issues
1            JSON    scan ran, issues found
99           empty   hard error (not a repo, bad plugin)
===========  ======  ==================================

Exit 1 therefore means "issues found", NOT failure, and must not be treated as
an error.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess  # nosec B404 - qlty is a local dev binary invoked with a fixed arg vector, never shell=True
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from core.cli_errors import CLIError, ExitCode

from .models import Finding, Location, Source, WireFormat

# Exit codes qlty uses to mean "the scan itself ran". Anything else is a hard
# error where stdout is empty and no finding set exists to parse.
_SCAN_RAN_EXIT_CODES = frozenset({0, 1})

# Default lookup order for the qlty binary. CLAUDE.md documents ~/.qlty/bin/qlty
# as the canonical install path; PATH is the fallback.
_DEFAULT_BINARY = Path.home() / ".qlty" / "bin" / "qlty"

_SUBPROCESS_TIMEOUT_SECONDS = 600

# Remedy attached to every QltyNotInstalledError so the framework's error
# renderer can print an actionable next step rather than only the failure.
_INSTALL_HINT = (
    "Install qlty from https://qlty.sh (it lands in ~/.qlty/bin/qlty), "
    "or point $QLTY_BIN at an existing binary."
)


class QltyError(CLIError):
    """Base class for qlty invocation failures.

    Extends ``CLIError`` so the CLIApp framework routes these through
    ``handle_error``, which renders ``hint`` alongside the message the same way
    every other assistant CLI does.
    """

    def __init__(
        self,
        message: str,
        code: ExitCode = ExitCode.ERROR,
        hint: Optional[str] = None,
    ) -> None:
        super().__init__(message, code, hint)


class QltyNotInstalledError(QltyError):
    """The qlty binary could not be located."""

    def __init__(self, message: str, hint: Optional[str] = None) -> None:
        super().__init__(
            message,
            ExitCode.CONFIG_ERROR,
            hint or _INSTALL_HINT,
        )


class QltyInvocationError(QltyError):
    """qlty ran but produced output that could not be parsed.

    Raised rather than returning ``[]`` so a degraded scan can never be
    mistaken for a clean repo.
    """


def resolve_binary(explicit: Optional[str] = None) -> str:
    """Locate the qlty binary, preferring an explicit path.

    Order: explicit argument, ``$QLTY_BIN``, ``~/.qlty/bin/qlty``, then PATH.
    """
    for candidate in (explicit, os.environ.get("QLTY_BIN")):
        if candidate:
            if Path(candidate).is_file():
                return candidate
            raise QltyNotInstalledError(f"qlty binary not found at: {candidate}")

    if _DEFAULT_BINARY.is_file():
        return str(_DEFAULT_BINARY)

    found = shutil.which("qlty")
    if found:
        return found

    raise QltyNotInstalledError(
        "qlty binary not found (looked in $QLTY_BIN, ~/.qlty/bin/qlty, PATH). "
        "Install from https://qlty.sh or set QLTY_BIN."
    )


@dataclass(frozen=True)
class InvocationResult:
    """Outcome of one qlty subprocess call, including how it degraded."""

    findings: tuple[Finding, ...]
    wire_format: WireFormat
    source: Source
    command: tuple[str, ...]
    degraded: bool = False
    degrade_reason: str = ""


@dataclass(frozen=True)
class CompletedRun:
    """Raw result of a subprocess call, before parsing."""

    stdout: str
    stderr: str
    returncode: int
    command: tuple[str, ...]


class QltyRunner:
    """Runs qlty and returns normalized findings.

    All subprocess invocation in this package goes through here so the
    JSON->SARIF fallback and the parse-error-vs-clean-repo distinction are
    enforced in exactly one place.
    """

    def __init__(
        self,
        binary: Optional[str] = None,
        cwd: Optional[Path] = None,
        timeout: int = _SUBPROCESS_TIMEOUT_SECONDS,
    ) -> None:
        self._binary = binary
        self._cwd = cwd
        self._timeout = timeout

    def _resolved_binary(self) -> str:
        return resolve_binary(self._binary)

    def _execute(self, args: Sequence[str]) -> CompletedRun:
        """Run qlty with the given args, capturing stdout/stderr.

        qlty writes progress spinners to stderr, so only stdout is parsed.
        """
        command = (self._resolved_binary(), *args)
        try:
            # The binary path is not a hardcoded constant: resolve_binary()
            # honours an explicit argument and $QLTY_BIN. What is guaranteed is
            # that the argument vector is built here (never from user input) and
            # that shell=True is never used, so no shell metacharacter in any
            # resolved path or argument can be interpreted.
            proc = subprocess.run(  # nosec B603 - fixed arg vector built in-module, never shell=True
                command,
                capture_output=True,
                text=True,
                cwd=str(self._cwd) if self._cwd else None,
                timeout=self._timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise QltyInvocationError(
                f"qlty timed out after {self._timeout}s: {' '.join(command)}",
                hint=(
                    "Narrow the scan with explicit paths or --changed, or raise "
                    "QltyRunner(timeout=...)."
                ),
            ) from exc
        except OSError as exc:
            raise QltyInvocationError(
                f"could not execute qlty ({command[0]}): {exc}",
                hint=(
                    "Check the binary exists and is executable "
                    f"(chmod +x {command[0]}), or set $QLTY_BIN."
                ),
            ) from exc

        return CompletedRun(
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            returncode=proc.returncode,
            command=command,
        )

    def invoke(
        self,
        source: Source,
        *,
        scan_all: bool = True,
        paths: Sequence[str] = (),
    ) -> InvocationResult:
        """Run one qlty subcommand, preferring --json and falling back to --sarif.

        Returns normalized findings. Raises ``QltyInvocationError`` if neither
        format yields parseable output -- never returns an empty list to
        represent a failure.
        """
        base_args = self._base_args(source, scan_all=scan_all, paths=paths)

        json_run = self._execute([*base_args, "--json"])
        if self._scan_ran(json_run):
            findings = self._parse_or_raise(
                json_run, WireFormat.JSON, source, parse_json_findings
            )
            return InvocationResult(
                findings=tuple(findings),
                wire_format=WireFormat.JSON,
                source=source,
                command=json_run.command,
            )

        # --json did not produce a usable run. This is the F4 event: it may have
        # been removed upstream. Fall back to the documented --sarif, but record
        # the degradation so it is reported rather than silently absorbed.
        json_failure = self._failure_summary(json_run)
        sarif_run = self._execute([*base_args, "--sarif"])
        if not self._scan_ran(sarif_run):
            raise QltyInvocationError(
                "qlty failed in both --json and --sarif modes; no finding set "
                f"was produced (this is NOT a clean repo).\n"
                f"  --json:  {json_failure}\n"
                f"  --sarif: {self._failure_summary(sarif_run)}"
            )

        findings = self._parse_or_raise(
            sarif_run, WireFormat.SARIF, source, parse_sarif_findings
        )
        return InvocationResult(
            findings=tuple(findings),
            wire_format=WireFormat.SARIF,
            source=source,
            command=sarif_run.command,
            degraded=True,
            degrade_reason=(
                f"--json unavailable for '{source.value}' ({json_failure}); "
                "fell back to --sarif. Numeric values are unavailable in SARIF."
            ),
        )

    @staticmethod
    def _base_args(
        source: Source, *, scan_all: bool, paths: Sequence[str]
    ) -> list[str]:
        args = [source.value]
        if scan_all:
            args.append("--all")
        if source is Source.CHECK:
            # Never mutate the working tree from a read-only scan.
            args.extend(["--no-fix", "--no-cache"])
        if paths:
            # End-of-options marker: without it a path that starts with "-"
            # (e.g. a file literally named "-foo.py", or a stray "--all") is
            # read by qlty as a flag, silently changing the scan's meaning.
            args.append("--")
            args.extend(paths)
        return args

    @staticmethod
    def _scan_ran(run: CompletedRun) -> bool:
        """Whether qlty actually completed a scan (vs. hard-erroring)."""
        return run.returncode in _SCAN_RAN_EXIT_CODES

    @staticmethod
    def _failure_summary(run: CompletedRun) -> str:
        detail = " ".join(run.stderr.split())[:200] or "no stderr output"
        return f"exit {run.returncode}: {detail}"

    @staticmethod
    def _parse_or_raise(
        run: CompletedRun,
        wire_format: WireFormat,
        source: Source,
        parser: Callable[[str, Source], list[Finding]],
    ) -> list[Finding]:
        """Parse stdout, converting malformed payloads into a loud failure."""
        try:
            return parser(run.stdout, source)
        except QltyInvocationError:
            raise
        except (ValueError, KeyError, TypeError) as exc:
            raise QltyInvocationError(
                f"qlty {source.value} returned unparseable {wire_format.value} "
                f"output (exit {run.returncode}); refusing to report this as a "
                f"clean scan: {exc}"
            ) from exc


def _loads(payload: str, wire_format: WireFormat) -> object:
    """Parse a JSON payload, treating empty stdout as a hard failure.

    Empty stdout accompanies qlty's hard-error exits. A clean scan emits ``[]``
    (JSON) or a SARIF document with an empty ``results`` array -- both parse
    fine -- so empty output here always means something went wrong.
    """
    if not payload.strip():
        raise QltyInvocationError(
            f"qlty produced no {wire_format.value} output; a clean scan emits an "
            "empty result set, so empty output indicates a failed run"
        )
    return json.loads(payload)


def parse_json_findings(payload: str, source: Source) -> list[Finding]:
    """Normalize qlty's undocumented ``--json`` output.

    Shape: a flat array of objects keyed by ``ruleKey`` with a numeric
    ``value`` and a ``location.path``.
    """
    data = _loads(payload, WireFormat.JSON)
    if not isinstance(data, list):
        raise QltyInvocationError(
            f"expected a JSON array from qlty {source.value}, got "
            f"{type(data).__name__}"
        )

    # Every element must be an object. Skipping non-dict entries would let a
    # changed output format decay into [] -- indistinguishable from a clean
    # repo, which is the one thing this module exists to prevent.
    malformed = sum(1 for item in data if not isinstance(item, dict))
    if malformed:
        raise QltyInvocationError(
            f"qlty {source.value} returned {malformed} of {len(data)} JSON "
            "entries that are not objects; the output format may have changed. "
            "Refusing to report a partial finding set as a complete scan."
        )
    return [_finding_from_json(item, source) for item in data]


def _finding_from_json(item: dict, source: Source) -> Finding:
    properties = item.get("properties") or {}
    raw_value = item.get("value")
    return Finding(
        rule=str(item.get("ruleKey", "")),
        location=_location_from_json(item.get("location")),
        level=_normalize_level(str(item.get("level", ""))),
        message=str(item.get("message", "")),
        source=source,
        wire_format=WireFormat.JSON,
        tool=str(item.get("tool", "")),
        value=raw_value if isinstance(raw_value, int) else None,
        other_locations=tuple(
            _location_from_json(loc) for loc in item.get("otherLocations") or []
        ),
        group_key=_str_or_none(properties.get("structural_hash")),
    )


def _location_from_json(raw: object) -> Location:
    if not isinstance(raw, dict):
        return Location(path="", line=0)
    rng = raw.get("range")
    line = 0
    if isinstance(rng, dict):
        start = rng.get("startLine")
        line = start if isinstance(start, int) else 0
    return Location(path=str(raw.get("path", "")), line=line)


def parse_sarif_findings(payload: str, source: Source) -> list[Finding]:
    """Normalize SARIF output onto the same ``Finding`` shape as JSON.

    SARIF differs from qlty's JSON in ways that break a pass-through:

    * results live under ``runs[0].results[]`` rather than at the top level
    * ``ruleId`` is namespaced by the producing tool -- ``qlty:function-parameters``
      for smells, ``radarlint-python:python:S5655`` for check. The namespace is
      only the FIRST segment; ``python:S5655`` is itself the rule key and must
      survive intact (see ``_strip_rule_namespace``).
    * there is no numeric ``value``; it appears only in message prose.

    Without this normalization a SARIF fallback yields rule keys matching
    nothing in the strategy table, so every finding silently classifies as
    "unknown rule".
    """
    data = _loads(payload, WireFormat.SARIF)
    if not isinstance(data, dict):
        raise QltyInvocationError(
            f"expected a SARIF object from qlty {source.value}, got "
            f"{type(data).__name__}"
        )

    runs = data.get("runs")
    if not isinstance(runs, list) or not runs:
        raise QltyInvocationError(
            f"SARIF from qlty {source.value} has no 'runs'; cannot distinguish "
            "this from a clean scan"
        )

    findings: list[Finding] = []
    malformed = 0
    for run in runs:
        if not isinstance(run, dict):
            malformed += 1
            continue
        for result in run.get("results") or []:
            if isinstance(result, dict):
                findings.append(_finding_from_sarif(result, source))
            else:
                malformed += 1

    # As with JSON: silently skipping malformed entries could decay a changed
    # format into an empty finding set that reads as a clean repo.
    if malformed:
        raise QltyInvocationError(
            f"qlty {source.value} returned {malformed} malformed SARIF "
            "entries; the output format may have changed. Refusing to report "
            "a partial finding set as a complete scan."
        )
    return findings


def _finding_from_sarif(result: dict, source: Source) -> Finding:
    raw_rule = str(result.get("ruleId", ""))
    tool, rule = _strip_rule_namespace(raw_rule)
    properties = result.get("properties") or {}
    locations = _locations_from_sarif(result.get("locations"))
    related = _locations_from_sarif(result.get("relatedLocations"))
    primary = locations[0] if locations else Location(path="", line=0)

    return Finding(
        rule=rule,
        location=primary,
        level=_normalize_level(str(result.get("level", ""))),
        message=_sarif_message(result),
        source=source,
        wire_format=WireFormat.SARIF,
        tool=tool,
        # SARIF carries no numeric `value`; it is embedded in message prose.
        # Left as None so value-based filters report "unfiltered", never
        # "no matches".
        value=None,
        other_locations=tuple(locations[1:] + related),
        group_key=_str_or_none(properties.get("structural_hash")),
    )


def _strip_rule_namespace(rule_id: str) -> tuple[str, str]:
    """Split a SARIF ``ruleId`` into (tool, rule).

    qlty namespaces the producing tool as the first colon-separated segment:

    * ``qlty:function-parameters``        -> ("qlty", "function-parameters")
    * ``radarlint-python:python:S5655``   -> ("radarlint-python", "python:S5655")

    Only the first segment is stripped. Splitting on every colon would mangle
    ``python:S5655``, whose colon is part of the rule key itself, leaving a key
    that matches nothing in the strategy table.
    """
    if ":" not in rule_id:
        return ("", rule_id)
    tool, _, rest = rule_id.partition(":")
    return (tool, rest)


def _locations_from_sarif(raw: object) -> list[Location]:
    if not isinstance(raw, list):
        return []
    locations: list[Location] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        physical = entry.get("physicalLocation")
        if not isinstance(physical, dict):
            continue
        artifact = physical.get("artifactLocation") or {}
        region = physical.get("region") or {}
        start = region.get("startLine") if isinstance(region, dict) else None
        locations.append(
            Location(
                path=str(artifact.get("uri", "")) if isinstance(artifact, dict) else "",
                line=start if isinstance(start, int) else 0,
            )
        )
    return locations


def _sarif_message(result: dict) -> str:
    message = result.get("message")
    if isinstance(message, dict):
        return str(message.get("text", ""))
    return str(message or "")


def _normalize_level(level: str) -> str:
    """Map qlty's two level vocabularies onto one lowercase form.

    JSON uses ``LEVEL_HIGH``/``LEVEL_NOTE``; SARIF uses ``error``/``warning``/
    ``note``. Normalizing keeps rendering and filtering format-agnostic.
    """
    cleaned = level.strip().lower()
    if cleaned.startswith("level_"):
        cleaned = cleaned[len("level_"):]
    return cleaned or "unknown"


def _str_or_none(value: object) -> Optional[str]:
    return str(value) if isinstance(value, str) and value else None
