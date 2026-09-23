"""Agent-access rule checks for the workflow linter.

Validates that a stage's ``access:`` field matches what its role can
actually do, surfacing mismatches as ``LintWarning`` entries on the shared
``LintResult``. These are warnings rather than errors because the ``access``
field is documentation — no runtime code reads it; the real gate is
``disallowedTools:`` in ``.claude/agents/<role>.md``.

Two disagreements are surfaced:

* ``read-only`` on a stage that lists Write/Edit in ``tools:``, or that
  declares no tools (empty = all tools) on a Write-capable role — the
  declaration implies a restriction that does not exist.
* ``read-write`` on a stage whose role disallows the Write tool — the stage
  cannot produce its required outputs and will stall.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from workflow.models import AgentSpec, StageSpec

from .linter_types import LintResult, LintWarning

__all__ = [
    "_check_agent_access",
    "_check_stage_access",
    "_roles_that_cannot_write",
    "_role_is_defined",
]

_AGENTS_DIR = Path(__file__).resolve().parents[2] / ".claude" / "agents"

# The Write tool name as it appears in ``disallowedTools:`` frontmatter.
_WRITE_TOOL = "Write"


def _roles_that_cannot_write(agents_dir: Path | None = None) -> frozenset[str]:
    """Return role names whose agent definition disallows the Write tool.

    Derived from the definitions on disk rather than hardcoded. A hardcoded list
    goes stale the moment someone edits frontmatter -- which is exactly what
    happened in PR #392, where `researcher` and `Plan` both changed and every
    reader working from memory got the wrong answer.

    Returns an empty set if the directory is missing, so linting a workflow from
    outside a checkout degrades to "no access warnings" rather than raising.
    """
    d = agents_dir if agents_dir is not None else _AGENTS_DIR
    if not d.is_dir():
        return frozenset()
    blocked: set[str] = set()
    for md in d.glob("*.md"):
        try:
            text = md.read_text(encoding="utf-8", errors="replace")
        except OSError:  # nosec B112 - an unreadable agent file is not a lint failure
            continue
        for line in text.splitlines():
            if not line.startswith("disallowedTools:"):
                continue
            tools = {t.strip() for t in line.split(":", 1)[1].split(",")}
            if _WRITE_TOOL in tools:
                blocked.add(md.stem)
            break
    return frozenset(blocked)


def _role_is_defined(role: str, agents_dir: Path | None = None) -> bool:
    """True if ``role`` names an agent definition in ``.claude/agents/``.

    Workflows also use pseudo-roles that name no agent -- ``inline`` is the one in
    this tree -- and those have no frontmatter to serve as the enforcement gate.
    """
    d = agents_dir if agents_dir is not None else _AGENTS_DIR
    return (d / f"{role}.md").is_file()


def _check_agent_access(defn: object, result: LintResult) -> None:
    """Warn where a stage's ``access:`` disagrees with what its role can do.

    ``access`` is parsed and validated in ``parser_fields.py`` and stored on
    ``AgentSpec`` -- and then read by nothing. No code in ``src/`` grants or
    restricts anything based on it, and the same is true of a stage's ``tools:``
    list. Both are documentation.

    That matters because reviewers reasonably read ``access: read-only`` as a
    guarantee and file it as a security finding when a stage writes anyway. The
    only real gate is the ``disallowedTools:`` frontmatter in
    ``.claude/agents/<role>.md``.

    Two disagreements are worth surfacing, and they fail in opposite directions:

    * ``read-only`` on a stage that lists Write/Edit in ``tools:`` -- the
      declaration implies a restriction that does not exist.
    * ``read-write`` on a stage whose role CANNOT write -- the stage is
      unsatisfiable: it will gather its data and then be unable to emit any of
      it, stalling the run on a missing required output.

    Deliberately NOT warned: ``read-only`` on a stage that merely *has* a
    Write-capable role but declares no write tools. ``access`` defaults to
    ``read_only`` when the key is absent, so the parsed spec cannot distinguish
    "declared read-only" from "said nothing" -- and after #392 relaxed
    ``researcher``, almost every role can write. Warning on that shape fires on
    any stage that omits ``access`` entirely, including a minimal two-line
    gather stage that is claiming nothing. That is noise, and it broke a
    ``--strict`` lint fixture that was legitimately clean.

    Warnings rather than errors: 87 stages carried the first shape before #392
    and the tree still ran, so failing the lint would break every existing
    workflow over a field that changes no behaviour.
    """
    from workflow.models import WorkflowDefinition

    if not isinstance(defn, WorkflowDefinition):
        return
    _check_stage_access(defn.stages, result)


def _read_only_reason(agent: AgentSpec, role: str, cannot_write: frozenset[str]) -> str:
    """Why an ``access: read-only`` declaration is misleading, or "" if it is not.

    Two shapes qualify, and the second needs three gates that each fixed a real
    false positive:

    * the stage names Write/Edit in ``tools`` -- a claim regardless of role;
    * the stage declares NO tools, which means ALL tools (models.py: "allowed
      tools (empty = all)"), so read-only is the most permissive shape rather
      than the least.

    Gates on the second: ``access_declared`` because ``access`` defaults to
    read_only when the key is absent, and without it the branch fires on every
    minimal stage that never mentioned access (it broke a ``--strict`` fixture
    that was legitimately clean); ``_role_is_defined`` because ``role: inline``
    and other pseudo-roles name no agent, so citing their frontmatter is
    nonsense; and ``cannot_write`` because a role whose frontmatter withholds
    Write makes the declaration accurate.
    """
    write_tools = sorted(t for t in agent.tools if t in {"Write", "Edit"})
    if write_tools:
        return f"lists {write_tools} in tools"
    if (
        getattr(agent, "access_declared", False)
        and not agent.tools
        and _role_is_defined(role)
        and role not in cannot_write
    ):
        return (
            f"declares no tools, which means ALL tools, and role '{role}' "
            f"is permitted Write"
        )
    return ""


def _access_warning(stage_name: str, role: str, reason: str) -> LintWarning:
    """The read-only-but-writable warning, pointing at the real gate."""
    return LintWarning(
        stage=stage_name,
        field="agent.access",
        message=(
            f"declares access: read-only but {reason} — access is not "
            f"enforced at runtime (nothing reads it), so this restricts "
            f"nothing; the real gate is disallowedTools in "
            f".claude/agents/{role}.md"
        ),
    )


def _unsatisfiable_warning(stage_name: str, role: str) -> LintWarning:
    """The read-write-but-cannot-write warning: the stage stalls on its output."""
    return LintWarning(
        stage=stage_name,
        field="agent.access",
        message=(
            f"declares access: read-write but role '{role}' disallows the "
            f"Write tool (.claude/agents/{role}.md), so this stage cannot "
            f"produce its outputs — use a Write-capable role"
        ),
    )


def _check_stage_access(stages: tuple[StageSpec, ...], result: LintResult) -> None:
    """Apply the access cross-check to a bare sequence of stages.

    Split out from ``_check_agent_access`` so fragments get the same treatment.
    ``lint_workflow`` returns through ``_lint_fragment`` for any file declaring
    ``fragment: true``, well before the full-workflow checks run -- so a fragment
    carrying either mismatch was accepted silently. 19 fragment files were
    unchecked, including the shared ones every workflow includes.

    The two warning paths live in helpers above: inlined, the loop plus nested
    access branches plus the four-clause guard exceeded the repo's
    cognitive-complexity limit.
    """
    from workflow.models import AgentAccess

    cannot_write = _roles_that_cannot_write()
    for stage in stages:
        agent = getattr(stage, "agent", None)
        if agent is None:
            continue
        role = agent.role
        if agent.access == AgentAccess.read_only:
            reason = _read_only_reason(agent, role, cannot_write)
            if reason:
                result.warnings.append(_access_warning(stage.name, role, reason))
        elif agent.access == AgentAccess.read_write and role in cannot_write:
            result.warnings.append(_unsatisfiable_warning(stage.name, role))
