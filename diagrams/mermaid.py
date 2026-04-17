"""Mermaid diagram builders — fluent API for generating .mmd text."""

from __future__ import annotations

from typing import Optional


class FlowchartBuilder:
    """Build Mermaid flowchart diagrams with a fluent API.

    Directions: TB (top-bottom), LR (left-right), TD, BT, RL.
    """

    SHAPES = {
        "rect": ("[", "]"),
        "round": ("(", ")"),
        "diamond": ("{", "}"),
        "circle": ("((", "))"),
        "stadium": ("([", "])"),
        "cylinder": ("[(", ")]"),
        "hexagon": ("{{", "}}"),
    }

    def __init__(self, direction: str = "TB") -> None:
        self.direction = direction
        self._nodes: list[str] = []
        self._edges: list[str] = []
        self._subgraphs: list[str] = []

    def node(self, node_id: str, label: str, shape: str = "rect") -> FlowchartBuilder:
        left, right = self.SHAPES.get(shape, ("[", "]"))
        self._nodes.append(f"    {node_id}{left}{label}{right}")
        return self

    def edge(self, src: str, dst: str, label: str = "",
             style: str = "-->") -> FlowchartBuilder:
        if label:
            self._edges.append(f"    {src} {style}|{label}| {dst}")
        else:
            self._edges.append(f"    {src} {style} {dst}")
        return self

    def subgraph(self, sub_id: str, label: str, body: str) -> FlowchartBuilder:
        self._subgraphs.append(
            f"    subgraph {sub_id}[\"{label}\"]\n{body}\n    end"
        )
        return self

    def render(self) -> str:
        parts = [f"flowchart {self.direction}"]
        parts.extend(self._nodes)
        parts.extend(self._subgraphs)
        parts.extend(self._edges)
        return "\n".join(parts)


class SequenceDiagramBuilder:
    """Build Mermaid sequence diagrams with a fluent API."""

    def __init__(self) -> None:
        self._participants: list[str] = []
        self._steps: list[str] = []

    def participant(self, name: str, alias: str = "") -> SequenceDiagramBuilder:
        if alias:
            self._participants.append(f"    participant {alias} as {name}")
        else:
            self._participants.append(f"    participant {name}")
        return self

    def message(self, src: str, dst: str, text: str,
                arrow: str = "->>") -> SequenceDiagramBuilder:
        self._steps.append(f"    {src}{arrow}{dst}: {text}")
        return self

    def note(self, text: str,
             over: Optional[list[str]] = None) -> SequenceDiagramBuilder:
        if not over:
            raise ValueError(
                "SequenceDiagramBuilder.note() requires at least one participant in 'over'."
            )
        loc = f"over {','.join(over)}"
        self._steps.append(f"    Note {loc}: {text}")
        return self

    def loop(self, label: str, body: list[str]) -> SequenceDiagramBuilder:
        self._steps.append(f"    loop {label}")
        self._steps.extend(f"        {s}" for s in body)
        self._steps.append("    end")
        return self

    def alt(self, condition: str, then_body: list[str],
            else_body: Optional[list[str]] = None,
            else_label: str = "else") -> SequenceDiagramBuilder:
        self._steps.append(f"    alt {condition}")
        self._steps.extend(f"        {s}" for s in then_body)
        if else_body:
            self._steps.append(f"    else {else_label}")
            self._steps.extend(f"        {s}" for s in else_body)
        self._steps.append("    end")
        return self

    def render(self) -> str:
        parts = ["sequenceDiagram"]
        parts.extend(self._participants)
        parts.extend(self._steps)
        return "\n".join(parts)


class GanttBuilder:
    """Build Mermaid Gantt diagrams."""

    def __init__(self, title: str, date_format: str = "YYYY-MM-DD") -> None:
        self.title = title
        self.date_format = date_format
        self._sections: list[str] = []

    def section(self, name: str, tasks: list[str]) -> GanttBuilder:
        self._sections.append(f"    section {name}")
        self._sections.extend(f"        {t}" for t in tasks)
        return self

    def render(self) -> str:
        parts = [
            "gantt",
            f"    title {self.title}",
            f"    dateFormat {self.date_format}",
        ]
        parts.extend(self._sections)
        return "\n".join(parts)


class PieBuilder:
    """Build Mermaid pie charts."""

    def __init__(self, title: str) -> None:
        self.title = title
        self._slices: list[str] = []

    def slice(self, label: str, value: float) -> PieBuilder:
        self._slices.append(f'    "{label}" : {value}')
        return self

    def render(self) -> str:
        parts = [f"pie title {self.title}"]
        parts.extend(self._slices)
        return "\n".join(parts)
