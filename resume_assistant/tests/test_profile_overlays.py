import json
import unittest
from pathlib import Path

from resume_assistant.overlays import apply_profile_overlays


class TestProfileOverlays(unittest.TestCase):
    def test_structured_profile_dir_overlays(self):
        profile = "test_profile"
        base = {
            "name": "Base Name",
            "email": "base@example.com",
            "skills_groups": [],
        }
        prof_dir = Path("config") / "profiles" / profile
        prof_dir.mkdir(parents=True, exist_ok=True)
        paths = [
            prof_dir / "profile.yaml",
            prof_dir / "skills_groups.yaml",
            prof_dir / "experience.yaml",
            prof_dir / "interests.yaml",
        ]
        try:
            (prof_dir / "profile.yaml").write_text(
                "\n".join(
                    [
                        "name: Profile Name",
                        "contact:",
                        "  email: contact@example.com",
                        "  links:",
                        "    - https://example.com",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (prof_dir / "skills_groups.yaml").write_text(
                "\n".join(
                    [
                        "groups:",
                        "  - title: Platform",
                        "    items:",
                        "      - name: Kubernetes",
                        "        desc: clusters",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (prof_dir / "experience.yaml").write_text(
                "\n".join(
                    [
                        "experience:",
                        "  - title: SRE",
                        "    company: ExampleCo",
                        "    start: 2020",
                        "    end: 2023",
                        "    bullets:",
                        "      - Built alerts",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            (prof_dir / "interests.yaml").write_text(
                "\n".join(
                    [
                        "interests:",
                        "  - Running",
                        "  - Writing",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            out = apply_profile_overlays(base, profile)

            self.assertEqual(out.get("name"), "Profile Name")
            # Contact email should not override an existing base email.
            self.assertEqual(out.get("email"), "base@example.com")
            self.assertEqual(out.get("links"), ["https://example.com"])
            self.assertEqual(out.get("skills_groups")[0]["title"], "Platform")
            self.assertEqual(out.get("experience")[0]["title"], "SRE")
            self.assertEqual(out.get("interests"), ["Running", "Writing"])
        finally:
            for p in paths:
                try:
                    p.unlink()
                except FileNotFoundError:
                    pass
            try:
                (prof_dir / "__pycache__").rmdir()
            except Exception:
                pass
            try:
                prof_dir.rmdir()
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main(verbosity=2)
