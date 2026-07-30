"""YAML-to-Mermaid converters — flowchart and sequence diagram builders."""

from __future__ import annotations

import sys


def _load_yaml(content: str) -> dict | None:
    try:
        import yaml  # noqa: PLC0415
        return yaml.safe_load(content)
    except ImportError:
        import json
        try:
            return json.loads(content)
        except Exception as e:
            print(f"Error parsing input: {e}", file=sys.stderr)
            return None
    except Exception as e:
        print(f"Error parsing YAML: {e}", file=sys.stderr)
        return None


def _build_flowchart_from_spec(spec: dict) -> str:
    from .mermaid import FlowchartBuilder

    builder = FlowchartBuilder()
    if "direction" in spec:
        builder.with_direction(spec["direction"])
    if "title" in spec:
        builder.with_title(spec["title"])
    for node_spec in spec.get("nodes", []):
        builder.node(
            node_id=node_spec["id"],
            label=node_spec.get("label"),
            shape=node_spec.get("shape", "rect"),
        )
    for edge_spec in spec.get("edges", []):
        builder.edge(
            src=edge_spec["source"],
            dst=edge_spec["target"],
            label=edge_spec.get("label", ""),
            style=edge_spec.get("style", "-->"),
        )
    return builder.render()


def _build_sequence_from_spec(spec: dict) -> str:
    from .mermaid import SequenceDiagramBuilder

    builder = SequenceDiagramBuilder()
    if "title" in spec:
        builder.with_title(spec["title"])
    if spec.get("autonumber"):
        builder.autonumber()
    for p_spec in spec.get("participants", []):
        builder.participant(
            name=p_spec["id"],
            alias=p_spec.get("label", ""),
            actor=p_spec.get("actor", False),
        )
    for m_spec in spec.get("messages", []):
        builder.message(
            src=m_spec["sender"],
            dst=m_spec["receiver"],
            text=m_spec["text"],
            arrow=m_spec.get("arrow_type", "->>"),
            activate=m_spec.get("activate", False),
            deactivate=m_spec.get("deactivate", False),
        )
    return builder.render()


def _convert_yaml_spec(spec: dict) -> tuple[str | None, int]:
    """Convert a YAML spec dict to mermaid text. Returns (text, exit_code)."""
    if not isinstance(spec, dict):
        print("Error: YAML spec must be a dictionary", file=sys.stderr)
        return None, 1

    diagram_type = spec.get("type", "flowchart").lower()
    try:
        if diagram_type in ("flowchart", "graph"):
            return _build_flowchart_from_spec(spec), 0
        elif diagram_type in ("sequence", "sequencediagram"):
            return _build_sequence_from_spec(spec), 0
        else:
            print(f"Error: Unsupported diagram type {diagram_type!r}", file=sys.stderr)
            print("Supported types: flowchart, sequence", file=sys.stderr)
            return None, 1
    except KeyError as e:
        print(f"Error: Missing required field {e} in spec", file=sys.stderr)
        return None, 1
    except Exception as e:
        print(f"Error building diagram: {e}", file=sys.stderr)
        return None, 1
