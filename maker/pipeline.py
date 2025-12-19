from __future__ import annotations

"""Maker pipeline primitives built on shared core scaffolding."""

from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
from typing import List

from core.pipeline import Consumer, Processor, Producer, ResultEnvelope


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


@dataclass
class ToolRequest:
    module: str
    args: List[str]


class ToolRequestConsumer(Consumer[ToolRequest]):
    """Return the pre-parsed ToolRequest (keeps pipeline structure uniform)."""

    def __init__(self, request: ToolRequest) -> None:
        self._request = request

    def consume(self) -> ToolRequest:
        return self._request


class ModuleRunnerProcessor(Processor[ToolRequest, ResultEnvelope[int]]):
    """Run maker modules via `python -m` and capture their exit status."""

    def process(self, payload: ToolRequest) -> ResultEnvelope[int]:
        cmd = [sys.executable, "-m", payload.module, *payload.args]
        rc = subprocess.call(cmd)
        status = "success" if rc == 0 else "error"
        return ResultEnvelope(status=status, payload=rc)


class ModuleResultProducer(Producer[ResultEnvelope[int]]):
    """Emit diagnostics for module execution."""

    def produce(self, result: ResultEnvelope[int]) -> None:
        if not result.ok():
            code = result.payload if result.payload is not None else "unknown"
            print(f"[maker] tool exited with code {code}")
