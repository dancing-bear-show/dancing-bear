"""Tests for apple_music/user_token_cli.py uncovered branches."""

from __future__ import annotations

import unittest
import unittest.mock as mock
from io import StringIO

from apple_music import user_token_cli


class TestBuildParser(unittest.TestCase):
    def test_parser_defaults(self):
        parser = user_token_cli.build_parser()
        args = parser.parse_args([])
        self.assertEqual(args.profile, "musickit.personal")
        self.assertIsNone(args.config)
        self.assertIsNone(args.developer_token)
        self.assertFalse(args.serve)
        self.assertEqual(args.port, 0)
        self.assertFalse(args.open)
        self.assertFalse(args.no_open)

    def test_parser_flags(self):
        parser = user_token_cli.build_parser()
        args = parser.parse_args(["--serve", "--port", "8080", "--open", "--no-open"])
        self.assertTrue(args.serve)
        self.assertEqual(args.port, 8080)
        self.assertTrue(args.open)
        self.assertTrue(args.no_open)


class TestMainMissingToken(unittest.TestCase):
    def test_missing_token_returns_2(self):
        with mock.patch("apple_music.user_token_cli.load_profile", return_value=(None, {})):
            with mock.patch.dict("os.environ", {}, clear=True):
                rc = user_token_cli.main(["--profile", "musickit.personal"])
        self.assertEqual(rc, 2)

    def test_missing_token_prints_to_stderr(self):
        with mock.patch("apple_music.user_token_cli.load_profile", return_value=(None, {})):
            with mock.patch.dict("os.environ", {}, clear=True):
                buf = StringIO()
                with mock.patch("sys.stderr", buf):
                    user_token_cli.main(["--profile", "musickit.personal"])
        self.assertIn("Missing developer token", buf.getvalue())


class TestMainDataUrl(unittest.TestCase):
    def test_prints_url_without_open(self):
        with mock.patch("apple_music.user_token_cli.load_profile", return_value=(None, {})):
            with mock.patch.dict("os.environ", {"APPLE_MUSIC_DEVELOPER_TOKEN": "MYDEV"}):
                with mock.patch("apple_music.user_token_cli.build_data_url", return_value="data:text/html,test") as m_build:
                    buf = StringIO()
                    with mock.patch("sys.stdout", buf):
                        rc = user_token_cli.main([])
        self.assertEqual(rc, 0)
        m_build.assert_called_once_with("MYDEV")
        self.assertIn("data:text/html,test", buf.getvalue())

    def test_open_flag_opens_browser(self):
        with mock.patch("apple_music.user_token_cli.load_profile", return_value=(None, {})):
            with mock.patch.dict("os.environ", {"APPLE_MUSIC_DEVELOPER_TOKEN": "MYDEV"}):
                with mock.patch("apple_music.user_token_cli.build_data_url", return_value="data:text/html,test"):
                    with mock.patch("webbrowser.open") as m_open:
                        rc = user_token_cli.main(["--open"])
        self.assertEqual(rc, 0)
        m_open.assert_called_once_with("data:text/html,test")

    def test_no_open_flag_suppresses_browser(self):
        with mock.patch("apple_music.user_token_cli.load_profile", return_value=(None, {})):
            with mock.patch.dict("os.environ", {"APPLE_MUSIC_DEVELOPER_TOKEN": "MYDEV"}):
                with mock.patch("apple_music.user_token_cli.build_data_url", return_value="data:text/html,test"):
                    with mock.patch("webbrowser.open") as m_open:
                        rc = user_token_cli.main(["--open", "--no-open"])
        self.assertEqual(rc, 0)
        m_open.assert_not_called()

    def test_developer_token_from_arg_overrides_env(self):
        with mock.patch("apple_music.user_token_cli.load_profile", return_value=(None, {})):
            with mock.patch.dict("os.environ", {"APPLE_MUSIC_DEVELOPER_TOKEN": "ENV_TOKEN"}):
                with mock.patch("apple_music.user_token_cli.build_data_url", return_value="data:text/html,ok") as m_build:
                    user_token_cli.main(["--developer-token", "ARG_TOKEN"])
        m_build.assert_called_once_with("ARG_TOKEN")

    def test_developer_token_from_profile(self):
        profile_cfg = {"developer_token": "PROFILE_TOKEN"}
        with mock.patch("apple_music.user_token_cli.load_profile", return_value=(None, profile_cfg)):
            with mock.patch.dict("os.environ", {}, clear=True):
                with mock.patch("apple_music.user_token_cli.build_data_url", return_value="data:text/html,ok") as m_build:
                    rc = user_token_cli.main([])
        self.assertEqual(rc, 0)
        m_build.assert_called_once_with("PROFILE_TOKEN")


