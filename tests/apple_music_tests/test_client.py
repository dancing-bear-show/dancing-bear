"""Tests for apple_music/client.py uncovered branches."""

from __future__ import annotations

import unittest

from apple_music.client import AppleMusicClient, AppleMusicCLIError
from tests.apple_music_tests.fixtures import FakeResponse, FakeSession


class TestMakePath(unittest.TestCase):
    """Tests for _make_path(), the path normalizer used before delegating to HttpClient."""

    def setUp(self):
        self.client = AppleMusicClient("dev", "user")

    def test_absolute_http_url_returned_unchanged(self):
        path = self.client._make_path("http://example.com/path")
        self.assertEqual(path, "http://example.com/path")

    def test_absolute_https_url_returned_unchanged(self):
        path = self.client._make_path("https://api.example.com/v1/me/playlists?offset=2")
        self.assertEqual(path, "https://api.example.com/v1/me/playlists?offset=2")

    def test_relative_path_prefixes_v1(self):
        path = self.client._make_path("me/library/playlists")
        self.assertEqual(path, "/v1/me/library/playlists")

    def test_relative_path_with_leading_slash_prefixes_v1(self):
        path = self.client._make_path("/me/library/playlists")
        self.assertEqual(path, "/v1/me/library/playlists")

    def test_path_already_v1_not_doubled(self):
        path = self.client._make_path("v1/me/library/playlists")
        self.assertEqual(path, "/v1/me/library/playlists")


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
        fake_resp.content = b'{"data": [{"id": "new-pl"}]}'
        fake_resp.headers = {}
        fake_resp.json.return_value = {"data": [{"id": "new-pl"}]}
        fake_session.request.return_value = fake_resp

        client = AppleMusicClient("dev", "user", session=fake_session)
        result = client._post("me/library/playlists", {"attributes": {"name": "Test"}})
        self.assertEqual(result["data"][0]["id"], "new-pl")
        fake_session.request.assert_called_once()

    def test_delete_request(self):
        fake_session = unittest.mock.MagicMock()
        fake_resp = unittest.mock.MagicMock()
        fake_resp.status_code = 204
        fake_resp.content = b'{}'
        fake_resp.headers = {}
        fake_resp.json.return_value = {}
        fake_session.request.return_value = fake_resp

        client = AppleMusicClient("dev", "user", session=fake_session)
        result = client._request("DELETE", "me/library/playlists/abc123")
        self.assertEqual(result, {})
        fake_session.request.assert_called_once()

    def test_error_status_raises_apple_music_error(self):
        session = FakeSession([FakeResponse({"error": "Unauthorized"}, 401)])
        client = AppleMusicClient("dev", "user", session=session)
        with self.assertRaises(AppleMusicCLIError) as ctx:
            client._get("me/storefront")
        self.assertIn("401", str(ctx.exception))

    def test_400_error_raises_apple_music_error(self):
        session = FakeSession([FakeResponse({"error": "Forbidden"}, 403)])
        client = AppleMusicClient("dev", "user", session=session)
        with self.assertRaises(AppleMusicCLIError) as ctx:
            client._get("me/library/playlists")
        self.assertIn("403", str(ctx.exception))


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


def _make_fake_session(json_body: dict, status: int = 200):
    fake_session = unittest.mock.MagicMock()
    fake_resp = unittest.mock.MagicMock()
    fake_resp.status_code = status
    fake_resp.content = b'{}'
    fake_resp.headers = {}
    fake_resp.json.return_value = json_body
    fake_session.request.return_value = fake_resp
    return fake_session, fake_resp


class TestHighLevelMethods(unittest.TestCase):
    def test_list_library_playlists_with_limit(self):
        fake_session, _ = _make_fake_session({"data": [{"id": "pl1"}, {"id": "pl2"}]})
        client = AppleMusicClient("dev", "user", session=fake_session)
        result = client.list_library_playlists(limit=5)
        self.assertEqual(len(result), 2)
        url_called = fake_session.request.call_args[0][1]
        self.assertIn("limit=5", url_called)

    def test_list_library_playlists_no_limit(self):
        fake_session, _ = _make_fake_session({"data": [{"id": "pl1"}]})
        client = AppleMusicClient("dev", "user", session=fake_session)
        result = client.list_library_playlists()
        self.assertEqual(len(result), 1)
        call_kwargs = fake_session.request.call_args
        params = call_kwargs[1].get("params") or {}
        self.assertNotIn("limit", params)

    def test_list_playlist_tracks_with_limit(self):
        fake_session, _ = _make_fake_session({"data": [{"id": "t1"}]})
        client = AppleMusicClient("dev", "user", session=fake_session)
        result = client.list_playlist_tracks("pl123", limit=10)
        self.assertEqual(len(result), 1)

    def test_ping(self):
        fake_session, _ = _make_fake_session({"data": [{"id": "us"}]})
        client = AppleMusicClient("dev", "user", session=fake_session)
        result = client.ping()
        self.assertEqual(result["data"][0]["id"], "us")

    def test_search_songs(self):
        body = {"results": {"songs": {"data": [{"id": "song1", "attributes": {"name": "Test Song"}}]}}}
        fake_session, _ = _make_fake_session(body)
        client = AppleMusicClient("dev", "user", session=fake_session)
        result = client.search_songs("Test Song", "us", limit=1)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["id"], "song1")

    def test_create_playlist_with_description(self):
        fake_session, _ = _make_fake_session({"data": [{"id": "new-pl"}]})
        client = AppleMusicClient("dev", "user", session=fake_session)
        tracks = [{"id": "t1", "type": "library-songs"}]
        result = client.create_playlist("My Playlist", tracks, description="A great mix")
        self.assertIn("data", result)
        call_kwargs = fake_session.request.call_args
        body = call_kwargs[1]["json"]
        self.assertEqual(body["attributes"]["description"], "A great mix")

    def test_create_playlist_without_description(self):
        fake_session, _ = _make_fake_session({"data": []})
        client = AppleMusicClient("dev", "user", session=fake_session)
        result = client.create_playlist("Simple", [])
        self.assertIn("data", result)
        call_kwargs = fake_session.request.call_args
        body = call_kwargs[1]["json"]
        self.assertNotIn("description", body["attributes"])

    def test_delete_playlist(self):
        fake_session, _ = _make_fake_session({}, status=204)
        client = AppleMusicClient("dev", "user", session=fake_session)
        result = client.delete_playlist("pl-to-delete")
        self.assertEqual(result, {})
        fake_session.request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
