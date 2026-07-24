"""Maker pipeline primitives built on shared core scaffolding."""
from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Callable

from core.cli_output import output
from core.pipeline import BaseProducer, RequestConsumer, SafeProcessor


@dataclass
class ToolSpec:
    """Lightweight record describing a maker tool module."""

    relative_path: Path
    module: str

    def display_row(self) -> str:
        return f"- maker/{self.relative_path.as_posix()}"


def scan_tools(root: Path) -> list[str]:
    """Return relative posix paths of all *.py files under maker subdirectories."""
    tools: list[str] = []
    for sub in sorted(p for p in root.iterdir() if p.is_dir()):
        for py in sorted(sub.glob("*.py")):
            tools.append(py.relative_to(root).as_posix())
    return tools


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

    specs: list[ToolSpec]
    text: str


class ToolCatalogProcessor(SafeProcessor[ToolCatalogRequest, ToolCatalogResult]):
    """Scan maker/ subdirectories and format catalog."""

    def _process_safe(self, payload: ToolCatalogRequest) -> ToolCatalogResult:
        specs: list[ToolSpec] = []
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

    def _produce_success(self, payload: ToolCatalogResult, diagnostics: dict[str, Any] | None) -> None:
        output(payload.text)


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
    error: str | None = None


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

    def _produce_success(self, payload: ToolResult, diagnostics: dict[str, Any] | None) -> None:
        # Success case: tool ran without errors, nothing to print
        pass
