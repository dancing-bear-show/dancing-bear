"""Mermaid diagram renderers.

TextRenderer: zero-dependency plain text output.
LocalRenderer: renders via local mmdc CLI (requires @mermaid-js/mermaid-cli).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RenderConfig:
    """Rendering options shared across LocalRenderer methods.

    output_format: Target format ("svg", "png", "pdf"). None lets render_to_file
        infer the format from the output file extension; render() defaults to "svg".
    """

    output_format: str | None = None
    background: str | None = None
    theme: str | None = None
    width: int | None = None
    height: int | None = None


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


class LocalRendererError(Exception):
    """Error raised by LocalRenderer when mmdc is unavailable or fails."""


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
        config: RenderConfig,
    ) -> list[str]:
        cmd = [self.mmdc_path, "-i", input_path, "-o", output_path]
        if config.background:
            cmd.extend(["-b", config.background])
        if config.theme:
            cmd.extend(["-t", config.theme])
        if config.width:
            cmd.extend(["-w", str(config.width)])
        if config.height:
            cmd.extend(["-H", str(config.height)])
        return cmd

    def _run(self, cmd: list[str]) -> None:
        import subprocess
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
        config: RenderConfig = RenderConfig(),
    ) -> bytes:
        """Render a diagram to bytes.

        Args:
            diagram: Builder, model, or raw mermaid string.
            config: Rendering options (format, background, theme, dimensions).
                    config.output_format defaults to "svg" when None.

        Returns:
            Rendered diagram bytes.

        Raises:
            LocalRendererError: If rendering fails.
        """
        import pathlib
        import tempfile

        output_format = config.output_format or "svg"

        mermaid_text = self._get_mermaid_text(diagram)
        if config.theme == "dark":
            from .dark_mode import apply_dark_mode_fixes
            mermaid_text = apply_dark_mode_fixes(mermaid_text)

        if output_format not in {"svg", "png", "pdf"}:
            raise ValueError(f"Unsupported format {output_format!r}")

        with tempfile.TemporaryDirectory() as tmpdir:
            inp = pathlib.Path(tmpdir) / "input.mmd"
            out = pathlib.Path(tmpdir) / f"output.{output_format}"
            inp.write_text(mermaid_text)

            cmd = self._build_command(str(inp), str(out), config)
            self._run(cmd)

            if not out.exists():
                raise LocalRendererError("mmdc did not produce output file")
            return out.read_bytes()

    def render_to_file(
        self,
        diagram: object,
        output_path: str,
        config: RenderConfig = RenderConfig(),
    ) -> str:
        """Render a diagram directly to a file on disk.

        Args:
            diagram: Builder, model, or raw mermaid string.
            output_path: Destination file path.
            config: Rendering options. config.output_format overrides the
                    format inferred from output_path's extension; if
                    output_path lacks a matching extension, it is appended.

        Returns:
            The output path.

        Raises:
            LocalRendererError: If rendering fails.
            ValueError: If the output format cannot be determined.
        """
        import pathlib
        import tempfile

        if config.output_format is not None:
            if config.output_format not in {"svg", "png", "pdf"}:
                raise ValueError(f"Unsupported format {config.output_format!r}")
            if not output_path.endswith(f".{config.output_format}"):
                output_path = f"{output_path}.{config.output_format}"
        else:
            self._infer_format(output_path)  # validate extension; raises ValueError if unsupported

        mermaid_text = self._get_mermaid_text(diagram)
        if config.theme == "dark":
            from .dark_mode import apply_dark_mode_fixes
            mermaid_text = apply_dark_mode_fixes(mermaid_text)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".mmd", delete=False) as f:
            f.write(mermaid_text)
            tmp_input = f.name

        try:
            cmd = self._build_command(tmp_input, output_path, config)
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
            self.render(diagram, RenderConfig(output_format="svg"))
            return True, None
        except LocalRendererError as e:
            return False, str(e)
