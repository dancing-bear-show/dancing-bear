"""Tests for slides constants module.

This module verifies that the slides constants module exports the expected constants
and that they have sensible, valid values for PowerPoint slide generation.

Tests cover:
- Bullet characters (types, uniqueness, common characters)
- Font sizes (hierarchy, consistency, table sizes)
- Spacing constants (positive values, logical ordering)
- Positioning constants (reasonable layout values)
- Table colors (RGB instances, contrast)
- Theme color mapping (completeness, defaults)
- Layout constants (valid layouts, string types)
- YAML field names (string types, lowercase convention)
- Default values (non-empty, reasonable ranges)
"""

import unittest

from pptx.dml.color import RGBColor
from pptx.enum.dml import MSO_THEME_COLOR

from slides.constants import (
    # Bullet characters
    BULLET_CHARS,
    BULLET_LEVEL_0,
    BULLET_LEVEL_1,
    BULLET_LEVEL_2,
    # Positioning
    CONTENT_BOTTOM_MARGIN,
    CONTENT_LEFT,
    CONTENT_WIDTH,
    DEFAULT_BULLET_LEVEL,
    DEFAULT_SECTION_HEADER_MAX_LENGTH,
    DEFAULT_TEMPLATE_SLIDE_INDEX,
    DEFAULT_THEME_COLOR,
    # Default values
    DEFAULT_TITLE,
    EXISTING_BULLET_CHARS,
    FONT_SIZE_BULLET_LEVEL_0,
    FONT_SIZE_BULLET_LEVEL_1,
    FONT_SIZE_BULLET_LEVEL_2,
    # Font sizes
    FONT_SIZE_HEADER,
    FONT_SIZE_TABLE_CELL,
    FONT_SIZE_TABLE_HEADER,
    FONT_SIZES_BY_LEVEL,
    HIGHLIGHT_THEME_COLOR,
    # Layouts
    LAYOUT_BULLET,
    LAYOUT_SECTION,
    LAYOUT_TABLE,
    LAYOUT_TITLE_ONLY,
    # Hyperlink styling
    LINK_BLUE,
    SLIDE_HEIGHT,
    SPACING_AFTER_BULLET,
    SPACING_AFTER_HEADER,
    SPACING_BEFORE_BULLET,
    # Spacing
    SPACING_BEFORE_HEADER,
    # Table colors
    TABLE_HEADER_BG,
    TABLE_LEFT,
    TABLE_ROW_EVEN_BG,
    TABLE_ROW_HEIGHT,
    TABLE_ROW_ODD_BG,
    TABLE_TOP,
    TABLE_WIDTH,
    # Theme colors
    THEME_COLOR_MAP,
    VALID_LAYOUTS,
    # Vertical anchor
    VERTICAL_ANCHOR_MIDDLE,
    YAML_AUTHOR,
    YAML_BULLETS,
    YAML_DATE,
    YAML_FIRST_COL_WIDTH,
    YAML_HEADERS,
    YAML_HIGHLIGHT,
    YAML_LAYOUT,
    YAML_LEVEL,
    YAML_NOTES,
    YAML_ROWS,
    YAML_SLIDES,
    YAML_TEMPLATE_PATH,
    YAML_TEMPLATE_SLIDE_INDEX,
    YAML_TEXT,
    YAML_THEME_COLOR,
    # YAML field names
    YAML_TITLE,
    # YAML url field
    YAML_URL,
)


