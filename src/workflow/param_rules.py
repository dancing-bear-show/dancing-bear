"""Engine-enforced validation of caller-overridable trigger params.

Trigger params are overridable with ``--params`` and ``resolve_params``
substitutes them into stage description TEXT by raw string replacement. A
check written into a stage prompt runs too late -- the value is already in the
prompt the agent reads -- so the rules declared here are enforced by the
engine itself, in ``compile_workflow``, BEFORE any substitution happens.

YAML shape (both keys optional, both inside ``trigger:``)::

    trigger:
      source: manual
      params:
        ollama_host: "http://localhost:11434"
        pr_number: ""
      param_rules:                     # name -> full-match regex
        ollama_host: 'https?://[A-Za-z0-9._-]+(:[0-9]{1,5})?/?'
        pr_number: '[1-9][0-9]{0,8}'
      required: [pr_number]            # effective value must be non-blank

Semantics, applied to the EFFECTIVE value (declared default merged with any
override):

* every param value must be a string;
* a ``required`` param must be non-blank (whitespace-only counts as blank);
* a rule is applied with ``re.fullmatch`` -- but only to a non-blank value.
  An optional param left blank is allowed, because blank is the conventional
  "not supplied" default across the catalog and substitutes nothing; a param
  whose blank value is unsafe must be listed in ``required``.

The regex check itself is ``param_guard.check_params`` -- the same full-match,
no-echo implementation behind ``workflow check-params`` -- so the two entry
points cannot drift. Failure messages name the param and the reason and
NEVER the value: a rejected value is untrusted, and echoing it copies it into
logs.

Fragments (``include:``) may declare their own ``param_rules``/``required``;
they are combined with the importing workflow's (see ``ParamRules.merged``).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from os import PathLike
from typing import Any

from workflow.models import ParamRules
from workflow.param_guard import ParamCheck, ParamGuardResult, check_params
from workflow.parser_errors import WorkflowParseError
from workflow.placeholders import is_identifier

__all__ = [
    "ENGINE_BUILTIN_PARAMS",
    "UnsafePathError",
    "check_rules_declared",
    "is_identifier",
    "parse_param_rules",
    "require_shell_safe_path",
    "undeclared_overrides",
    "validate_param_values",
]

# Params the engine itself injects, so an override of them is legitimate even
# though no workflow declares them. ``work_dir`` is added by the CLI's
# ``run``/``init-workspace`` (``cli_dispatch._build_resolved_params``).
# ``{workspace}`` is deliberately NOT here: it is filled in by the /workflow
# skill from ``init-workspace``'s output, never from params, and accepting it
# as an override would let ``--params workspace=...`` bypass the path check.
ENGINE_BUILTIN_PARAMS: frozenset[str] = frozenset({"work_dir"})

# A path that is substituted into stage text an agent may run as shell must
# not be able to break out of quoting: no whitespace, quotes, ``$``, backtick,
# ``;&|<>()``, globs, braces, backslash, or newline. ``:`` is allowed because
# the orchestrator's default run id embeds an ISO timestamp.
_SHELL_SAFE_PATH_RE = re.compile(r"[A-Za-z0-9._/+@%=,:~-]+")
_SHELL_SAFE_PATH_HINT = "allowed: letters, digits, and . _ / + @ % = , : ~ -"


class UnsafePathError(ValueError):
    """A workspace-related path contains characters unsafe for shell rendering."""


def undeclared_overrides(declared: Iterable[str], overrides: Iterable[str]) -> list[str]:
    """Display labels for override keys that are neither declared nor built-in.

    A non-identifier key is reported only as ``a non-identifier param name``
    (once), never verbatim: such a key is caller-controlled text, and an
    identifier-shaped one is safe to name.
    """
    allowed = set(declared) | ENGINE_BUILTIN_PARAMS
    rejected = [k for k in overrides if k not in allowed]
    labels = sorted({k for k in rejected if is_identifier(k)})
    if any(not is_identifier(k) for k in rejected):
        labels.append("a non-identifier param name")
    return labels


def require_shell_safe_path(path: str | PathLike[str], what: str) -> None:
    """Raise :class:`UnsafePathError` unless *path* is shell-safe; never echo it.

    Args:
        path: The path to check (``str`` or ``os.PathLike``).
        what: A value-free description of the path, used in the message.
    """
    if _SHELL_SAFE_PATH_RE.fullmatch(str(path)) is None:
        raise UnsafePathError(
            f"{what} contains characters unsafe for shell rendering"
            f" ({_SHELL_SAFE_PATH_HINT}); choose another path"
        )


def _parse_checks(raw: object, source: str) -> tuple[ParamCheck, ...]:
    """Parse the ``param_rules`` mapping, rejecting non-string and invalid regexes."""
    if not isinstance(raw, dict):
        raise WorkflowParseError(
            f"{source}: trigger 'param_rules' must be a mapping, got {type(raw).__name__}"
        )
    checks: list[ParamCheck] = []
    for key, pattern in raw.items():
        name = str(key)
        if not isinstance(pattern, str):
            raise WorkflowParseError(
                f"{source}: trigger param_rules[{name!r}] must be a string regex,"
                f" got {type(pattern).__name__}"
            )
        try:
            re.compile(pattern)
        except re.error as exc:
            raise WorkflowParseError(
                f"{source}: trigger param_rules[{name!r}] is not a valid regex: {exc}"
            ) from exc
        checks.append(ParamCheck(name=name, pattern=pattern))
    return tuple(checks)


def _parse_required(raw: object, source: str) -> frozenset[str]:
    """Parse the ``required`` list of param names."""
    if not isinstance(raw, list) or not all(isinstance(n, str) for n in raw):
        raise WorkflowParseError(
            f"{source}: trigger 'required' must be a list of param names"
        )
    return frozenset(raw)


def parse_param_rules(trigger: Mapping[str, Any], source: str) -> ParamRules:
    """Parse ``param_rules`` and ``required`` from a raw ``trigger:`` mapping.

    Only shape is checked here; whether each name is declared is checked by
    :func:`check_rules_declared` once included fragments' params are merged.

    Raises:
        WorkflowParseError: on a non-mapping ``param_rules``, a non-string or
            invalid regex, or a ``required`` that is not a list of strings.
    """
    checks = _parse_checks(trigger["param_rules"], source) if "param_rules" in trigger else ()
    required = _parse_required(trigger["required"], source) if "required" in trigger else frozenset()
    return ParamRules(checks=checks, required=required)


def check_rules_declared(rules: ParamRules, params: Mapping[str, str], source: str) -> None:
    """Reject rules on undeclared params, and non-blank defaults that fail their rule.

    A rule on an undeclared name would never fire -- the name has no default,
    so an override of it is the only way it gets a value, and an author who
    misspelt the name would believe it protected. A default that fails its
    own rule is an author error that would otherwise surface only at compile.

    Raises:
        WorkflowParseError: naming every offending param (never its value).
    """
    names = {c.name for c in rules.checks} | rules.required
    undeclared = sorted(names - set(params))
    if undeclared:
        raise WorkflowParseError(
            f"{source}: trigger param_rules/required name undeclared param(s)"
            f" {undeclared}; declare them under trigger.params"
        )
    defaults_ok = check_params(dict(params), _applicable(rules.checks, params))
    if not defaults_ok.ok:
        raise WorkflowParseError(
            f"{source}: trigger param default fails its own rule: {'; '.join(defaults_ok.failures)}"
        )


def _is_blank(value: object) -> bool:
    """A string that is empty or whitespace-only. Non-strings are not blank."""
    return isinstance(value, str) and not value.strip()


def _applicable(checks: Iterable[ParamCheck], params: Mapping[str, object]) -> list[ParamCheck]:
    """Checks whose param holds a non-blank string -- the values rules apply to."""
    return [
        c for c in checks
        if isinstance(params.get(c.name), str) and not _is_blank(params.get(c.name))
    ]


def validate_param_values(rules: ParamRules, params: Mapping[str, object]) -> ParamGuardResult:
    """Validate effective trigger params against *rules*, collecting every failure.

    Never echoes a value. A blank required param is reported as missing, and a
    blank optional one is exempt from its rule (see the module docstring).
    """
    failures: list[str] = [
        f"{name}: not a string (got {type(value).__name__})"
        for name, value in params.items()
        if not isinstance(value, str)
    ]
    failures.extend(
        f"{name}: required but blank; pass it with --params {name}=<value>"
        for name in sorted(rules.required)
        if _is_blank(params.get(name, ""))
    )
    failures.extend(check_params(dict(params), _applicable(rules.checks, params)).failures)
    return ParamGuardResult(ok=not failures, failures=tuple(failures))
