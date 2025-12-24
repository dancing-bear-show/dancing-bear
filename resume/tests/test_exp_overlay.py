import json
import tempfile
import unittest
import subprocess
import sys
from pathlib import Path


CLI = [sys.executable, "-m", "resume"]


class TestExperienceOverlay(unittest.TestCase):
    def test_overlay_experience_from_config(self):
        try:
            import docx  # noqa: F401
        except Exception:
            self.skipTest("python-docx not installed")

        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            data = td / "data.json"
            out = td / "out.docx"
            profile = "test_profile"
            # base data with a role we expect to be replaced
            payload = {
                "name": "Overlay Test",
                "experience": [
                    {"title": "Old Role", "company": "OldCo", "start": "2020", "end": "2021", "location": "Remote", "bullets": ["Old bullet"]}
                ],
            }
            data.write_text(json.dumps(payload), encoding="utf-8")
            # write overlay under config/
            cfg = Path("config") / f"experience.{profile}.yaml"
            cfg.write_text(
                """
experience:
  - title: New Role
    company: NewCo
    start: 2022
    end: 2023
    location: Remote
    bullets:
      - New bullet A
      - New bullet B
""".strip(),
                encoding="utf-8",
            )
            try:
                r = subprocess.run(  # nosec B603
                    CLI
                    + [
                        "render",
                        "--data",
                        str(data),
                        "--template",
                        "config/template.onepage.yaml",
                        "--profile",
                        profile,
                        "--out",
                        str(out),
                    ],
                    capture_output=True,
                )
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertTrue(out.exists())
                # inspect docx text contains New Role and not Old Role
                from docx import Document  # type: ignore

                doc = Document(str(out))
                text = "\n".join(p.text for p in doc.paragraphs)
                self.assertIn("New Role at NewCo", text)
                self.assertNotIn("Old Role at OldCo", text)
            finally:
                try:
                    cfg.unlink()
                except Exception:
                    pass  # nosec B110 - test cleanup


if __name__ == "__main__":
    unittest.main(verbosity=2)
