"""Tests for CLI helper functions in resume/cli/main.py."""
import tempfile
import unittest
from pathlib import Path

from resume.cli.main import (
    _try_load_structure,
    _find_structure_in_dirs,
    _find_structure_in_config,
)


class TestTryLoadStructure(unittest.TestCase):
    """Tests for _try_load_structure helper."""

    def test_loads_existing_yaml(self):
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            f.write("sections:\n  - experience\n  - education\n")
            f.flush()
            path = Path(f.name)
        try:
            result = _try_load_structure(path)
            self.assertEqual(result, {"sections": ["experience", "education"]})
        finally:
            path.unlink()

    def test_loads_existing_json(self):
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            f.write('{"sections": ["skills"]}')
            f.flush()
            path = Path(f.name)
        try:
            result = _try_load_structure(path)
            self.assertEqual(result, {"sections": ["skills"]})
        finally:
            path.unlink()

    def test_returns_none_for_missing_file(self):
        result = _try_load_structure(Path("/nonexistent/file.yaml"))
        self.assertIsNone(result)

    def test_returns_none_for_invalid_yaml(self):
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False, mode="w") as f:
            f.write("invalid: yaml: content: [")
            f.flush()
            path = Path(f.name)
        try:
            result = _try_load_structure(path)
            self.assertIsNone(result)
        finally:
            path.unlink()


class TestFindStructureInDirs(unittest.TestCase):
    """Tests for _find_structure_in_dirs helper."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_finds_nested_structure(self):
        # Create nested structure: temp_dir/myprofile/structure.yaml
        prof_dir = self.temp_dir / "myprofile"
        prof_dir.mkdir()
        (prof_dir / "structure.yaml").write_text("order: [experience]\n")

        result = _find_structure_in_dirs("myprofile", [self.temp_dir])
        self.assertEqual(result, {"order": ["experience"]})

    def test_finds_legacy_flat_structure(self):
        # Create legacy structure: temp_dir/myprofile.structure.yaml
        (self.temp_dir / "myprofile.structure.yaml").write_text("order: [skills]\n")

        result = _find_structure_in_dirs("myprofile", [self.temp_dir])
        self.assertEqual(result, {"order": ["skills"]})

    def test_prefers_nested_over_legacy(self):
        # Create both nested and legacy
        prof_dir = self.temp_dir / "myprofile"
        prof_dir.mkdir()
        (prof_dir / "structure.yaml").write_text("source: nested\n")
        (self.temp_dir / "myprofile.structure.yaml").write_text("source: legacy\n")

        result = _find_structure_in_dirs("myprofile", [self.temp_dir])
        self.assertEqual(result, {"source": "nested"})

    def test_searches_multiple_dirs(self):
        second_dir = self.temp_dir / "second"
        second_dir.mkdir()
        (second_dir / "myprofile.structure.json").write_text('{"found": true}')

        result = _find_structure_in_dirs("myprofile", [self.temp_dir, second_dir])
        self.assertEqual(result, {"found": True})

    def test_returns_none_when_not_found(self):
        result = _find_structure_in_dirs("nonexistent", [self.temp_dir])
        self.assertIsNone(result)

    def test_tries_multiple_extensions(self):
        prof_dir = self.temp_dir / "myprofile"
        prof_dir.mkdir()
        (prof_dir / "structure.yml").write_text("ext: yml\n")

        result = _find_structure_in_dirs("myprofile", [self.temp_dir])
        self.assertEqual(result, {"ext": "yml"})


class TestFindStructureInConfig(unittest.TestCase):
    """Tests for _find_structure_in_config helper."""

    def setUp(self):
        self.config_dir = Path("config") / "profiles" / "test_cli_profile"
        self.config_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.config_dir, ignore_errors=True)

    def test_finds_config_structure(self):
        (self.config_dir / "structure.yaml").write_text("from: config\n")

        result = _find_structure_in_config("test_cli_profile")
        self.assertEqual(result, {"from": "config"})

    def test_returns_none_when_not_found(self):
        result = _find_structure_in_config("nonexistent_profile")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main(verbosity=2)
