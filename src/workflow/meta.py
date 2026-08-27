"""App metadata for the workflow CLI."""

from __future__ import annotations

from core.meta_base import AppMeta

META = AppMeta(
    app_id="workflow",
    purpose="YAML DAG workflow engine — parse, compile, run, lint, and manage workflows",
    display_name="Workflow",
    example_cmd="./bin/workflow run <file.yaml> --params k=v",
)
