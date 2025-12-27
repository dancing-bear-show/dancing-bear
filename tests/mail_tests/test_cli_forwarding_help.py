import unittest

from tests.fixtures import bin_path, has_pyyaml, repo_root, run


@unittest.skipUnless(has_pyyaml(), "requires PyYAML")
class ForwardingHelpTests(unittest.TestCase):
    def test_forwarding_group_help_lists_subcommands(self):
        root = repo_root()
        wrapper = bin_path("mail")
        self.assertTrue(wrapper.exists(), "bin/mail not found")
        proc = run([str(wrapper), "forwarding", "--help"], cwd=str(root))
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        out = proc.stdout
        # Expect key subcommands present in help
        self.assertIn("list", out)
        self.assertIn("add", out)
        self.assertIn("status", out)
        self.assertIn("enable", out)
        self.assertIn("disable", out)


if __name__ == "__main__":
    unittest.main()
