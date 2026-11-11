"""Data-table-driven secret and PII scanner/scrubber for export: block/scrub/warn rule catalog, scan, scrub, and blocking predicate."""

from __future__ import annotations

import re
from dataclasses import dataclass

from memory.models import Redaction

__all__ = ["REDACTION_RULES", "RedactionRule", "has_blocking", "scan", "scrub"]


@dataclass(frozen=True)
class RedactionRule:
    """A single redaction rule with a pattern and replacement strategy.

    Rules are frozen to prevent mutation after definition, allowing them to be
    safely reused in parametrized tests over the REDACTION_RULES tuple.

    Attributes:
        rule_id: Unique identifier for this rule (e.g., 'aws-access-key').
        severity: One of 'block', 'scrub', or 'warn'.
            - 'block': export aborts with no override flag (high-precision credentials).
            - 'scrub': replaced automatically and logged in redactions.
            - 'warn': reported, exportable with --allow-warn (best-effort patterns).
        pattern: Compiled regex pattern to match findings.
        replacement: Text to substitute for matched content (or preview for block/warn).
        description: Human-readable description of what this rule detects.
        requires_anonymize: If True, this rule only fires when anonymize=True.
    """

    rule_id: str
    severity: str
    pattern: re.Pattern[str]
    replacement: str
    description: str
    requires_anonymize: bool = False


SEVERITY_BLOCK = "block"
SEVERITY_SCRUB = "scrub"
SEVERITY_WARN = "warn"

# Text-scrub pattern/replacement below — never used as a filesystem path.
_SCRATCH_RE = re.compile(r"/private/tmp/claude-\d+/[^\s)}'\"]+/scratchpad")  # NOSONAR
_SCRATCH_REPL = "/private/tmp/claude-[REDACTED]/[...]/scratchpad"  # NOSONAR