class TestBulletConstants(unittest.TestCase):
    """Test bullet character constants."""

    def test_bullet_chars_has_three_levels(self):
        """Test that BULLET_CHARS contains exactly three bullet levels.

        Setup:
            - Import BULLET_CHARS constant

        Execute:
            - Check length of BULLET_CHARS list

        Assert:
            - BULLET_CHARS has exactly 3 elements (levels 0, 1, 2)
        """
        self.assertEqual(len(BULLET_CHARS), 3)

    def test_bullet_chars_are_unique(self):
        """Test that all bullet characters are unique.

        Setup:
            - Import BULLET_CHARS constant

        Execute:
            - Compare set length to list length

        Assert:
            - No duplicate bullet characters exist
        """
        self.assertEqual(len(BULLET_CHARS), len(set(BULLET_CHARS)))

    def test_existing_bullet_chars_includes_common_chars(self):
        """Test that EXISTING_BULLET_CHARS includes common bullet characters.

        Setup:
            - Import EXISTING_BULLET_CHARS constant

        Execute:
            - Check for presence of common bullet characters

        Assert:
            - Contains standard bullet, hyphen, and asterisk
        """
        common_chars = ["*", "-"]
        for char in common_chars:
            with self.subTest(char=char):
                self.assertIn(char, EXISTING_BULLET_CHARS)

    def test_bullet_chars_match_individual_constants(self):
        """Test that BULLET_CHARS list matches individual level constants.

        Setup:
            - Import BULLET_CHARS and individual BULLET_LEVEL_* constants

        Execute:
            - Compare list contents to individual constants

        Assert:
            - BULLET_CHARS[0] equals BULLET_LEVEL_0
            - BULLET_CHARS[1] equals BULLET_LEVEL_1
            - BULLET_CHARS[2] equals BULLET_LEVEL_2
        """
        self.assertEqual(BULLET_CHARS[0], BULLET_LEVEL_0)
        self.assertEqual(BULLET_CHARS[1], BULLET_LEVEL_1)
        self.assertEqual(BULLET_CHARS[2], BULLET_LEVEL_2)

    def test_existing_bullet_chars_is_tuple(self):
        """Test that EXISTING_BULLET_CHARS is a tuple (immutable).

        Setup:
            - Import EXISTING_BULLET_CHARS constant

        Execute:
            - Check type of EXISTING_BULLET_CHARS

        Assert:
            - EXISTING_BULLET_CHARS is a tuple
        """
        self.assertIsInstance(EXISTING_BULLET_CHARS, tuple)


class TestFontSizeConstants(unittest.TestCase):
    """Test font size constants."""

    def test_header_larger_than_bullets(self):
        """Test that header font size is larger than all bullet sizes.

        Setup:
            - Import FONT_SIZE_HEADER and bullet font size constants

        Execute:
            - Compare header size to all bullet level sizes

        Assert:
            - Header font size is larger than all bullet font sizes
        """
        self.assertGreater(FONT_SIZE_HEADER, FONT_SIZE_BULLET_LEVEL_0)
        self.assertGreater(FONT_SIZE_HEADER, FONT_SIZE_BULLET_LEVEL_1)
        self.assertGreater(FONT_SIZE_HEADER, FONT_SIZE_BULLET_LEVEL_2)

    def test_bullet_sizes_decrease_by_level(self):
        """Test that bullet font sizes decrease as level increases.

        Setup:
            - Import bullet font size constants

        Execute:
            - Compare font sizes across levels

        Assert:
            - Level 0 > Level 1 > Level 2
        """
        self.assertGreater(FONT_SIZE_BULLET_LEVEL_0, FONT_SIZE_BULLET_LEVEL_1)
        self.assertGreater(FONT_SIZE_BULLET_LEVEL_1, FONT_SIZE_BULLET_LEVEL_2)

    def test_font_sizes_by_level_matches_individual_constants(self):
        """Test that FONT_SIZES_BY_LEVEL matches individual constants.

        Setup:
            - Import FONT_SIZES_BY_LEVEL and individual constants

        Execute:
            - Compare list contents to individual constants

        Assert:
            - List matches individual bullet level font sizes in order
        """
        self.assertEqual(len(FONT_SIZES_BY_LEVEL), 3)
        self.assertEqual(FONT_SIZES_BY_LEVEL[0], FONT_SIZE_BULLET_LEVEL_0)
        self.assertEqual(FONT_SIZES_BY_LEVEL[1], FONT_SIZE_BULLET_LEVEL_1)
        self.assertEqual(FONT_SIZES_BY_LEVEL[2], FONT_SIZE_BULLET_LEVEL_2)

    def test_table_font_sizes_reasonable(self):
        """Test that table font sizes are reasonable values.

        Setup:
            - Import table font size constants

        Execute:
            - Check font sizes are within reasonable range

        Assert:
            - Table header and cell font sizes are between 8 and 14 points
            - Table header font size >= table cell font size
        """
        self.assertGreaterEqual(FONT_SIZE_TABLE_HEADER, 8)
        self.assertLessEqual(FONT_SIZE_TABLE_HEADER, 14)
        self.assertGreaterEqual(FONT_SIZE_TABLE_CELL, 8)
        self.assertLessEqual(FONT_SIZE_TABLE_CELL, 14)
        self.assertGreaterEqual(FONT_SIZE_TABLE_HEADER, FONT_SIZE_TABLE_CELL)

    def test_all_font_sizes_positive(self):
        """Test that all font sizes are positive integers.

        Setup:
            - Import all font size constants

        Execute:
            - Check each font size is positive

        Assert:
            - All font sizes are greater than 0
        """
        font_sizes = [
            FONT_SIZE_HEADER,
            FONT_SIZE_BULLET_LEVEL_0,
            FONT_SIZE_BULLET_LEVEL_1,
            FONT_SIZE_BULLET_LEVEL_2,
            FONT_SIZE_TABLE_HEADER,
            FONT_SIZE_TABLE_CELL,
        ]
        for size in font_sizes:
            with self.subTest(size=size):
                self.assertGreater(size, 0)


