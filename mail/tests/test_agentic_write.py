import sys
import tempfile
import unittest
from pathlib import Path


class TestAgenticWrite(unittest.TestCase):
    def setUp(self) -> None:
        pkg_parent = Path(__file__).resolve().parents[2]
        sys.path.insert(0, str(pkg_parent))

    def test_agentic_write_to_file(self):
        import mail_assistant.llm_cli as mod  # type: ignore
        with tempfile.TemporaryDirectory() as td:
            target = Path(td) / 'AGENTIC.out.md'
            rc = mod.main(["agentic", "--write", str(target)])
            self.assertEqual(rc, 0)
            content = target.read_text(encoding='utf-8')
            self.assertTrue(content.startswith("agentic: mail_assistant"))