REDACTION_RULES: tuple[RedactionRule, ...] = (
    # BLOCK rules — high-precision credential shapes only
    RedactionRule(
        rule_id="aws-access-key",
        severity=SEVERITY_BLOCK,
        pattern=re.compile(r"(?:^|\s)(AKIA|ASIA)[0-9A-Z]{16}(?:\s|$)", re.MULTILINE),
        replacement="[REDACTED_AWS_KEY]",
        description="AWS access key (AKIA/ASIA prefix)",
    ),
    RedactionRule(
        rule_id="private-key-block",
        severity=SEVERITY_BLOCK,
        pattern=re.compile(
            r"-----BEGIN\s++(?:RSA\s++)?PRIVATE\s++KEY(?:\s++[^\n]*)?-----"
        ),
        replacement="[REDACTED_PRIVATE_KEY]",
        description="PEM private key block header",
    ),
    RedactionRule(
        rule_id="bearer-token",
        severity=SEVERITY_BLOCK,
        pattern=re.compile(
            r"(?:^|\s|['\"])Bearer\s+([a-z0-9\-._~+/]+=*)(?:\s|$|['\"])",
            re.IGNORECASE | re.MULTILINE,
        ),
        replacement="[REDACTED_BEARER_TOKEN]",
        description="HTTP Bearer token",
    ),
    RedactionRule(
        rule_id="github-token",
        severity=SEVERITY_BLOCK,
        pattern=re.compile(r"(?:ghp|gho|ghu|ghs|ghr)_\w{36,255}", re.ASCII),
        replacement="[REDACTED_GITHUB_TOKEN]",
        description="GitHub personal access token (ghp_/gho_/ghu_/ghs_/ghr_ prefix)",
    ),
    RedactionRule(
        rule_id="slack-token",
        severity=SEVERITY_BLOCK,
        pattern=re.compile(r"(?:xoxb|xoxp|xoxc|xoxa)-[A-Za-z0-9\-]{80,100}"),
        replacement="[REDACTED_SLACK_TOKEN]",
        description="Slack token (xox prefix)",
    ),
    RedactionRule(
        rule_id="credentials-ini-content",
        severity=SEVERITY_BLOCK,
        pattern=re.compile(
            r"api_key\s*=\s*[a-z0-9\-_]{20,}|secret_key\s*=\s*[a-z0-9\-_/+=]{20,}",
            re.IGNORECASE,
        ),
        replacement="[REDACTED_CREDENTIALS]",
        description="Credentials.ini-style key=value pair",
    ),
    # SCRUB rules — automatically replaced, logged in redactions
    RedactionRule(
        rule_id="abs-home-path",
        severity=SEVERITY_SCRUB,
        pattern=re.compile(r"/Users/([A-Za-z0-9._\-]+)/"),
        replacement="~/",
        description="Absolute home path (/Users/<name>/...)",
    ),
    RedactionRule(
        rule_id="abs-home-path-slug-form",
        severity=SEVERITY_SCRUB,
        pattern=re.compile(r"-Users-([A-Za-z0-9._\-]+)-"),
        replacement="-Users-<home>-",
        description="Home path slug encoding (-Users-<name>-...)",
    ),
    RedactionRule(
        rule_id="origin-session-id",
        severity=SEVERITY_SCRUB,
        pattern=re.compile(
            r"origin_session_id['\"]?\s*[:=]\s*['\"]?([a-f0-9\-]{36})['\"]?"
        ),
        replacement="origin_session_id: [REDACTED_SESSION_ID]",
        description="Origin session UUID",
    ),
    RedactionRule(
        rule_id="worktree-path",
        severity=SEVERITY_SCRUB,
        pattern=re.compile(r"\.claude/worktrees/[A-Za-z0-9\-_]+"),
        replacement=".claude/worktrees/[REDACTED]",
        description="Isolated worktree path",
    ),
    RedactionRule(
        rule_id="machine-hostname",
        severity=SEVERITY_SCRUB,
        pattern=re.compile(
            r"[Hh]ostname['\"]?\s*[:=]\s*['\"]?([A-Za-z0-9\-_.]+)['\"]?(?:\s|$)"
        ),
        replacement="Hostname: [REDACTED]",
        description="Machine hostname",
    ),
    RedactionRule(
        rule_id="data-home-path",
        severity=SEVERITY_SCRUB,
        pattern=re.compile(r"~?/?\.local/share/dancing-bear/[^\s)}'\"]+"),
        replacement="~/.local/share/dancing-bear/[REDACTED]",
        description="dancing-bear data directory path",
    ),
    RedactionRule(
        rule_id="scratchpad-path",
        severity=SEVERITY_SCRUB,
        pattern=_SCRATCH_RE,
        replacement=_SCRATCH_REPL,
        description="Claude scratchpad directory",
    ),
    RedactionRule(
        rule_id="local-username",
        severity=SEVERITY_SCRUB,
        pattern=re.compile(
            r"(?:[Uu]ser|[Uu]sername)['\"]?\s*[:=]\s*['\"]?([a-z_][a-z0-9_\-]{2,})['\"]?"
        ),
        replacement="username: [REDACTED]",
        description="Local system username (only under --anonymize)",
        requires_anonymize=True,
    ),
    # WARN rules — reported, exportable with --allow-warn
    RedactionRule(
        rule_id="internal-hostname",
        severity=SEVERITY_WARN,
        pattern=re.compile(r"(?:[a-z0-9\-]+\.)+(?:internal|corp)\b"),
        replacement="[INTERNAL_HOSTNAME]",
        description="Internal hostname (*.internal, *.corp)",
    ),
    RedactionRule(
        rule_id="rfc1918-ip",
        severity=SEVERITY_WARN,
        pattern=re.compile(
            r"(?:10\.(?:\d{1,3}\.){2}\d{1,3}"
            r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
            r"|192\.168\.\d{1,3}\.\d{1,3})",
            re.ASCII,
        ),
        replacement="[RFC1918_IP]",
        description="RFC 1918 private IP address",
    ),
    RedactionRule(
        rule_id="incident-id",
        severity=SEVERITY_WARN,
        pattern=re.compile(r"\b(?:INC-|SEV-)\d+\b"),
        replacement="[INCIDENT_ID]",
        description="Incident ID (INC-\\d+, SEV-\\d)",
    ),
    RedactionRule(
        rule_id="person-name",
        severity=SEVERITY_WARN,
        pattern=re.compile(r"(?:@|by|from)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)"),
        replacement="@[PERSON]",
        description="Person name (best-effort keyword heuristic near @ or Slack handles; will miss most real names in prose)",
    ),
    RedactionRule(
        rule_id="credential-assignment",
        severity=SEVERITY_WARN,
        pattern=re.compile(
            r"(?:api_key|password|secret)\s*=\s*[a-z0-9\-_]{6,}", re.IGNORECASE
        ),
        replacement="[REDACTED_CREDENTIAL]",
        description="Generic api_key/password/secret assignment (warn only; block would false-positive on ordinary prose)",
    ),
    RedactionRule(
        rule_id="jira-key",
        severity=SEVERITY_WARN,
        pattern=re.compile(r"\b[A-Z]{2,}-\d{2,}\b"),
        replacement="[JIRA_KEY]",
        description="Jira ticket key (e.g., TEAM-123)",
    ),
    RedactionRule(
        rule_id="pr-url",
        severity=SEVERITY_WARN,
        pattern=re.compile(
            r"https://github\.com/[A-Za-z0-9\-_]+/[A-Za-z0-9\-_]+/pull/\d+"
        ),
        replacement="https://github.com/[REPO]/pull/[NUMBER]",
        description="GitHub pull request URL",
    ),
    RedactionRule(
        rule_id="long-b64",
        severity=SEVERITY_WARN,
        pattern=re.compile(r"[A-Za-z0-9+/]{64,}={0,2}(?=\s|$)"),
        replacement="[BASE64_CONTENT]",
        description="Long base64-encoded content (64+ chars)",
    ),
)


