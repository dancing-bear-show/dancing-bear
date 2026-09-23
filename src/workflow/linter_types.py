"""Shared types for the workflow linter.

``LintError``, ``LintWarning``, and ``LintResult`` live here so that
``linter.py`` and ``linter_access.py`` can both import them without
creating a circular dependency.
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "LintError",
    "LintWarning",
    "LintResult",
]


@dataclass(frozen=True)
class LintError:
    """A fatal structural error that makes the workflow invalid."""

    stage: str  # stage name, or "<global>" for top-level errors
    field: str  # YAML field where the error was found
    message: str


@dataclass(frozen=True)
class LintWarning:
    """A non-fatal issue that may indicate a misconfiguration."""

    stage: str
    field: str
    message: str


@dataclass
class LintResult:
    """Aggregated output of a lint run."""

    file: str
    valid: bool = True
    errors: list[LintError] = field(default_factory=list)
    warnings: list[LintWarning] = field(default_factory=list)
    stages: int = 0
    dag_depth: int = 0

    def as_dict(self) -> dict[str, object]:
        """Render as a flat dict suitable for emit_one / emit_rows."""
        return {
            "file": self.file,
            "valid": self.valid,
            "errors": [
                {"stage": e.stage, "field": e.field, "message": e.message}
                for e in self.errors
            ],
            "warnings": [
                {"stage": w.stage, "field": w.field, "message": w.message}
                for w in self.warnings
            ],
            "stages": self.stages,
            "dag_depth": self.dag_depth,
        }
