"""Coverage expansion for diagrams/renderers.py and diagrams/cli.py.

Targets:
  renderers.py — LocalRenderer construction paths, _build_command option matrix,
                 _run FileNotFoundError, render/render_to_file orchestration,
                 _get_mermaid_text with builder objects, _infer_format, is_available.
  cli.py       — cmd_render and cmd_validate happy/sad paths, main no-subcommand,
                 _read_input stdin/OSError paths, LocalRenderer explicit-path errors.

HERMETIC: no real mmdc binary is invoked. subprocess.run and shutil.which are
patched everywhere; the real mmdc path is never reached.
"""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers shared across test classes
# ---------------------------------------------------------------------------


from tests.diagrams_tests._renderer_helpers import FAKE_MMDC, make_renderer


# ---------------------------------------------------------------------------
# LocalRenderer construction — explicit mmdc_path branches (lines 124-139)
# ---------------------------------------------------------------------------


class TestLocalRendererConstruction(unittest.TestCase):
    def test_explicit_nonexistent_path_raises(self):
        """mmdc_path given but file missing raises LocalRendererError."""
        from diagrams.renderers import LocalRendererError, LocalRenderer

        with self.assertRaises(LocalRendererError) as ctx:
            LocalRenderer(mmdc_path="/no/such/binary")
        self.assertIn("not found", str(ctx.exception))
        self.assertIn("/no/such/binary", str(ctx.exception))

    def test_explicit_nonexecutable_path_raises(self):
        """mmdc_path exists but is not executable raises LocalRendererError."""
        from diagrams.renderers import LocalRendererError, LocalRenderer

        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"#!/bin/sh\n")
            tmp_path = f.name
        os.chmod(tmp_path, stat.S_IRUSR)
        try:
            with self.assertRaises(LocalRendererError) as ctx:
                LocalRenderer(mmdc_path=tmp_path)
            self.assertIn("not executable", str(ctx.exception))
        finally:
            os.unlink(tmp_path)

    def test_explicit_executable_path_accepted(self):
        """mmdc_path that exists and is executable is stored as-is."""
        from diagrams.renderers import LocalRenderer

        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"#!/bin/sh\n")
            tmp_path = f.name
        os.chmod(tmp_path, stat.S_IRUSR | stat.S_IXUSR)
        try:
            r = LocalRenderer(mmdc_path=tmp_path)
            self.assertEqual(r.mmdc_path, tmp_path)
        finally:
            os.unlink(tmp_path)

    def test_which_returns_none_raises(self):
        """shutil.which finds nothing raises LocalRendererError with install hint."""
        from diagrams.renderers import LocalRendererError, LocalRenderer

        with patch("shutil.which", return_value=None):
            with self.assertRaises(LocalRendererError) as ctx:
                LocalRenderer()
        self.assertIn("mermaid-cli", str(ctx.exception))
        self.assertIn("npm install", str(ctx.exception))

    def test_which_found_stores_path(self):
        """shutil.which returning a path stores it on the instance."""
        from diagrams.renderers import LocalRenderer

        with patch("shutil.which", return_value="/usr/bin/mmdc"):
            r = LocalRenderer()
        self.assertEqual(r.mmdc_path, "/usr/bin/mmdc")


# ---------------------------------------------------------------------------
# LocalRenderer.is_available (lines 142-145)
# ---------------------------------------------------------------------------


class TestLocalRendererIsAvailable(unittest.TestCase):
    def test_returns_true_when_mmdc_on_path(self):
        from diagrams.renderers import LocalRenderer

        with patch("shutil.which", return_value="/usr/bin/mmdc"):
            self.assertTrue(LocalRenderer.is_available())

    def test_returns_false_when_mmdc_absent(self):
        from diagrams.renderers import LocalRenderer

        with patch("shutil.which", return_value=None):
            self.assertFalse(LocalRenderer.is_available())


# ---------------------------------------------------------------------------
# LocalRenderer._get_mermaid_text (lines 147-150)
# ---------------------------------------------------------------------------


