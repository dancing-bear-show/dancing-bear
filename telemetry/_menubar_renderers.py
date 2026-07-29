"""Icon rendering helpers extracted from _menubar_app.py."""
from __future__ import annotations

from telemetry._menubar_config import _IconTemplate
from telemetry.tui import format_tokens as _format_tokens


def _icon_substitutions(
    icon_ctx: dict[str, dict], mtd_cost: float, score: int, otel_cost_1d: float = 0.0
) -> dict[str, str]:
    """Build substitution mapping for the icon template."""
    h1 = icon_ctx.get("1h", {}) or {}
    d1 = icon_ctx.get("1d", {}) or {}
    tok = h1.get("input_tokens", 0) + h1.get("output_tokens", 0)
    return {
        "score": str(score),
        "1h_spend": f"${h1.get('cost', 0.0):.2f}",
        "1d_spend": f"${d1.get('cost', 0.0):.2f}",
        "mtd_spend": f"${mtd_cost:.2f}",
        "tokens_1h": _format_tokens(tok),
        "otel_1d": f"${otel_cost_1d:.2f}",
    }


def _render_icon_plain(
    template: str, icon_ctx: dict[str, dict], mtd_cost: float, score: int,
    otel_cost_1d: float = 0.0,
) -> str:
    """Render template as plain text. Unknown $vars pass through literally."""
    values = _icon_substitutions(icon_ctx, mtd_cost, score, otel_cost_1d)
    return _IconTemplate(template).safe_substitute(values)


def _icon_token_stream(template: str) -> list[tuple[str, str]]:
    """Split a template into (kind, text) tokens."""
    tokens: list[tuple[str, str]] = []
    pos = 0
    for m in _IconTemplate.pattern.finditer(template):
        if m.start() > pos:
            tokens.append(("lit", template[pos:m.start()]))
        if m.group("escaped") is not None:
            tokens.append(("lit", "$"))
        elif m.group("invalid") is not None:
            tokens.append(("lit", m.group(0)))
        elif m.group("braced") is not None:
            tokens.append(("braced", m.group("braced")))
        else:
            tokens.append(("var", m.group("named")))
        pos = m.end()
    if pos < len(template):
        tokens.append(("lit", template[pos:]))
    return tokens
