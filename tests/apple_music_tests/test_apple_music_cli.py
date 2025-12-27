import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from apple_music import __main__ as cli
from apple_music.client import AppleMusicClient
from apple_music import token_helpers, user_token_cli

from tests.apple_music_tests.fixtures import (
    FakeAppleMusicClient,
    FakeResponse,
    FakeSession,
    make_playlist,
    make_track,
)


class AppleMusicClientTests(unittest.TestCase):
    def test_paginates_and_limits(self):
        responses = [
            FakeResponse({"data": [{"id": "1"}, {"id": "2"}], "next": "v1/me/library/playlists?offset=2"}),
            FakeResponse({"data": [{"id": "3"}]}),
        ]
        session = FakeSession(responses)
        client = AppleMusicClient("dev", "user", session=session)
        items = client.list_library_playlists(limit=3)
        self.assertEqual([i["id"] for i in items], ["1", "2", "3"])
        self.assertEqual(len(session.calls), 2)


class AppleMusicCLITests(unittest.TestCase):
    def test_cli_exports_using_credentials_file(self):
        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "credentials.ini"
            cfg.write_text(
                "[musickit.personal]\n"
                "developer_token = DEV_TOKEN\n"
                "user_token = USER_TOKEN\n"
            )
            out_path = Path(td) / "out.json"

            stub = FakeAppleMusicClient(
                playlists=[make_playlist("1", "My Mix")],
                tracks=[make_track("t1", "Song", "Artist", "Album")],
            )

            with mock.patch("apple_music.cli.AppleMusicClient", return_value=stub):
                rc = cli.main(["export", "--config", str(cfg), "--out", str(out_path)])
            self.assertEqual(rc, 0)
            data = json.loads(out_path.read_text())
            self.assertEqual(data["playlists"][0]["name"], "My Mix")
            self.assertEqual(data["playlists"][0]["tracks"][0]["artist"], "Artist")

    def test_builds_data_url_and_cli_uses_env(self):
        url = token_helpers.build_data_url("DEV_TOKEN")
        self.assertIn("data:text/html,", url)
        self.assertIn("DEV_TOKEN", url)

        with tempfile.TemporaryDirectory():
            with mock.patch.dict("os.environ", {"APPLE_MUSIC_DEVELOPER_TOKEN": "DEV_TOKEN"}):
                with mock.patch.object(user_token_cli, "build_data_url", return_value="URL") as m_build:
                    with mock.patch("webbrowser.open") as m_open:
                        rc = user_token_cli.main(["--open"])
        self.assertEqual(rc, 0)
        m_build.assert_called_once_with("DEV_TOKEN")
        m_open.assert_called_once_with("URL")

    def test_ping_uses_env_tokens(self):
        stub = FakeAppleMusicClient(storefront="us")

        with mock.patch("apple_music.cli.AppleMusicClient", return_value=stub):
            with mock.patch.dict("os.environ", {"APPLE_MUSIC_DEVELOPER_TOKEN": "DEV", "APPLE_MUSIC_USER_TOKEN": "USER"}):
                rc = cli.main(["ping"])
        self.assertEqual(rc, 0)

    def test_ping_reads_credentials_and_prints_json(self):
        stub = FakeAppleMusicClient(storefront="ca")

        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "credentials.ini"
            cfg.write_text(
                "[musickit.personal]\n"
                "developer_token = DEV\n"
                "user_token = USER\n"
            )
            with mock.patch("apple_music.cli.AppleMusicClient", return_value=stub):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = cli.main(["ping", "--config", str(cfg)])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue().strip())
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["storefront"], "ca")

    def test_list_and_tracks(self):
        stub = FakeAppleMusicClient(
            playlists=[make_playlist("1", "P1"), make_playlist("2", "P2")],
            tracks_by_playlist={
                "1": [make_track("t1", "Song1", "A1", "AL1"), make_track("t2", "Song2", "A2", "AL2")],
                "2": [],
            },
        )

        with mock.patch("apple_music.cli.AppleMusicClient", return_value=stub):
            buf = io.StringIO()
            with mock.patch.dict("os.environ", {"APPLE_MUSIC_DEVELOPER_TOKEN": "DEV", "APPLE_MUSIC_USER_TOKEN": "USER"}):
                with redirect_stdout(buf):
                    rc = cli.main(["tracks"])
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(len(data["tracks"]), 2)
        self.assertEqual(data["tracks"][0]["playlist_name"], "P1")

        with mock.patch("apple_music.cli.AppleMusicClient", return_value=stub):
            buf = io.StringIO()
            with mock.patch.dict("os.environ", {"APPLE_MUSIC_DEVELOPER_TOKEN": "DEV", "APPLE_MUSIC_USER_TOKEN": "USER"}):
                with redirect_stdout(buf):
                    rc = cli.main(["list", "--playlist-limit", "1"])
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(len(data["playlists"]), 2)

    def test_create_playlist_with_shuffle_and_dry_run(self):
        stub = FakeAppleMusicClient(storefront="us")

        with mock.patch("apple_music.cli.AppleMusicClient", return_value=stub):
            buf = io.StringIO()
            with mock.patch.dict("os.environ", {"APPLE_MUSIC_DEVELOPER_TOKEN": "DEV", "APPLE_MUSIC_USER_TOKEN": "USER"}):
                with redirect_stdout(buf):
                    rc = cli.main(["--dry-run", "create", "--shuffle-seed", "1", "--count", "3"])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertIn("plan", payload)
        self.assertEqual(payload["plan"]["storefront"], "us")
        self.assertLessEqual(len(stub.search_calls), 3)

        with mock.patch("apple_music.cli.AppleMusicClient", return_value=stub):
            buf = io.StringIO()
            with mock.patch.dict("os.environ", {"APPLE_MUSIC_DEVELOPER_TOKEN": "DEV", "APPLE_MUSIC_USER_TOKEN": "USER"}):
                with redirect_stdout(buf):
                    rc = cli.main(["create", "--shuffle-seed", "1", "--count", "2", "--name", "My Playlist"])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertIn("created", payload)
        self.assertEqual(payload["plan"]["name"], "My Playlist")

    def test_create_sonic_playlist(self):
        stub = FakeAppleMusicClient(storefront="us")

        with mock.patch("apple_music.cli.AppleMusicClient", return_value=stub):
            buf = io.StringIO()
            with mock.patch.dict("os.environ", {"APPLE_MUSIC_DEVELOPER_TOKEN": "DEV", "APPLE_MUSIC_USER_TOKEN": "USER"}):
                with redirect_stdout(buf):
                    rc = cli.main(["create", "--preset", "sonic", "--count", "3", "--shuffle-seed", "2"])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertIn("created", payload)
        self.assertEqual(payload["created"]["name"], "Sonic Movie Hits")

    def test_dedupe_plans_and_deletes(self):
        stub = FakeAppleMusicClient(
            storefront="us",
            playlists=[
                make_playlist("a1", "Mix", date_added="2024-01-01T00:00:00Z"),
                make_playlist("a2", "Mix", date_added="2025-01-01T00:00:00Z"),
                make_playlist("b1", "Solo"),
            ],
        )

        with mock.patch("apple_music.cli.AppleMusicClient", return_value=stub):
            buf = io.StringIO()
            with mock.patch.dict("os.environ", {"APPLE_MUSIC_DEVELOPER_TOKEN": "DEV", "APPLE_MUSIC_USER_TOKEN": "USER"}):
                with redirect_stdout(buf):
                    rc = cli.main(["dedupe", "--keep", "latest"])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["duplicates"][0]["keep"], "a2")  # latest kept

        with mock.patch("apple_music.cli.AppleMusicClient", return_value=stub):
            buf = io.StringIO()
            with mock.patch.dict("os.environ", {"APPLE_MUSIC_DEVELOPER_TOKEN": "DEV", "APPLE_MUSIC_USER_TOKEN": "USER"}):
                with redirect_stdout(buf):
                    rc = cli.main(["dedupe", "--keep", "first", "--delete"])
        self.assertEqual(rc, 0)
        self.assertIn("a2", stub.deleted)


if __name__ == "__main__":
    unittest.main()
