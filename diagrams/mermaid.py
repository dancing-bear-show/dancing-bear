"""Mermaid diagram builders — fluent API for generating .mmd text."""

from __future__ import annotations

_INDENT_END = "    end"


class FlowchartBuilder:
    """Build Mermaid flowchart diagrams with a fluent API.

    Directions: TB (top-bottom), LR (left-right), TD, BT, RL.
    """

    SHAPES: dict[str, tuple[str, str]] = {
        "rect": ("[", "]"),
        "round": ("(", ")"),
        "stadium": ("([", "])"),
        "subroutine": ("[[", "]]"),
        "cylinder": ("[(", ")]"),
        "circle": ("((", "))"),
        "asymmetric": (">", "]"),
        "rhombus": ("{", "}"),
        "diamond": ("{", "}"),
        "hexagon": ("{{", "}}"),
        "parallelogram": ("[/", "/]"),
        "parallelogram_alt": ("[\\", "\\]"),
        "trapezoid": ("[/", "\\]"),
        "trapezoid_alt": ("[\\", "/]"),
        "double_circle": ("(((", ")))"),
    }

    _VALID_DIRECTIONS: frozenset[str] = frozenset({"TB", "LR", "BT", "RL", "TD"})

    def __init__(self, direction: str = "TB") -> None:
        self._direction = direction.upper()
        self._title: str | None = None
        self._nodes: list[tuple[str, str, str]] = []  # (id, label, shape)
        self._edges: list[tuple[str, str, str, str]] = []  # (src, dst, label, style)
        self._subgraphs: list[tuple[str, str, list[str]]] = []  # (id, label, [node_ids])
        self._styles: list[str] = []  # raw style lines

    def with_title(self, title: str) -> FlowchartBuilder:
        """Set the diagram title (rendered as YAML front-matter)."""
        self._title = title
        return self

    def with_direction(self, direction: str) -> FlowchartBuilder:
        """Set the flowchart direction (TB, LR, BT, RL, TD)."""
        upper = direction.upper()
        if upper not in self._VALID_DIRECTIONS:
            raise ValueError(
                f"Invalid direction {direction!r}. Must be one of: {sorted(self._VALID_DIRECTIONS)}"
            )
        self._direction = upper
        return self

    def node(self, node_id: str, label: str | None = None, shape: str = "rect") -> FlowchartBuilder:
        """Add a node. label defaults to node_id when not provided."""
        self._nodes.append((node_id, label if label is not None else node_id, shape))
        return self

    def style(self, node_id: str, css: str) -> FlowchartBuilder:
        """Add a style directive for a node, e.g. style A fill:#f9f,stroke:#333."""
        self._styles.append(f"    style {node_id} {css}")
        return self

    def edge(
        self,
        src: str,
        dst: str,
        label: str = "",
        style: str = "-->",
    ) -> FlowchartBuilder:
        """Add an edge between two nodes."""
        self._edges.append((src, dst, label, style))
        return self

    def subgraph(self, sub_id: str, label: str, body: str = "") -> FlowchartBuilder:
        """Add a subgraph. body is raw indented mermaid lines (legacy compat).

        When body is provided, it is emitted verbatim. When absent, pass
        node_ids via the node_ids kwarg (not available in legacy signature).
        """
        # Store as list-of-ids = [] plus raw body in label field using separator sentinel
        # to preserve backwards compat while supporting new node-based subgraph too.
        self._subgraphs.append((sub_id, label, [body] if body else []))
        return self

    def _subgraph_node_ids(self) -> set[str]:
        """Collect node IDs that belong to any subgraph (non-legacy items)."""
        ids: set[str] = set()
        for _, _, items in self._subgraphs:
            for item in items:
                if not item.startswith("    "):
                    ids.add(item)
        return ids

    def _render_subgraph_item(self, item: str, lines: list[str]) -> None:
        """Append a single subgraph item (raw line or node lookup) to lines."""
        if item.startswith("    "):
            lines.append(item)  # raw body line (legacy)
            return
        for nid, nlabel, nshape in self._nodes:
            if nid == item:
                left, right = self.SHAPES.get(nshape, ("[", "]"))
                lines.append(f"        {nid}{left}{nlabel}{right}")
                break

    def _render_subgraphs(self, lines: list[str]) -> None:
        """Append subgraph blocks to lines."""
        for sub_id, label, node_ids_or_body in self._subgraphs:
            lines.append(f'    subgraph {sub_id}["{label}"]')
            for item in node_ids_or_body:
                self._render_subgraph_item(item, lines)
            lines.append(_INDENT_END)

    def _render_edges(self, lines: list[str]) -> None:
        """Append edge lines to lines."""
        for src, dst, label, arrow in self._edges:
            if label:
                lines.append(f"    {src} {arrow}|{label}| {dst}")
            else:
                lines.append(f"    {src} {arrow} {dst}")

    def render(self) -> str:
        """Render the flowchart as Mermaid markdown text."""
        lines: list[str] = []

        if self._title:
            lines.append("---")
            lines.append(f"title: {self._title}")
            lines.append("---")

        lines.append(f"flowchart {self._direction}")

        subgraph_ids = self._subgraph_node_ids()
        for node_id, label, shape in self._nodes:
            if node_id not in subgraph_ids:
                left, right = self.SHAPES.get(shape, ("[", "]"))
                lines.append(f"    {node_id}{left}{label}{right}")

        self._render_subgraphs(lines)
        self._render_edges(lines)
        lines.extend(self._styles)

        return "\n".join(lines)


