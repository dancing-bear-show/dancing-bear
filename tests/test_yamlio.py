import os
import tempfile
import unittest
from pathlib import Path

from tests.fixtures import has_pyyaml


@unittest.skipUnless(has_pyyaml(), "requires PyYAML")
class YamlIOTests(unittest.TestCase):
    def test_load_config_missing_returns_empty(self):
        from mail_assistant.yamlio import load_config

        with tempfile.TemporaryDirectory() as td:
            missing = os.path.join(td, "nope.yaml")
            self.assertEqual(load_config(missing), {})

    def test_dump_and_load_roundtrip(self):
        from mail_assistant.yamlio import load_config, dump_config

        data = {
            "filters": [
                {
                    "name": "Retailers",
                    "match": {"from": "(amazon|bestbuy|walmart)@*"},
                    "action": {"add": ["Lists/Commercial"], "remove": ["INBOX"]},
                }
            ],
            "labels": [
                {"name": "Lists/Commercial", "color": {"backgroundColor": "#00ff00", "textColor": "#000000"}}
            ],
        }
        with tempfile.TemporaryDirectory() as td:
            p = os.path.join(td, "cfg.yaml")
            dump_config(p, data)
            self.assertTrue(os.path.exists(p))

            loaded = load_config(p)
            self.assertEqual(loaded, data)

            # Ensure output is human-readable YAML (no Python tags)
            text = Path(p).read_text(encoding="utf-8")
            self.assertIn("filters:", text)
            self.assertIn("labels:", text)
            self.assertNotIn("!!python", text)


if __name__ == "__main__":
    unittest.main()
