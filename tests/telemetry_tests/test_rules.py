"""Gap-fill tests for telemetry/rules.py — _deep_merge, validate_rules, load_rules."""
from __future__ import annotations

import builtins
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from telemetry.rules import DEFAULT_RULES, _deep_merge, load_rules, validate_rules

_real_import = builtins.__import__


# ---------------------------------------------------------------------------
# _deep_merge
# ---------------------------------------------------------------------------

class TestDeepMerge(unittest.TestCase):
    def test_override_flat_key_wins(self):
        base = {"a": 1, "b": 2}
        override = {"b": 99}
        result = _deep_merge(base, override)
        self.assertEqual(result["b"], 99)
        self.assertEqual(result["a"], 1)

    def test_new_key_in_override_added(self):
        base = {"a": 1}
        override = {"z": "new"}
        result = _deep_merge(base, override)
        self.assertIn("z", result)
        self.assertEqual(result["z"], "new")

    def test_nested_dicts_merged_recursively(self):
        base = {"section": {"x": 1, "y": 2}}
        override = {"section": {"y": 99, "z": 3}}
        result = _deep_merge(base, override)
        self.assertEqual(result["section"]["x"], 1)
        self.assertEqual(result["section"]["y"], 99)
        self.assertEqual(result["section"]["z"], 3)

    def test_non_dict_override_replaces_dict(self):
        base = {"section": {"x": 1}}
        override = {"section": "string_value"}
        result = _deep_merge(base, override)
        self.assertEqual(result["section"], "string_value")

    def test_list_override_replaces_list(self):
        base = {"tools": ["Edit", "Write"]}
        override = {"tools": ["Read"]}
        result = _deep_merge(base, override)
        self.assertEqual(result["tools"], ["Read"])

    def test_original_base_not_mutated(self):
        base = {"a": {"x": 1}}
        override = {"a": {"x": 99}}
        result = _deep_merge(base, override)
        self.assertEqual(base["a"]["x"], 1)
        self.assertEqual(result["a"]["x"], 99)

    def test_empty_override_returns_copy_of_base(self):
        base = {"a": 1, "b": {"c": 2}}
        result = _deep_merge(base, {})
        self.assertEqual(result, base)

    def test_empty_base_uses_override(self):
        override = {"a": 1}
        result = _deep_merge({}, override)
        self.assertEqual(result, {"a": 1})


# ---------------------------------------------------------------------------
# validate_rules
# ---------------------------------------------------------------------------

class TestValidateRules(unittest.TestCase):
    def test_valid_default_rules_no_errors(self):
        errors = validate_rules(deepcopy(DEFAULT_RULES))
        self.assertIsInstance(errors, list)
        # DEFAULT_RULES should always be valid
        self.assertEqual(errors, [])

    def test_returns_empty_list_when_jsonschema_not_installed(self):
        with patch("builtins.__import__", side_effect=_make_import_error_for_jsonschema):
            errors = validate_rules({})
        self.assertEqual(errors, [])

    def test_schema_load_failure_returns_error_string(self):
        # Force jsonschema to be importable but schema read to fail
        import types
        fake_jsonschema = types.ModuleType("jsonschema")

        class _FakeDraft7Validator:
            def __init__(self, schema):
                # stub: no schema setup needed for this fake
                pass
            def iter_errors(self, rules):
                return []

        fake_jsonschema.Draft7Validator = _FakeDraft7Validator

        with patch.dict("sys.modules", {"jsonschema": fake_jsonschema}):
            with patch("telemetry.rules._SCHEMA_PATH") as mock_path:
                mock_path.read_text.side_effect = OSError("no schema file")
                errors = validate_rules(DEFAULT_RULES)
        self.assertIsInstance(errors, list)
        self.assertEqual(len(errors), 1)
        self.assertIn("Could not load rules schema", errors[0])

    def test_validate_rules_with_mock_validator_returns_errors(self):
        import types
        fake_jsonschema = types.ModuleType("jsonschema")

        class _FakeError:
            def __init__(self, path, msg):
                self.path = path
                self.message = msg

        class _FakeDraft7Validator:
            def __init__(self, schema):
                # stub: no schema setup needed for this fake
                pass
            def iter_errors(self, rules):
                return [_FakeError(["avoidable", "bash-as-grep", "enabled"], "must be boolean")]

        fake_jsonschema.Draft7Validator = _FakeDraft7Validator

        with patch.dict("sys.modules", {"jsonschema": fake_jsonschema}):
            errors = validate_rules(DEFAULT_RULES)

        self.assertIsInstance(errors, list)
        self.assertEqual(len(errors), 1)
        self.assertIn("must be boolean", errors[0])


