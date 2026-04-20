"""Tests for diagrams/mermaid.py builders (FlowchartBuilder, GanttBuilder, PieBuilder, SequenceDiagramBuilder)."""

import unittest

from diagrams.mermaid import FlowchartBuilder, GanttBuilder, PieBuilder, SequenceDiagramBuilder


class TestFlowchartBuilder(unittest.TestCase):
    def test_default_direction(self):
        fb = FlowchartBuilder()
        result = fb.render()
        self.assertIn("flowchart TB", result)

    def test_custom_direction(self):
        fb = FlowchartBuilder(direction="LR")
        result = fb.render()
        self.assertIn("flowchart LR", result)

    def test_node_default_shape(self):
        fb = FlowchartBuilder()
        fb.node("A", "Label A")
        result = fb.render()
        self.assertIn("A[Label A]", result)

    def test_node_round_shape(self):
        fb = FlowchartBuilder()
        fb.node("A", "Label A", shape="round")
        result = fb.render()
        self.assertIn("A(Label A)", result)

    def test_node_diamond_shape(self):
        fb = FlowchartBuilder()
        fb.node("A", "Decision", shape="diamond")
        result = fb.render()
        self.assertIn("A{Decision}", result)

    def test_node_circle_shape(self):
        fb = FlowchartBuilder()
        fb.node("A", "Circle", shape="circle")
        result = fb.render()
        self.assertIn("A((Circle))", result)

    def test_node_unknown_shape_uses_rect_fallback(self):
        fb = FlowchartBuilder()
        fb.node("X", "Text", shape="nonexistent")
        result = fb.render()
        self.assertIn("X[Text]", result)

    def test_edge_without_label(self):
        fb = FlowchartBuilder()
        fb.edge("A", "B")
        result = fb.render()
        self.assertIn("A --> B", result)

    def test_edge_with_label(self):
        fb = FlowchartBuilder()
        fb.edge("A", "B", label="yes")
        result = fb.render()
        self.assertIn("A -->|yes| B", result)

    def test_edge_custom_style(self):
        fb = FlowchartBuilder()
        fb.edge("A", "B", style="-.->")
        result = fb.render()
        self.assertIn("A -.-> B", result)

    def test_subgraph(self):
        fb = FlowchartBuilder()
        fb.subgraph("sg1", "My Group", "    A[Node A]")
        result = fb.render()
        self.assertIn('subgraph sg1["My Group"]', result)
        self.assertIn("end", result)

    def test_fluent_chaining(self):
        fb = FlowchartBuilder()
        result = fb.node("A", "Start").node("B", "End").edge("A", "B").render()
        self.assertIn("A[Start]", result)
        self.assertIn("B[End]", result)
        self.assertIn("A --> B", result)

    def test_all_shapes_render(self):
        for shape in ["rect", "round", "diamond", "circle", "stadium", "cylinder", "hexagon"]:
            fb = FlowchartBuilder()
            fb.node("N", "Label", shape=shape)
            result = fb.render()
            self.assertIn("flowchart", result)
            self.assertIn("N", result)


class TestGanttBuilder(unittest.TestCase):
    def test_basic_render(self):
        gb = GanttBuilder("Test Gantt")
        result = gb.render()
        self.assertIn("gantt", result)
        self.assertIn("title Test Gantt", result)
        self.assertIn("dateFormat YYYY-MM-DD", result)

    def test_custom_date_format(self):
        gb = GanttBuilder("Test", date_format="HH:mm")
        result = gb.render()
        self.assertIn("dateFormat HH:mm", result)

    def test_section_with_tasks(self):
        gb = GanttBuilder("Tasks")
        gb.section("Phase 1", ["Task A :t1, 2026-04-01, 1d", "Task B :t2, 2026-04-02, 1d"])
        result = gb.render()
        self.assertIn("section Phase 1", result)
        self.assertIn("Task A", result)
        self.assertIn("Task B", result)

    def test_multiple_sections(self):
        gb = GanttBuilder("Multi")
        gb.section("Phase 1", ["T1 :t1, 2026-04-01, 1d"])
        gb.section("Phase 2", ["T2 :t2, 2026-04-02, 1d"])
        result = gb.render()
        self.assertIn("section Phase 1", result)
        self.assertIn("section Phase 2", result)

    def test_empty_gantt(self):
        gb = GanttBuilder("Empty")
        result = gb.render()
        self.assertIn("gantt", result)
        self.assertNotIn("section", result)

    def test_fluent_chaining(self):
        result = GanttBuilder("Chain").section("S1", ["T :t, 2026-01-01, 1d"]).render()
        self.assertIn("section S1", result)


