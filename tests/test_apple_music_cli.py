import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from apple_music_assistant import __main__ as cli
from apple_music_assistant.client import AppleMusicClient
from apple_music_assistant import token_helpers, user_token_cli


class FakeResponse:
    def __init__(self, body: dict, status: int = 200):
        self.status_code = status
        self._body = body
        self.text = json.dumps(body)

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, headers=None, params=None, json=None):
        self.calls.append({"url": url, "params": params})
        if not self.responses:  # pragma: no cover - defensive
            raise AssertionError("No response queued")
        return self.responses.pop(0)


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

            playlists = [
                {"id": "1", "attributes": {"name": "My Mix"}},
            ]
            tracks = [
                {"id": "t1", "attributes": {"name": "Song", "artistName": "Artist", "albumName": "Album"}},
            ]

            def stub_client(dev, user):
                return SimpleNamespace(
                    list_library_playlists=lambda limit=None: playlists,
                    list_playlist_tracks=lambda playlist_id, limit=None: tracks,
                )

            with mock.patch("apple_music_assistant.cli.AppleMusicClient", side_effect=stub_client):
                rc = cli.main(["--config", str(cfg), "--out", str(out_path)])
            self.assertEqual(rc, 0)
            data = json.loads(out_path.read_text())
            self.assertEqual(data["playlists"][0]["name"], "My Mix")
            self.assertEqual(data["playlists"][0]["tracks"][0]["artist"], "Artist")

    def test_builds_data_url_and_cli_uses_env(self):
        url = token_helpers.build_data_url("DEV_TOKEN")
        self.assertIn("data:text/html,", url)
        self.assertIn("DEV_TOKEN", url)

        with tempfile.TemporaryDirectory() as td:
            with mock.patch.dict("os.environ", {"APPLE_MUSIC_DEVELOPER_TOKEN": "DEV_TOKEN"}):
                with mock.patch.object(user_token_cli, "build_data_url", return_value="URL") as m_build:
                    with mock.patch("webbrowser.open") as m_open:
                        rc = user_token_cli.main(["--open"])
        self.assertEqual(rc, 0)
        m_build.assert_called_once_with("DEV_TOKEN")
        m_open.assert_called_once_with("URL")

    def test_ping_uses_env_tokens(self):
        def stub_client(dev, user):
            return SimpleNamespace(ping=lambda: {"data": [{"id": "us"}]})

        with mock.patch("apple_music_assistant.cli.AppleMusicClient", side_effect=stub_client):
            with mock.patch.dict("os.environ", {"APPLE_MUSIC_DEVELOPER_TOKEN": "DEV", "APPLE_MUSIC_USER_TOKEN": "USER"}):
                rc = cli.main(["ping"])
        self.assertEqual(rc, 0)

    def test_ping_reads_credentials_and_prints_json(self):
        def stub_client(dev, user):
            return SimpleNamespace(ping=lambda: {"data": [{"id": "ca"}]})

        with tempfile.TemporaryDirectory() as td:
            cfg = Path(td) / "credentials.ini"
            cfg.write_text(
                "[musickit.personal]\n"
                "developer_token = DEV\n"
                "user_token = USER\n"
            )
            with mock.patch("apple_music_assistant.cli.AppleMusicClient", side_effect=stub_client):
                buf = io.StringIO()
                with redirect_stdout(buf):
                    rc = cli.main(["--config", str(cfg), "ping"])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue().strip())
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["storefront"], "ca")

    def test_list_and_tracks(self):
        playlists = [
            {"id": "1", "attributes": {"name": "P1"}},
            {"id": "2", "attributes": {"name": "P2"}},
        ]
        tracks = [
            {"id": "t1", "attributes": {"name": "Song1", "artistName": "A1", "albumName": "AL1"}},
            {"id": "t2", "attributes": {"name": "Song2", "artistName": "A2", "albumName": "AL2"}},
        ]

        def stub_client(dev, user):
            return SimpleNamespace(
                list_library_playlists=lambda limit=None: playlists,
                list_playlist_tracks=lambda pid, limit=None: tracks if pid == "1" else [],
            )

        with mock.patch("apple_music_assistant.cli.AppleMusicClient", side_effect=stub_client):
            buf = io.StringIO()
            with mock.patch.dict("os.environ", {"APPLE_MUSIC_DEVELOPER_TOKEN": "DEV", "APPLE_MUSIC_USER_TOKEN": "USER"}):
                with redirect_stdout(buf):
                    rc = cli.main(["tracks"])
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(len(data["tracks"]), 2)
        self.assertEqual(data["tracks"][0]["playlist_name"], "P1")

        with mock.patch("apple_music_assistant.cli.AppleMusicClient", side_effect=stub_client):
            buf = io.StringIO()
            with mock.patch.dict("os.environ", {"APPLE_MUSIC_DEVELOPER_TOKEN": "DEV", "APPLE_MUSIC_USER_TOKEN": "USER"}):
                with redirect_stdout(buf):
                    rc = cli.main(["list", "--playlist-limit", "1"])
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(len(data["playlists"]), 2)

    def test_create_playlist_with_shuffle_and_dry_run(self):
        seeds_order = []

        class StubClient:
            def __init__(self):
                self.search_calls = []
                self.created = None

            def ping(self):
                return {"data": [{"id": "us"}]}

            def search_songs(self, term, storefront, limit=1):
                self.search_calls.append((term, storefront, limit))
                # Return deterministic song id from term
                return [{"id": f"id-{term.replace(' ', '-')}", "type": "songs", "attributes": {"name": term}}]

            def create_playlist(self, name, tracks, description=None):
                self.created = {"name": name, "tracks": tracks}
                return self.created

            def list_library_playlists(self, limit=None):
                return []

            def list_playlist_tracks(self, pid, limit=None):
                return []

        stub = StubClient()
        with mock.patch("apple_music_assistant.cli.AppleMusicClient", return_value=stub):
            buf = io.StringIO()
            with mock.patch.dict("os.environ", {"APPLE_MUSIC_DEVELOPER_TOKEN": "DEV", "APPLE_MUSIC_USER_TOKEN": "USER"}):
                with redirect_stdout(buf):
                    rc = cli.main(["create", "--shuffle-seed", "1", "--count", "3", "--dry-run"])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertIn("plan", payload)
        self.assertEqual(payload["plan"]["storefront"], "us")
        self.assertLessEqual(len(stub.search_calls), 3)

        with mock.patch("apple_music_assistant.cli.AppleMusicClient", return_value=stub):
            buf = io.StringIO()
            with mock.patch.dict("os.environ", {"APPLE_MUSIC_DEVELOPER_TOKEN": "DEV", "APPLE_MUSIC_USER_TOKEN": "USER"}):
                with redirect_stdout(buf):
                    rc = cli.main(["create", "--shuffle-seed", "1", "--count", "2", "--name", "My Playlist"])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertIn("created", payload)
        self.assertEqual(payload["plan"]["name"], "My Playlist")

    def test_create_sonic_playlist(self):
        class StubClient:
            def __init__(self):
                self.search_calls = []

            def ping(self):
                return {"data": [{"id": "us"}]}

            def search_songs(self, term, storefront, limit=1):
                self.search_calls.append((term, storefront, limit))
                return [{"id": f"id-{term}", "type": "songs", "attributes": {"name": term}}]

            def create_playlist(self, name, tracks, description=None):
                return {"name": name, "tracks": tracks, "description": description}

            def list_library_playlists(self, limit=None):
                return []

            def list_playlist_tracks(self, pid, limit=None):
                return []

        stub = StubClient()
        with mock.patch("apple_music_assistant.cli.AppleMusicClient", return_value=stub):
            buf = io.StringIO()
            with mock.patch.dict("os.environ", {"APPLE_MUSIC_DEVELOPER_TOKEN": "DEV", "APPLE_MUSIC_USER_TOKEN": "USER"}):
                with redirect_stdout(buf):
                    rc = cli.main(["create", "--preset", "sonic", "--count", "3", "--shuffle-seed", "2"])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertIn("created", payload)
        self.assertEqual(payload["created"]["name"], "Sonic Movie Hits")

    def test_dedupe_plans_and_deletes(self):
        class StubClient:
            def __init__(self):
                self.deleted = []

            def list_library_playlists(self, limit=None):
                return [
                    {"id": "a1", "attributes": {"name": "Mix", "dateAdded": "2024-01-01T00:00:00Z"}},
                    {"id": "a2", "attributes": {"name": "Mix", "dateAdded": "2025-01-01T00:00:00Z"}},
                    {"id": "b1", "attributes": {"name": "Solo"}},
                ]

            def delete_playlist(self, pid):
                self.deleted.append(pid)
                return {"id": pid}

            def ping(self):
                return {"data": [{"id": "us"}]}

        stub = StubClient()
        with mock.patch("apple_music_assistant.cli.AppleMusicClient", return_value=stub):
            buf = io.StringIO()
            with mock.patch.dict("os.environ", {"APPLE_MUSIC_DEVELOPER_TOKEN": "DEV", "APPLE_MUSIC_USER_TOKEN": "USER"}):
                with redirect_stdout(buf):
                    rc = cli.main(["dedupe", "--keep", "latest"])
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["duplicates"][0]["keep"], "a2")  # latest kept

        with mock.patch("apple_music_assistant.cli.AppleMusicClient", return_value=stub):
            buf = io.StringIO()
            with mock.patch.dict("os.environ", {"APPLE_MUSIC_DEVELOPER_TOKEN": "DEV", "APPLE_MUSIC_USER_TOKEN": "USER"}):
                with redirect_stdout(buf):
                    rc = cli.main(["dedupe", "--keep", "first", "--delete"])
        self.assertEqual(rc, 0)
        self.assertIn("a2", stub.deleted)


if __name__ == "__main__":
    unittest.main()