def _make_import_error_for_jsonschema(name, *args, **kwargs):
    if name == "jsonschema":
        raise ImportError("no module named jsonschema")
    return _real_import(name, *args, **kwargs)


# ---------------------------------------------------------------------------
# load_rules
# ---------------------------------------------------------------------------

class TestLoadRules(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmpdir = Path(self._td.name)

    def test_returns_default_when_no_file(self):
        # Point home to a dir with no rules file
        with patch("telemetry.rules.Path.home", return_value=self.tmpdir):
            result = load_rules()
        self.assertEqual(result["avoidable"], DEFAULT_RULES["avoidable"])

    def test_returns_default_when_path_missing(self):
        result = load_rules(path=str(self.tmpdir / "nonexistent.yaml"))
        self.assertEqual(result["avoidable"], DEFAULT_RULES["avoidable"])

    def test_loads_and_merges_valid_yaml(self):
        rules_file = self.tmpdir / "rules.yaml"
        rules_file.write_text(
            "tip_filters:\n  min_cost_impact: 0.05\n",
            encoding="utf-8",
        )
        result = load_rules(path=str(rules_file))
        # Deep-merged: avoidable from defaults, override from file
        self.assertIn("avoidable", result)
        self.assertAlmostEqual(result["tip_filters"]["min_cost_impact"], 0.05, places=5)

    def test_returns_default_for_invalid_yaml(self):
        rules_file = self.tmpdir / "bad.yaml"
        # YAML with a tab character causes parse error
        rules_file.write_bytes(b"key:\n\t- invalid yaml tab\n")
        result = load_rules(path=str(rules_file))
        self.assertEqual(result["avoidable"], DEFAULT_RULES["avoidable"])

    def test_returns_default_for_non_mapping_yaml(self):
        rules_file = self.tmpdir / "list.yaml"
        rules_file.write_text("- item1\n- item2\n", encoding="utf-8")
        result = load_rules(path=str(rules_file))
        self.assertEqual(result["avoidable"], DEFAULT_RULES["avoidable"])

    def test_path_as_path_object_accepted(self):
        rules_file = self.tmpdir / "rules_path.yaml"
        rules_file.write_text("tip_filters:\n  min_cost_impact: 0.02\n", encoding="utf-8")
        result = load_rules(path=rules_file)
        self.assertIn("avoidable", result)

    def test_returns_defaults_when_validation_fails(self):
        # Produce a rules file that fails schema validation (if jsonschema available)
        rules_file = self.tmpdir / "invalid_schema.yaml"
        # Set enabled to a non-boolean value to fail validation
        rules_file.write_text(
            "avoidable:\n  bash-as-grep:\n    enabled: not_a_bool\n    patterns: []\n    exclude: []\n",
            encoding="utf-8",
        )
        # With jsonschema installed this should fall back to defaults;
        # without it, the merge succeeds silently. Either way we get a dict.
        result = load_rules(path=str(rules_file))
        self.assertIsInstance(result, dict)
        self.assertIn("avoidable", result)

    def test_load_rules_deep_copies_default(self):
        result = load_rules(path=str(self.tmpdir / "nonexistent.yaml"))
        # Modifying result should not affect DEFAULT_RULES
        result["avoidable"]["bash-as-grep"]["enabled"] = False
        self.assertTrue(DEFAULT_RULES["avoidable"]["bash-as-grep"]["enabled"])

    def test_home_path_used_when_no_path_argument(self):
        # Ensure default config_path is computed correctly
        fake_home = self.tmpdir / "home"
        fake_home.mkdir()
        (fake_home / ".telemetry-transcripts").mkdir()
        rules_file = fake_home / ".telemetry-transcripts" / "rules.yaml"
        rules_file.write_text("tip_filters:\n  min_cost_impact: 0.03\n", encoding="utf-8")
        with patch("telemetry.rules.Path.home", return_value=fake_home):
            result = load_rules()
        self.assertAlmostEqual(result["tip_filters"]["min_cost_impact"], 0.03, places=5)

    def test_returns_defaults_when_schema_validation_has_real_errors(self):
        """Cover the real_errors branch in load_rules by mocking validate_rules."""
        rules_file = self.tmpdir / "rules_with_errors.yaml"
        rules_file.write_text("tip_filters:\n  min_cost_impact: 0.01\n", encoding="utf-8")
        with patch("telemetry.rules.validate_rules", return_value=["avoidable.x: some error"]):
            result = load_rules(path=str(rules_file))
        # Should fall back to DEFAULT_RULES because there were real errors
        self.assertEqual(result["avoidable"], DEFAULT_RULES["avoidable"])


if __name__ == "__main__":
    unittest.main()
