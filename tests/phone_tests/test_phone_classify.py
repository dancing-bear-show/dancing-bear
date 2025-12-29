"""Tests for phone.classify module."""

from unittest import TestCase

from phone.classify import classify_app
from phone.constants import FOLDERS


class ClassifyAppTests(TestCase):
    def test_folders_list(self):
        expected = ["Work", "Media", "Social", "Finance", "Travel", "Health", "Shopping", "Utilities"]
        self.assertEqual(FOLDERS, expected)

    def test_apple_apps_explicit_mapping(self):
        # Media apps
        self.assertEqual(classify_app("com.apple.mobileslideshow"), "Media")
        self.assertEqual(classify_app("com.apple.tv"), "Media")
        self.assertEqual(classify_app("com.apple.podcasts"), "Media")
        self.assertEqual(classify_app("com.apple.Music"), "Media")
        # Work apps
        self.assertEqual(classify_app("com.apple.mobilemail"), "Work")
        self.assertEqual(classify_app("com.apple.mobilecal"), "Work")
        self.assertEqual(classify_app("com.apple.reminders"), "Work")
        # Utilities
        self.assertEqual(classify_app("com.apple.mobilesafari"), "Utilities")
        self.assertEqual(classify_app("com.apple.Preferences"), "Utilities")
        # Travel
        self.assertEqual(classify_app("com.apple.Maps"), "Travel")
        # Finance
        self.assertEqual(classify_app("com.apple.stocks"), "Finance")
        # Social
        self.assertEqual(classify_app("com.apple.facetime"), "Social")
        self.assertEqual(classify_app("com.apple.MobileSMS"), "Social")
        # Shopping
        self.assertEqual(classify_app("com.apple.AppStore"), "Shopping")

    def test_pattern_matching_work(self):
        self.assertEqual(classify_app("com.slack"), "Work")
        self.assertEqual(classify_app("com.atlassian.jira"), "Work")
        self.assertEqual(classify_app("us.zoom.videomeetings"), "Work")
        self.assertEqual(classify_app("com.microsoft.teams"), "Work")

    def test_pattern_matching_media(self):
        self.assertEqual(classify_app("com.spotify.client"), "Media")
        self.assertEqual(classify_app("com.netflix.Netflix"), "Media")
        self.assertEqual(classify_app("com.google.ios.youtube"), "Media")

    def test_pattern_matching_social(self):
        self.assertEqual(classify_app("com.facebook.Facebook"), "Social")
        self.assertEqual(classify_app("com.burbn.instagram"), "Social")
        self.assertEqual(classify_app("com.twitter.twitter"), "Social")
        self.assertEqual(classify_app("com.ss.iphone.ugc.tiktok"), "Social")

    def test_pattern_matching_shopping(self):
        self.assertEqual(classify_app("com.amazon.Amazon"), "Shopping")
        self.assertEqual(classify_app("com.target.targetapp"), "Shopping")
        self.assertEqual(classify_app("com.doordash.DoorDash"), "Shopping")

    def test_pattern_matching_travel(self):
        self.assertEqual(classify_app("com.ubercab.UberClient"), "Travel")
        self.assertEqual(classify_app("com.airbnb.app"), "Travel")
        self.assertEqual(classify_app("com.waze.iphone"), "Travel")

    def test_pattern_matching_finance(self):
        self.assertEqual(classify_app("com.paypal.PPClient"), "Finance")
        self.assertEqual(classify_app("com.venmo"), "Finance")
        self.assertEqual(classify_app("com.chase.sig.android"), "Finance")

    def test_pattern_matching_health(self):
        self.assertEqual(classify_app("com.peloton.cycle"), "Health")
        self.assertEqual(classify_app("com.strava"), "Health")
        self.assertEqual(classify_app("com.calm.meditation"), "Health")

    def test_default_to_utilities(self):
        # Use bundle IDs that don't match any patterns
        self.assertEqual(classify_app("com.unknown.xyzqrs"), "Utilities")
        self.assertEqual(classify_app("net.obscure.thing"), "Utilities")

    def test_case_insensitive_matching(self):
        # Pattern matching should be case-insensitive
        self.assertEqual(classify_app("COM.SPOTIFY.CLIENT"), "Media")
        self.assertEqual(classify_app("Com.Slack"), "Work")
