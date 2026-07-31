"""Tests for apple_music processor/producer pipeline pairs (C2/C8/C9).

Happy-path: consumer → processor → producer, asserting typed output objects.
Sad-path: each distinct raise site in _process_safe surfaces the correct error.
"""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout

from apple_music.cli import (
    ExportPlaylistResult,
    ExportProcessor,
    ExportProducer,
    ExportRequest,
    ListPlaylistsProcessor,
    ListPlaylistsProducer,
    ListPlaylistsRequest,
    PlaylistResult,
    TrackResult,
    TracksProcessor,
    TracksProducer,
    TracksRequest,
)
from core.cli_errors import AuthError
from core.cli_output import OutputConfig, OutputFormat, OutputWriter
from core.pipeline import ResultEnvelope

from tests.apple_music_tests.fixtures import (
    FakeAppleMusicClient,
    make_playlist,
    make_track,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _json_writer() -> OutputWriter:
    """Return an OutputWriter configured for JSON output to stdout."""
    return OutputWriter(config=OutputConfig(format=OutputFormat.JSON))


def _capture_producer(producer_instance, envelope: ResultEnvelope) -> dict:
    """Run producer.produce() and return parsed JSON from its output."""
    buf = io.StringIO()
    with redirect_stdout(buf):
        producer_instance.produce(envelope)
    raw = buf.getvalue().strip()
    return json.loads(raw)


# ---------------------------------------------------------------------------
# ListPlaylistsProcessor happy-path
# ---------------------------------------------------------------------------


class TestListPlaylistsProcessorHappy(unittest.TestCase):
    def setUp(self):
        self.client = FakeAppleMusicClient(
            playlists=[
                make_playlist("pl-1", "Chill Mix"),
                make_playlist("pl-2", "Workout"),
            ]
        )

    def test_returns_typed_playlist_results(self):
        request = ListPlaylistsRequest(client=self.client, limit=None)
        envelope = ListPlaylistsProcessor().process(request)

        self.assertTrue(envelope.ok())
        payload = envelope.payload
        self.assertIsInstance(payload, list)
        self.assertEqual(len(payload), 2)
        self.assertIsInstance(payload[0], PlaylistResult)
        self.assertEqual(payload[0].id, "pl-1")
        self.assertEqual(payload[0].name, "Chill Mix")
        self.assertEqual(payload[0].track_count, 0)

    def test_respects_limit_via_client(self):
        """FakeAppleMusicClient ignores limit (returns all); processor trusts client."""
        request = ListPlaylistsRequest(client=self.client, limit=1)
        envelope = ListPlaylistsProcessor().process(request)
        self.assertTrue(envelope.ok())
        # All playlists returned because FakeAppleMusicClient ignores limit
        self.assertEqual(len(envelope.payload), 2)

    def test_empty_playlists_returns_empty_list(self):
        client = FakeAppleMusicClient(playlists=[])
        envelope = ListPlaylistsProcessor().process(ListPlaylistsRequest(client=client))
        self.assertTrue(envelope.ok())
        self.assertEqual(envelope.payload, [])


# ---------------------------------------------------------------------------
# ListPlaylistsProducer happy-path
# ---------------------------------------------------------------------------


class TestListPlaylistsProducerHappy(unittest.TestCase):
    def test_produces_playlists_key_with_id_and_name(self):
        results = [PlaylistResult(id="pl-1", name="Chill Mix", track_count=5)]
        envelope = ResultEnvelope(status="success", payload=results)

        data = _capture_producer(ListPlaylistsProducer(_json_writer()), envelope)

        self.assertIn("playlists", data)
        self.assertEqual(len(data["playlists"]), 1)
        self.assertEqual(data["playlists"][0]["id"], "pl-1")
        self.assertEqual(data["playlists"][0]["name"], "Chill Mix")

    def test_produces_nothing_on_error_envelope(self):
        envelope = ResultEnvelope(
            status="error", diagnostics={"message": "something went wrong"}
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            ListPlaylistsProducer(_json_writer()).produce(envelope)
        # No JSON emitted on error
        self.assertEqual(buf.getvalue().strip(), "")


# ---------------------------------------------------------------------------
# ListPlaylistsProcessor sad-path
# ---------------------------------------------------------------------------


class TestListPlaylistsProcessorSad(unittest.TestCase):
    def test_exception_in_client_returns_error_envelope(self):
        class _BrokenClient:
            def list_library_playlists(self, limit=None):
                raise RuntimeError("API unavailable")

        request = ListPlaylistsRequest(client=_BrokenClient())
        envelope = ListPlaylistsProcessor().process(request)

        self.assertFalse(envelope.ok())
        self.assertIn("API unavailable", envelope.diagnostics["message"])

    def test_auth_error_surfaces_in_envelope(self):
        class _UnauthorizedClient:
            def list_library_playlists(self, limit=None):
                raise AuthError("Missing token")

        request = ListPlaylistsRequest(client=_UnauthorizedClient())
        envelope = ListPlaylistsProcessor().process(request)

        self.assertFalse(envelope.ok())
        self.assertIn("Missing token", envelope.diagnostics["message"])


# ---------------------------------------------------------------------------
# TracksProcessor happy-path
# ---------------------------------------------------------------------------


class TestTracksProcessorHappy(unittest.TestCase):
    def setUp(self):
        self.client = FakeAppleMusicClient(
            playlists=[make_playlist("pl-1", "Workout")],
            tracks_by_playlist={
                "pl-1": [make_track("t1", "Eye of the Tiger", "Survivor", "Eye of the Tiger")]
            },
        )

    def test_returns_typed_track_results(self):
        request = TracksRequest(client=self.client, playlist_limit=None, track_limit=None)
        envelope = TracksProcessor().process(request)

        self.assertTrue(envelope.ok())
        payload = envelope.payload
        self.assertIsInstance(payload, list)
        self.assertEqual(len(payload), 1)

        track = payload[0]
        self.assertIsInstance(track, TrackResult)
        self.assertEqual(track.id, "t1")
        self.assertEqual(track.title, "Eye of the Tiger")
        self.assertEqual(track.artist, "Survivor")
        self.assertEqual(track.album, "Eye of the Tiger")
        self.assertEqual(track.playlist_id, "pl-1")
        self.assertEqual(track.playlist_name, "Workout")

    def test_optional_fields_are_none_when_absent(self):
        request = TracksRequest(client=self.client)
        envelope = TracksProcessor().process(request)

        track = envelope.payload[0]
        self.assertIsNone(track.duration_ms)
        self.assertIsNone(track.track_number)

    def test_multiple_playlists_flattened(self):
        client = FakeAppleMusicClient(
            playlists=[make_playlist("a", "A"), make_playlist("b", "B")],
            tracks_by_playlist={
                "a": [make_track("t1", "Song1", "Art1", "Al1")],
                "b": [make_track("t2", "Song2", "Art2", "Al2"), make_track("t3", "Song3", "Art3", "Al3")],
            },
        )
        envelope = TracksProcessor().process(TracksRequest(client=client))

        self.assertTrue(envelope.ok())
        self.assertEqual(len(envelope.payload), 3)
        playlist_ids = {tr.playlist_id for tr in envelope.payload}
        self.assertEqual(playlist_ids, {"a", "b"})

    def test_empty_playlists_returns_empty_tracks(self):
        client = FakeAppleMusicClient(playlists=[])
        envelope = TracksProcessor().process(TracksRequest(client=client))
        self.assertTrue(envelope.ok())
        self.assertEqual(envelope.payload, [])


# ---------------------------------------------------------------------------
# TracksProducer happy-path
# ---------------------------------------------------------------------------


class TestTracksProducerHappy(unittest.TestCase):
    def test_produces_tracks_key_with_all_fields(self):
        results = [
            TrackResult(
                id="t1",
                title="Eye of the Tiger",
                artist="Survivor",
                album="Eye of the Tiger",
                playlist_id="pl-1",
                playlist_name="Workout",
                duration_ms=245000,
                track_number=1,
            )
        ]
        envelope = ResultEnvelope(status="success", payload=results)

        data = _capture_producer(TracksProducer(_json_writer()), envelope)

        self.assertIn("tracks", data)
        self.assertEqual(len(data["tracks"]), 1)
        t = data["tracks"][0]
        self.assertEqual(t["id"], "t1")
        self.assertEqual(t["name"], "Eye of the Tiger")
        self.assertEqual(t["artist"], "Survivor")
        self.assertEqual(t["album"], "Eye of the Tiger")
        self.assertEqual(t["playlist_id"], "pl-1")
        self.assertEqual(t["playlist_name"], "Workout")
        self.assertEqual(t["duration_ms"], 245000)
        self.assertEqual(t["track_number"], 1)

    def test_produces_nothing_on_error_envelope(self):
        envelope = ResultEnvelope(status="error", diagnostics={"message": "fail"})
        buf = io.StringIO()
        with redirect_stdout(buf):
            TracksProducer(_json_writer()).produce(envelope)
        self.assertEqual(buf.getvalue().strip(), "")


# ---------------------------------------------------------------------------
# TracksProcessor sad-path
# ---------------------------------------------------------------------------


class TestTracksProcessorSad(unittest.TestCase):
    def test_exception_during_playlist_fetch_returns_error(self):
        class _BrokenClient:
            def list_library_playlists(self, limit=None):
                raise RuntimeError("timeout")

            def list_playlist_tracks(self, playlist_id, limit=None):
                return []

        envelope = TracksProcessor().process(TracksRequest(client=_BrokenClient()))
        self.assertFalse(envelope.ok())
        self.assertIn("timeout", envelope.diagnostics["message"])

    def test_exception_during_track_fetch_returns_error(self):
        class _TrackBrokenClient:
            def list_library_playlists(self, limit=None):
                return [make_playlist("pl-1", "Mix")]

            def list_playlist_tracks(self, playlist_id, limit=None):
                raise RuntimeError("track fetch failed")

        envelope = TracksProcessor().process(TracksRequest(client=_TrackBrokenClient()))
        self.assertFalse(envelope.ok())
        self.assertIn("track fetch failed", envelope.diagnostics["message"])

    def test_auth_error_during_playlist_fetch_surfaces_in_envelope(self):
        class _AuthBrokenClient:
            def list_library_playlists(self, limit=None):
                raise AuthError("token expired")

            def list_playlist_tracks(self, playlist_id, limit=None):
                return []

        envelope = TracksProcessor().process(TracksRequest(client=_AuthBrokenClient()))
        self.assertFalse(envelope.ok())
        self.assertIn("token expired", envelope.diagnostics["message"])


# ---------------------------------------------------------------------------
# ExportProcessor happy-path
# ---------------------------------------------------------------------------


class TestExportProcessorHappy(unittest.TestCase):
    def setUp(self):
        self.client = FakeAppleMusicClient(
            playlists=[make_playlist("pl-1", "Chill Mix")],
            tracks_by_playlist={
                "pl-1": [make_track("t1", "Song", "Artist", "Album")]
            },
        )

    def test_returns_typed_export_playlist_results(self):
        request = ExportRequest(client=self.client)
        envelope = ExportProcessor().process(request)

        self.assertTrue(envelope.ok())
        payload = envelope.payload
        self.assertIsInstance(payload, list)
        self.assertEqual(len(payload), 1)

        ep = payload[0]
        self.assertIsInstance(ep, ExportPlaylistResult)
        self.assertEqual(ep.id, "pl-1")
        self.assertEqual(ep.name, "Chill Mix")
        self.assertIsNone(ep.description)  # not set on make_playlist fixture

    def test_export_playlist_contains_tracks_as_dicts(self):
        request = ExportRequest(client=self.client)
        envelope = ExportProcessor().process(request)

        ep = envelope.payload[0]
        self.assertIsInstance(ep.tracks, list)
        self.assertEqual(len(ep.tracks), 1)

        tr = ep.tracks[0]
        self.assertIsInstance(tr, dict)
        self.assertEqual(tr["id"], "t1")
        self.assertEqual(tr["name"], "Song")
        self.assertEqual(tr["artist"], "Artist")
        self.assertEqual(tr["album"], "Album")

    def test_empty_playlists_returns_empty_list(self):
        client = FakeAppleMusicClient(playlists=[])
        envelope = ExportProcessor().process(ExportRequest(client=client))
        self.assertTrue(envelope.ok())
        self.assertEqual(envelope.payload, [])

    def test_playlist_with_no_tracks_has_empty_track_list(self):
        client = FakeAppleMusicClient(
            playlists=[make_playlist("pl-2", "Empty")],
            tracks_by_playlist={"pl-2": []},
        )
        envelope = ExportProcessor().process(ExportRequest(client=client))
        self.assertTrue(envelope.ok())
        self.assertEqual(envelope.payload[0].tracks, [])


# ---------------------------------------------------------------------------
# ExportProducer happy-path
# ---------------------------------------------------------------------------


class TestExportProducerHappy(unittest.TestCase):
    def test_produces_playlists_key_with_tracks(self):
        results = [
            ExportPlaylistResult(
                id="pl-1",
                name="Chill Mix",
                description=None,
                tracks=[{"id": "t1", "name": "Song", "artist": "Artist", "album": "Album"}],
            )
        ]
        envelope = ResultEnvelope(status="success", payload=results)

        data = _capture_producer(ExportProducer(_json_writer()), envelope)

        self.assertIn("playlists", data)
        self.assertEqual(len(data["playlists"]), 1)
        pl = data["playlists"][0]
        self.assertEqual(pl["id"], "pl-1")
        self.assertEqual(pl["name"], "Chill Mix")
        self.assertIsNone(pl["description"])
        self.assertEqual(len(pl["tracks"]), 1)
        self.assertEqual(pl["tracks"][0]["id"], "t1")

    def test_produces_nothing_on_error_envelope(self):
        envelope = ResultEnvelope(status="error", diagnostics={"message": "oops"})
        buf = io.StringIO()
        with redirect_stdout(buf):
            ExportProducer(_json_writer()).produce(envelope)
        self.assertEqual(buf.getvalue().strip(), "")


# ---------------------------------------------------------------------------
# ExportProcessor sad-path
# ---------------------------------------------------------------------------


class TestExportProcessorSad(unittest.TestCase):
    def test_exception_during_playlist_fetch_returns_error(self):
        class _BrokenClient:
            def list_library_playlists(self, limit=None):
                raise RuntimeError("network error")

            def list_playlist_tracks(self, playlist_id, limit=None):
                return []

        envelope = ExportProcessor().process(ExportRequest(client=_BrokenClient()))
        self.assertFalse(envelope.ok())
        self.assertIn("network error", envelope.diagnostics["message"])

    def test_exception_during_track_fetch_returns_error(self):
        class _TrackBrokenClient:
            def list_library_playlists(self, limit=None):
                return [{"id": "pl-1", "attributes": {"name": "Mix"}}]

            def list_playlist_tracks(self, playlist_id, limit=None):
                raise RuntimeError("track API error")

        envelope = ExportProcessor().process(ExportRequest(client=_TrackBrokenClient()))
        self.assertFalse(envelope.ok())
        self.assertIn("track API error", envelope.diagnostics["message"])

    def test_auth_error_surfaces_in_envelope(self):
        class _AuthBrokenClient:
            def list_library_playlists(self, limit=None):
                raise AuthError("Missing developer token")

            def list_playlist_tracks(self, playlist_id, limit=None):
                return []

        envelope = ExportProcessor().process(ExportRequest(client=_AuthBrokenClient()))
        self.assertFalse(envelope.ok())
        self.assertIn("Missing developer token", envelope.diagnostics["message"])


if __name__ == "__main__":
    unittest.main()
