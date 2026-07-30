"""Shared exception type for workflow YAML parsing/validation failures."""

from __future__ import annotations


class WorkflowParseError(Exception):
    """Raised when a workflow definition fails validation."""
