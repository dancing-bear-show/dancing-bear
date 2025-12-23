import json
import tempfile
import unittest
import subprocess
from pathlib import Path


CLI = ["python", "-m", "resume_assistant"]


class TestExperienceExport(unittest.TestCase):
    def test_experience_export_from_data(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            data = td / "data.json"
            out = td / "exp.yaml"
            payload = {
                "name": "Alex",
                "experience": [
                    {"title": "Engineer", "company": "Acme", "start": "2020", "end": "2022", "location": "Remote", "bullets": ["Did X", "Did Y"]},
                    {"title": "DevOps", "company": "Other", "start": "2018", "end": "2020", "location": "Remote", "bullets": ["Built CI", "Deployed"]},
                ],
            }
            data.write_text(json.dumps(payload), encoding="utf-8")
            r = subprocess.run(CLI + ["experience", "export", "--data", str(data), "--out", str(out)], capture_output=True)  # nosec B603
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertTrue(out.exists())
            # basic content check
            text = out.read_text(encoding="utf-8")
            self.assertIn("experience:", text)
            self.assertIn("Engineer", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)

