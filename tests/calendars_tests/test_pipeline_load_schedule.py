"""Tests for calendars/pipeline.py _load_schedule_sources function."""
import tempfile
import unittest
from pathlib import Path

from tests.fixtures import has_pyyaml


class TestLoadScheduleSources(unittest.TestCase):
    """Tests for _load_schedule_sources helper function."""

    @unittest.skipUnless(has_pyyaml(), 'requires PyYAML')
    def test_load_schedule_sources_from_csv(self):
        """_load_schedule_sources should load items from CSV files."""
        from calendars.pipeline import _load_schedule_sources

        # Create a temporary CSV file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as tmp:
            tmp.write('Subject,Days,Times\n')
            tmp.write('Swim Class,Monday,5:00pm-5:30pm\n')
            tmp_path = Path(tmp.name)

        try:
            items = _load_schedule_sources([str(tmp_path)], kind='csv')
            self.assertGreater(len(items), 0)
            # Items should be normalized events (dicts)
            self.assertIsInstance(items[0], dict)
        finally:
            tmp_path.unlink(missing_ok=True)

    @unittest.skipUnless(has_pyyaml(), 'requires PyYAML')
    def test_load_schedule_sources_multiple_files(self):
        """_load_schedule_sources should load from multiple sources."""
        from calendars.pipeline import _load_schedule_sources

        # Create two CSV files
        files = []
        for i in range(2):
            tmp = tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False)
            tmp.write('Subject,Days,Times\n')
            tmp.write(f'Event {i},Monday,5:00pm-5:30pm\n')
            tmp.close()
            files.append(Path(tmp.name))

        try:
            items = _load_schedule_sources([str(f) for f in files], kind='csv')
            self.assertEqual(len(items), 2)
        finally:
            for f in files:
                f.unlink(missing_ok=True)

    @unittest.skipUnless(has_pyyaml(), 'requires PyYAML')
    def test_load_schedule_sources_normalizes_events(self):
        """_load_schedule_sources should normalize items to event dicts."""
        from calendars.pipeline import _load_schedule_sources

        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False) as tmp:
            tmp.write('Subject,Days,Times\n')
            tmp.write('Test Event,Monday,5:00pm-5:30pm\n')
            tmp_path = Path(tmp.name)

        try:
            items = _load_schedule_sources([str(tmp_path)], kind='csv')
            self.assertGreater(len(items), 0)
            # Should have subject, start, end keys (normalized event format)
            event = items[0]
            self.assertIn('subject', event)
        finally:
            tmp_path.unlink(missing_ok=True)

    @unittest.skipUnless(has_pyyaml(), 'requires PyYAML')
    def test_load_schedule_sources_empty_list(self):
        """_load_schedule_sources should return empty list for no sources."""
        from calendars.pipeline import _load_schedule_sources

        items = _load_schedule_sources([], kind='csv')
        self.assertEqual(items, [])
