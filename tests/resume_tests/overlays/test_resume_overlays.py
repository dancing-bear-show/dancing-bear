"""Tests for resume/overlays.py profile overlay functionality."""

import tempfile
import unittest
from pathlib import Path

from tests.fixtures import TempDirMixin


class TestApplyProfileOverlays(TempDirMixin, unittest.TestCase):
    """Tests for apply_profile_overlays function."""

    def _write_yaml(self, path: Path, content: str):
        """Write YAML content to a file."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def test_returns_data_unchanged_when_no_profile(self):
        from resume.overlays import apply_profile_overlays

        data = {"name": "John Doe", "skills": ["Python"]}
        result = apply_profile_overlays(data, None)
        self.assertEqual(result, data)

    def test_returns_data_unchanged_when_empty_profile(self):
        from resume.overlays import apply_profile_overlays

        data = {"name": "John Doe"}
        result = apply_profile_overlays(data, "")
        self.assertEqual(result, data)

    def test_applies_profile_config_from_new_path(self):
        from resume.overlays import apply_profile_overlays

        with self.in_tmpdir():
            profile_dir = Path("config/profiles/tech")
            self._write_yaml(
                profile_dir / "profile.yaml",
                "name: Jane Smith\nheadline: Software Engineer\nemail: jane@example.com\n",
            )

            data = {"name": "Original Name"}
            result = apply_profile_overlays(data, "tech")

            self.assertEqual(result["name"], "Jane Smith")
            self.assertEqual(result["headline"], "Software Engineer")
            self.assertEqual(result["email"], "jane@example.com")

    def test_applies_profile_config_from_legacy_path(self):
        from resume.overlays import apply_profile_overlays

        with self.in_tmpdir():
            # Legacy path: config/profile.<profile>.yaml
            self._write_yaml(
                Path("config/profile.legacy.yaml"),
                "name: Legacy Name\nphone: 555-1234\n",
            )

            data = {"name": "Original"}
            result = apply_profile_overlays(data, "legacy")

            self.assertEqual(result["name"], "Legacy Name")
            self.assertEqual(result["phone"], "555-1234")

    def test_new_path_takes_precedence_over_legacy(self):
        from resume.overlays import apply_profile_overlays

        with self.in_tmpdir():
            # Both paths exist - new should win
            profile_dir = Path("config/profiles/both")
            self._write_yaml(profile_dir / "profile.yaml", "name: New Path\n")
            self._write_yaml(Path("config/profile.both.yaml"), "name: Legacy Path\n")

            data = {}
            result = apply_profile_overlays(data, "both")

            self.assertEqual(result["name"], "New Path")

    def test_applies_contact_nested_fields(self):
        from resume.overlays import apply_profile_overlays

        with self.in_tmpdir():
            profile_dir = Path("config/profiles/contact")
            self._write_yaml(
                profile_dir / "profile.yaml",
                "contact:\n"
                "  email: contact@example.com\n"
                "  phone: 555-9999\n"
                "  location: San Francisco\n"
                "  links:\n"
                "    - url: https://github.com/user\n",
            )

            data = {}
            result = apply_profile_overlays(data, "contact")

            self.assertEqual(result["email"], "contact@example.com")
            self.assertEqual(result["phone"], "555-9999")
            self.assertEqual(result["location"], "San Francisco")
            self.assertEqual(result["links"], [{"url": "https://github.com/user"}])

    def test_does_not_overwrite_existing_contact_fields(self):
        from resume.overlays import apply_profile_overlays

        with self.in_tmpdir():
            profile_dir = Path("config/profiles/partial")
            self._write_yaml(
                profile_dir / "profile.yaml",
                "contact:\n  email: new@example.com\n  phone: 555-NEW\n",
            )

            data = {"email": "existing@example.com"}
            result = apply_profile_overlays(data, "partial")

            # Existing email should be preserved
            self.assertEqual(result["email"], "existing@example.com")
            # Phone should be added since it didn't exist
            self.assertEqual(result["phone"], "555-NEW")

    def test_applies_skills_groups_and_experience_overlays(self):
        """Each overlay filename dispatches to its own result key.

        skills_groups.yaml populates result["skills_groups"]; experience.yaml
        populates result["experience"] — two separate dispatch branches in
        apply_profile_overlays, exercised here as parallel cases.
        """
        from resume.overlays import apply_profile_overlays

        cases = [
            (
                "skills_groups",
                "skills", "skills_groups.yaml",
                "groups:\n"
                "  - name: Languages\n"
                "    skills: [Python, Java]\n"
                "  - name: Tools\n"
                "    skills: [Docker, K8s]\n",
                "skills_groups", "name", "Languages",
            ),
            (
                "experience",
                "exp", "experience.yaml",
                "experience:\n"
                "  - title: Senior Engineer\n"
                "    company: TechCorp\n"
                "  - title: Junior Dev\n"
                "    company: StartupXYZ\n",
                "experience", "title", "Senior Engineer",
            ),
        ]
        for label, profile, filename, yaml_content, result_key, item_key, first_value in cases:
            with self.subTest(label), self.in_tmpdir():
                profile_dir = Path("config/profiles") / profile
                self._write_yaml(profile_dir / filename, yaml_content)

                data = {}
                result = apply_profile_overlays(data, profile)

                self.assertEqual(len(result[result_key]), 2)
                self.assertEqual(result[result_key][0][item_key], first_value)

    def test_applies_experience_from_roles_key(self):
        from resume.overlays import apply_profile_overlays

        with self.in_tmpdir():
            profile_dir = Path("config/profiles/roles")
            self._write_yaml(
                profile_dir / "experience.yaml",
                "roles:\n  - title: Manager\n    company: BigCo\n",
            )

            data = {}
            result = apply_profile_overlays(data, "roles")

            self.assertEqual(result["experience"][0]["title"], "Manager")

    def test_applies_list_overlays(self):
        from resume.overlays import apply_profile_overlays

        with self.in_tmpdir():
            profile_dir = Path("config/profiles/lists")
            self._write_yaml(
                profile_dir / "interests.yaml",
                "interests:\n  - Open Source\n  - Machine Learning\n",
            )
            self._write_yaml(
                profile_dir / "languages.yaml",
                "languages:\n  - English\n  - Spanish\n",
            )
            self._write_yaml(
                profile_dir / "certifications.yaml",
                "certifications:\n  - AWS Solutions Architect\n",
            )

            data = {}
            result = apply_profile_overlays(data, "lists")

            self.assertEqual(result["interests"], ["Open Source", "Machine Learning"])
            self.assertEqual(result["languages"], ["English", "Spanish"])
            self.assertEqual(result["certifications"], ["AWS Solutions Architect"])

    def test_handles_raw_list_overlay(self):
        from resume.overlays import apply_profile_overlays

        with self.in_tmpdir():
            profile_dir = Path("config/profiles/rawlist")
            # Some overlays might be raw lists
            self._write_yaml(
                profile_dir / "interests.yaml",
                "- Photography\n- Hiking\n",
            )

            data = {}
            result = apply_profile_overlays(data, "rawlist")

            self.assertEqual(result["interests"], ["Photography", "Hiking"])

    def test_handles_interests_in_profile(self):
        from resume.overlays import apply_profile_overlays

        with self.in_tmpdir():
            profile_dir = Path("config/profiles/inprofile")
            self._write_yaml(
                profile_dir / "profile.yaml",
                "name: Test\ninterests:\n  - Reading\npresentations:\n  - Talk 1\n",
            )

            data = {}
            result = apply_profile_overlays(data, "inprofile")

            self.assertEqual(result["interests"], ["Reading"])
            self.assertEqual(result["presentations"], ["Talk 1"])

    def test_handles_malformed_files_gracefully(self):
        from resume.overlays import apply_profile_overlays

        with self.in_tmpdir():
            profile_dir = Path("config/profiles/bad")
            # Write invalid YAML
            (profile_dir / "profile.yaml").parent.mkdir(parents=True, exist_ok=True)
            (profile_dir / "profile.yaml").write_text("{{invalid yaml")

            data = {"name": "Original"}
            # Should not raise, just return original data
            result = apply_profile_overlays(data, "bad")

            self.assertEqual(result["name"], "Original")


class TestApplyProfileOverlaysNestedGroupItems(TempDirMixin, unittest.TestCase):
    """apply_profile_overlays passes through nested dict items in skills groups."""

    def test_skills_groups_nested_dict_items_pass_through(self):
        # Distinct from the flat name/skills shape covered elsewhere: this
        # group shape nests title/items with dict items carrying name/desc.
        from resume.overlays import apply_profile_overlays

        with self.in_tmpdir():
            profile_dir = Path("config/profiles/nested")
            profile_dir.mkdir(parents=True, exist_ok=True)
            (profile_dir / "skills_groups.yaml").write_text(
                "groups:\n"
                "  - title: Platform\n"
                "    items:\n"
                "      - name: Kubernetes\n"
                "        desc: clusters\n"
            )

            data = {}
            result = apply_profile_overlays(data, "nested")

            self.assertEqual(result["skills_groups"][0]["title"], "Platform")
            self.assertEqual(result["skills_groups"][0]["items"][0]["name"], "Kubernetes")
            self.assertEqual(result["skills_groups"][0]["items"][0]["desc"], "clusters")


class TestTryLoadFromPaths(unittest.TestCase):
    """Tests for _try_load_from_paths helper."""

    def test_returns_none_when_no_paths_exist(self):
        from resume.overlays import _try_load_from_paths

        result = _try_load_from_paths((Path("/nonexistent/a.yaml"), Path("/nonexistent/b.yaml")))
        self.assertIsNone(result)

    def test_loads_first_existing_path(self):
        from resume.overlays import _try_load_from_paths

        with tempfile.TemporaryDirectory() as tmpdir:
            p1 = Path(tmpdir) / "first.yaml"
            p2 = Path(tmpdir) / "second.yaml"
            p1.write_text("key: first\n")
            p2.write_text("key: second\n")

            result = _try_load_from_paths((p1, p2))
            self.assertEqual(result["key"], "first")

    def test_falls_back_to_second_path(self):
        from resume.overlays import _try_load_from_paths

        with tempfile.TemporaryDirectory() as tmpdir:
            p1 = Path(tmpdir) / "nonexistent.yaml"
            p2 = Path(tmpdir) / "exists.yaml"
            p2.write_text("key: second\n")

            result = _try_load_from_paths((p1, p2))
            self.assertEqual(result["key"], "second")


class TestGetOverlayPaths(unittest.TestCase):
    """Tests for _get_overlay_paths helper."""

    def test_returns_new_and_legacy_paths(self):
        from resume.overlays import _get_overlay_paths

        prof_dir = Path("config/profiles/myprof")
        cfg_dir = Path("config")
        new_path, old_path = _get_overlay_paths(prof_dir, cfg_dir, "myprof", "skills")
        self.assertEqual(new_path, Path("config/profiles/myprof/skills.yaml"))
        self.assertEqual(old_path, Path("config/skills.myprof.yaml"))


class TestLoadListOverlay(TempDirMixin, unittest.TestCase):
    """Tests for _load_list_overlay helper."""

    def test_dict_format_with_matching_key(self):
        from resume.overlays import _load_list_overlay

        prof_dir = Path(self.tmpdir) / "profiles" / "test"
        prof_dir.mkdir(parents=True)
        (prof_dir / "interests.yaml").write_text("interests:\n  - Reading\n  - Coding\n")

        result = _load_list_overlay(prof_dir, Path(self.tmpdir), "test", "interests")
        self.assertEqual(result, ["Reading", "Coding"])

    def test_raw_list_format(self):
        from resume.overlays import _load_list_overlay

        prof_dir = Path(self.tmpdir) / "profiles" / "test"
        prof_dir.mkdir(parents=True)
        (prof_dir / "hobbies.yaml").write_text("- Gaming\n- Music\n")

        result = _load_list_overlay(prof_dir, Path(self.tmpdir), "test", "hobbies")
        self.assertEqual(result, ["Gaming", "Music"])

    def test_returns_none_when_not_found(self):
        from resume.overlays import _load_list_overlay

        prof_dir = Path(self.tmpdir) / "profiles" / "test"
        result = _load_list_overlay(prof_dir, Path(self.tmpdir), "test", "missing")
        self.assertIsNone(result)


class TestApplyProfileConfig(unittest.TestCase):
    """Tests for _apply_profile_config helper."""

    def test_applies_top_level_fields(self):
        from resume.overlays import _apply_profile_config

        out = {}
        prof_data = {"name": "John Doe", "headline": "Engineer"}
        _apply_profile_config(out, prof_data)
        self.assertEqual(out["name"], "John Doe")
        self.assertEqual(out["headline"], "Engineer")

    def test_applies_nested_contact(self):
        from resume.overlays import _apply_profile_config

        out = {}
        prof_data = {
            "contact": {
                "email": "john@example.com",
                "phone": "555-1234",
                "links": ["https://github.com/john"],
            }
        }
        _apply_profile_config(out, prof_data)
        self.assertEqual(out["email"], "john@example.com")
        self.assertEqual(out["phone"], "555-1234")
        self.assertEqual(out["links"], ["https://github.com/john"])

    def test_does_not_override_existing_contact(self):
        from resume.overlays import _apply_profile_config

        out = {"email": "existing@example.com"}
        prof_data = {"contact": {"email": "new@example.com"}}
        _apply_profile_config(out, prof_data)
        self.assertEqual(out["email"], "existing@example.com")

    def test_applies_lists(self):
        from resume.overlays import _apply_profile_config

        out = {}
        prof_data = {"interests": ["Reading", "Hiking"], "presentations": ["Talk 1"]}
        _apply_profile_config(out, prof_data)
        self.assertEqual(out["interests"], ["Reading", "Hiking"])
        self.assertEqual(out["presentations"], ["Talk 1"])


if __name__ == "__main__":
    unittest.main()
