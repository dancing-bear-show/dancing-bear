"""Output filenames the Claude Code harness refuses when a subagent writes them.

A subagent's Write of a file named exactly ``report.md``, ``summary.md`` or
``findings.md`` is rejected with "Subagents should return findings as text, not
write report files." The match is on the basename, case-insensitive, in any
directory; ``run-report.md``, ``final-report.md``, ``run-summary.md`` and
``report.json`` are all accepted. Measured by probe on 2026-09-23 after
review-fix-threads' report stage failed on PR #408. The rule is the harness's,
not ours, so it is re-measured rather than reasoned about if it is questioned.

A stage can name its output two ways, and both must be checked:

* literally, in ``writes_to`` -- visible to ``workflow lint``;
* through a param, e.g. validate-then-render's ``{report_artifact}``, which the
  fragment leaves out of ``writes_to`` because it cannot be resolved statically.
  Its value comes from trigger defaults (lint can see those) or from ``--params``
  at compile time (only the compiler can), so the linter and the compiler share
  this module.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from workflow.models import StageSpec

REFUSED_OUTPUT_NAMES = frozenset({"report.md", "summary.md", "findings.md"})

_PARAM_REF = re.compile(r"(?<!\{)\{([a-z_][a-z0-9_]*)\}(?!\})")


def is_refused(path: str) -> bool:
    """True when the harness would refuse a subagent Write of *path*."""
    return PurePosixPath(path).name.lower() in REFUSED_OUTPUT_NAMES


@dataclass(frozen=True)
class RefusedOutput:
    """One stage output the harness would refuse.

    ``param`` is set when the name arrives through a param; ``declared`` is the
    writes_to entry or ``{param}`` as written, never the substituted value, so a
    message built from it cannot echo caller-supplied text.
    """

    stage: str
    declared: str
    refused_name: str  # always one of REFUSED_OUTPUT_NAMES
    param: str | None = None


def _substitute(text: str, params: Mapping[str, str]) -> str:
    return _PARAM_REF.sub(lambda m: str(params.get(m.group(1), m.group(0))), text)


def find_refused_outputs(
    stages: Iterable[StageSpec],
    params: Mapping[str, str],
    *,
    literal: bool = True,
) -> list[RefusedOutput]:
    """Every agent-stage output the harness would refuse, given *params*.

    With ``literal=False`` only param-derived names are reported -- the
    compiler's view, since literal ``writes_to`` entries are lint's job and do
    not change with ``--params``.

    A param counts when an agent stage references it (description or
    writes_to) and its value's basename is refused. Inline, local and skill
    stages are exempt: no subagent writes their outputs.
    """
    found: list[RefusedOutput] = []
    for stage in stages:
        if stage.executor == "agent":
            found.extend(_from_writes_to(stage, params, literal))
            found.extend(_from_description(stage, params))
    return found


def _from_writes_to(stage: StageSpec, params: Mapping[str, str], literal: bool) -> list[RefusedOutput]:
    found: list[RefusedOutput] = []
    for path in stage.writes_to:
        # Only a param in the FILENAME makes the name param-derived.
        # "{workspace}/report.md" is a literal report.md in a param directory.
        name_refs = _PARAM_REF.findall(PurePosixPath(path).name)
        resolved = _substitute(path, params) if name_refs else path
        if not is_refused(resolved) or (not name_refs and not literal):
            continue
        found.append(RefusedOutput(stage.name, path, PurePosixPath(resolved).name.lower(),
                                   param=name_refs[-1] if name_refs else None))
    return found


def _from_description(stage: StageSpec, params: Mapping[str, str]) -> list[RefusedOutput]:
    """Params the description names but writes_to does not -- validate-then-render's shape."""
    in_writes = {name for path in stage.writes_to for name in _PARAM_REF.findall(path)}
    found: list[RefusedOutput] = []
    for name in sorted(set(_PARAM_REF.findall(stage.description)) - in_writes):
        value = params.get(name)
        if isinstance(value, str) and is_refused(value):
            found.append(RefusedOutput(stage.name, "{" + name + "}",
                                       PurePosixPath(value).name.lower(), param=name))
    return found


def describe(item: RefusedOutput) -> str:
    """A message naming the stage and param, never the caller's raw value."""
    via = f" via param '{item.param}'" if item.param else ""
    return (
        f"stage '{item.stage}' writes '{item.declared}'{via}, a file named "
        f"'{item.refused_name}': the harness refuses a subagent Write of report.md, "
        "summary.md and findings.md, so this stage can never produce it -- use a "
        "prefixed name such as run-report.md"
    )