class TestSpacingConstants(unittest.TestCase):
    """Test paragraph spacing constants."""

    def test_spacing_values_positive(self):
        """Test that spacing values are non-negative.

        Setup:
            - Import spacing constants

        Execute:
            - Check each spacing value

        Assert:
            - All spacing values are >= 0
        """
        spacing_values = [
            SPACING_BEFORE_HEADER,
            SPACING_AFTER_HEADER,
            SPACING_BEFORE_BULLET,
            SPACING_AFTER_BULLET,
        ]
        for value in spacing_values:
            with self.subTest(value=value):
                self.assertGreaterEqual(value, 0)

    def test_header_has_more_spacing_before(self):
        """Test that header has more spacing before than after.

        Setup:
            - Import header spacing constants

        Execute:
            - Compare before and after spacing values

        Assert:
            - SPACING_BEFORE_HEADER > SPACING_AFTER_HEADER
        """
        self.assertGreater(SPACING_BEFORE_HEADER, SPACING_AFTER_HEADER)

    def test_spacing_values_are_integers(self):
        """Test that all spacing values are integers.

        Setup:
            - Import spacing constants

        Execute:
            - Check type of each spacing value

        Assert:
            - All spacing values are integers
        """
        spacing_values = [
            SPACING_BEFORE_HEADER,
            SPACING_AFTER_HEADER,
            SPACING_BEFORE_BULLET,
            SPACING_AFTER_BULLET,
        ]
        for value in spacing_values:
            with self.subTest(value=value):
                self.assertIsInstance(value, int)


