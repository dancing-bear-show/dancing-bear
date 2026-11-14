from __future__ import annotations

from core.meta_base import AppMeta

META = AppMeta(
    app_id="agent-helpers",
    purpose="Structured checks for agent sessions: tests, AST/import/JSON validation, patch analysis, git ops",
    display_name="Agent Helpers",
    bin_name="./bin/agent-helpers",
    example_cmd="./bin/agent-helpers validate-json --file findings.json --keys status,results",
)
