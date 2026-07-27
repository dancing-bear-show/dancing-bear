"""Rules management helpers for the telemetry CLI."""

from __future__ import annotations

from pathlib import Path

from rich.console import Console
from rich.table import Table

console = Console()


def _rules_init(config_path: Path) -> None:
    """Scaffold a starter rules.yaml if one does not exist."""
    import yaml

    config_path.parent.mkdir(parents=True, exist_ok=True)
    if config_path.exists():
        console.print(f"[yellow]Already exists:[/] {config_path}")
        return
    starter = {
        "avoidable": {
            "bash-as-grep": {"enabled": True},
            "bash-as-read": {"enabled": True},
            "bash-as-glob": {"enabled": True},
            "bash-as-write": {"enabled": True},
            "redundant-read": {"enabled": True, "window_seconds": 60},
            "rapid-re-edit": {"enabled": True, "window_seconds": 30},
        },
        "review": {
            "abandoned-search": {"enabled": True, "consecutive_reads": 3},
            "fruitless-agent": {"enabled": True, "window_seconds": 300},
        },
        "custom_rules": [],
    }
    config_path.write_text(yaml.safe_dump(starter, default_flow_style=False))
    console.print(f"[green]Created:[/] {config_path}")


def _rules_validate() -> int:
    """Validate the current rules file and return a non-zero exit code on errors."""
    from telemetry.rules import load_rules, validate_rules

    loaded = load_rules()
    errors = validate_rules(loaded)
    if errors:
        console.print("[red]Validation errors:[/]")
        for err in errors:
            console.print(f"  [red]•[/] {err}")
        return 1
    console.print("[green]No errors — rules are valid.[/]")
    return 0


def _rules_explain(name: str) -> None:
    """Print config and fix hints for a named rule."""
    from telemetry.rules import load_rules

    loaded = load_rules()
    for category in ("avoidable", "review"):
        rule_cfg = loaded.get(category, {}).get(name)
        if rule_cfg is None:
            continue
        console.print(f"[bold cyan]{name}[/]  ([dim]{category}[/])")
        console.print(f"  Config: {rule_cfg}")
        fix_hints = loaded.get("fix_hints", {}).get(name, {})
        if fix_hints:
            console.print("  Fix hints:")
            for level, hint in fix_hints.items():
                console.print(f"    [dim]{level}:[/] {hint}")
        return
    console.print(f"[yellow]Rule not found:[/] {name}")
    console.print("[dim]Use 'telemetry rules' to list all rules.[/]")


def _rules_list() -> None:
    """Print a table of all configured rules."""
    from telemetry.rules import load_rules

    loaded = load_rules()
    table = Table(show_header=True, header_style="bold", title="Telemetry Rules")
    table.add_column("Name", style="cyan")
    table.add_column("Category")
    table.add_column("Enabled", justify="center")
    table.add_column("Config")

    for category in ("avoidable", "review"):
        cat_rules = loaded.get(category, {})
        for rule_name, cfg in cat_rules.items():
            if not isinstance(cfg, dict):
                continue
            enabled = cfg.get("enabled", True)
            enabled_str = "[green]yes[/]" if enabled else "[dim]no[/]"
            config_items = {
                k: v for k, v in cfg.items()
                if k != "enabled" and not isinstance(v, list)
            }
            config_str = "  ".join(f"{k}={v}" for k, v in config_items.items())
            table.add_row(rule_name, category, enabled_str, config_str or "—")

    custom = loaded.get("custom_rules", [])
    for i, rule in enumerate(custom):
        rule_name = rule.get("reason", f"custom-{i}")
        table.add_row(rule_name, "custom", "[green]yes[/]", str(rule.get("tool", "any")))

    console.print(table)