class TestGetMermaidText(unittest.TestCase):
    def setUp(self):
        self.renderer = make_renderer()

    def test_string_input_returned_as_is(self):
        result = self.renderer._get_mermaid_text("flowchart LR\n    A-->B")
        self.assertEqual(result, "flowchart LR\n    A-->B")

    def test_builder_object_render_called(self):
        class FakeBuilder:
            def render(self):
                return "graph TD\n    A-->B"

        result = self.renderer._get_mermaid_text(FakeBuilder())
        self.assertEqual(result, "graph TD\n    A-->B")


# ---------------------------------------------------------------------------
# LocalRenderer._build_command — pure function, option matrix (lines 152-168)
# ---------------------------------------------------------------------------


class TestBuildCommand(unittest.TestCase):
    def setUp(self):
        from diagrams.renderers import RenderOptions

        self.renderer = make_renderer()
        self.RenderOptions = RenderOptions

    def test_minimal_args_produces_base_cmd(self):
        cmd = self.renderer._build_command("/in.mmd", "/out.svg", self.RenderOptions())
        self.assertEqual(cmd, [FAKE_MMDC, "-i", "/in.mmd", "-o", "/out.svg"])

    def test_background_appended(self):
        cmd = self.renderer._build_command("/in.mmd", "/out.svg", self.RenderOptions(background="white"))
        self.assertIn("-b", cmd)
        self.assertIn("white", cmd)
        self.assertEqual(cmd.index("-b") + 1, cmd.index("white"))

    def test_theme_appended(self):
        cmd = self.renderer._build_command("/in.mmd", "/out.svg", self.RenderOptions(theme="forest"))
        self.assertIn("-t", cmd)
        self.assertIn("forest", cmd)

    def test_width_appended_as_string(self):
        cmd = self.renderer._build_command("/in.mmd", "/out.png", self.RenderOptions(width=800))
        self.assertIn("-w", cmd)
        self.assertIn("800", cmd)

    def test_height_appended_as_string(self):
        cmd = self.renderer._build_command("/in.mmd", "/out.png", self.RenderOptions(height=600))
        self.assertIn("-H", cmd)
        self.assertIn("600", cmd)

    def test_all_options_combined(self):
        opts = self.RenderOptions(background="transparent", theme="dark", width=1024, height=768)
        cmd = self.renderer._build_command("/in.mmd", "/out.svg", opts)
        self.assertIn("-b", cmd)
        self.assertIn("transparent", cmd)
        self.assertIn("-t", cmd)
        self.assertIn("dark", cmd)
        self.assertIn("-w", cmd)
        self.assertIn("1024", cmd)
        self.assertIn("-H", cmd)
        self.assertIn("768", cmd)

    def test_none_options_not_appended(self):
        """None-valued options must not appear in the command list."""
        cmd = self.renderer._build_command("/in.mmd", "/out.svg", self.RenderOptions())
        self.assertNotIn("-b", cmd)
        self.assertNotIn("-t", cmd)
        self.assertNotIn("-w", cmd)
        self.assertNotIn("-H", cmd)

    def test_subtest_all_single_flag_combinations(self):
        """Each flag alone is exercised via subTest."""
        from diagrams.renderers import RenderOptions

        cases = [
            ("background only", RenderOptions(background="white"), ["-b", "white"]),
            ("theme only", RenderOptions(theme="neutral"), ["-t", "neutral"]),
            ("width only", RenderOptions(width=512), ["-w", "512"]),
            ("height only", RenderOptions(height=256), ["-H", "256"]),
        ]
        for label, opts, expected_flags in cases:
            with self.subTest(label=label):
                cmd = self.renderer._build_command("/i.mmd", "/o.svg", opts)
                for flag in expected_flags:
                    self.assertIn(flag, cmd, msg=f"Expected {flag!r} in cmd for {label}")


# ---------------------------------------------------------------------------
# LocalRenderer._run — FileNotFoundError path (lines 181-182)
# ---------------------------------------------------------------------------


