"""Tests for apple_music/client.py uncovered branches."""

from __future__ import annotations

import unittest

from apple_music.client import AppleMusicClient, AppleMusicError
from tests.apple_music_tests.fixtures import FakeResponse, FakeSession


class TestMakeUrl(unittest.TestCase):
    def setUp(self):
        self.client = AppleMusicClient("dev", "user")

    def test_absolute_http_url_returned_unchanged(self):
        url = self.client._make_url("http://example.com/path")
        self.assertEqual(url, "http://example.com/path")

    def test_absolute_https_url_returned_unchanged(self):
        url = self.client._make_url("https://api.example.com/v1/me/playlists?offset=2")
        self.assertEqual(url, "https://api.example.com/v1/me/playlists?offset=2")

    def test_relative_path_builds_url(self):
        url = self.client._make_url("me/library/playlists")
        self.assertEqual(url, "https://api.music.apple.com/v1/me/library/playlists")

    def test_relative_path_with_leading_slash(self):
        url = self.client._make_url("/me/library/playlists")
        self.assertEqual(url, "https://api.music.apple.com/v1/me/library/playlists")

    def test_base_url_trailing_slash_stripped(self):
        client = AppleMusicClient("dev", "user", base_url="https://api.music.apple.com/")
        url = client._make_url("me/storefront")
        self.assertEqual(url, "https://api.music.apple.com/v1/me/storefront")


class TestRequestMethod(unittest.TestCase):
    def test_get_request_sends_headers(self):
        session = FakeSession([FakeResponse({"data": []}, 200)])
        client = AppleMusicClient("mydev", "myuser", session=session)
        result = client._get("me/storefront")
        self.assertEqual(result, {"data": []})
        call = session.calls[0]
        self.assertIn("api.music.apple.com", call["url"])

    def test_post_request(self):
        fake_session = unittest.mock.MagicMock()
        fake_resp = unittest.mock.MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {"data": [{"id": "new-pl"}]}
        fake_session.post.return_value = fake_resp

        client = AppleMusicClient("dev", "user", session=fake_session)
        result = client._post("me/library/playlists", {"attributes": {"name": "Test"}})
        self.assertEqual(result["data"][0]["id"], "new-pl")
        fake_session.post.assert_called_once()

    def test_delete_request(self):
        fake_session = unittest.mock.MagicMock()
        fake_resp = unittest.mock.MagicMock()
        fake_resp.status_code = 204
        fake_resp.json.return_value = {}
        fake_session.delete.return_value = fake_resp

        client = AppleMusicClient("dev", "user", session=fake_session)
        result = client._request("DELETE", "me/library/playlists/abc123")
        self.assertEqual(result, {})
        fake_session.delete.assert_called_once()

    def test_error_status_raises_apple_music_error(self):
        fake_session = unittest.mock.MagicMock()
        fake_resp = unittest.mock.MagicMock()
        fake_resp.status_code = 401
        fake_resp.text = "Unauthorized"
        fake_session.get.return_value = fake_resp

        client = AppleMusicClient("dev", "user", session=fake_session)
        with self.assertRaises(AppleMusicError) as ctx:
            client._get("me/storefront")
        self.assertIn("401", str(ctx.exception))

    def test_400_error_raises_apple_music_error(self):
        fake_session = unittest.mock.MagicMock()
        fake_resp = unittest.mock.MagicMock()
        fake_resp.status_code = 403
        fake_resp.text = "Forbidden"
        fake_session.get.return_value = fake_resp

        client = AppleMusicClient("dev", "user", session=fake_session)
        with self.assertRaises(AppleMusicError):
            client._get("me/library/playlists")


class TestPaginate(unittest.TestCase):
    def test_pagination_with_next_link(self):
        responses = [
            FakeResponse({"data": [{"id": "1"}, {"id": "2"}], "next": "/v1/me/library/playlists?offset=2"}),
            FakeResponse({"data": [{"id": "3"}]}),
        ]
        session = FakeSession(responses)
        client = AppleMusicClient("dev", "user", session=session)
        result = list(client._paginate("me/library/playlists"))
        self.assertEqual([r["id"] for r in result], ["1", "2", "3"])

    def test_pagination_respects_limit(self):
        responses = [
            FakeResponse({"data": [{"id": "1"}, {"id": "2"}, {"id": "3"}], "next": "/v1/me/playlists?offset=3"}),
        ]
        session = FakeSession(responses)
        client = AppleMusicClient("dev", "user", session=session)
        result = list(client._paginate("me/library/playlists", limit=2))
        self.assertEqual(len(result), 2)

    def test_pagination_no_next(self):
        responses = [
            FakeResponse({"data": [{"id": "a"}]}),
        ]
        session = FakeSession(responses)
        client = AppleMusicClient("dev", "user", session=session)
        result = list(client._paginate("me/library/playlists"))
        self.assertEqual([r["id"] for r in result], ["a"])


