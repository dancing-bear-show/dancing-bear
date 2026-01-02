import os
import stat
import subprocess
import tempfile
import textwrap
from pathlib import Path
import unittest

from tests.fixtures import bin_path, repo_root


class TestIosInstallProfileAuth(unittest.TestCase):
    def setUp(self):
        self.repo_root = repo_root()
        self.bin_install = bin_path("ios-install-profile")
        self.assertTrue(self.bin_install.exists(), "ios-install-profile not found")

        # Temp workspace for stubs and config
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tmpdir = Path(self.tmp.name)

        # Stub cfgutil that records args
        self.capture_file = self.tmpdir / "cfgutil_args.txt"
        cfgutil = self.tmpdir / "cfgutil"
        cfgutil.write_text(textwrap.dedent(f"""
            #!/usr/bin/env bash
            set -euo pipefail
            if [[ "${{1:-}}" == "list" ]]; then
              echo "Type: iPad16,2\tECID: 0xEC1D\tUDID: TESTUDID Location: 0x100000 Name: iPad"
              exit 0
            fi
            echo "$@" >> "{self.capture_file}"
            exit 0
        """), encoding="utf-8")
        os.chmod(cfgutil, stat.S_IRWXU)

        # Stub openssl that creates requested output files
        openssl = self.tmpdir / "openssl"
        openssl.write_text(textwrap.dedent("""
            #!/usr/bin/env bash
            set -euo pipefail
            cmd=${1:-}
            shift || true
            out=""
            # Find -out <path> in args
            while [[ $# -gt 0 ]]; do
              if [[ "$1" == "-out" ]]; then
                out="$2"; shift 2; continue
              fi
              shift || true
            done
            if [[ -n "$out" ]]; then
              mkdir -p "$(dirname "$out")"
              printf 'DER' > "$out"
            fi
            exit 0
        """), encoding="utf-8")
        os.chmod(openssl, stat.S_IRWXU)

        # Config directory and credentials.ini
        cfg_dir = self.tmpdir
        cfg_dir.mkdir(parents=True, exist_ok=True)
        self.credentials = cfg_dir / "credentials.ini"

        # Dummy supervision identity .p12 and profile
        self.p12 = self.tmpdir / "SHERWIN.p12"
        self.p12.write_bytes(b"dummy p12")
        self.profile = self.tmpdir / "test.mobileconfig"
        self.profile.write_text("profile", encoding="utf-8")

        self.credentials.write_text(textwrap.dedent(f"""
            [ios_layout_manager]
            supervision_identity_p12 = {self.p12}
            supervision_identity_pass = TESTPASS
        """), encoding="utf-8")

        # Environment for the test
        self.env = os.environ.copy()
        # Prepend stub bin to PATH
        self.env["PATH"] = f"{self.tmpdir}:{self.env.get('PATH','')}"
        # XDG config so resolve_config finds our credentials
        self.env["XDG_CONFIG_HOME"] = str(self.tmpdir)

    def run_install(self, extra_args=None):
        args = [str(self.bin_install), "--udid", "TESTUDID", "--profile", str(self.profile), "--creds-profile", "ios_layout_manager"]
        if extra_args:
            args.extend(extra_args)
        return subprocess.run(args, env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)  # nosec S603 - test code with trusted local script

    def test_reads_identity_from_credentials_and_passes_to_cfgutil(self):
        # Run installer; stubs should cause success
        proc = self.run_install()
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        # Verify cfgutil was invoked with certificate and private-key options
        self.assertTrue(self.capture_file.exists(), "cfgutil capture not found; stub may not have been used")
        content = self.capture_file.read_text(encoding="utf-8")
        self.assertIn("install-profile", content)
        self.assertIn(str(self.profile), content)
        self.assertIn("--certificate", content)
        self.assertIn("--private-key", content)


if __name__ == "__main__":
    unittest.main(verbosity=2)
