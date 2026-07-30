"""Tests for telemetry/_menubar_config.py — config loading, saving, and parsing helpers."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from telemetry._menubar_config import (
    _DEFAULT_COST_MULTIPLIER,
    _DEFAULT_ICON_TEMPLATE,
    _DEFAULT_MONTHLY_BUDGET,
    _DEFAULT_POLL_INTERVAL,
    _DEFAULT_SECTIONS,
    _ICON_LEGACY_MAP,
    _POLL_INTERVAL_MAX,
    _POLL_INTERVAL_MIN,
    _any_otel_sections_enabled,
    _apply_budget,
    _apply_config_line,
    _apply_cost_multiplier,
    _apply_icon_display,
    _apply_max_tips,
    _apply_poll_interval,
    _coerce_bool,
    _coerce_cost_multiplier,
    _coerce_icon_display,
    _config_to_text,
    _icon_template_vars,
    _load_config,
    _merge_section,
    _migrate_flat_keys,
    _parse_bool,
    _parse_config_text,
    _save_config,
)


class TestCoerceBool(unittest.TestCase):
    def test_true_bool_passthrough(self) -> None:
        self.assertTrue(_coerce_bool(True, False))

    def test_false_bool_passthrough(self) -> None:
        self.assertFalse(_coerce_bool(False, True))

    def test_int_one_is_true(self) -> None:
        self.assertTrue(_coerce_bool(1, False))

    def test_int_zero_is_false(self) -> None:
        self.assertFalse(_coerce_bool(0, True))

    def test_string_on_is_true(self) -> None:
        self.assertTrue(_coerce_bool("on", False))

    def test_string_true_is_true(self) -> None:
        self.assertTrue(_coerce_bool("true", False))

    def test_string_yes_is_true(self) -> None:
        self.assertTrue(_coerce_bool("yes", False))

    def test_string_1_is_true(self) -> None:
        self.assertTrue(_coerce_bool("1", False))

    def test_string_off_is_false(self) -> None:
        self.assertFalse(_coerce_bool("off", True))

    def test_string_false_is_false(self) -> None:
        self.assertFalse(_coerce_bool("false", True))

    def test_string_no_is_false(self) -> None:
        self.assertFalse(_coerce_bool("no", True))

    def test_string_0_is_false(self) -> None:
        self.assertFalse(_coerce_bool("0", True))

    def test_unrecognized_string_returns_default(self) -> None:
        self.assertTrue(_coerce_bool("maybe", True))
        self.assertFalse(_coerce_bool("maybe", False))

    def test_none_returns_default(self) -> None:
        self.assertTrue(_coerce_bool(None, True))


class TestCoerceCostMultiplier(unittest.TestCase):
    def test_valid_float(self) -> None:
        self.assertEqual(_coerce_cost_multiplier(0.7), 0.7)

    def test_valid_int(self) -> None:
        self.assertEqual(_coerce_cost_multiplier(2), 2.0)

    def test_zero_returns_default(self) -> None:
        self.assertEqual(_coerce_cost_multiplier(0), _DEFAULT_COST_MULTIPLIER)

    def test_negative_returns_default(self) -> None:
        self.assertEqual(_coerce_cost_multiplier(-1.0), _DEFAULT_COST_MULTIPLIER)

    def test_string_returns_default(self) -> None:
        self.assertEqual(_coerce_cost_multiplier("abc"), _DEFAULT_COST_MULTIPLIER)

    def test_none_returns_default(self) -> None:
        self.assertEqual(_coerce_cost_multiplier(None), _DEFAULT_COST_MULTIPLIER)


class TestCoerceIconDisplay(unittest.TestCase):
    def test_non_string_returns_default(self) -> None:
        self.assertEqual(_coerce_icon_display(42), _DEFAULT_ICON_TEMPLATE)
        self.assertEqual(_coerce_icon_display(None), _DEFAULT_ICON_TEMPLATE)

    def test_empty_string_returns_default(self) -> None:
        self.assertEqual(_coerce_icon_display(""), _DEFAULT_ICON_TEMPLATE)
        self.assertEqual(_coerce_icon_display("   "), _DEFAULT_ICON_TEMPLATE)

    def test_legacy_key_migrated(self) -> None:
        for legacy_key, expected in _ICON_LEGACY_MAP.items():
            with self.subTest(key=legacy_key):
                self.assertEqual(_coerce_icon_display(legacy_key), expected)

    def test_template_string_passthrough(self) -> None:
        self.assertEqual(_coerce_icon_display("$1d_spend"), "$1d_spend")

    def test_custom_template_passthrough(self) -> None:
        self.assertEqual(_coerce_icon_display("$score ($1d_spend)"), "$score ($1d_spend)")


class TestIconTemplateVars(unittest.TestCase):
    def test_single_variable(self) -> None:
        self.assertEqual(_icon_template_vars("$score"), {"score"})

    def test_multiple_variables(self) -> None:
        vars_ = _icon_template_vars("$score $1d_spend $mtd_spend")
        self.assertIn("score", vars_)
        self.assertIn("1d_spend", vars_)
        self.assertIn("mtd_spend", vars_)

    def test_braced_variable(self) -> None:
        self.assertIn("1d_spend", _icon_template_vars("${1d_spend}"))

    def test_no_variables(self) -> None:
        self.assertEqual(_icon_template_vars("static text"), set())

    def test_empty_string(self) -> None:
        self.assertEqual(_icon_template_vars(""), set())


class TestAnyOtelSectionsEnabled(unittest.TestCase):
    def test_all_disabled_returns_false(self) -> None:
        cfg = {"sections": {k: {"enabled": False} for k in [
            "otel_usage", "otel_models", "otel_meta", "otel_hooks",
            "otel_tools", "otel_code", "otel_skills", "otel_sessions",
        ]}}
        self.assertFalse(_any_otel_sections_enabled(cfg))

    def test_one_enabled_returns_true(self) -> None:
        cfg = {"sections": {"otel_usage": {"enabled": True}}}
        self.assertTrue(_any_otel_sections_enabled(cfg))

    def test_missing_sections_returns_false(self) -> None:
        self.assertFalse(_any_otel_sections_enabled({}))


class TestMergeSection(unittest.TestCase):
    def test_default_returned_when_stored_not_dict(self) -> None:
        defaults = {"enabled": True, "show_tokens": False}
        result = _merge_section(defaults, None)
        self.assertEqual(result, defaults)

    def test_stored_bool_overrides_default(self) -> None:
        defaults = {"enabled": True}
        result = _merge_section(defaults, {"enabled": False})
        self.assertFalse(result["enabled"])

    def test_stored_string_on_coerced_to_true(self) -> None:
        defaults = {"enabled": False}
        result = _merge_section(defaults, {"enabled": "on"})
        self.assertTrue(result["enabled"])

    def test_int_default_uses_max_tips_clamping(self) -> None:
        defaults = {"enabled": True, "max_tips": 3}
        result = _merge_section(defaults, {"max_tips": 20})
        self.assertEqual(result["max_tips"], 10)  # capped at _MAX_TIPS_LIMIT

    def test_int_default_minimum_clamped(self) -> None:
        defaults = {"enabled": True, "max_tips": 3}
        result = _merge_section(defaults, {"max_tips": 0})
        self.assertEqual(result["max_tips"], 1)

    def test_unknown_keys_in_stored_ignored(self) -> None:
        defaults = {"enabled": True}
        result = _merge_section(defaults, {"enabled": False, "unknown_key": "value"})
        self.assertNotIn("unknown_key", result)


class TestMigrateFlatKeys(unittest.TestCase):
    def test_empty_dict_returns_empty(self) -> None:
        self.assertEqual(_migrate_flat_keys({}), {})

    def test_show_tokens_migrated(self) -> None:
        result = _migrate_flat_keys({"show_tokens": True})
        self.assertTrue(result["usage"]["show_tokens"])

    def test_show_models_migrated(self) -> None:
        result = _migrate_flat_keys({"show_models": False})
        self.assertFalse(result["models"]["enabled"])

    def test_multiple_keys_migrated(self) -> None:
        raw = {
            "show_tokens": True,
            "show_sessions": False,
            "show_models": True,
            "show_insights": False,
        }
        result = _migrate_flat_keys(raw)
        self.assertTrue(result["usage"]["show_tokens"])
        self.assertFalse(result["usage"]["show_sessions"])
        self.assertTrue(result["models"]["enabled"])
        self.assertFalse(result["insights"]["enabled"])


class TestLoadConfig(unittest.TestCase):
    def test_missing_file_returns_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nonexistent.json"
            cfg = _load_config(path)
            self.assertEqual(cfg["monthly_budget"], _DEFAULT_MONTHLY_BUDGET)
            self.assertEqual(cfg["poll_interval"], _DEFAULT_POLL_INTERVAL)
            self.assertEqual(cfg["cost_multiplier"], _DEFAULT_COST_MULTIPLIER)

    def test_invalid_json_returns_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bad.json"
            path.write_text("not json")
            cfg = _load_config(path)
            self.assertEqual(cfg["monthly_budget"], _DEFAULT_MONTHLY_BUDGET)

    def test_valid_config_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            data = {
                "monthly_budget": 2500.0,
                "poll_interval": 60,
                "cost_multiplier": 0.8,
                "sections": {k: dict(v) for k, v in _DEFAULT_SECTIONS.items()},
            }
            path.write_text(json.dumps(data))
            cfg = _load_config(path)
            self.assertEqual(cfg["monthly_budget"], 2500.0)
            self.assertEqual(cfg["poll_interval"], 60)
            self.assertAlmostEqual(cfg["cost_multiplier"], 0.8)

    def test_negative_budget_uses_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            path.write_text(json.dumps({"monthly_budget": -100}))
            cfg = _load_config(path)
            self.assertEqual(cfg["monthly_budget"], _DEFAULT_MONTHLY_BUDGET)

    def test_poll_interval_clamped_to_min(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            path.write_text(json.dumps({"poll_interval": 1}))
            cfg = _load_config(path)
            self.assertEqual(cfg["poll_interval"], _POLL_INTERVAL_MIN)

    def test_poll_interval_clamped_to_max(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            path.write_text(json.dumps({"poll_interval": 9999}))
            cfg = _load_config(path)
            self.assertEqual(cfg["poll_interval"], _POLL_INTERVAL_MAX)

    def test_legacy_icon_display_migrated_and_saved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            path.write_text(json.dumps({"icon_display": "budget_score"}))
            cfg = _load_config(path)
            self.assertEqual(cfg["icon_display"], "$score")
            # File should have been rewritten with the migrated value
            saved = json.loads(path.read_text())
            self.assertEqual(saved["icon_display"], "$score")

    def test_non_dict_json_uses_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            path.write_text(json.dumps([1, 2, 3]))
            cfg = _load_config(path)
            self.assertEqual(cfg["monthly_budget"], _DEFAULT_MONTHLY_BUDGET)

    def test_flat_keys_migrated_and_saved(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            path.write_text(json.dumps({"show_tokens": False}))
            cfg = _load_config(path)
            self.assertFalse(cfg["sections"]["usage"]["show_tokens"])


class TestSaveConfig(unittest.TestCase):
    def test_save_and_reload(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            cfg = {
                "monthly_budget": 1234.0,
                "icon_display": "$score",
                "poll_interval": 45,
                "cost_multiplier": 1.0,
                "sections": {k: dict(v) for k, v in _DEFAULT_SECTIONS.items()},
            }
            _save_config(cfg, config_path=path)
            loaded = json.loads(path.read_text())
            self.assertEqual(loaded["monthly_budget"], 1234.0)

    def test_atomic_write_uses_replace(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            cfg = {"monthly_budget": 500.0, "sections": {}}
            _save_config(cfg, config_path=path)
            self.assertTrue(path.exists())
            # No .tmp files should remain
            tmp_files = list(Path(tmpdir).glob("*.tmp"))
            self.assertEqual(tmp_files, [])

    def test_creates_parent_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "nested" / "dir" / "config.json"
            cfg = {"monthly_budget": 100.0, "sections": {}}
            _save_config(cfg, config_path=path)
            self.assertTrue(path.exists())


class TestSaveConfigWriteError(unittest.TestCase):
    def test_error_cleans_up_tmp_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "config.json"
            cfg = {"monthly_budget": 100.0, "sections": {}}
            with patch("os.replace", side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    _save_config(cfg, config_path=path)
            # No .tmp files should remain after the error
            tmp_files = list(Path(tmpdir).glob("*.tmp"))
            self.assertEqual(tmp_files, [])


class TestConfigToText(unittest.TestCase):
    def _default_cfg(self) -> dict:
        return _load_config(Path("/nonexistent/path/that/doesnt/exist"))

    def test_contains_monthly_budget(self) -> None:
        cfg = self._default_cfg()
        text = _config_to_text(cfg)
        self.assertIn("monthly_budget:", text)

    def test_contains_poll_interval(self) -> None:
        cfg = self._default_cfg()
        text = _config_to_text(cfg)
        self.assertIn("poll_interval:", text)

    def test_contains_icon_display(self) -> None:
        cfg = self._default_cfg()
        text = _config_to_text(cfg)
        self.assertIn("icon_display:", text)

    def test_contains_sections_header(self) -> None:
        cfg = self._default_cfg()
        text = _config_to_text(cfg)
        self.assertIn("sections:", text)

    def test_otel_sections_present(self) -> None:
        cfg = self._default_cfg()
        text = _config_to_text(cfg)
        self.assertIn("otel_usage:", text)

    def test_usage_sub_rows_present(self) -> None:
        cfg = self._default_cfg()
        text = _config_to_text(cfg)
        self.assertIn("tokens:", text)
        self.assertIn("sessions:", text)

    def test_budget_formatted_without_decimal(self) -> None:
        cfg = self._default_cfg()
        cfg["monthly_budget"] = 4000.0
        text = _config_to_text(cfg)
        self.assertIn("monthly_budget: 4000", text)


class TestParseBool(unittest.TestCase):
    def test_on_true_yes_1(self) -> None:
        for val in ("on", "true", "yes", "1"):
            with self.subTest(val=val):
                self.assertTrue(_parse_bool(val))

    def test_off_false_no_0(self) -> None:
        for val in ("off", "false", "no", "0"):
            with self.subTest(val=val):
                self.assertFalse(_parse_bool(val))

    def test_unrecognized_returns_none(self) -> None:
        self.assertIsNone(_parse_bool("maybe"))
        self.assertIsNone(_parse_bool(""))

    def test_strips_whitespace(self) -> None:
        self.assertTrue(_parse_bool("  on  "))


class TestApplyBudget(unittest.TestCase):
    def test_valid_positive_budget_applied(self) -> None:
        cfg: dict = {}
        result = _apply_budget(cfg, "1000")
        self.assertTrue(result)
        self.assertEqual(cfg["monthly_budget"], 1000.0)

    def test_zero_budget_rejected(self) -> None:
        cfg: dict = {}
        result = _apply_budget(cfg, "0")
        self.assertFalse(result)
        self.assertNotIn("monthly_budget", cfg)

    def test_negative_budget_rejected(self) -> None:
        cfg: dict = {}
        result = _apply_budget(cfg, "-100")
        self.assertFalse(result)

    def test_non_numeric_rejected(self) -> None:
        cfg: dict = {}
        result = _apply_budget(cfg, "abc")
        self.assertFalse(result)


class TestApplyPollInterval(unittest.TestCase):
    def test_valid_interval_applied_and_clamped(self) -> None:
        cfg: dict = {}
        result = _apply_poll_interval(cfg, "60")
        self.assertTrue(result)
        self.assertEqual(cfg["poll_interval"], 60)

    def test_below_min_clamped(self) -> None:
        cfg: dict = {}
        _apply_poll_interval(cfg, "1")
        self.assertEqual(cfg["poll_interval"], _POLL_INTERVAL_MIN)

    def test_above_max_clamped(self) -> None:
        cfg: dict = {}
        _apply_poll_interval(cfg, "9999")
        self.assertEqual(cfg["poll_interval"], _POLL_INTERVAL_MAX)

    def test_invalid_string_rejected(self) -> None:
        cfg: dict = {}
        result = _apply_poll_interval(cfg, "xyz")
        self.assertFalse(result)


class TestApplyCostMultiplier(unittest.TestCase):
    def test_valid_multiplier_applied(self) -> None:
        cfg: dict = {}
        result = _apply_cost_multiplier(cfg, "0.7")
        self.assertTrue(result)
        self.assertAlmostEqual(cfg["cost_multiplier"], 0.7)

    def test_zero_rejected(self) -> None:
        cfg: dict = {}
        result = _apply_cost_multiplier(cfg, "0")
        self.assertFalse(result)

    def test_negative_rejected(self) -> None:
        cfg: dict = {}
        result = _apply_cost_multiplier(cfg, "-1")
        self.assertFalse(result)

    def test_invalid_string_rejected(self) -> None:
        cfg: dict = {}
        result = _apply_cost_multiplier(cfg, "abc")
        self.assertFalse(result)


class TestApplyMaxTips(unittest.TestCase):
    def test_valid_value_applied(self) -> None:
        cfg = {"sections": {"insights": {"max_tips": 3}}}
        result = _apply_max_tips(cfg, "5")
        self.assertTrue(result)
        self.assertEqual(cfg["sections"]["insights"]["max_tips"], 5)

    def test_invalid_value_rejected(self) -> None:
        cfg = {"sections": {"insights": {"max_tips": 3}}}
        result = _apply_max_tips(cfg, "abc")
        self.assertFalse(result)


class TestApplyIconDisplay(unittest.TestCase):
    def test_valid_template_applied(self) -> None:
        cfg: dict = {}
        result = _apply_icon_display(cfg, "$score")
        self.assertTrue(result)
        self.assertEqual(cfg["icon_display"], "$score")

    def test_empty_string_rejected(self) -> None:
        cfg: dict = {}
        result = _apply_icon_display(cfg, "   ")
        self.assertFalse(result)


class TestApplyConfigLine(unittest.TestCase):
    def _make_bool_keys(self) -> tuple[dict, dict]:
        """Return a minimal cfg + bool_keys for testing."""
        sections = {k: dict(v) for k, v in _DEFAULT_SECTIONS.items()}
        cfg = {
            "monthly_budget": _DEFAULT_MONTHLY_BUDGET,
            "icon_display": _DEFAULT_ICON_TEMPLATE,
            "poll_interval": _DEFAULT_POLL_INTERVAL,
            "cost_multiplier": _DEFAULT_COST_MULTIPLIER,
            "sections": sections,
        }
        s = cfg["sections"]
        bool_keys = {
            "usage": (s["usage"], "enabled"),
            "models": (s["models"], "enabled"),
        }
        return cfg, bool_keys

    def test_monthly_budget_dispatched(self) -> None:
        cfg, bk = self._make_bool_keys()
        result = _apply_config_line("monthly_budget", "2000", cfg, bk)
        self.assertTrue(result)
        self.assertEqual(cfg["monthly_budget"], 2000.0)

    def test_icon_display_dispatched(self) -> None:
        cfg, bk = self._make_bool_keys()
        result = _apply_config_line("icon_display", "$1d_spend", cfg, bk)
        self.assertTrue(result)

    def test_poll_interval_dispatched(self) -> None:
        cfg, bk = self._make_bool_keys()
        result = _apply_config_line("poll_interval", "30", cfg, bk)
        self.assertTrue(result)

    def test_cost_multiplier_dispatched(self) -> None:
        cfg, bk = self._make_bool_keys()
        result = _apply_config_line("cost_multiplier", "0.9", cfg, bk)
        self.assertTrue(result)

    def test_bool_key_dispatched(self) -> None:
        cfg, bk = self._make_bool_keys()
        result = _apply_config_line("usage", "off", cfg, bk)
        self.assertTrue(result)
        self.assertFalse(cfg["sections"]["usage"]["enabled"])

    def test_unknown_key_returns_false(self) -> None:
        cfg, bk = self._make_bool_keys()
        result = _apply_config_line("unknown_setting", "value", cfg, bk)
        self.assertFalse(result)

    def test_bool_key_with_invalid_value_returns_false(self) -> None:
        cfg, bk = self._make_bool_keys()
        result = _apply_config_line("usage", "maybe", cfg, bk)
        self.assertFalse(result)


class TestParseConfigText(unittest.TestCase):
    def _base_cfg(self) -> dict:
        return _load_config(Path("/nonexistent/path"))

    def test_roundtrip_through_config_to_text(self) -> None:
        cfg = self._base_cfg()
        text = _config_to_text(cfg)
        parsed, rejected = _parse_config_text(text, cfg)
        self.assertEqual(rejected, [])
        self.assertEqual(parsed["monthly_budget"], cfg["monthly_budget"])

    def test_comment_lines_ignored(self) -> None:
        cfg = self._base_cfg()
        text = "# this is a comment\nmonthly_budget: 500"
        parsed, rejected = _parse_config_text(text, cfg)
        self.assertEqual(parsed["monthly_budget"], 500.0)
        self.assertEqual(rejected, [])

    def test_empty_lines_ignored(self) -> None:
        cfg = self._base_cfg()
        text = "\n\nmonthly_budget: 300\n\n"
        parsed, rejected = _parse_config_text(text, cfg)
        self.assertEqual(parsed["monthly_budget"], 300.0)

    def test_sections_header_line_ignored(self) -> None:
        cfg = self._base_cfg()
        text = "sections:\nmonthly_budget: 200"
        parsed, rejected = _parse_config_text(text, cfg)
        self.assertEqual(parsed["monthly_budget"], 200.0)

    def test_invalid_key_goes_to_rejected(self) -> None:
        cfg = self._base_cfg()
        text = "nonexistent_key: value"
        _, rejected = _parse_config_text(text, cfg)
        self.assertEqual(len(rejected), 1)
        self.assertIn("nonexistent_key", rejected[0])

    def test_usage_section_toggle(self) -> None:
        cfg = self._base_cfg()
        text = "usage: off"
        parsed, _ = _parse_config_text(text, cfg)
        self.assertFalse(parsed["sections"]["usage"]["enabled"])

    def test_bool_toggle_for_models(self) -> None:
        cfg = self._base_cfg()
        text = "models: off"
        parsed, _ = _parse_config_text(text, cfg)
        self.assertFalse(parsed["sections"]["models"]["enabled"])

    def test_does_not_mutate_input_cfg(self) -> None:
        cfg = self._base_cfg()
        original_budget = cfg["monthly_budget"]
        _parse_config_text("monthly_budget: 999", cfg)
        self.assertEqual(cfg["monthly_budget"], original_budget)


if __name__ == "__main__":
    unittest.main()