class TestMainServe(unittest.TestCase):
    def test_serve_mode_serves_and_exits(self):
        mock_server = mock.MagicMock()
        mock_server.server_address = ("127.0.0.1", 9999)
        mock_server.handle_request = mock.MagicMock()

        with mock.patch("apple_music.user_token_cli.load_profile", return_value=(None, {})):
            with mock.patch.dict("os.environ", {"APPLE_MUSIC_DEVELOPER_TOKEN": "MYDEV"}):
                with mock.patch("apple_music.user_token_cli.build_html", return_value="<html>test</html>"):
                    with mock.patch("apple_music.user_token_cli._serve_once", return_value=(mock_server, "http://127.0.0.1:9999/")) as m_serve:
                        with mock.patch("webbrowser.open") as m_open:
                            buf = StringIO()
                            with mock.patch("sys.stdout", buf):
                                rc = user_token_cli.main(["--serve"])
        self.assertEqual(rc, 0)
        m_serve.assert_called_once_with("<html>test</html>", 0)
        m_open.assert_called_once_with("http://127.0.0.1:9999/")
        mock_server.handle_request.assert_called_once()
        self.assertIn("http://127.0.0.1:9999/", buf.getvalue())

    def test_serve_no_open_skips_browser(self):
        mock_server = mock.MagicMock()
        mock_server.server_address = ("127.0.0.1", 9999)

        with mock.patch("apple_music.user_token_cli.load_profile", return_value=(None, {})):
            with mock.patch.dict("os.environ", {"APPLE_MUSIC_DEVELOPER_TOKEN": "MYDEV"}):
                with mock.patch("apple_music.user_token_cli.build_html", return_value="<html/>"):
                    with mock.patch("apple_music.user_token_cli._serve_once", return_value=(mock_server, "http://127.0.0.1:9999/")):
                        with mock.patch("webbrowser.open") as m_open:
                            rc = user_token_cli.main(["--serve", "--no-open"])
        self.assertEqual(rc, 0)
        m_open.assert_not_called()

    def test_serve_custom_port(self):
        mock_server = mock.MagicMock()
        mock_server.server_address = ("127.0.0.1", 8080)

        with mock.patch("apple_music.user_token_cli.load_profile", return_value=(None, {})):
            with mock.patch.dict("os.environ", {"APPLE_MUSIC_DEVELOPER_TOKEN": "MYDEV"}):
                with mock.patch("apple_music.user_token_cli.build_html", return_value="<html/>"):
                    with mock.patch("apple_music.user_token_cli._serve_once", return_value=(mock_server, "http://127.0.0.1:8080/")) as m_serve:
                        rc = user_token_cli.main(["--serve", "--no-open", "--port", "8080"])
        self.assertEqual(rc, 0)
        m_serve.assert_called_once_with("<html/>", 8080)


class TestServeOnce(unittest.TestCase):
    def test_serve_once_binds_and_returns_url(self):
        # Test that _serve_once creates server and returns a URL
        server, url = user_token_cli._serve_once("<html>test</html>", 0)
        try:
            self.assertIn("http://127.0.0.1:", url)
            self.assertTrue(url.endswith("/"))
        finally:
            server.server_close()


if __name__ == "__main__":
    unittest.main()