class SequenceDiagramBuilder:
    """Build Mermaid sequence diagrams with a fluent API."""

    def __init__(self) -> None:
        self._title: str | None = None
        self._autonumber: bool = False
        self._participants: list[str] = []
        self._steps: list[str] = []

    def with_title(self, title: str) -> SequenceDiagramBuilder:
        """Set the diagram title (rendered as YAML front-matter)."""
        self._title = title
        return self

    def autonumber(self, enabled: bool = True) -> SequenceDiagramBuilder:
        """Enable or disable auto-numbering of messages."""
        self._autonumber = enabled
        return self

    def participant(self, name: str, alias: str = "", actor: bool = False) -> SequenceDiagramBuilder:
        """Add a participant or actor. alias is the display label."""
        keyword = "actor" if actor else "participant"
        if alias:
            self._participants.append(f"    {keyword} {name} as {alias}")
        else:
            self._participants.append(f"    {keyword} {name}")
        return self

    def actor(self, name: str, alias: str = "") -> SequenceDiagramBuilder:
        """Add an actor (stick-figure) participant."""
        return self.participant(name, alias, actor=True)

    def message(
        self,
        src: str,
        dst: str,
        text: str,
        arrow: str = "->>",
        activate: bool = False,
        deactivate: bool = False,
    ) -> SequenceDiagramBuilder:
        """Add a message between participants."""
        suffix = ""
        if activate:
            suffix = "+"
        elif deactivate:
            suffix = "-"
        self._steps.append(f"    {src}{arrow}{suffix}{dst}: {text}")
        return self

    def request(self, src: str, dst: str, text: str) -> SequenceDiagramBuilder:
        """Add a request message (solid arrow ->>  with receiver activation)."""
        return self.message(src, dst, text, "->>", activate=True)

    def response(self, src: str, dst: str, text: str) -> SequenceDiagramBuilder:
        """Add a response message (dashed arrow -->>  with sender deactivation)."""
        return self.message(src, dst, text, "-->>", deactivate=True)

    def activate(self, participant: str) -> SequenceDiagramBuilder:
        """Emit an explicit activate directive for a participant."""
        self._steps.append(f"    activate {participant}")
        return self

    def deactivate(self, participant: str) -> SequenceDiagramBuilder:
        """Emit an explicit deactivate directive for a participant."""
        self._steps.append(f"    deactivate {participant}")
        return self

    def note(self, text: str, over: list[str] | None = None) -> SequenceDiagramBuilder:
        """Add a note over one or more participants."""
        if not over:
            raise ValueError(
                "SequenceDiagramBuilder.note() requires at least one participant in 'over'."
            )
        loc = f"over {','.join(over)}"
        self._steps.append(f"    Note {loc}: {text}")
        return self

    def loop(self, label: str, body: list[str]) -> SequenceDiagramBuilder:
        """Add a loop block."""
        self._steps.append(f"    loop {label}")
        self._steps.extend(f"        {s}" for s in body)
        self._steps.append(_INDENT_END)
        return self

    def alt(
        self,
        condition: str,
        then_body: list[str],
        else_body: list[str] | None = None,
        else_label: str = "else",
    ) -> SequenceDiagramBuilder:
        """Add an alt/else block."""
        self._steps.append(f"    alt {condition}")
        self._steps.extend(f"        {s}" for s in then_body)
        if else_body:
            self._steps.append(f"    else {else_label}")
            self._steps.extend(f"        {s}" for s in else_body)
        self._steps.append(_INDENT_END)
        return self

    def render(self) -> str:
        """Render the sequence diagram as Mermaid markdown text."""
        lines: list[str] = []

        if self._title:
            lines.append("---")
            lines.append(f"title: {self._title}")
            lines.append("---")

        lines.append("sequenceDiagram")

        if self._autonumber:
            lines.append("    autonumber")

        lines.extend(self._participants)
        lines.extend(self._steps)
        return "\n".join(lines)


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