class TestHighLevelMethods(unittest.TestCase):
    def test_list_library_playlists_with_limit(self):
        fake_session = unittest.mock.MagicMock()
        fake_resp = unittest.mock.MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {"data": [{"id": "pl1"}, {"id": "pl2"}]}
        fake_session.get.return_value = fake_resp

        client = AppleMusicClient("dev", "user", session=fake_session)
        result = client.list_library_playlists(limit=5)
        self.assertEqual(len(result), 2)
        # Verify limit was passed as a param
        call_kwargs = fake_session.get.call_args
        self.assertIn({"limit": 5}, [call_kwargs[1].get("params")])

    def test_list_library_playlists_no_limit(self):
        fake_session = unittest.mock.MagicMock()
        fake_resp = unittest.mock.MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {"data": [{"id": "pl1"}]}
        fake_session.get.return_value = fake_resp

        client = AppleMusicClient("dev", "user", session=fake_session)
        result = client.list_library_playlists()
        self.assertEqual(len(result), 1)
        call_kwargs = fake_session.get.call_args
        # No limit key in params when limit is None
        params = call_kwargs[1].get("params") or {}
        self.assertNotIn("limit", params)

    def test_list_playlist_tracks_with_limit(self):
        fake_session = unittest.mock.MagicMock()
        fake_resp = unittest.mock.MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {"data": [{"id": "t1"}]}
        fake_session.get.return_value = fake_resp

        client = AppleMusicClient("dev", "user", session=fake_session)
        result = client.list_playlist_tracks("pl123", limit=10)
        self.assertEqual(len(result), 1)

    def test_ping(self):
        fake_session = unittest.mock.MagicMock()
        fake_resp = unittest.mock.MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {"data": [{"id": "us"}]}
        fake_session.get.return_value = fake_resp

        client = AppleMusicClient("dev", "user", session=fake_session)
        result = client.ping()
        self.assertEqual(result["data"][0]["id"], "us")

    def test_search_songs(self):
        fake_session = unittest.mock.MagicMock()
        fake_resp = unittest.mock.MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {
            "results": {"songs": {"data": [{"id": "song1", "attributes": {"name": "Test Song"}}]}}
        }
        fake_session.get.return_value = fake_resp

        client = AppleMusicClient("dev", "user", session=fake_session)
        result = client.search_songs("Test Song", "us", limit=1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "song1")

    def test_create_playlist_with_description(self):
        fake_session = unittest.mock.MagicMock()
        fake_resp = unittest.mock.MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {"data": [{"id": "new-pl"}]}
        fake_session.post.return_value = fake_resp

        client = AppleMusicClient("dev", "user", session=fake_session)
        tracks = [{"id": "t1", "type": "library-songs"}]
        result = client.create_playlist("My Playlist", tracks, description="A great mix")
        self.assertIn("data", result)
        # Verify description was included in the body
        call_kwargs = fake_session.post.call_args
        body = call_kwargs[1]["json"]
        self.assertEqual(body["attributes"]["description"], "A great mix")

    def test_create_playlist_without_description(self):
        fake_session = unittest.mock.MagicMock()
        fake_resp = unittest.mock.MagicMock()
        fake_resp.status_code = 200
        fake_resp.json.return_value = {"data": []}
        fake_session.post.return_value = fake_resp

        client = AppleMusicClient("dev", "user", session=fake_session)
        result = client.create_playlist("Simple", [])
        self.assertIn("data", result)
        # Verify no description key in body
        call_kwargs = fake_session.post.call_args
        body = call_kwargs[1]["json"]
        self.assertNotIn("description", body["attributes"])

    def test_delete_playlist(self):
        fake_session = unittest.mock.MagicMock()
        fake_resp = unittest.mock.MagicMock()
        fake_resp.status_code = 204
        fake_resp.json.return_value = {}
        fake_session.delete.return_value = fake_resp

        client = AppleMusicClient("dev", "user", session=fake_session)
        result = client.delete_playlist("pl-to-delete")
        self.assertEqual(result, {})
        fake_session.delete.assert_called_once()


if __name__ == "__main__":
    unittest.main()
