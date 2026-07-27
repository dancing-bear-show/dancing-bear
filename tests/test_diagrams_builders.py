"""Tests for upgraded diagrams/mermaid.py builder methods."""

from __future__ import annotations

import unittest

from diagrams.mermaid import FlowchartBuilder, SequenceDiagramBuilder


class TestFlowchartBuilderWithTitle(unittest.TestCase):
    def test_with_title_adds_frontmatter(self):
        out = FlowchartBuilder().with_title("My Diagram").node("A", "Start").render()
        self.assertIn("---", out)
        self.assertIn("title: My Diagram", out)

    def test_no_title_no_frontmatter(self):
        out = FlowchartBuilder().node("A", "Start").render()
        self.assertNotIn("---", out)
        self.assertNotIn("title:", out)

    def test_title_appears_before_flowchart_line(self):
        out = FlowchartBuilder().with_title("Test").node("A", "A").render()
        lines = out.splitlines()
        # frontmatter block is first
        self.assertEqual(lines[0], "---")
        self.assertEqual(lines[1], "title: Test")
        self.assertEqual(lines[2], "---")
        self.assertIn("flowchart", lines[3])


class TestFlowchartBuilderDirection(unittest.TestCase):
    def test_default_direction_tb(self):
        out = FlowchartBuilder().render()
        self.assertIn("flowchart TB", out)

    def test_constructor_direction(self):
        out = FlowchartBuilder(direction="LR").node("A", "A").render()
        self.assertIn("flowchart LR", out)

    def test_with_direction_changes_direction(self):
        out = FlowchartBuilder().with_direction("LR").node("A", "A").render()
        self.assertIn("flowchart LR", out)

    def test_with_direction_lowercase_normalised(self):
        out = FlowchartBuilder().with_direction("lr").node("A", "A").render()
        self.assertIn("flowchart LR", out)

    def test_with_direction_invalid_raises(self):
        with self.assertRaises(ValueError):
            FlowchartBuilder().with_direction("XY")

    def test_with_direction_returns_self(self):
        b = FlowchartBuilder()
        result = b.with_direction("TB")
        self.assertIs(result, b)


class TestFlowchartBuilderStyleMethod(unittest.TestCase):
    def test_style_appended_to_output(self):
        out = (
            FlowchartBuilder()
            .node("A", "Start")
            .style("A", "fill:#f9f,stroke:#333")
            .render()
        )
        self.assertIn("style A fill:#f9f,stroke:#333", out)

    def test_multiple_styles(self):
        out = (
            FlowchartBuilder()
            .node("A", "A")
            .node("B", "B")
            .style("A", "fill:#red")
            .style("B", "fill:#blue")
            .render()
        )
        self.assertIn("style A fill:#red", out)
        self.assertIn("style B fill:#blue", out)

    def test_style_returns_self(self):
        b = FlowchartBuilder()
        result = b.style("A", "fill:#f00")
        self.assertIs(result, b)


class TestFlowchartBuilderNodeLabel(unittest.TestCase):
    def test_node_label_defaults_to_id(self):
        out = FlowchartBuilder().node("NodeA").render()
        self.assertIn("NodeA[NodeA]", out)

    def test_node_explicit_label(self):
        out = FlowchartBuilder().node("A", "My Label").render()
        self.assertIn("A[My Label]", out)

    def test_node_shape_diamond(self):
        out = FlowchartBuilder().node("D", "Decision", "diamond").render()
        self.assertIn("D{Decision}", out)


class TestSequenceDiagramBuilderWithTitle(unittest.TestCase):
    def test_with_title_adds_frontmatter(self):
        out = (
            SequenceDiagramBuilder()
            .with_title("Auth Flow")
            .participant("A", "Alice")
            .render()
        )
        self.assertIn("---", out)
        self.assertIn("title: Auth Flow", out)

    def test_title_before_sequencediagram(self):
        out = SequenceDiagramBuilder().with_title("T").render()
        lines = out.splitlines()
        self.assertEqual(lines[0], "---")
        self.assertEqual(lines[2], "---")
        self.assertIn("sequenceDiagram", lines[3])


