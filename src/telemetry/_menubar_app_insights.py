"""Insights section mixin extracted from _menubar_app.py."""
from __future__ import annotations

from pathlib import Path

from telemetry._menubar_budget import _safe_float, _safe_int
from telemetry._menubar_config import _MAX_TIPS_LIMIT
from telemetry.tui import format_cost as _format_cost


class InsightsMixin:
    """Methods for rendering the Insights menu section."""

    @staticmethod
    def _project_label_from_path(project_path: str | None) -> str:
        if not project_path:
            return ""
        name = Path(project_path).name
        parts = [p for p in name.split("-") if p]
        return parts[-1][:32] if parts else ""

    def _make_tip_click_handler(self, idx: int):  # type: ignore[no-untyped-def]
        def _handler(_sender: object) -> None:  # noqa: ARG001
            # Late import avoids circular: _menubar_app imports this module.
            import rumps as _rumps  # type: ignore[import-not-found]
            data = self._insights_tip_hints[idx] if idx < len(self._insights_tip_hints) else {}  # type: ignore[attr-defined]
            rule = data.get("claude_rule") or ""
            reason = data.get("waste_reason") or "tip"
            if not rule:
                fix = data.get("fix_hint") or ""
                if fix:
                    self._copy_to_clipboard(fix)  # type: ignore[attr-defined]
                    self._notify("Fix copied", fix)  # type: ignore[attr-defined]
                return
            response = _rumps.alert(
                title=f"CLAUDE.md rule for {reason}",
                message=(
                    f"{rule}\n\n"
                    "Copy this rule, then paste it into your CLAUDE.md "
                    "(global ~/.claude/CLAUDE.md or project-level)."
                ),
                ok="Copy", cancel="Close",
            )
            if response == 1:
                self._copy_to_clipboard(rule)  # type: ignore[attr-defined]
                self._notify("Rule copied", rule)  # type: ignore[attr-defined]
        return _handler

    def _render_tip_row(self, idx: int, row: object, tips: list[dict]) -> None:
        if idx < len(tips):
            t = tips[idx]
            icon = "✗" if t.get("severity") == "avoidable" else "⚠"
            count = _safe_int(t.get("count"), 0)
            reason = str(t.get("waste_reason") or "?")
            tip_cost = _safe_float(t.get("cost_impact"), 0.0)
            row.title = f"  {icon} {count}× {reason}  ·  saves ~${tip_cost:.2f}"  # type: ignore[union-attr]
            row.hidden = False  # type: ignore[union-attr]
            self._insights_tip_hints[idx] = {  # type: ignore[attr-defined]
                "waste_reason": reason,
                "claude_rule": str(t.get("claude_rule") or ""),
                "fix_hint": str(t.get("fix_hint") or ""),
            }
        else:
            row.hidden = True  # type: ignore[union-attr]
            self._insights_tip_hints[idx] = {}  # type: ignore[attr-defined]

    def _render_insights(self, payload: dict | None, max_tips: int = _MAX_TIPS_LIMIT) -> None:
        if payload is None:
            self._hdr_insights.title = "-- Insights --"  # type: ignore[attr-defined]
            self._info_insights_summary.title = "  ccpulse data not available"  # type: ignore[attr-defined]
            for idx, row in enumerate(self._insights_tip_rows):  # type: ignore[attr-defined]
                row.title = f"  insights_tip_{idx + 1}"
                row.hidden = True
                self._insights_tip_hints[idx] = {}  # type: ignore[attr-defined]
            return

        project_short = self._project_label_from_path(payload.get("project_path"))
        self._hdr_insights.title = (  # type: ignore[attr-defined]
            f"-- Insights ({project_short}) --" if project_short
            else "-- Insights (current session) --"
        )
        eff = _safe_float(payload.get("efficiency_score"), 0.0)
        ws = payload.get("waste_summary") if isinstance(payload.get("waste_summary"), dict) else {}
        cost = _safe_float(payload.get("cost_usd"), 0.0)
        cost_est = bool(payload.get("cost_is_estimated", False))
        avoid = _safe_int(ws.get("avoidable"), 0)
        review = _safe_int(ws.get("review"), 0)
        self._info_insights_summary.title = (  # type: ignore[attr-defined]
            f"  Eff {eff:.0f}%  |  {avoid} avoid / {review} review  |  {_format_cost(cost, cost_est)}"
        )

        raw_tips = payload.get("tips") or []
        tips = [t for t in raw_tips if isinstance(t, dict)][:max_tips]
        for idx, row in enumerate(self._insights_tip_rows):  # type: ignore[attr-defined]
            self._render_tip_row(idx, row, tips)
