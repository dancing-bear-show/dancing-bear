"""Dataclasses for normalized qlty findings and remediation strategies.

qlty emits two wire formats (undocumented ``--json`` and ``--sarif``) whose
field names and rule identifiers differ. Everything in this module is the
*normalized* form both are mapped onto, so downstream code never branches on
which wire format produced a finding.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Tier(str, Enum):
    """Action class for a rule. The tier, not the count, decides what happens.

    Values are stable strings so JSON output is greppable: the lettered tiers
    serialize as "A"/"B"/"C"/"D", and the sentinel as "unknown".
    """

    A = "A"  # mechanical, safe to fan out
    B = "B"  # judgment required, triage before acting
    C = "C"  # false positive, suppress with a stated reason
    D = "D"  # advisory: read before acting; no auto-proposed fix
    INFO = "informational"  # not a defect; a scanner notice with no action
    UNKNOWN = "unknown"  # rule absent from the strategy table


class Source(str, Enum):
    """Which qlty subcommand produced a finding.

    ``check`` (lint/security) and ``smells`` (structure/duplication) are
    disjoint sets; neither is a superset of the other, so a merged finding
    set must record its origin (plan F2).
    """

    CHECK = "check"
    SMELLS = "smells"


class WireFormat(str, Enum):
    """Which qlty output format a finding was parsed from."""

    JSON = "json"
    SARIF = "sarif"


@dataclass(frozen=True)
class Location:
    """A file path plus 1-indexed start line, as reported by qlty."""

    path: str
    line: int = 0

    def __str__(self) -> str:
        return f"{self.path}:{self.line}" if self.line else self.path


@dataclass(frozen=True)
class Finding:
    """One normalized qlty finding.

    ``value`` is the numeric metric qlty thresholds on (parameter count,
    duplicated-line count). It is present in ``--json`` but absent from SARIF,
    where it is only embedded in message prose -- so it is Optional and callers
    that filter on it must treat ``None`` as "unknown", never as "no match"
    (plan F4).

    ``group_key`` is qlty's ``structural_hash`` for duplication findings. qlty
    reports each clone pair once per location, so findings sharing a
    ``group_key`` are the same underlying clone group and must be deduped
    before counting or the rule is overstated (~2x).
    """

    rule: str
    location: Location
    level: str
    message: str
    source: Source
    wire_format: WireFormat
    tool: str = ""
    value: Optional[int] = None
    other_locations: tuple[Location, ...] = field(default_factory=tuple)
    group_key: Optional[str] = None

    @property
    def file(self) -> str:
        """Path of the primary location."""
        return self.location.path

    @property
    def line(self) -> int:
        """1-indexed start line of the primary location."""
        return self.location.line

    @property
    def identity(self) -> tuple[str, str, int]:
        """Stable identity for cross-run comparison.

        Totals are not a progress signal (plan F5); comparing finding
        identities is. Deliberately excludes ``value`` and ``message`` so a
        finding is "the same finding" across runs even if its metric shifts.
        """
        return (self.rule, self.location.path, self.location.line)

    def dedup_key(self) -> tuple[str, ...]:
        """Key collapsing duplicate reports of one underlying finding.

        Duplication findings are reported once per location; grouping on
        qlty's ``structural_hash`` collapses them to one entry per clone
        group. Non-duplication findings fall back to their identity.
        """
        if self.group_key:
            return (self.rule, self.group_key)
        return (self.rule, self.location.path, str(self.location.line))


@dataclass(frozen=True)
class RuleStrategy:
    """Remediation strategy for one qlty rule."""

    rule: str
    tier: Tier
    action: str
    rationale: str

    @property
    def actionable(self) -> bool:
        """Whether triage may auto-propose a fix without a human reading first.

        Tier D withholds an auto-proposed fix, but that is a statement about
        *who decides*, not a claim that the findings are never real. The
        rationale for D here is that the metric is untrustworthy (a structural
        hasher that fires on any two similarly-sized literals), so a proposal
        generated from the metric alone would be unsafe. Genuine duplication
        can still exist and still be worth fixing -- see ``needs_human_read``,
        which is how such a finding reaches a person rather than being dropped.
        """
        return self.tier in (Tier.A, Tier.B)

    @property
    def needs_human_read(self) -> bool:
        """Whether a person must read the finding before any action.

        True for Tier D: the finding is surfaced with all its locations and
        escalates to a human, rather than being silently discarded. This is
        the difference between "no automated proposal" and "not real debt".
        """
        return self.tier is Tier.D

    @property
    def reportable_only(self) -> bool:
        """Whether the finding carries no remediation path at all.

        True only for informational scanner notices, which are not defects.
        """
        return self.tier is Tier.INFO
