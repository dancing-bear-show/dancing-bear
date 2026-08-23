"""Unit tests for the slides CSV loader."""

import tempfile
import unittest
from pathlib import Path

from slides.parsers_csv import load_deck_from_csv
from slides.schema import BulletItem, TableSlide


# ---------------------------------------------------------------------------
# load_deck_from_csv
# ---------------------------------------------------------------------------

class TestLoadDeckFromCsv(unittest.TestCase):
    """Tests for load_deck_from_csv."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmpdir.name)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write(self, name: str, content: str) -> Path:
        p = self.tmp_path / name
        p.write_text(content, encoding="utf-8")
        return p

    def test_bullet_mode(self):
        """CSV with slide_title/summary columns groups into bullet slides."""
        csv_file = self._write(
            "bullets.csv",
            "slide_title,summary\n"
            "Intro,Welcome\n"
            "Intro,Overview\n"
            "Details,Point A\n",
        )

        deck = load_deck_from_csv(csv_file, title="CSV Deck")
        self.assertEqual(deck.metadata.title, "CSV Deck")
        self.assertEqual(len(deck.slides), 2)
        self.assertEqual(deck.slides[0].title, "Intro")
        self.assertEqual(len(deck.slides[0].bullets), 2)
        self.assertEqual(deck.slides[1].title, "Details")
        self.assertEqual(len(deck.slides[1].bullets), 1)

    def test_table_mode(self):
        """CSV without title column creates a table slide."""
        csv_file = self._write(
            "table.csv",
            "name,value,status\n"
            "SvcA,99.9%,OK\n"
            "SvcB,98.5%,WARN\n",
        )

        deck = load_deck_from_csv(csv_file, title="Table Deck")
        self.assertEqual(len(deck.slides), 1)
        slide = deck.slides[0]
        self.assertIsInstance(slide, TableSlide)
        self.assertEqual(slide.headers, ["name", "value", "status"])
        self.assertEqual(len(slide.rows), 2)
        self.assertEqual(slide.rows[0], ["SvcA", "99.9%", "OK"])

    def test_empty_csv(self):
        """Empty CSV produces deck with no slides."""
        csv_file = self._write("empty.csv", "slide_title,summary\n")

        deck = load_deck_from_csv(csv_file, title="Empty")
        self.assertEqual(len(deck.slides), 0)
        self.assertEqual(deck.metadata.title, "Empty")

    def test_custom_column_names(self):
        """Custom title_column and text_column parameters work."""
        csv_file = self._write(
            "custom.csv",
            "heading,body\n"
            "Topic A,Content 1\n"
            "Topic A,Content 2\n",
        )

        deck = load_deck_from_csv(
            csv_file,
            title_column="heading",
            text_column="body",
        )
        self.assertEqual(len(deck.slides), 1)
        self.assertEqual(deck.slides[0].title, "Topic A")
        self.assertEqual(len(deck.slides[0].bullets), 2)

    def test_auto_pagination_csv(self):
        """CSV bullet mode respects bullet_limit for auto-pagination."""
        rows = "\n".join(f"Topic,Bullet {i}" for i in range(10))
        csv_file = self._write("long.csv", f"slide_title,summary\n{rows}\n")

        deck = load_deck_from_csv(csv_file, bullet_limit=4)
        self.assertGreater(len(deck.slides), 2)
        self.assertIn("(cont.)", deck.slides[1].title)

    def test_metadata_passthrough(self):
        """Author, template_path, theme_color pass through."""
        csv_file = self._write("meta.csv", "slide_title,summary\nA,B\n")

        deck = load_deck_from_csv(
            csv_file,
            author="Charlie",
            template_path="/tmp/t.pptx",  # nosec B108 - mock path arg, no file read
            template_slide_index=7,
            theme_color="ACCENT_3",
        )
        self.assertEqual(deck.metadata.author, "Charlie")
        self.assertEqual(deck.template_path, "/tmp/t.pptx")  # nosec B108 - asserting on mock data value
        self.assertEqual(deck.metadata.template_slide_index, 7)
        self.assertEqual(deck.metadata.theme_color, "ACCENT_3")

    def test_empty_text_rows_skipped(self):
        """Rows with empty summary text are skipped."""
        csv_file = self._write(
            "gaps.csv",
            "slide_title,summary\n"
            "Topic,Content\n"
            "Topic,\n"
            "Topic,More content\n",
        )

        deck = load_deck_from_csv(csv_file)
        self.assertEqual(len(deck.slides[0].bullets), 2)

    def test_table_mode_no_crash(self):
        """CSV table-data path (no title_column/text_column) does not crash in _chunk_slides."""
        csv_file = self._write(
            "table_only.csv",
            "host,cpu,memory\n"
            "web-1,45%,2GB\n"
            "web-2,78%,4GB\n"
            "web-3,12%,1GB\n",
        )

        deck = load_deck_from_csv(csv_file, title="Table Test")
        self.assertEqual(len(deck.slides), 1)
        slide = deck.slides[0]
        self.assertIsInstance(slide, TableSlide)
        self.assertEqual(slide.title, "Table Test")
        self.assertEqual(slide.headers, ["host", "cpu", "memory"])
        self.assertEqual(len(slide.rows), 3)

    def test_highlights_in_csv_text(self):
        """Bold markdown in CSV summary text produces highlights."""
        csv_file = self._write(
            "highlights.csv",
            "slide_title,summary\n"
            "Topic,Use **terraform** carefully\n",
        )

        deck = load_deck_from_csv(csv_file)
        bullet = deck.slides[0].bullets[0]
        self.assertIsInstance(bullet, BulletItem)
        self.assertIn("terraform", bullet.highlight)

if __name__ == "__main__":
    unittest.main()
