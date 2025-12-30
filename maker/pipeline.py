"""Maker pipeline primitives built on shared core scaffolding."""
from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, Callable, List, Optional

from core.pipeline import Consumer, Processor, Producer, ResultEnvelope, RequestConsumer


@dataclass
class ToolSpec:
    """Lightweight record describing a maker tool module."""

    relative_path: Path
    module: str

    def display_row(self) -> str:
        return f"- maker/{self.relative_path.as_posix()}"


class ToolCatalogConsumer(Consumer[List[ToolSpec]]):
    """Scan maker/ subdirectories for python modules to surface as tools."""

    def __init__(self, tools_root: Path) -> None:
        self._root = tools_root

    def consume(self) -> List[ToolSpec]:
        specs: List[ToolSpec] = []
        for sub in sorted(self._root.iterdir()):
            if not sub.is_dir():
                continue
            for py in sorted(sub.glob("*.py")):
                rel = py.relative_to(self._root)
                module = ".".join(("maker",) + rel.with_suffix("").parts)
                specs.append(ToolSpec(relative_path=rel, module=module))
        return specs


class ToolCatalogFormatter(Processor[List[ToolSpec], str]):
    """Render a catalog of tools into CLI-friendly text."""

    def process(self, payload: List[ToolSpec]) -> str:
        if not payload:
            return "No maker tools found."
        lines = ["Available maker tools:"]
        lines.extend(spec.display_row() for spec in payload)
        return "\n".join(lines)


class ConsoleProducer(Producer[str]):
    """Print textual output to stdout."""

    def produce(self, result: str) -> None:
        print(result)


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


class ToolRunnerProcessor(Processor[ToolRequest, ResultEnvelope[ToolResult]]):
    """Run maker modules via direct import and call their entry point."""

    def process(self, payload: ToolRequest) -> ResultEnvelope[ToolResult]:
        try:
            mod = import_module(payload.module)
            entry: Callable[[], Any] = getattr(mod, payload.entry_point, None)
            if not callable(entry):
                return ResultEnvelope(
                    status="error",
                    payload=ToolResult(
                        module=payload.module,
                        return_code=1,
                        error=f"Module {payload.module} has no callable '{payload.entry_point}'",
                    ),
                )
            result = entry()
            rc = int(result) if isinstance(result, int) else 0
            return ResultEnvelope(
                status="success",
                payload=ToolResult(module=payload.module, return_code=rc),
            )
        except Exception as e:
            return ResultEnvelope(
                status="error",
                payload=ToolResult(
                    module=payload.module,
                    return_code=1,
                    error=str(e),
                ),
            )


class ToolResultProducer(Producer[ResultEnvelope[ToolResult]]):
    """Emit diagnostics for tool execution."""

    def produce(self, result: ResultEnvelope[ToolResult]) -> None:
        if not result.ok() and result.payload:
            if result.payload.error:
                print(f"[maker] {result.payload.module}: {result.payload.error}")
            else:
                print(f"[maker] {result.payload.module} exited with code {result.payload.return_code}")
