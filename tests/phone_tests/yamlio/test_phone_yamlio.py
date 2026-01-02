"""Tests for phone/yamlio.py wrapper functions."""
import tempfile
import unittest
from pathlib import Path

from phone.yamlio import dump_config, load_config


class TestLoadConfig(unittest.TestCase):
    """Tests for load_config function."""

    def test_load_config_with_none_returns_empty_dict(self):
        """load_config(None) should return empty dict."""
        result = load_config(None)
        self.assertEqual(result, {})

    def test_load_config_with_valid_yaml(self):
        """load_config should load YAML file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write('key: value\nlist:\n  - item1\n  - item2\n')
            f.flush()
            path = f.name

        try:
            result = load_config(path)
            self.assertEqual(result['key'], 'value')
            self.assertEqual(result['list'], ['item1', 'item2'])
        finally:
            Path(path).unlink()

    def test_load_config_with_path_object(self):
        """load_config should accept Path objects."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write('test: data\n')
            f.flush()
            path = Path(f.name)

        try:
            result = load_config(path)
            self.assertEqual(result['test'], 'data')
        finally:
            path.unlink()


class TestDumpConfig(unittest.TestCase):
    """Tests for dump_config function."""

    def test_dump_config_creates_yaml_file(self):
        """dump_config should write YAML to file."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            path = f.name

        try:
            data = {'key': 'value', 'list': ['a', 'b', 'c']}
            dump_config(path, data)

            # Verify file was created and contains correct data
            result = load_config(path)
            self.assertEqual(result, data)
        finally:
            Path(path).unlink()

    def test_dump_config_with_path_object(self):
        """dump_config should accept Path objects."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            path = Path(f.name)

        try:
            data = {'test': 'value'}
            dump_config(path, data)

            result = load_config(path)
            self.assertEqual(result, data)
        finally:
            path.unlink()

    def test_dump_config_creates_parent_directories(self):
        """dump_config should create parent directories if needed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / 'nested' / 'dir' / 'config.yaml'

            data = {'nested': 'config'}
            dump_config(path, data)

            self.assertTrue(path.exists())
            result = load_config(path)
            self.assertEqual(result, data)


if __name__ == '__main__':
    unittest.main()