class TestPieBuilder(unittest.TestCase):
    def test_basic_render(self):
        pb = PieBuilder("My Chart")
        result = pb.render()
        self.assertIn("pie title My Chart", result)

    def test_with_slices(self):
        pb = PieBuilder("Cost")
        pb.slice("Opus $10.00", 10.0)
        pb.slice("Sonnet $5.50", 5.5)
        result = pb.render()
        self.assertIn('"Opus $10.00" : 10.0', result)
        self.assertIn('"Sonnet $5.50" : 5.5', result)

    def test_empty_pie_no_slices(self):
        pb = PieBuilder("Empty")
        result = pb.render()
        self.assertEqual(result, "pie title Empty")

    def test_fluent_chaining(self):
        result = PieBuilder("Chain").slice("A", 1.0).slice("B", 2.0).render()
        self.assertIn('"A" : 1.0', result)
        self.assertIn('"B" : 2.0', result)


class TestSequenceDiagramBuilderExtra(unittest.TestCase):
    """Additional coverage for SequenceDiagramBuilder paths not covered by existing tests."""

    def test_participant_with_alias(self):
        builder = SequenceDiagramBuilder()
        builder.participant("A", alias="Alice")
        result = builder.render()
        self.assertIn("participant A as Alice", result)

    def test_participant_without_alias(self):
        builder = SequenceDiagramBuilder()
        builder.participant("B")
        result = builder.render()
        self.assertIn("participant B", result)
        self.assertNotIn("as", result)

    def test_message_default_arrow(self):
        builder = SequenceDiagramBuilder()
        builder.message("A", "B", "hello")
        result = builder.render()
        self.assertIn("A->>B: hello", result)

    def test_message_custom_arrow(self):
        builder = SequenceDiagramBuilder()
        builder.message("A", "B", "sync", arrow="->")
        result = builder.render()
        self.assertIn("A->B: sync", result)

    def test_loop_renders(self):
        builder = SequenceDiagramBuilder()
        builder.loop("retry", ["A->>B: attempt"])
        result = builder.render()
        self.assertIn("loop retry", result)
        self.assertIn("A->>B: attempt", result)
        self.assertIn("end", result)

    def test_alt_without_else(self):
        builder = SequenceDiagramBuilder()
        builder.alt("success", ["A->>B: ok"])
        result = builder.render()
        self.assertIn("alt success", result)
        self.assertIn("A->>B: ok", result)
        self.assertIn("end", result)
        self.assertNotIn("else", result)

    def test_note_multiple_participants(self):
        builder = SequenceDiagramBuilder()
        builder.participant("A").participant("B")
        builder.note("both", over=["A", "B"])
        result = builder.render()
        self.assertIn("Note over A,B: both", result)

    def test_full_sequence_diagram(self):
        builder = SequenceDiagramBuilder()
        (builder
            .participant("Client", alias="User")
            .participant("Server")
            .message("Client", "Server", "request")
            .message("Server", "Client", "response", arrow="-->>")
         )
        result = builder.render()
        self.assertIn("sequenceDiagram", result)
        self.assertIn("participant Client as User", result)
        self.assertIn("Client->>Server: request", result)
        self.assertIn("Server-->>Client: response", result)


if __name__ == "__main__":
    unittest.main()