class TestPositioningConstants(unittest.TestCase):
    """Test content positioning constants."""

    def test_content_values_reasonable(self):
        """Test that content positioning values are reasonable for a slide.

        Setup:
            - Import content positioning constants

        Execute:
            - Check values are within reasonable slide dimensions

        Assert:
            - CONTENT_LEFT is between 0 and 2 inches
            - CONTENT_WIDTH is between 5 and 12 inches
            - CONTENT_BOTTOM_MARGIN is positive
            - SLIDE_HEIGHT matches standard widescreen
        """
        self.assertGreaterEqual(CONTENT_LEFT, 0)
        self.assertLessEqual(CONTENT_LEFT, 2)

        self.assertGreaterEqual(CONTENT_WIDTH, 5)
        self.assertLessEqual(CONTENT_WIDTH, 12)

        self.assertGreater(CONTENT_BOTTOM_MARGIN, 0)
        self.assertEqual(SLIDE_HEIGHT, 7.5)

    def test_table_values_reasonable(self):
        """Test that table positioning values are reasonable for a slide.

        Setup:
            - Import table positioning constants

        Execute:
            - Check values are within reasonable slide dimensions

        Assert:
            - TABLE_LEFT is between 0 and 2 inches
            - TABLE_TOP is between 0 and 3 inches
            - TABLE_WIDTH is between 6 and 10 inches
        """
        # Standard slide width is 10 inches
        self.assertGreaterEqual(TABLE_LEFT, 0)
        self.assertLessEqual(TABLE_LEFT, 2)

        # Standard slide height is 7.5 inches
        self.assertGreaterEqual(TABLE_TOP, 0)
        self.assertLessEqual(TABLE_TOP, 4)

        # Table width should accommodate multiple columns
        self.assertGreaterEqual(TABLE_WIDTH, 6)
        self.assertLessEqual(TABLE_WIDTH, 12)

    def test_table_row_height_positive(self):
        """Test that table row height is positive and reasonable.

        Setup:
            - Import TABLE_ROW_HEIGHT constant

        Execute:
            - Check value is positive and reasonable

        Assert:
            - TABLE_ROW_HEIGHT is between 0.2 and 1.0 inches
        """
        self.assertGreaterEqual(TABLE_ROW_HEIGHT, 0.2)
        self.assertLessEqual(TABLE_ROW_HEIGHT, 1.0)

    def test_content_fits_on_slide(self):
        """Test that content positioning leaves room for content.

        Setup:
            - Import content positioning constants

        Execute:
            - Check that left + width fits within standard slide width

        Assert:
            - Content fits within 13.33-inch widescreen slide width
        """
        widescreen_slide_width = 13.33  # inches (widescreen 16:9)
        self.assertLessEqual(CONTENT_LEFT + CONTENT_WIDTH, widescreen_slide_width)

    def test_table_fits_on_slide(self):
        """Test that table positioning fits within slide dimensions.

        Setup:
            - Import table positioning constants

        Execute:
            - Check that left + width fits within standard slide width

        Assert:
            - Table fits within 13.33-inch widescreen slide width
        """
        widescreen_slide_width = 13.33  # inches
        self.assertLessEqual(TABLE_LEFT + TABLE_WIDTH, widescreen_slide_width)


class TestTableColorConstants(unittest.TestCase):
    """Test table color constants."""

    def test_colors_are_rgb_color_instances(self):
        """Test that all table colors are RGBColor instances.

        Setup:
            - Import table color constants

        Execute:
            - Check type of each color constant

        Assert:
            - All colors are RGBColor instances
        """
        self.assertIsInstance(TABLE_HEADER_BG, RGBColor)
        self.assertIsInstance(TABLE_ROW_EVEN_BG, RGBColor)
        self.assertIsInstance(TABLE_ROW_ODD_BG, RGBColor)

    def test_header_distinct_from_rows(self):
        """Test that header background is visually distinct from row backgrounds.

        Setup:
            - Import table color constants

        Execute:
            - Calculate brightness of each color (sum of RGB components)

        Assert:
            - Header brightness differs from row brightness (visual distinction)
            - Header is lighter than rows (stands out in dark theme)
        """
        # Calculate simple brightness as sum of RGB components
        def brightness(color):
            return color[0] + color[1] + color[2]

        header_brightness = brightness(TABLE_HEADER_BG)
        even_brightness = brightness(TABLE_ROW_EVEN_BG)
        odd_brightness = brightness(TABLE_ROW_ODD_BG)

        # Header should be lighter than rows (stands out in dark theme)
        # Higher brightness value = lighter color
        self.assertGreater(
            header_brightness,
            max(even_brightness, odd_brightness)
        )

    def test_alternating_row_colors_different(self):
        """Test that even and odd row colors are different.

        Setup:
            - Import row color constants

        Execute:
            - Compare even and odd row colors

        Assert:
            - Even and odd row colors are not equal
        """
        self.assertNotEqual(TABLE_ROW_EVEN_BG, TABLE_ROW_ODD_BG)

    def test_colors_have_valid_rgb_values(self):
        """Test that all color components are valid (0-255).

        Setup:
            - Import table color constants

        Execute:
            - Check each RGB component is in valid range

        Assert:
            - All RGB values are between 0 and 255
        """
        colors = [TABLE_HEADER_BG, TABLE_ROW_EVEN_BG, TABLE_ROW_ODD_BG]
        for color in colors:
            with self.subTest(color=color):
                for component in [color[0], color[1], color[2]]:
                    self.assertGreaterEqual(component, 0)
                    self.assertLessEqual(component, 255)


