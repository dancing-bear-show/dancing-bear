"""Tests for apple_music/token_helpers.py page generation."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import unittest
import urllib.parse
from pathlib import Path

from apple_music.token_helpers import build_data_url, build_html

INLINE_SCRIPT_RE = re.compile(r"<script(?![^>]*\ssrc=)[^>]*>(.*?)</script>", re.S)


def _inline_scripts(html: str) -> list[str]:
    return INLINE_SCRIPT_RE.findall(html)


class TestBuildHtml(unittest.TestCase):
    def test_developer_token_is_substituted(self):
        html = build_html("DEVTOKEN123")
        self.assertIn("DEVTOKEN123", html)
        self.assertNotIn("__DEV_TOKEN__", html)

    def test_waits_for_musickit_loaded_event(self):
        """MusicKit v3 defines window.MusicKit asynchronously; configuring early throws."""
        html = build_html("tok")
        self.assertIn("musickitloaded", html)
        configure_at = html.index("MusicKit.configure")
        self.assertLess(html.index("whenMusicKitReady"), configure_at)

    def test_posts_token_back_to_local_server(self):
        html = build_html("tok")
        self.assertIn('fetch("/token"', html)
        self.assertIn('method: "POST"', html)

    def test_reports_blocked_musickit_script(self):
        """A blocked CDN must surface on the page, not hang on the initial text."""
        html = build_html("tok")
        self.assertIn("onerror=", html)

    def test_inline_script_has_no_raw_newlines_in_string_literals(self):
        r"""Guard the template's \n escapes.

        HTML_TEMPLATE is a non-raw triple-quoted Python string, so a bare "\n"
        written for JavaScript becomes a real newline and splits the JS string
        literal across lines — a SyntaxError that kills the whole script block.
        """
        for block in _inline_scripts(build_html("tok")):
            for lineno, line in enumerate(block.splitlines(), start=1):
                # An odd number of unescaped double quotes means a literal spans lines.
                unescaped = re.sub(r"\\.", "", line)
                self.assertEqual(
                    unescaped.count('"') % 2,
                    0,
                    f"unterminated JS string literal on inline-script line {lineno}: {line!r}",
                )


@unittest.skipIf(shutil.which("node") is None, "node not available for JS syntax check")
class TestInlineScriptSyntax(unittest.TestCase):
    def test_inline_scripts_parse(self):
        """Parse the generated JS with node so a broken page fails here, not in a browser."""
        node_bin = shutil.which("node")
        blocks = _inline_scripts(build_html("tok"))
        self.assertTrue(blocks, "expected inline script blocks in the auth page")
        with tempfile.TemporaryDirectory() as tmp:
            for index, block in enumerate(blocks):
                script = Path(tmp) / f"block{index}.js"
                script.write_text(block, encoding="utf-8")
                result = subprocess.run(  # nosec B603 - fixed argv, no shell, test-only
                    [node_bin, "--check", str(script)],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(
                    result.returncode,
                    0,
                    f"inline script block {index} is not valid JavaScript:\n{result.stderr}",
                )


class TestBuildDataUrl(unittest.TestCase):
    def test_data_url_is_percent_encoded_html(self):
        url = build_data_url("tok")
        self.assertTrue(url.startswith("data:text/html,"))
        decoded = urllib.parse.unquote(url[len("data:text/html,") :])
        self.assertIn("<!doctype html>", decoded)
        self.assertIn("tok", decoded)



class TestTokenPathSharing(unittest.TestCase):
    def test_page_posts_to_the_shared_token_path(self):
        """The page and the server that accepts the POST must agree on the path."""
        from apple_music.token_helpers import TOKEN_PATH

        html = build_html("tok")
        self.assertIn(f'fetch("{TOKEN_PATH}"', html)
        self.assertNotIn("__TOKEN_PATH__", html)

    def test_data_url_also_substitutes_the_token_path(self):
        decoded = urllib.parse.unquote(build_data_url("tok")[len("data:text/html,") :])
        self.assertNotIn("__TOKEN_PATH__", decoded)

if __name__ == "__main__":
    unittest.main()
