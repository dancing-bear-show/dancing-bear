import io
import unittest
from contextlib import redirect_stdout

from tests.fixtures import bin_path, repo_root


class TestLlmCli(unittest.TestCase):
    def test_help(self):
        import subprocess  # nosec B404
        import sys
        root = repo_root()
        proc = subprocess.run([sys.executable, str(bin_path('llm')), '--help'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(root))  # nosec B603 - test code with trusted local script
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn('Unified LLM utilities', proc.stdout)

    def test_inventory_stdout(self):
        from mail import llm_cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = llm_cli.main(['inventory', '--stdout'])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn('LLM Agent Inventory', out)

    def test_familiar_stdout(self):
        from mail import llm_cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = llm_cli.main(['familiar', '--stdout'])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn('agent_note:', out)

    def test_inventory_json(self):
        from mail import llm_cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = llm_cli.main(['inventory', '--format', 'json', '--stdout'])
        self.assertEqual(rc, 0)
        import json
        data = json.loads(buf.getvalue())
        self.assertIn('wrappers', data)
        self.assertIn('areas', data)
        self.assertIn('mail_groups', data)

    def test_inventory_is_not_self_referential(self):
        """The markdown inventory must carry real content, not a pointer to itself."""
        from mail import llm_cli
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = llm_cli.main(['inventory', '--stdout'])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertNotIn('(see .llm/INVENTORY.md)', out)
        for package in ('mail', 'calendars', 'workflow', 'telemetry'):
            self.assertIn(package, out)

    def test_inventory_json_reflects_real_packages(self):
        """JSON inventory is derived from the repo, not a hardcoded stub."""
        from mail import llm_cli
        import json
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = llm_cli.main(['inventory', '--format', 'json', '--stdout'])
        self.assertEqual(rc, 0)
        data = json.loads(buf.getvalue())
        # The old stub returned exactly ["bin/mail-assistant"] and ["mail", "calendar"].
        self.assertGreater(len(data['packages']), 10)
        self.assertGreater(len(data['wrappers']), 10)
        self.assertIn('workflow', data['packages'])

    def test_check_respects_sla_env(self):
        import subprocess  # nosec B404
        import sys
        import os
        root = repo_root()
        env = dict(os.environ)
        # Allow .llm to be considered within SLA to avoid failing in CI
        env['LLM_SLA'] = '.llm:365,Root:365'
        proc = subprocess.run([sys.executable, str(bin_path('llm')), 'check'], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=str(root), env=env)  # nosec B603 - test code with trusted local script
        self.assertEqual(proc.returncode, 0, msg=proc.stdout + "\n" + proc.stderr)

    def test_repo_llm_app_phone(self):
        from core import llm_cli as repo_llm
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = repo_llm.main(['--app', 'phone', 'agentic', '--stdout'])
        self.assertEqual(rc, 0)
        out = buf.getvalue()
        self.assertIn('agentic: phone', out)

    def test_default_llm_config_derive_all_includes_shared_files(self):
        """A config that does not opt out still derives the three shared docs.

        The domain fix works by setting inventory_filename / familiar_filename /
        policies_filename to None in make_domain_llm_module, which required
        widening those LlmConfig fields to `str | None`. Their DEFAULTS are the
        compatibility contract for any direct LlmConfig / make_app_llm_config
        caller, and nothing else pins them: the repo-level test below exercises
        _handle_derive_all, which hard-codes the DEFAULT_* constants, and every
        domain test asserts these fields are None. Verified the gap by setting
        familiar_filename's default to None -- the whole tests/llm suite stayed
        green.
        """
        from core.llm_cli import _collect_derive_outputs, make_app_llm_config

        config = make_app_llm_config(
            prog='llm-probe',
            description='probe',
            agentic=lambda: 'agentic: probe',
            domain_map=lambda: 'domain map',
            inventory=lambda: 'inventory body',
            familiar_compact=lambda: 'familiar body',
            policies=lambda: 'policies body',
        )
        written = {name for name, _ in _collect_derive_outputs(config)}
        for name in ('INVENTORY.md', 'familiarize.yaml', 'PR_POLICIES.yaml'):
            self.assertIn(
                name,
                written,
                f'default LlmConfig must still derive {name}; a caller that does '
                'not opt out relies on these defaults',
            )

    def test_repo_derive_all_still_writes_shared_files(self):
        """The repo-level generator owns the five shared .llm/ docs.

        Counterpart to LLMCLIContractMixin.test_derive_all_outputs_files, which
        asserts the opposite for DOMAIN modules. Domain derive-all was writing
        unsuffixed INVENTORY.md / familiarize.yaml / PR_POLICIES.yaml, so
        `llm --app phone derive-all --out-dir .llm` replaced the repo-wide
        capsule with phone's.

        Note this does NOT guard the domain fix directly: _handle_derive_all
        builds its output list from the DEFAULT_*_FILENAME constants and never
        reads LlmConfig, so the two paths are independent by construction --
        verified by setting LlmConfig.inventory_filename's default to None,
        which leaves this test passing. It pins the repo-level contract itself,
        which workflows/shared/sync-docs-on-land.yaml depends on: it regenerates
        .llm/ with this command and gates on `git diff --exit-code`.
        """
        import tempfile
        from pathlib import Path

        from core import llm_cli as repo_llm

        with tempfile.TemporaryDirectory() as td:
            buf = io.StringIO()
            with redirect_stdout(buf):
                rc = repo_llm.main(
                    ['derive-all', '--out-dir', td, '--include-generated', '--stdout']
                )
            self.assertEqual(rc, 0)
            for name in (
                'AGENTIC.md',
                'DOMAIN_MAP.md',
                'INVENTORY.md',
                'familiarize.yaml',
                'PR_POLICIES.yaml',
            ):
                path = Path(td) / name
                self.assertTrue(
                    path.exists(), f'repo-level derive-all must write {name}'
                )
                self.assertGreater(
                    path.stat().st_size, 0, f'{name} was written empty'
                )


if __name__ == '__main__':
    unittest.main()