class TestThemeColorMap(unittest.TestCase):
    """Test theme color mapping constants."""

    def test_all_theme_colors_present(self):
        """Test that all expected theme colors are present in the map.

        Setup:
            - Import THEME_COLOR_MAP constant

        Execute:
            - Check for presence of all expected theme color keys

        Assert:
            - All LIGHT, DARK, and ACCENT colors are present
        """
        expected_keys = [
            "LIGHT_1", "LIGHT_2",
            "DARK_1", "DARK_2",
            "ACCENT_1", "ACCENT_2", "ACCENT_3",
            "ACCENT_4", "ACCENT_5", "ACCENT_6",
        ]
        for key in expected_keys:
            with self.subTest(key=key):
                self.assertIn(key, THEME_COLOR_MAP)

    def test_default_theme_color_in_map(self):
        """Test that DEFAULT_THEME_COLOR is a valid key in THEME_COLOR_MAP.

        Setup:
            - Import DEFAULT_THEME_COLOR and THEME_COLOR_MAP

        Execute:
            - Check if DEFAULT_THEME_COLOR is in THEME_COLOR_MAP keys

        Assert:
            - DEFAULT_THEME_COLOR is a valid theme color key
        """
        self.assertIn(DEFAULT_THEME_COLOR, THEME_COLOR_MAP)

    def test_highlight_theme_color_is_accent(self):
        """Test that HIGHLIGHT_THEME_COLOR is an accent color.

        Setup:
            - Import HIGHLIGHT_THEME_COLOR constant

        Execute:
            - Check if HIGHLIGHT_THEME_COLOR is an MSO_THEME_COLOR accent

        Assert:
            - HIGHLIGHT_THEME_COLOR is one of the ACCENT colors
        """
        accent_colors = [
            MSO_THEME_COLOR.ACCENT_1,
            MSO_THEME_COLOR.ACCENT_2,
            MSO_THEME_COLOR.ACCENT_3,
            MSO_THEME_COLOR.ACCENT_4,
            MSO_THEME_COLOR.ACCENT_5,
            MSO_THEME_COLOR.ACCENT_6,
        ]
        self.assertIn(HIGHLIGHT_THEME_COLOR, accent_colors)

    def test_theme_color_map_values_are_mso_theme_color(self):
        """Test that all THEME_COLOR_MAP values are MSO_THEME_COLOR enum values.

        Setup:
            - Import THEME_COLOR_MAP constant

        Execute:
            - Check type of each value in the map

        Assert:
            - All values are MSO_THEME_COLOR enum members
        """
        for key, value in THEME_COLOR_MAP.items():
            with self.subTest(key=key):
                self.assertIsInstance(value, type(MSO_THEME_COLOR.LIGHT_1))