def scan(text: str, *, anonymize: bool = False) -> tuple[Redaction, ...]:
    """Scan text against all redaction rules and return matching findings.

    Evaluates each rule in REDACTION_RULES and returns a tuple of Redaction
    objects for matches. Rules with requires_anonymize=True are evaluated only
    when anonymize=True.

    Line numbers are 1-indexed and computed from the match offset. The matched
    preview is MASKED (not the raw matched secret) to prevent leaking credentials
    in the export summary or when serializing to bundles.

    Args:
        text: The text to scan.
        anonymize: If True, evaluate rules marked requires_anonymize=True.

    Returns:
        Tuple of Redaction objects, empty if no findings.

    Note:
        Regex scanning cannot catch prose-form secrets, so the human
        confirmation step in export is the real last line of defense.
    """
    findings: list[Redaction] = []

    for rule in REDACTION_RULES:
        if rule.requires_anonymize and not anonymize:
            continue

        for match in rule.pattern.finditer(text):
            start_offset = match.start()
            line_no = text[:start_offset].count("\n") + 1

            masked_preview = rule.replacement

            findings.append(
                Redaction(
                    rule_id=rule.rule_id,
                    severity=rule.severity,
                    line_no=line_no,
                    matched=masked_preview,
                    replacement=rule.replacement,
                )
            )

    return tuple(findings)


def scrub(text: str, *, anonymize: bool = False) -> tuple[str, tuple[Redaction, ...]]:
    """Apply scrub-severity redactions to text and return modified text + findings.

    Scans text and applies replacements only for rules with severity='scrub'.
    Rules with severity='block' or 'warn' are reported in the returned Redaction
    tuple but do not modify the text (block aborts upstream, warn is informational).

    Callers MUST apply scrub to the body AND to every frontmatter string value
    including unknown_keys — scrubbing only the body leaks secrets stored in
    metadata.

    Args:
        text: The text to scrub.
        anonymize: If True, evaluate rules marked requires_anonymize=True.

    Returns:
        Tuple of (scrubbed_text, Redaction tuple) where Redaction includes
        all findings (block, scrub, warn).

    Note:
        Regex scrubbing cannot catch prose-form secrets, so the human
        confirmation step in export is the real last line of defense.
    """
    findings = scan(text, anonymize=anonymize)
    scrubbed_text = text

    for rule in REDACTION_RULES:
        if rule.requires_anonymize and not anonymize:
            continue
        if rule.severity != SEVERITY_SCRUB:
            continue

        scrubbed_text = rule.pattern.sub(rule.replacement, scrubbed_text)

    return scrubbed_text, findings


def has_blocking(reds: tuple[Redaction, ...]) -> bool:
    """Return True if any Redaction has severity == 'block'.

    Args:
        reds: Tuple of Redaction objects to check.

    Returns:
        True if any Redaction has severity='block', False otherwise.
    """
    return any(red.severity == SEVERITY_BLOCK for red in reds)
