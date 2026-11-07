"""Tests for profile directory resolution and the CWD-relative regression fix.

Covers:
- resolve_profile_dir() search order (config_home → CWD → packaged)
- _validate_profile_name() safety checks
- apply_profile_overlays() loading from DANCING_BEAR_CONFIG_HOME
- apply_profile_overlays() error on unknown profile
- End-to-end CLI test: experience export with --profile from an unrelated CWD
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

from tests.fixtures import TempDirMixin


# ---------------------------------------------------------------------------
# _validate_profile_name
# ---------------------------------------------------------------------------


class TestValidateProfileName(unittest.TestCase):
    """_validate_profile_name rejects unsafe names."""

    def test_accepts_simple_names(self):
        from resume.overlays import _validate_profile_name

        for name in ("sample", "brian", "tech-company", "v2", "a", "my_profile"):
            with self.subTest(name=name):
                _validate_profile_name(name)  # must not raise

    def test_rejects_path_traversal(self):
        from resume.overlays import _validate_profile_name
        from core.cli_errors import CLIError

        for name in ("../x", "a/../b", "..", "a/b", "/etc/passwd"):
            with self.subTest(name=name):
                with self.assertRaises(CLIError, msg=f"expected CLIError for {name!r}"):
                    _validate_profile_name(name)

    def test_rejects_leading_dot(self):
        from resume.overlays import _validate_profile_name
        from core.cli_errors import CLIError

        with self.assertRaises(CLIError):
            _validate_profile_name(".hidden")

    def test_rejects_empty_string(self):
        from resume.overlays import _validate_profile_name
        from core.cli_errors import CLIError

        with self.assertRaises(CLIError):
            _validate_profile_name("")

    def test_rejects_path_traversal_exit_code_is_usage(self):
        """Unsafe name raises CLIError with ExitCode.USAGE (not NOT_FOUND)."""
        from resume.overlays import _validate_profile_name
        from core.cli_errors import CLIError, ExitCode

        with self.assertRaises(CLIError) as ctx:
            _validate_profile_name("../evil")
        self.assertEqual(ctx.exception.code, ExitCode.USAGE)


# ---------------------------------------------------------------------------
# resolve_profile_dir
# ---------------------------------------------------------------------------


class TestResolveProfileDir(TempDirMixin, unittest.TestCase):
    """resolve_profile_dir() respects the documented search order."""

    def test_resolves_from_config_home(self):
        """Profile directory under DANCING_BEAR_CONFIG_HOME/resume/profiles/<p>."""
        from resume.overlays import resolve_profile_dir

        config_home = Path(self.tmpdir) / "config_home"
        prof_dir = config_home / "resume" / "profiles" / "myprof"
        prof_dir.mkdir(parents=True)

        with self.in_tmpdir():
            with mock.patch.dict(os.environ, {"DANCING_BEAR_CONFIG_HOME": str(config_home)}):
                result = resolve_profile_dir("myprof")

        self.assertIsNotNone(result)
        self.assertEqual(result, prof_dir)

    def test_resolves_from_cwd(self):
        """CWD config/profiles/<p> is returned when config_home has nothing."""
        from resume.overlays import resolve_profile_dir

        empty_home = Path(self.tmpdir) / "empty_home"
        empty_home.mkdir()

        with self.in_tmpdir():
            prof_dir = Path("config") / "profiles" / "cwd_prof"
            prof_dir.mkdir(parents=True)
            with mock.patch.dict(os.environ, {"DANCING_BEAR_CONFIG_HOME": str(empty_home)}):
                result = resolve_profile_dir("cwd_prof")
            # Resolve while still in tmpdir so relative paths compare correctly.
            self.assertIsNotNone(result)
            self.assertEqual(result.resolve(), prof_dir.resolve())

    def test_resolves_packaged_sample(self):
        """The 'sample' profile resolves via the packaged directory from any CWD."""
        from resume.overlays import resolve_profile_dir

        empty_home = Path(self.tmpdir) / "empty_home"
        empty_home.mkdir()

        with self.in_tmpdir():
            with mock.patch.dict(os.environ, {"DANCING_BEAR_CONFIG_HOME": str(empty_home)}):
                result = resolve_profile_dir("sample")

        self.assertIsNotNone(result)
        self.assertTrue(result.is_dir())
        # Packaged sample has at least profile.yaml
        self.assertTrue((result / "profile.yaml").exists())

    def test_config_home_beats_cwd(self):
        """config_home takes precedence when both have the profile directory."""
        from resume.overlays import resolve_profile_dir

        config_home_dir = Path(self.tmpdir) / "home"
        home_prof = config_home_dir / "resume" / "profiles" / "dupe"
        home_prof.mkdir(parents=True)
        (home_prof / "profile.yaml").write_text("name: From Home\n")

        with self.in_tmpdir():
            cwd_prof = Path("config") / "profiles" / "dupe"
            cwd_prof.mkdir(parents=True)
            (cwd_prof / "profile.yaml").write_text("name: From CWD\n")

            with mock.patch.dict(os.environ, {"DANCING_BEAR_CONFIG_HOME": str(config_home_dir)}):
                result = resolve_profile_dir("dupe")

        self.assertEqual(result, home_prof)

    def test_returns_none_for_unknown_profile(self):
        """Returns None when no directory is found in any search location."""
        from resume.overlays import resolve_profile_dir

        empty_home = Path(self.tmpdir) / "empty"
        empty_home.mkdir()

        with self.in_tmpdir():
            with mock.patch.dict(os.environ, {"DANCING_BEAR_CONFIG_HOME": str(empty_home)}):
                result = resolve_profile_dir("definitely_does_not_exist_xyz123")

        self.assertIsNone(result)

    def test_rejects_unsafe_name(self):
        """Unsafe profile name raises CLIError immediately (not ValueError)."""
        from resume.overlays import resolve_profile_dir
        from core.cli_errors import CLIError

        with self.assertRaises(CLIError):
            resolve_profile_dir("../x")


# ---------------------------------------------------------------------------
# apply_profile_overlays — config_home resolution (regression)
# ---------------------------------------------------------------------------


class TestApplyProfileOverlaysFromConfigHome(TempDirMixin, unittest.TestCase):
    """Regression: overlays load from config_home when CWD has no profiles."""

    def _write_yaml(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def test_loads_experience_from_config_home_in_unrelated_cwd(self):
        """Experience overlay loaded from config_home; CWD has no config/profiles."""
        from resume.overlays import apply_profile_overlays

        config_home_dir = Path(self.tmpdir) / "config_home"
        prof_dir = config_home_dir / "resume" / "profiles" / "regtest"
        self._write_yaml(
            prof_dir / "experience.yaml",
            "experience:\n  - title: Regression Engineer\n    company: TestCo\n",
        )

        with self.in_tmpdir():
            with mock.patch.dict(os.environ, {"DANCING_BEAR_CONFIG_HOME": str(config_home_dir)}):
                result = apply_profile_overlays({}, "regtest")

        self.assertIn("experience", result)
        self.assertTrue(result["experience"], "experience list must be non-empty")
        self.assertEqual(result["experience"][0]["title"], "Regression Engineer")

    def test_loads_profile_config_from_config_home(self):
        """Name / headline from profile.yaml in config_home overrides base data."""
        from resume.overlays import apply_profile_overlays

        config_home_dir = Path(self.tmpdir) / "config_home"
        prof_dir = config_home_dir / "resume" / "profiles" / "nametest"
        self._write_yaml(
            prof_dir / "profile.yaml",
            "name: Config Home Name\nheadline: Staff Engineer\n",
        )

        with self.in_tmpdir():
            with mock.patch.dict(os.environ, {"DANCING_BEAR_CONFIG_HOME": str(config_home_dir)}):
                result = apply_profile_overlays({"name": "Original"}, "nametest")

        self.assertEqual(result["name"], "Config Home Name")
        self.assertEqual(result["headline"], "Staff Engineer")

    def test_config_home_beats_cwd_overlays(self):
        """config_home overlay wins when both config_home and CWD have the profile dir."""
        from resume.overlays import apply_profile_overlays

        config_home_dir = Path(self.tmpdir) / "config_home"
        home_prof = config_home_dir / "resume" / "profiles" / "prio"
        home_prof.mkdir(parents=True)
        (home_prof / "experience.yaml").write_text(
            "experience:\n  - title: Home Engineer\n    company: HomeCo\n"
        )

        with self.in_tmpdir():
            cwd_prof = Path("config") / "profiles" / "prio"
            cwd_prof.mkdir(parents=True)
            (cwd_prof / "experience.yaml").write_text(
                "experience:\n  - title: CWD Engineer\n    company: CWDCo\n"
            )

            with mock.patch.dict(os.environ, {"DANCING_BEAR_CONFIG_HOME": str(config_home_dir)}):
                result = apply_profile_overlays({}, "prio")

        self.assertEqual(result["experience"][0]["title"], "Home Engineer")

    def test_cwd_overlay_still_works(self):
        """CWD config/profiles/<p> still loads when config_home has no match."""
        from resume.overlays import apply_profile_overlays

        empty_home = Path(self.tmpdir) / "empty_home"
        empty_home.mkdir()

        with self.in_tmpdir():
            cwd_prof = Path("config") / "profiles" / "cwdonly"
            cwd_prof.mkdir(parents=True)
            (cwd_prof / "profile.yaml").write_text("name: CWD User\n")

            with mock.patch.dict(os.environ, {"DANCING_BEAR_CONFIG_HOME": str(empty_home)}):
                result = apply_profile_overlays({}, "cwdonly")

        self.assertEqual(result["name"], "CWD User")

    def test_packaged_sample_resolves_from_unrelated_cwd(self):
        """The packaged 'sample' profile loads from any CWD."""
        from resume.overlays import apply_profile_overlays

        empty_home = Path(self.tmpdir) / "empty_home"
        empty_home.mkdir()

        with self.in_tmpdir():
            with mock.patch.dict(os.environ, {"DANCING_BEAR_CONFIG_HOME": str(empty_home)}):
                result = apply_profile_overlays({}, "sample")

        # The packaged sample profile has at least a name in profile.yaml
        self.assertIn("name", result, "sample profile.yaml must set a name")


# ---------------------------------------------------------------------------
# apply_profile_overlays — warning (not error) on unknown profile
# ---------------------------------------------------------------------------


class TestApplyProfileOverlaysUnknownProfile(TempDirMixin, unittest.TestCase):
    """Unknown profile emits a stderr warning and returns data unchanged."""

    def test_returns_data_unchanged_for_unknown_profile(self):
        """Unknown profile: return value equals the input data."""
        from resume.overlays import apply_profile_overlays

        empty_home = Path(self.tmpdir) / "empty"
        empty_home.mkdir()
        base = {"name": "Test", "experience": [{"title": "Dev"}]}

        with self.in_tmpdir():
            with mock.patch.dict(os.environ, {"DANCING_BEAR_CONFIG_HOME": str(empty_home)}):
                result = apply_profile_overlays(base, "unknown_profile_xyz")

        self.assertEqual(result, base, "Data must be returned unchanged for unknown profile")

    def test_does_not_raise_for_unknown_profile(self):
        """No exception is raised when the profile is not found anywhere."""
        from resume.overlays import apply_profile_overlays

        empty_home = Path(self.tmpdir) / "empty"
        empty_home.mkdir()

        with self.in_tmpdir():
            with mock.patch.dict(os.environ, {"DANCING_BEAR_CONFIG_HOME": str(empty_home)}):
                # Must not raise
                apply_profile_overlays({}, "no_such_profile_abc")

    def test_warning_includes_profile_name(self):
        """The stderr warning names the missing profile."""
        from resume.overlays import apply_profile_overlays
        import io

        empty_home = Path(self.tmpdir) / "empty"
        empty_home.mkdir()
        profile = "definitely_missing_profile_xyz"

        buf = io.StringIO()
        with self.in_tmpdir():
            with mock.patch.dict(os.environ, {"DANCING_BEAR_CONFIG_HOME": str(empty_home)}):
                with mock.patch("sys.stderr", buf):
                    apply_profile_overlays({}, profile)

        output = buf.getvalue()
        self.assertIn(profile, output)

    def test_warning_includes_searched_paths(self):
        """The stderr warning lists at least one searched directory."""
        from resume.overlays import apply_profile_overlays, _searched_dirs
        import io

        empty_home = Path(self.tmpdir) / "empty"
        empty_home.mkdir()
        profile = "no_such_profile_abc"

        buf = io.StringIO()
        with self.in_tmpdir():
            with mock.patch.dict(os.environ, {"DANCING_BEAR_CONFIG_HOME": str(empty_home)}):
                expected_dirs = _searched_dirs(profile)
                with mock.patch("sys.stderr", buf):
                    apply_profile_overlays({}, profile)

        output = buf.getvalue()
        self.assertTrue(
            any(str(d) in output for d in expected_dirs),
            f"Expected at least one of {expected_dirs} in warning: {output!r}",
        )

    def test_legacy_only_profile_loads_without_warning(self):
        """A profile with only legacy flat files loads silently."""
        from resume.overlays import apply_profile_overlays
        import io

        empty_home = Path(self.tmpdir) / "empty"
        empty_home.mkdir()

        buf = io.StringIO()
        with self.in_tmpdir():
            Path("config").mkdir()
            Path("config/profile.legacyonly.yaml").write_text("name: Legacy Only\n")

            with mock.patch.dict(os.environ, {"DANCING_BEAR_CONFIG_HOME": str(empty_home)}):
                with mock.patch("sys.stderr", buf):
                    result = apply_profile_overlays({}, "legacyonly")

        self.assertEqual(result["name"], "Legacy Only")
        # Legacy flat files found → no warning written
        self.assertEqual(buf.getvalue(), "")

    def test_rejects_unsafe_profile_name_with_cli_error(self):
        """Unsafe profile names raise CLIError with ExitCode.USAGE."""
        from resume.overlays import apply_profile_overlays
        from core.cli_errors import CLIError, ExitCode

        with self.assertRaises(CLIError) as ctx:
            apply_profile_overlays({}, "../evil")
        self.assertEqual(ctx.exception.code, ExitCode.USAGE)

        with self.assertRaises(CLIError) as ctx2:
            apply_profile_overlays({}, "a/b")
        self.assertEqual(ctx2.exception.code, ExitCode.USAGE)


# ---------------------------------------------------------------------------
# End-to-end CLI test
# ---------------------------------------------------------------------------


class TestExperienceExportCLIFromUnrelatedCWD(TempDirMixin, unittest.TestCase):
    """End-to-end: experience export with --profile loads overlays from config_home."""

    def _write_yaml(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def test_experience_role_appears_in_output(self):
        """Running experience export from an unrelated CWD picks up config_home overlays."""
        from resume.cli.main import main

        config_home_dir = Path(self.tmpdir) / "config_home"
        prof_dir = config_home_dir / "resume" / "profiles" / "e2eprof"
        self._write_yaml(
            prof_dir / "experience.yaml",
            "experience:\n  - title: E2E Test Engineer\n    company: RegCo\n",
        )

        # Minimal data file — just a name so _load_candidate_data succeeds.
        data_dir = Path(self.tmpdir) / "data"
        data_dir.mkdir()
        data_file = data_dir / "data.json"
        data_file.write_text('{"name": "Test User"}')

        out_file = Path(self.tmpdir) / "out_experience.yaml"

        # CWD is an unrelated temp dir with no config/ directory.
        with self.in_tmpdir():
            with mock.patch.dict(os.environ, {"DANCING_BEAR_CONFIG_HOME": str(config_home_dir)}):
                exit_code = main([
                    "experience", "export",
                    "--data", str(data_file),
                    "--profile", "e2eprof",
                    "--out", str(out_file),
                ])

        self.assertEqual(exit_code, 0, "CLI must exit 0 on success")
        self.assertTrue(out_file.exists(), "Output file must be written")

        output_text = out_file.read_text()
        self.assertIn("E2E Test Engineer", output_text)
        self.assertIn("RegCo", output_text)

    def test_unknown_profile_emits_warning_and_exports_data(self):
        """CLI exits 0 (with stderr warning) when --profile names a non-existent profile.

        The documented flow ``extract --profile X`` → ``render --profile X`` must
        succeed even when no overlay directory exists for X — the flag doubles as
        an output-naming prefix, so it must not block the pipeline.
        """
        from resume.cli.main import main
        import io

        empty_home = Path(self.tmpdir) / "empty_home"
        empty_home.mkdir()

        data_dir = Path(self.tmpdir) / "data"
        data_dir.mkdir()
        data_file = data_dir / "data.json"
        data_file.write_text('{"name": "Test User", "experience": [{"title": "Dev"}]}')

        out_file = Path(self.tmpdir) / "out.yaml"

        buf = io.StringIO()
        with self.in_tmpdir():
            with mock.patch.dict(os.environ, {"DANCING_BEAR_CONFIG_HOME": str(empty_home)}):
                with mock.patch("sys.stderr", buf):
                    exit_code = main([
                        "experience", "export",
                        "--data", str(data_file),
                        "--profile", "absolutely_nonexistent_profile_xyz",
                        "--out", str(out_file),
                    ])

        self.assertEqual(exit_code, 0, "CLI must exit 0 — unknown profile emits a warning, not an error")
        # Warning was printed mentioning the profile
        self.assertIn("absolutely_nonexistent_profile_xyz", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