class TestSequenceDiagramBuilderAutonumber(unittest.TestCase):
    def test_autonumber_disabled_by_default(self):
        out = SequenceDiagramBuilder().participant("A").render()
        self.assertNotIn("autonumber", out)

    def test_autonumber_enabled(self):
        out = SequenceDiagramBuilder().autonumber().participant("A").render()
        self.assertIn("autonumber", out)

    def test_autonumber_appears_after_sequencediagram(self):
        out = SequenceDiagramBuilder().autonumber().render()
        lines = out.splitlines()
        seq_idx = next(i for i, l in enumerate(lines) if "sequenceDiagram" in l)
        auto_idx = next(i for i, l in enumerate(lines) if "autonumber" in l)
        self.assertGreater(auto_idx, seq_idx)

    def test_autonumber_false_disables(self):
        out = SequenceDiagramBuilder().autonumber(False).render()
        self.assertNotIn("autonumber", out)

    def test_autonumber_returns_self(self):
        b = SequenceDiagramBuilder()
        result = b.autonumber()
        self.assertIs(result, b)


class TestSequenceDiagramBuilderRequestResponse(unittest.TestCase):
    def test_request_uses_solid_arrow(self):
        out = SequenceDiagramBuilder().request("A", "B", "GET /api").render()
        # solid arrow ->> with activation +
        self.assertIn("A->>+B: GET /api", out)

    def test_response_uses_dashed_arrow(self):
        out = SequenceDiagramBuilder().response("B", "A", "200 OK").render()
        # dashed arrow -->> followed by a separate deactivate directive targeting
        # the *sender* (B), not the destination. Mermaid's "B-->>-A" syntax
        # deactivates the destination A, which is wrong for a response; we emit
        # "deactivate B" on a separate line so the sender is deactivated instead.
        self.assertIn("B-->>A: 200 OK", out)
        self.assertIn("deactivate B", out)

    def test_request_response_returns_self(self):
        b = SequenceDiagramBuilder()
        self.assertIs(b.request("A", "B", "x"), b)
        self.assertIs(b.response("B", "A", "y"), b)

    def test_request_response_combined(self):
        out = (
            SequenceDiagramBuilder()
            .participant("C", "Client")
            .participant("S", "Server")
            .request("C", "S", "Login")
            .response("S", "C", "Token")
            .render()
        )
        self.assertIn("C->>+S: Login", out)
        # Server (src) is deactivated after the response, not the Client (dst).
        self.assertIn("S-->>C: Token", out)
        self.assertIn("deactivate S", out)


class TestSequenceDiagramBuilderActivateDeactivate(unittest.TestCase):
    def test_activate_emitted(self):
        out = SequenceDiagramBuilder().activate("Worker").render()
        self.assertIn("activate Worker", out)

    def test_deactivate_emitted(self):
        out = SequenceDiagramBuilder().deactivate("Worker").render()
        self.assertIn("deactivate Worker", out)

    def test_activate_returns_self(self):
        b = SequenceDiagramBuilder()
        self.assertIs(b.activate("X"), b)

    def test_deactivate_returns_self(self):
        b = SequenceDiagramBuilder()
        self.assertIs(b.deactivate("X"), b)


class TestSequenceDiagramBuilderActor(unittest.TestCase):
    def test_actor_keyword(self):
        out = SequenceDiagramBuilder().actor("U", "User").render()
        self.assertIn("actor U as User", out)

    def test_actor_no_alias(self):
        out = SequenceDiagramBuilder().actor("U").render()
        self.assertIn("actor U", out)
        self.assertNotIn("as", out)


class TestSequenceDiagramBuilderChaining(unittest.TestCase):
    def test_full_chain(self):
        out = (
            SequenceDiagramBuilder()
            .with_title("Full Test")
            .autonumber()
            .participant("C", "Client")
            .actor("U", "User")
            .request("C", "U", "Ping")
            .response("U", "C", "Pong")
            .activate("C")
            .deactivate("C")
            .render()
        )
        self.assertIn("title: Full Test", out)
        self.assertIn("autonumber", out)
        self.assertIn("participant C as Client", out)
        self.assertIn("actor U as User", out)
        self.assertIn("C->>+U: Ping", out)
        # User (src) is deactivated after responding; deactivate targets sender U.
        self.assertIn("U-->>C: Pong", out)
        self.assertIn("deactivate U", out)
        self.assertIn("activate C", out)
        self.assertIn("deactivate C", out)


if __name__ == "__main__":
    unittest.main()
