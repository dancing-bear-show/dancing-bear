import json
import tempfile
import unittest
import subprocess
from pathlib import Path


CLI = ["python", "-m", "resume_assistant"]


class TestOnePageRender(unittest.TestCase):
    def test_onepage_render_skippable(self):
        try:
            import docx  # noqa: F401
        except Exception:
            self.skipTest("python-docx not installed")

        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            data = td / "data.json"
            out = td / "out.docx"
            # Build candidate data with 5 roles and >3 bullets each
            exp = []
            for i in range(1, 6):
                exp.append({
                    "title": f"Engineer {i}",
                    "company": f"Co{i}",
                    "start": f"202{i}",
                    "end": f"202{i+1}",
                    "location": "Remote",
                    "bullets": [
                        f"Did thing {j} for role {i}" for j in range(1, 6)
                    ],
                })
            payload = {
                "name": "Test Person",
                "email": "test@example.com",
                "phone": "5550001111",
                "location": "Somewhere, ZZ",
                "summary": "Impactful engineer. Builds reliable systems. Ships results.",
                "skills_groups": [
                    {"title": "Platform", "items": ["AWS", "Kubernetes", "Architecture"]},
                    {"title": "Reliability", "items": ["SLOs", "On-call", "Incidents", "Postmortems"]},
                ],
                "experience": exp,
                "education": [{"degree": "BS CS", "institution": "Uni", "year": "2012"}],
            }
            data.write_text(json.dumps(payload), encoding="utf-8")

            r = subprocess.run(CLI + [
                "render", "--data", str(data), "--template", "config/template.onepage.yaml", "--out", str(out)
            ])
            self.assertEqual(r.returncode, 0)
            self.assertTrue(out.exists())

            # Inspect docx for margins and role trimming
            from docx import Document  # type: ignore

            doc = Document(str(out))
            # Margins should be <= 0.5" per onepage template (0.4")
            sec = doc.sections[0]
            # value is in EMUs; compare in inches
            def emu_to_in(v):
                try:
                    return v.inches
                except Exception:
                    # Fallback for older versions
                    return float(v) / 914400.0

            self.assertLessEqual(emu_to_in(sec.left_margin), 0.5 + 1e-6)
            # Ensure only first 4 roles rendered
            text = "\n".join(p.text for p in doc.paragraphs)
            self.assertIn("Engineer 4 at Co4", text)
            self.assertNotIn("Engineer 5 at Co5", text)
            # Ensure bullets per role trimmed to <=3 (spot check role 1)
            self.assertIn("Did thing 3 for role 1", text)
            self.assertNotIn("Did thing 4 for role 1", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)

