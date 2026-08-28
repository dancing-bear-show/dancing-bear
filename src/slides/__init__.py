"""Slide deck generation from YAML definitions and multiple input formats."""

from slides.constants import (
    DEFAULT_TEMPLATE_SLIDE_INDEX,
    DEFAULT_THEME_COLOR,
    VALID_LAYOUTS,
)
from slides.generator import (
    SlideGenerator,
    generate_from_yaml,
    generate_pptx,
    load_deck_from_yaml,
)
from slides.parsers_csv import load_deck_from_csv
from slides.parsers_dict import load_deck_from_dict
from slides.parsers_markdown import (
    load_deck_from_markdown,
    load_deck_from_outline,
)
from slides.schema import (
    BulletItem,
    DeckMetadata,
    DeckOptions,
    SlideContent,
    SlideDeck,
    TableSlide,
)

__all__ = [
    "DEFAULT_TEMPLATE_SLIDE_INDEX",
    # Constants
    "DEFAULT_THEME_COLOR",
    "VALID_LAYOUTS",
    # Schema dataclasses
    "BulletItem",
    "DeckMetadata",
    "DeckOptions",
    "SlideContent",
    "SlideDeck",
    # Generator class and functions
    "SlideGenerator",
    "TableSlide",
    "generate_from_yaml",
    "generate_pptx",
    # Parsers (multiple input formats)
    "load_deck_from_csv",
    "load_deck_from_dict",
    "load_deck_from_markdown",
    "load_deck_from_outline",
    "load_deck_from_yaml",
]