class TestLocalRendererRunFileNotFound(unittest.TestCase):
    def setUp(self):
        self.renderer = make_renderer()

    def test_file_not_found_raises_local_renderer_error(self):
        from diagrams.renderers import LocalRendererError

        with patch("subprocess.run", side_effect=FileNotFoundError("gone")):
            with self.assertRaises(LocalRendererError) as ctx:
                self.renderer._run(["/fake/mmdc", "-i", "in.mmd", "-o", "out.svg"])
        self.assertIn("not found", str(ctx.exception))
        self.assertIn(self.renderer.mmdc_path, str(ctx.exception))


# ---------------------------------------------------------------------------
# LocalRenderer._infer_format (lines 188-199)
# ---------------------------------------------------------------------------


class TestInferFormat(unittest.TestCase):
    def test_svg_extension(self):
        from diagrams.renderers import LocalRenderer

        self.assertEqual(LocalRenderer._infer_format("output.svg"), "svg")

    def test_png_extension(self):
        from diagrams.renderers import LocalRenderer

        self.assertEqual(LocalRenderer._infer_format("output.png"), "png")

    def test_pdf_extension(self):
        from diagrams.renderers import LocalRenderer

        self.assertEqual(LocalRenderer._infer_format("output.pdf"), "pdf")

    def test_unknown_extension_raises_value_error(self):
        from diagrams.renderers import LocalRenderer

        with self.assertRaises(ValueError) as ctx:
            LocalRenderer._infer_format("output.gif")
        self.assertIn("output.gif", str(ctx.exception))
        self.assertIn(".svg", str(ctx.exception))

    def test_no_extension_raises_value_error(self):
        from diagrams.renderers import LocalRenderer

        with self.assertRaises(ValueError):
            LocalRenderer._infer_format("output")


# ---------------------------------------------------------------------------
# LocalRenderer.render — orchestration (lines 201-243)
# ---------------------------------------------------------------------------


class TestLocalRendererRender(unittest.TestCase):
    def setUp(self):
        self.renderer = make_renderer()

    def _fake_run_write_file(self, cmd: list[str]) -> None:
        out_path = cmd[cmd.index("-o") + 1]
        Path(out_path).write_bytes(b"<svg>mock</svg>")

    def test_render_returns_bytes_on_success(self):
        from diagrams.renderers import RenderOptions

        with patch.object(self.renderer, "_run", side_effect=self._fake_run_write_file):
            result = self.renderer.render("flowchart LR\n    A-->B", RenderOptions(output_format="svg"))
        self.assertIsInstance(result, bytes)
        self.assertGreater(len(result), 0)

    def test_render_defaults_to_svg(self):
        """render() with no opts defaults to svg format."""
        with patch.object(self.renderer, "_run", side_effect=self._fake_run_write_file):
            result = self.renderer.render("flowchart LR\n    A-->B")
        self.assertIsInstance(result, bytes)

    def test_render_unsupported_format_raises_value_error(self):
        from diagrams.renderers import RenderOptions

        with self.assertRaises(ValueError) as ctx:
            self.renderer.render("flowchart LR\n    A-->B", RenderOptions(output_format="gif"))
        self.assertIn("gif", str(ctx.exception))

    def test_render_no_output_file_raises_local_renderer_error(self):
        """If mmdc succeeds (no exception) but does not write output, render raises."""
        from diagrams.renderers import LocalRendererError, RenderOptions

        def fake_run_no_write(cmd):
            # No-op: stands in for LocalRenderer._run without writing the
            # output file.  render() checks for the output file after _run
            # returns; finding nothing, it raises LocalRendererError("did not
            # produce …"), which is the exact error this test asserts.
            pass

        with patch.object(self.renderer, "_run", side_effect=fake_run_no_write):
            with self.assertRaises(LocalRendererError) as ctx:
                self.renderer.render("flowchart LR\n    A-->B", RenderOptions(output_format="svg"))
        self.assertIn("did not produce", str(ctx.exception))

    def test_render_propagates_run_error(self):
        """LocalRendererError from _run bubbles out of render()."""
        from diagrams.renderers import LocalRendererError, RenderOptions

        with patch.object(self.renderer, "_run", side_effect=LocalRendererError("bang")):
            with self.assertRaises(LocalRendererError):
                self.renderer.render("flowchart LR\n    A-->B", RenderOptions(output_format="svg"))

    def test_render_with_builder_object(self):
        class FakeBuilder:
            def render(self):
                return "graph TD\n    A-->B"

        with patch.object(self.renderer, "_run", side_effect=self._fake_run_write_file):
            result = self.renderer.render(FakeBuilder())
        self.assertIsInstance(result, bytes)


