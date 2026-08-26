"""Shared test fixtures for slides parser tests."""

from __future__ import annotations

import unittest

from slides.schema import SlideDeck


def assert_metadata_passthrough(
    case: unittest.TestCase,
    deck: SlideDeck,
    *,
    author: str,
    template_path: str,
    template_slide_index: int,
    theme_color: str,
) -> None:
    """Assert author/template_path/template_slide_index/theme_color propagated to deck.

    Shared by the csv, markdown, and outline parser metadata-passthrough tests,
    which all exercise the identical author/template_path/template_slide_index/
    theme_color contract against their respective loader.
    """
    case.assertEqual(deck.metadata.author, author)
    case.assertEqual(deck.template_path, template_path)
    case.assertEqual(deck.metadata.template_slide_index, template_slide_index)
    case.assertEqual(deck.metadata.theme_color, theme_color)
