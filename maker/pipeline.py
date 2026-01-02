"""Maker pipeline primitives built on shared core scaffolding."""
from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.pipeline import BaseProducer, RequestConsumer, SafeProcessor


@dataclass
class ToolSpec:
    """Lightweight record describing a maker tool module."""

    relative_path: Path
    module: str

    def display_row(self) -> str:
        return f"- maker/{self.relative_path.as_posix()}"


# -----------------------------------------------------------------------------
# Tool catalog pipeline (list available tools)
# -----------------------------------------------------------------------------


@dataclass
class ToolCatalogRequest:
    """Request to list available maker tools."""

    tools_root: Path


# Type alias using generic RequestConsumer from core.pipeline
ToolCatalogRequestConsumer = RequestConsumer[ToolCatalogRequest]


@dataclass
class ToolCatalogResult:
    """Result from scanning for maker tools."""

    specs: List[ToolSpec]
    text: str


class ToolCatalogProcessor(SafeProcessor[ToolCatalogRequest, ToolCatalogResult]):
    """Scan maker/ subdirectories and format catalog."""

    def _process_safe(self, payload: ToolCatalogRequest) -> ToolCatalogResult:
        specs: List[ToolSpec] = []
        for sub in sorted(payload.tools_root.iterdir()):
            if not sub.is_dir():
                continue
            for py in sorted(sub.glob("*.py")):
                rel = py.relative_to(payload.tools_root)
                module = ".".join(("maker",) + rel.with_suffix("").parts)
                specs.append(ToolSpec(relative_path=rel, module=module))

        if not specs:
            text = "No maker tools found."
        else:
            lines = ["Available maker tools:"]
            lines.extend(spec.display_row() for spec in specs)
            text = "\n".join(lines)

        return ToolCatalogResult(specs=specs, text=text)


class ToolCatalogProducer(BaseProducer):
    """Print tool catalog to stdout."""

    def _produce_success(self, payload: ToolCatalogResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        print(payload.text)


# -----------------------------------------------------------------------------
# Tool execution pipeline (direct import pattern)
# -----------------------------------------------------------------------------


@dataclass
class ToolRequest:
    """Request to run a maker tool."""

    module: str
    entry_point: str = "main"


# Type alias using generic RequestConsumer from core.pipeline
ToolRequestConsumer = RequestConsumer[ToolRequest]


@dataclass
class ToolResult:
    """Result from running a maker tool."""

    module: str
    return_code: int
    error: Optional[str] = None


class ToolRunnerProcessor(SafeProcessor[ToolRequest, ToolResult]):
    """Run maker modules via direct import and call their entry point."""

    def _process_safe(self, payload: ToolRequest) -> ToolResult:
        mod = import_module(payload.module)
        entry: Callable[[], Any] = getattr(mod, payload.entry_point, None)  # type: ignore[assignment]
        if not callable(entry):
            raise ValueError(f"Module {payload.module} has no callable '{payload.entry_point}'")
        result = entry()
        rc = int(result) if isinstance(result, int) else 0
        return ToolResult(module=payload.module, return_code=rc)


class ToolResultProducer(BaseProducer):
    """Emit diagnostics for tool execution."""

    def _produce_success(self, payload: ToolResult, diagnostics: Optional[Dict[str, Any]]) -> None:
        # Success case: tool ran without errors, nothing to print
        pass