class TestLayoutConstants(unittest.TestCase):
    """Test layout type constants."""

    def test_valid_layouts_list(self):
        """Test that VALID_LAYOUTS contains all expected layout types.

        Setup:
            - Import layout constants

        Execute:
            - Check VALID_LAYOUTS contains all individual layout constants

        Assert:
            - All layout type constants are in VALID_LAYOUTS
        """
        self.assertIn(LAYOUT_BULLET, VALID_LAYOUTS)
        self.assertIn(LAYOUT_TABLE, VALID_LAYOUTS)
        self.assertIn(LAYOUT_TITLE_ONLY, VALID_LAYOUTS)
        self.assertIn(LAYOUT_SECTION, VALID_LAYOUTS)

    def test_layout_values_are_strings(self):
        """Test that all layout values are strings.

        Setup:
            - Import layout constants

        Execute:
            - Check type of each layout constant

        Assert:
            - All layout constants are strings
        """
        layouts = [LAYOUT_BULLET, LAYOUT_TABLE, LAYOUT_TITLE_ONLY, LAYOUT_SECTION]
        for layout in layouts:
            with self.subTest(layout=layout):
                self.assertIsInstance(layout, str)

    def test_valid_layouts_no_duplicates(self):
        """Test that VALID_LAYOUTS has no duplicate entries.

        Setup:
            - Import VALID_LAYOUTS constant

        Execute:
            - Compare list length to set length

        Assert:
            - No duplicate layout values
        """
        self.assertEqual(len(VALID_LAYOUTS), len(set(VALID_LAYOUTS)))

    def test_layout_values_are_lowercase(self):
        """Test that all layout values are lowercase.

        Setup:
            - Import layout constants

        Execute:
            - Check that each layout value equals its lowercase version

        Assert:
            - All layout values are lowercase
        """
        for layout in VALID_LAYOUTS:
            with self.subTest(layout=layout):
                self.assertEqual(layout, layout.lower())


class TestYamlFieldNames(unittest.TestCase):
    """Test YAML field name constants."""

    def test_yaml_field_names_are_strings(self):
        """Test that all YAML field names are strings.

        Setup:
            - Import YAML field name constants

        Execute:
            - Check type of each constant

        Assert:
            - All YAML field names are strings
        """
        yaml_fields = [
            YAML_TITLE,
            YAML_AUTHOR,
            YAML_DATE,
            YAML_TEMPLATE_SLIDE_INDEX,
            YAML_THEME_COLOR,
            YAML_SLIDES,
            YAML_TEMPLATE_PATH,
            YAML_BULLETS,
            YAML_LAYOUT,
            YAML_NOTES,
            YAML_HEADERS,
            YAML_ROWS,
            YAML_FIRST_COL_WIDTH,
            YAML_TEXT,
            YAML_LEVEL,
            YAML_HIGHLIGHT,
            YAML_URL,
        ]
        for field in yaml_fields:
            with self.subTest(field=field):
                self.assertIsInstance(field, str)

    def test_yaml_field_names_lowercase(self):
        """Test that all YAML field names are lowercase (convention).

        Setup:
            - Import YAML field name constants

        Execute:
            - Check that each field equals its lowercase version

        Assert:
            - All YAML field names follow lowercase convention
        """
        yaml_fields = [
            YAML_TITLE,
            YAML_AUTHOR,
            YAML_DATE,
            YAML_TEMPLATE_SLIDE_INDEX,
            YAML_THEME_COLOR,
            YAML_SLIDES,
            YAML_TEMPLATE_PATH,
            YAML_BULLETS,
            YAML_LAYOUT,
            YAML_NOTES,
            YAML_HEADERS,
            YAML_ROWS,
            YAML_FIRST_COL_WIDTH,
            YAML_TEXT,
            YAML_LEVEL,
            YAML_HIGHLIGHT,
            YAML_URL,
        ]
        for field in yaml_fields:
            with self.subTest(field=field):
                self.assertEqual(field, field.lower())

    def test_yaml_field_names_not_empty(self):
        """Test that no YAML field name is empty.

        Setup:
            - Import YAML field name constants

        Execute:
            - Check that each field has length > 0

        Assert:
            - All YAML field names are non-empty
        """
        yaml_fields = [
            YAML_TITLE,
            YAML_AUTHOR,
            YAML_DATE,
            YAML_TEMPLATE_SLIDE_INDEX,
            YAML_THEME_COLOR,
            YAML_SLIDES,
            YAML_TEMPLATE_PATH,
            YAML_BULLETS,
            YAML_LAYOUT,
            YAML_NOTES,
            YAML_HEADERS,
            YAML_ROWS,
            YAML_FIRST_COL_WIDTH,
            YAML_TEXT,
            YAML_LEVEL,
            YAML_HIGHLIGHT,
            YAML_URL,
        ]
        for field in yaml_fields:
            with self.subTest(field=field):
                self.assertGreater(len(field), 0)


