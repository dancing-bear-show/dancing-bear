"""Tests for apple_music playlist preset data integrity."""

from __future__ import annotations

import unittest

from apple_music.cli_playlist import PRESETS, _artists_overlap, _pick_matching_song


class TestPresetStructure(unittest.TestCase):
    def test_every_preset_has_required_fields(self):
        for key, preset in PRESETS.items():
            with self.subTest(preset=key):
                self.assertIn("name", preset)
                self.assertIn("seeds", preset)
                self.assertTrue(preset["name"], "preset name must be non-empty")
                self.assertTrue(preset["seeds"], "preset must have seeds")

    def test_seeds_are_title_artist_pairs(self):
        for key, preset in PRESETS.items():
            for seed in preset["seeds"]:
                with self.subTest(preset=key, seed=seed):
                    self.assertEqual(len(seed), 2, "seed must be a (title, artist) pair")
                    title, artist = seed
                    self.assertTrue(title.strip(), "seed title must be non-empty")
                    self.assertTrue(artist.strip(), "seed artist must be non-empty")


class TestPresetDuplicates(unittest.TestCase):
    def test_no_duplicate_seeds_within_a_preset(self):
        """Duplicates silently shrink a playlist: --count N yields fewer than N tracks."""
        for key, preset in PRESETS.items():
            seen: set[tuple[str, str]] = set()
            duplicates: list[tuple[str, str]] = []
            for title, artist in preset["seeds"]:
                identity = (title.casefold().strip(), artist.casefold().strip())
                if identity in seen:
                    duplicates.append((title, artist))
                seen.add(identity)
            with self.subTest(preset=key):
                self.assertEqual(duplicates, [], f"duplicate seeds in preset '{key}'")


class TestFrenchPresets(unittest.TestCase):
    """The French presets are era/genre splits and should stay distinguishable."""

    FRENCH_KEYS = ("french-chanson", "french-nouvelle-scene", "french-touch")

    def test_french_presets_registered(self):
        for key in self.FRENCH_KEYS:
            self.assertIn(key, PRESETS)

    def test_french_presets_have_enough_seeds_for_a_full_playlist(self):
        # The create command defaults to 20 tracks; presets must be able to fill that.
        for key in self.FRENCH_KEYS:
            with self.subTest(preset=key):
                self.assertGreaterEqual(len(PRESETS[key]["seeds"]), 20)

    def test_french_presets_do_not_duplicate_each_other(self):
        """Era/genre splits overlap with the broad french-pop set, but not with each other."""
        for i, left in enumerate(self.FRENCH_KEYS):
            for right in self.FRENCH_KEYS[i + 1 :]:
                left_seeds = {
                    (t.casefold(), a.casefold()) for t, a in PRESETS[left]["seeds"]
                }
                right_seeds = {
                    (t.casefold(), a.casefold()) for t, a in PRESETS[right]["seeds"]
                }
                with self.subTest(left=left, right=right):
                    self.assertEqual(
                        left_seeds & right_seeds,
                        set(),
                        f"'{left}' and '{right}' share seeds",
                    )



class TestArtistOverlap(unittest.TestCase):
    """Guards against Apple's fuzzy search crossing artists entirely."""

    def test_rejects_unrelated_artist(self):
        # "Wait M83" once matched a Ravel concerto via its "M. 83" catalog number.
        self.assertFalse(_artists_overlap("M83", "Maurice Ravel"))

    def test_accepts_exact_artist(self):
        self.assertTrue(_artists_overlap("M83", "M83"))

    def test_accepts_collaborator_subset(self):
        """Seeds join collaborators with spaces; Apple returns the lead artist."""
        self.assertTrue(_artists_overlap("Angèle Dua Lipa", "Angèle"))
        self.assertTrue(_artists_overlap("Daft Punk Pharrell Williams", "Daft Punk"))

    def test_stopwords_do_not_create_false_matches(self):
        self.assertFalse(_artists_overlap("La Femme", "La Rue Ketanou"))

    def test_empty_artist_defers_to_apple_ranking(self):
        self.assertTrue(_artists_overlap("", "Anything"))
        self.assertTrue(_artists_overlap("Anything", ""))


class TestPickMatchingSong(unittest.TestCase):
    def test_skips_wrong_artist_and_returns_the_later_correct_result(self):
        """Apple ranks catalog-wide, so the intended track is not always first."""
        results = [
            {"id": "1", "attributes": {"name": "Piano Concerto, M. 83", "artistName": "Ravel"}},
            {"id": "2", "attributes": {"name": "Wait", "artistName": "M83"}},
        ]
        self.assertEqual(_pick_matching_song(results, "M83")["id"], "2")

    def test_returns_none_when_no_candidate_matches(self):
        results = [{"id": "1", "attributes": {"name": "X", "artistName": "Someone Else"}}]
        self.assertIsNone(_pick_matching_song(results, "M83"))

    def test_null_attributes_do_not_raise(self):
        """Apple can return "attributes": null; that must not crash the matcher."""
        results = [{"id": "1", "attributes": None}, {"id": "2", "attributes": {"artistName": "M83"}}]
        self.assertIsNotNone(_pick_matching_song(results, "M83"))



class TestDeleteDuplicatePlaylists(unittest.TestCase):
    """_delete_duplicate_playlists skips non-string and None ids."""

    def test_skips_none_id(self):
        from apple_music.cli_playlist import _delete_duplicate_playlists
        from tests.apple_music_tests.fixtures import FakeAppleMusicClient

        client = FakeAppleMusicClient(storefront="us", playlists=[])
        result = _delete_duplicate_playlists(client, [{"title": "Mix"}])  # no id key
        self.assertEqual(result, [])
        self.assertEqual(client.deleted, [])

    def test_skips_non_string_id(self):
        from apple_music.cli_playlist import _delete_duplicate_playlists
        from tests.apple_music_tests.fixtures import FakeAppleMusicClient

        # An int id (from JSON parsing without schema validation) must be skipped,
        # not forwarded as a stringified path like "123" to the delete endpoint.
        client = FakeAppleMusicClient(storefront="us", playlists=[])
        result = _delete_duplicate_playlists(client, [{"id": 123, "title": "Mix"}])
        self.assertEqual(result, [])
        self.assertEqual(client.deleted, [])

    def test_deletes_valid_string_id(self):
        from apple_music.cli_playlist import _delete_duplicate_playlists
        from tests.apple_music_tests.fixtures import FakeAppleMusicClient

        client = FakeAppleMusicClient(storefront="us", playlists=[])
        result = _delete_duplicate_playlists(client, [{"id": "pl-abc", "title": "Mix"}])
        self.assertEqual(result, ["pl-abc"])
        self.assertIn("pl-abc", client.deleted)


if __name__ == "__main__":
    unittest.main()
