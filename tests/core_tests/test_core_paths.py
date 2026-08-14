"""Tests for core.paths output-root resolution."""

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from core.paths import APP_DIR_NAME, ENV_DATA_HOME, data_home, output_dir

# tests/core_tests/test_core_paths.py -> tests/core_tests -> tests -> checkout
REPO_ROOT = Path(__file__).resolve().parents[2]


def _env(**overrides):
    """Patch os.environ with the data-home vars cleared, then applied."""
    base = {k: v for k, v in os.environ.items()}
    for key in (ENV_DATA_HOME, "XDG_DATA_HOME"):
        base.pop(key, None)
    base.update({k: v for k, v in overrides.items() if v is not None})
    return patch.dict(os.environ, base, clear=True)


class TestDataHome(unittest.TestCase):
    def test_defaults_under_local_share(self):
        with _env():
            self.assertEqual(
                data_home(),
                Path(os.path.expanduser("~/.local/share")) / APP_DIR_NAME,
            )

    def test_default_is_outside_the_checkout(self):
        """The whole point: generated files must not land in the checkout.

        Anchored to the repo root derived from ``__file__`` rather than to the
        working directory — tests run from a parent of the checkout (or from
        ``~``, which contains the default ``~/.local/share``) would make a
        cwd-based assertion say the wrong thing in either direction.
        """
        with _env():
            resolved = data_home()
            self.assertTrue(resolved.is_absolute())
            self.assertFalse(resolved.is_relative_to(REPO_ROOT))

    def test_xdg_data_home_is_honoured(self):
        with _env(XDG_DATA_HOME="/fake/xdg"):
            self.assertEqual(data_home(), Path("/fake/xdg") / APP_DIR_NAME)

    def test_project_env_var_wins_over_xdg(self):
        with _env(**{ENV_DATA_HOME: "/fake/project", "XDG_DATA_HOME": "/fake/xdg"}):
            self.assertEqual(data_home(), Path("/fake/project"))

    def test_project_env_var_is_used_verbatim(self):
        """The override names the root itself, without an app subdirectory."""
        with _env(**{ENV_DATA_HOME: "/fake/project"}):
            self.assertEqual(data_home(), Path("/fake/project"))
            self.assertNotIn(APP_DIR_NAME, data_home().parts)

    def test_tilde_is_expanded(self):
        with _env(**{ENV_DATA_HOME: "~/somewhere"}):
            self.assertEqual(data_home(), Path(os.path.expanduser("~/somewhere")))
            self.assertNotIn("~", str(data_home()))

    def test_empty_env_var_falls_through(self):
        with _env(**{ENV_DATA_HOME: ""}):
            self.assertEqual(
                data_home(),
                Path(os.path.expanduser("~/.local/share")) / APP_DIR_NAME,
            )


class TestOutputDir(unittest.TestCase):
    def test_domain_gets_its_own_subdirectory(self):
        with _env(**{ENV_DATA_HOME: "/fake/data"}):
            self.assertEqual(output_dir("resume"), Path("/fake/data/resume"))
            self.assertEqual(output_dir("charts"), Path("/fake/data/charts"))

    def test_domains_do_not_collide(self):
        with _env(**{ENV_DATA_HOME: "/fake/data"}):
            self.assertNotEqual(output_dir("resume"), output_dir("charts"))

    def test_override_wins_over_env(self):
        with _env(**{ENV_DATA_HOME: "/fake/data"}):
            self.assertEqual(output_dir("resume", "/elsewhere"), Path("/elsewhere"))

    def test_relative_override_is_kept_relative(self):
        """`--out-dir out` must still mean ./out for existing scripts."""
        with _env(**{ENV_DATA_HOME: "/fake/data"}):
            self.assertEqual(output_dir("resume", "out"), Path("out"))

    def test_override_expands_tilde(self):
        with _env():
            self.assertEqual(
                output_dir("resume", "~/mine"),
                Path(os.path.expanduser("~/mine")),
            )

    def test_falsy_override_falls_back_to_default(self):
        with _env(**{ENV_DATA_HOME: "/fake/data"}):
            self.assertEqual(output_dir("resume", None), Path("/fake/data/resume"))
            self.assertEqual(output_dir("resume", ""), Path("/fake/data/resume"))

    def test_accepts_path_objects(self):
        with _env():
            self.assertEqual(output_dir("resume", Path("/some/where")), Path("/some/where"))

    def test_does_not_create_directories(self):
        """Resolution is pure; callers decide when to mkdir."""
        with _env(**{ENV_DATA_HOME: "/fake/definitely-not-created-by-tests"}):
            resolved = output_dir("resume")
            self.assertFalse(resolved.exists())


if __name__ == "__main__":
    unittest.main()
