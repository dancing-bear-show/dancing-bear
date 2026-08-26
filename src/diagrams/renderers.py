"""Mermaid diagram renderers.

TextRenderer: zero-dependency plain text output.
LocalRenderer: renders via local mmdc CLI (requires @mermaid-js/mermaid-cli).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from core.cli_errors import CLIError, ExitCode
from core.pipeline import BaseProducer, SafeProcessor


@dataclass(frozen=True)
class RenderOptions:
    """Visual rendering options shared by render/render_to_file/_build_command.

    output_format: format override; inferred from output extension when None.
    background: Background color (e.g. ``"white"``, ``"transparent"``).
    theme: Mermaid theme (``"default"``, ``"forest"``, ``"dark"``, ``"neutral"``).
    width: Output width in pixels (PNG only).
    height: Output height in pixels (PNG only).
    """

    output_format: str | None = None
    background: str | None = None
    theme: str | None = None
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True)
class RenderRequest:
    """Request to render a Mermaid diagram to a file.

    output_format: format override; inferred from output extension when None.
    """

    source: str
    output: str
    output_format: str | None = None
    background: str | None = None
    theme: str | None = None
    width: int | None = None
    height: int | None = None
    timeout: int = 60


@dataclass(frozen=True)
class RenderResult:
    """Result of a successful diagram render."""

    output_path: str
    size_bytes: int


class TextRenderer:
    """Render Mermaid diagrams as plain text or embedded code fences.

    No external dependencies — always importable.
    """

    def render(self, diagram: object) -> str:
        """Render a diagram builder or raw string to Mermaid text.

        Args:
            diagram: An object with a ``render()`` method, or a raw string.

        Returns:
            Mermaid markdown text.
        """
        if isinstance(diagram, str):
            return diagram
        return diagram.render()  # type: ignore[union-attr]

    def render_embedded(self, diagram: object) -> str:
        """Render wrapped in a ```mermaid code fence.

        Args:
            diagram: An object with a ``render()`` method, or a raw string.

        Returns:
            Mermaid text wrapped in a triple-backtick mermaid fence.
        """
        content = self.render(diagram)
        return f"```mermaid\n{content}\n```"


class LocalRendererError(CLIError):
    """Error raised by LocalRenderer when mmdc is unavailable or fails."""

    def __init__(self, message: str) -> None:
        super().__init__(message=message, code=ExitCode.ERROR)


class LocalRenderer:
    """Render Mermaid diagrams via the locally installed mmdc CLI.

    Requires: ``npm install -g @mermaid-js/mermaid-cli``

    All subprocess and shutil imports are deferred to call time so this
    class is always importable even when mmdc is not installed.

    Args:
        mmdc_path: Explicit path to mmdc binary. Auto-detected via PATH if None.
        timeout: Command timeout in seconds (default: 60).

    Raises:
        LocalRendererError: On construction if mmdc cannot be located.
    """

    def __init__(
        self,
        mmdc_path: str | None = None,
        timeout: int = 60,
    ) -> None:
        import os
        import shutil

        self.timeout = timeout

        if mmdc_path:
            import pathlib
            p = pathlib.Path(mmdc_path)
            if not p.exists():
                raise LocalRendererError(f"mmdc not found at: {mmdc_path}")
            if not os.access(mmdc_path, os.X_OK):
                raise LocalRendererError(f"mmdc not executable: {mmdc_path}")
            self.mmdc_path: str = mmdc_path
        else:
            found = shutil.which("mmdc")
            if not found:
                raise LocalRendererError(
                    "mermaid-cli (mmdc) not found. "
                    "Install with: npm install -g @mermaid-js/mermaid-cli"
                )
            self.mmdc_path = found

    @staticmethod
    def is_available() -> bool:
        """Return True if mmdc is on PATH."""
        import shutil
        return shutil.which("mmdc") is not None

    def _get_mermaid_text(self, diagram: object) -> str:
        if isinstance(diagram, str):
            return diagram
        return diagram.render()  # type: ignore[union-attr]

    def _build_command(
        self,
        input_path: str,
        output_path: str,
        opts: RenderOptions,
    ) -> list[str]:
        """Build the mmdc command list from input/output paths and render options."""
        cmd = [self.mmdc_path, "-i", input_path, "-o", output_path]
        if opts.background:
            cmd.extend(["-b", opts.background])
        if opts.theme:
            cmd.extend(["-t", opts.theme])
        if opts.width:
            cmd.extend(["-w", str(opts.width)])
        if opts.height:
            cmd.extend(["-H", str(opts.height)])
        return cmd

    def _run(self, cmd: list[str]) -> None:
        import subprocess  # nosec B404 - subprocess imported deliberately; individual call sites carry their own B602/B603 review
        try:
            result = subprocess.run(  # nosec B603 B607 - mmdc_path resolved via shutil.which or validated on construction
                cmd,
                capture_output=True,
                timeout=self.timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as e:
            raise LocalRendererError(f"mmdc timed out after {self.timeout}s") from e
        except FileNotFoundError as e:
            raise LocalRendererError(f"mmdc not found at {self.mmdc_path}") from e

        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            raise LocalRendererError(f"mmdc failed: {stderr}")

    @staticmethod
    def _infer_format(output_path: str) -> str:
        if output_path.endswith(".svg"):
            return "svg"
        if output_path.endswith(".png"):
            return "png"
        if output_path.endswith(".pdf"):
            return "pdf"
        raise ValueError(
            f"Cannot infer format from {output_path!r}. "
            "Use --format or a recognised extension (.svg, .png, .pdf)."
        )

    def render(
        self,
        diagram: object,
        opts: RenderOptions | None = None,
    ) -> bytes:
        """Render a diagram to bytes.

        Args:
            diagram: Builder, model, or raw mermaid string.
            opts: Visual rendering options (format, background, theme, width, height).
                  Defaults to SVG with no background, theme, or size override.

        Returns:
            Rendered diagram bytes.

        Raises:
            LocalRendererError: If rendering fails.
        """
        import pathlib
        import tempfile

        opts = opts or RenderOptions()
        output_format = opts.output_format or "svg"

        mermaid_text = self._get_mermaid_text(diagram)
        if opts.theme == "dark":
            from .dark_mode import apply_dark_mode_fixes
            mermaid_text = apply_dark_mode_fixes(mermaid_text)

        if output_format not in {"svg", "png", "pdf"}:
            raise ValueError(f"Unsupported format {output_format!r}")

        with tempfile.TemporaryDirectory() as tmpdir:
            inp = pathlib.Path(tmpdir) / "input.mmd"
            out = pathlib.Path(tmpdir) / f"output.{output_format}"
            inp.write_text(mermaid_text)

            cmd = self._build_command(str(inp), str(out), opts)
            self._run(cmd)

            if not out.exists():
                raise LocalRendererError("mmdc did not produce output file")
            return out.read_bytes()

    def render_to_file(
        self,
        diagram: object,
        output_path: str,
        opts: RenderOptions | None = None,
    ) -> str:
        """Render a diagram directly to a file on disk.

        Args:
            diagram: Builder, model, or raw mermaid string.
            output_path: Destination file path.
            opts: Visual rendering options (format, background, theme, width, height).
                  output_format is inferred from the output extension when None.

        Returns:
            The output path.

        Raises:
            LocalRendererError: If rendering fails.
            ValueError: If the output format cannot be determined.
        """
        import pathlib
        import tempfile

        opts = opts or RenderOptions()
        # Validate the target format up front (raises ValueError on an unknown
        # extension); mmdc derives the actual output format from output_path's
        # extension, so _build_command only needs the visual options
        # (background/theme/size) carried by opts.
        if opts.output_format is None:
            self._infer_format(output_path)

        mermaid_text = self._get_mermaid_text(diagram)
        if opts.theme == "dark":
            from .dark_mode import apply_dark_mode_fixes
            mermaid_text = apply_dark_mode_fixes(mermaid_text)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".mmd", delete=False) as f:
            f.write(mermaid_text)
            tmp_input = f.name

        try:
            cmd = self._build_command(tmp_input, output_path, opts)
            self._run(cmd)
            return output_path
        finally:
            pathlib.Path(tmp_input).unlink(missing_ok=True)

    def validate_syntax(self, diagram: object) -> tuple[bool, str | None]:
        """Validate Mermaid syntax by attempting an SVG render.

        Returns:
            ``(True, None)`` on success; ``(False, error_message)`` on failure.
        """
        try:
            self.render(diagram, RenderOptions(output_format="svg"))
            return True, None
        except LocalRendererError as e:
            return False, str(e)


# ── Pipeline classes ──────────────────────────────────────────────────────────


class RenderDiagramProcessor(SafeProcessor[RenderRequest, RenderResult]):
    """Renders a Mermaid diagram.

    Wraps LocalRenderer.render_to_file() (which calls _run()) in the
    SafeProcessor contract so cmd_render and cmd_validate can call via
    run_pipeline().  LocalRenderer itself is not renamed — it is an
    implementation detail, not a pipeline class.
    """

    def _process_safe(self, payload: RenderRequest) -> RenderResult:
        """Render diagram and return RenderResult; raises LocalRendererError on failure.

        output_format=None defers format inference to LocalRenderer._infer_format().
        """
        renderer = LocalRenderer(timeout=payload.timeout)
        opts = RenderOptions(
            output_format=payload.output_format,
            background=payload.background,
            theme=payload.theme,
            width=payload.width,
            height=payload.height,
        )
        renderer.render_to_file(payload.source, payload.output, opts)
        size = Path(payload.output).stat().st_size
        return RenderResult(output_path=payload.output, size_bytes=size)


class RenderDiagramProducer(BaseProducer):
    """Emits render result via OutputWriter."""

    def _produce_success(self, payload: RenderResult, diagnostics: dict | None = None) -> None:
        """Emit success message with output path."""
        self._writer.print(f"Rendered to: {payload.output_path}")