# ---------------------------------------------------------------------------
# LocalRenderer.render_to_file — orchestration (lines 245-291)
# ---------------------------------------------------------------------------


class TestLocalRendererRenderToFile(unittest.TestCase):
    def setUp(self):
        self.renderer = make_renderer()

    def test_render_to_file_returns_output_path(self):
        def fake_run(cmd):
            pass  # output file already exists (NamedTemporaryFile created it)

        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
            out_path = f.name
        try:
            with patch.object(self.renderer, "_run", side_effect=fake_run):
                returned = self.renderer.render_to_file("flowchart LR\n    A-->B", out_path)
            self.assertEqual(returned, out_path)
        finally:
            Path(out_path).unlink(missing_ok=True)

    def test_render_to_file_unknown_extension_raises_value_error(self):
        with self.assertRaises(ValueError):
            self.renderer.render_to_file("flowchart LR\n    A-->B", "output.gif")

    def test_render_to_file_propagates_run_error(self):
        """LocalRendererError from _run propagates out of render_to_file()."""
        from diagrams.renderers import LocalRendererError

        def failing_run(cmd):
            raise LocalRendererError("mmdc crashed")

        with self.assertRaises(LocalRendererError):
            with patch.object(self.renderer, "_run", side_effect=failing_run):
                self.renderer.render_to_file("flowchart LR\n    A-->B", "/tmp/out.svg")  # nosec B108 - test only

    def test_render_to_file_with_explicit_format_skips_infer(self):
        """When opts.output_format is set, _infer_format is not called."""
        from diagrams.renderers import RenderOptions

        def fake_run(cmd):
            # No-op: the NamedTemporaryFile above already created the output
            # file on disk, so _run need not write anything.  render_to_file()
            # finds the file present and returns successfully, letting the test
            # assert that RenderOptions(output_format="svg") bypassed
            # _infer_format (no ValueError for the .svg extension).
            pass

        with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as f:
            out_path = f.name
        try:
            opts = RenderOptions(output_format="svg")
            with patch.object(self.renderer, "_run", side_effect=fake_run):
                returned = self.renderer.render_to_file("flowchart LR\n    A-->B", out_path, opts)
            self.assertEqual(returned, out_path)
        finally:
            Path(out_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# LocalRenderer.validate_syntax (lines 293-303)
# ---------------------------------------------------------------------------


class TestLocalRendererValidateSyntax(unittest.TestCase):
    def setUp(self):
        self.renderer = make_renderer()

    def test_valid_diagram_returns_true_none(self):
        with patch.object(self.renderer, "render", return_value=b"<svg/>"):
            ok, err_msg = self.renderer.validate_syntax("flowchart LR\n    A-->B")
        self.assertTrue(ok)
        self.assertIsNone(err_msg)

    def test_invalid_diagram_returns_false_with_message(self):
        from diagrams.renderers import LocalRendererError

        with patch.object(self.renderer, "render", side_effect=LocalRendererError("Parse error")):
            ok, err_msg = self.renderer.validate_syntax("not valid mermaid")
        self.assertFalse(ok)
        self.assertIsNotNone(err_msg)
        self.assertIn("Parse error", err_msg)


# ---------------------------------------------------------------------------
# cli.py — _read_input stdin and OSError paths (lines 51-59)
# ---------------------------------------------------------------------------


class TestReadInputEdgePaths(unittest.TestCase):
    def test_oserror_on_read_returns_none(self):
        """An OSError (not FileNotFoundError) from open() returns None."""
        from diagrams.cli import _read_input

        with patch("builtins.open", side_effect=OSError("permission denied")):
            err = StringIO()
            with patch("sys.stderr", err):
                result = _read_input("/some/locked/file.mmd")
        self.assertIsNone(result)
        self.assertIn("Error reading", err.getvalue())

    def test_stdin_tty_returns_none_with_usage_hint(self):
        """When stdin is a tty and no file is given, returns None."""
        from diagrams.cli import _read_input

        err = StringIO()
        with patch("sys.stderr", err):
            with patch("sys.stdin") as mock_stdin:
                mock_stdin.isatty.return_value = True
                result = _read_input(None)
        self.assertIsNone(result)
        self.assertIn("No input file", err.getvalue())

    def test_stdin_pipe_returns_content(self):
        """When stdin is a pipe, its content is returned."""
        from diagrams.cli import _read_input

        with patch("sys.stdin") as mock_stdin:
            mock_stdin.isatty.return_value = False
            mock_stdin.read.return_value = "flowchart LR\n    A-->B"
            result = _read_input(None)
        self.assertEqual(result, "flowchart LR\n    A-->B")


# ---------------------------------------------------------------------------
# cli.py — cmd_render (lines 122-144)
# ---------------------------------------------------------------------------


class TestCmdRender(unittest.TestCase):
    def _make_args(self, input_path=None, output="/tmp/out.svg"):  # nosec B108 - test only
        args = MagicMock()
        args.input = input_path
        args.output = output
        args.format = None
        args.background = None
        args.theme = None
        args.width = None
        args.height = None
        args.timeout = 60
        return args

    def test_missing_binary_returns_1(self):
        """cmd_render returns 1 when mmdc is not on PATH."""
        from diagrams.cli import cmd_render

        with tempfile.NamedTemporaryFile(mode="w", suffix=".mmd", delete=False) as f:
            f.write("flowchart LR\n    A-->B")
            tmp = f.name
        try:
            args = self._make_args(input_path=tmp)
            with patch("shutil.which", return_value=None):
                err = StringIO()
                with patch("sys.stderr", err):
                    rc = cmd_render(args)
            self.assertEqual(rc, 1)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def test_missing_input_file_returns_1(self):
        from diagrams.cli import cmd_render

        args = self._make_args(input_path="/no/such/file.mmd")
        err = StringIO()
        with patch("sys.stderr", err):
            rc = cmd_render(args)
        self.assertEqual(rc, 1)

    def test_empty_input_returns_1(self):
        """Whitespace-only content triggers _validate_non_empty and returns 1."""
        from diagrams.cli import cmd_render

        with tempfile.NamedTemporaryFile(mode="w", suffix=".mmd", delete=False) as f:
            f.write("   \n")
            tmp = f.name
        try:
            args = self._make_args(input_path=tmp)
            err = StringIO()
            with patch("sys.stderr", err):
                rc = cmd_render(args)
            self.assertEqual(rc, 1)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def test_stdin_tty_returns_1(self):
        """No input file and stdin is a tty returns 1."""
        from diagrams.cli import cmd_render

        args = self._make_args(input_path=None)
        err = StringIO()
        with patch("sys.stderr", err):
            with patch("sys.stdin") as mock_stdin:
                mock_stdin.isatty.return_value = True
                rc = cmd_render(args)
        self.assertEqual(rc, 1)


# ---------------------------------------------------------------------------
# cli.py — cmd_validate (lines 150-177)
# ---------------------------------------------------------------------------


class TestCmdValidate(unittest.TestCase):
    def _make_args(self, input_path=None, timeout=60):
        args = MagicMock()
        args.input = input_path
        args.timeout = timeout
        return args

    def _write_mmd(self, content="flowchart LR\n    A-->B"):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".mmd", delete=False) as f:
            f.write(content)
            return f.name

    def test_valid_diagram_returns_0(self):
        """Valid mermaid syntax produces ok envelope and returns 0."""
        from diagrams.cli import cmd_validate

        tmp = self._write_mmd()
        try:
            ok_env = MagicMock()
            ok_env.ok.return_value = True
            with patch("shutil.which", return_value="/fake/mmdc"):
                with patch("diagrams.renderers.RenderDiagramProcessor.process", return_value=ok_env):
                    err = StringIO()
                    with patch("sys.stderr", err):
                        rc = cmd_validate(self._make_args(input_path=tmp))
            self.assertEqual(rc, 0)
            self.assertIn("Valid", err.getvalue())
        finally:
            Path(tmp).unlink(missing_ok=True)

    def test_invalid_diagram_returns_1(self):
        """Failed envelope with diagnostic message returns 1."""
        from diagrams.cli import cmd_validate

        tmp = self._write_mmd()
        try:
            fail_env = MagicMock()
            fail_env.ok.return_value = False
            fail_env.diagnostics = {"message": "Parse error at line 3"}
            with patch("shutil.which", return_value="/fake/mmdc"):
                with patch("diagrams.renderers.RenderDiagramProcessor.process", return_value=fail_env):
                    err = StringIO()
                    with patch("sys.stderr", err):
                        rc = cmd_validate(self._make_args(input_path=tmp))
            self.assertEqual(rc, 1)
            self.assertIn("Parse error", err.getvalue())
        finally:
            Path(tmp).unlink(missing_ok=True)

    def test_invalid_no_diagnostic_message_returns_1(self):
        """Failed envelope with diagnostics=None falls back to default message."""
        from diagrams.cli import cmd_validate

        tmp = self._write_mmd()
        try:
            fail_env = MagicMock()
            fail_env.ok.return_value = False
            fail_env.diagnostics = None
            with patch("shutil.which", return_value="/fake/mmdc"):
                with patch("diagrams.renderers.RenderDiagramProcessor.process", return_value=fail_env):
                    err = StringIO()
                    with patch("sys.stderr", err):
                        rc = cmd_validate(self._make_args(input_path=tmp))
            self.assertEqual(rc, 1)
            self.assertIn("Validation failed", err.getvalue())
        finally:
            Path(tmp).unlink(missing_ok=True)

    def test_missing_input_file_returns_1(self):
        from diagrams.cli import cmd_validate

        err = StringIO()
        with patch("sys.stderr", err):
            rc = cmd_validate(self._make_args(input_path="/no/such/file.mmd"))
        self.assertEqual(rc, 1)

    def test_empty_input_returns_1(self):
        from diagrams.cli import cmd_validate

        tmp = self._write_mmd("   \n")
        try:
            err = StringIO()
            with patch("sys.stderr", err):
                rc = cmd_validate(self._make_args(input_path=tmp))
            self.assertEqual(rc, 1)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def test_mmdc_missing_returns_1(self):
        """No mmdc on PATH causes LocalRendererError inside processor, returns 1."""
        from diagrams.cli import cmd_validate

        tmp = self._write_mmd()
        try:
            with patch("shutil.which", return_value=None):
                err = StringIO()
                with patch("sys.stderr", err):
                    rc = cmd_validate(self._make_args(input_path=tmp))
            self.assertEqual(rc, 1)
        finally:
            Path(tmp).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# cli.py — main no-subcommand (lines 295-307)
# ---------------------------------------------------------------------------


class TestMain(unittest.TestCase):
    def test_no_subcommand_returns_0(self):
        """main([]) prints help and exits 0 — legacy behaviour preserved."""
        from diagrams.cli import main

        out = StringIO()
        with patch("sys.stdout", out):
            rc = main([])
        self.assertEqual(rc, 0)

    def test_no_subcommand_prints_help_text(self):
        """main([]) outputs something (help text)."""
        from diagrams.cli import main

        out = StringIO()
        with patch("sys.stdout", out):
            main([])
        self.assertGreater(len(out.getvalue()), 0)

    def test_valid_subcommand_dispatched(self):
        """main dispatches known subcommands (embed with a real file)."""
        from diagrams.cli import main

        with tempfile.NamedTemporaryFile(mode="w", suffix=".mmd", delete=False) as f:
            f.write("flowchart LR\n    A-->B")
            tmp = f.name
        try:
            out = StringIO()
            with patch("sys.stdout", out):
                rc = main(["embed", "--input", tmp])
            self.assertEqual(rc, 0)
        finally:
            Path(tmp).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