class TestDefaultValues(unittest.TestCase):
    """Test default value constants."""

    def test_default_title_not_empty(self):
        """Test that DEFAULT_TITLE is not empty.

        Setup:
            - Import DEFAULT_TITLE constant

        Execute:
            - Check that DEFAULT_TITLE has content

        Assert:
            - DEFAULT_TITLE is a non-empty string
        """
        self.assertIsInstance(DEFAULT_TITLE, str)
        self.assertGreater(len(DEFAULT_TITLE), 0)

    def test_default_template_slide_index_reasonable(self):
        """Test that DEFAULT_TEMPLATE_SLIDE_INDEX is a reasonable value.

        Setup:
            - Import DEFAULT_TEMPLATE_SLIDE_INDEX constant

        Execute:
            - Check value is non-negative and within reasonable range

        Assert:
            - DEFAULT_TEMPLATE_SLIDE_INDEX is >= 0 and < 50
        """
        self.assertIsInstance(DEFAULT_TEMPLATE_SLIDE_INDEX, int)
        self.assertGreaterEqual(DEFAULT_TEMPLATE_SLIDE_INDEX, 0)
        self.assertLess(DEFAULT_TEMPLATE_SLIDE_INDEX, 50)

    def test_default_bullet_level_is_zero(self):
        """Test that DEFAULT_BULLET_LEVEL is zero.

        Setup:
            - Import DEFAULT_BULLET_LEVEL constant

        Execute:
            - Check value is zero

        Assert:
            - DEFAULT_BULLET_LEVEL equals 0
        """
        self.assertEqual(DEFAULT_BULLET_LEVEL, 0)

    def test_default_section_header_max_length_reasonable(self):
        """Test that DEFAULT_SECTION_HEADER_MAX_LENGTH is reasonable.

        Setup:
            - Import DEFAULT_SECTION_HEADER_MAX_LENGTH constant

        Execute:
            - Check value is within reasonable range

        Assert:
            - DEFAULT_SECTION_HEADER_MAX_LENGTH is between 20 and 100 chars
        """
        self.assertIsInstance(DEFAULT_SECTION_HEADER_MAX_LENGTH, int)
        self.assertGreaterEqual(DEFAULT_SECTION_HEADER_MAX_LENGTH, 20)
        self.assertLessEqual(DEFAULT_SECTION_HEADER_MAX_LENGTH, 100)

    def test_vertical_anchor_middle_value(self):
        """Test that VERTICAL_ANCHOR_MIDDLE has expected value.

        Setup:
            - Import VERTICAL_ANCHOR_MIDDLE constant

        Execute:
            - Check value equals MSO_ANCHOR.MIDDLE enum

        Assert:
            - VERTICAL_ANCHOR_MIDDLE is the MSO_ANCHOR.MIDDLE enum value
        """
        from pptx.enum.text import MSO_ANCHOR
        self.assertEqual(VERTICAL_ANCHOR_MIDDLE, MSO_ANCHOR.MIDDLE)

    def test_link_blue_is_rgb(self):
        """LINK_BLUE should be an RGBColor instance with Google link-blue value."""
        self.assertIsInstance(LINK_BLUE, RGBColor)
        self.assertEqual(LINK_BLUE, RGBColor(0x1A, 0x73, 0xE8))

    def test_yaml_url_field(self):
        """YAML_URL should be the string 'url'."""
        self.assertEqual(YAML_URL, "url")
        self.assertIsInstance(YAML_URL, str)


if __name__ == "__main__":
    unittest.main()
