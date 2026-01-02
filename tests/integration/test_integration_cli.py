"""Integration tests for CLI wrappers.

Tests that bin wrappers are executable and produce expected help output.
"""

import os
import subprocess
import sys
import unittest

from tests.fixtures import bin_path, repo_root


def _is_shell_script(path) -> bool:
    """Check if file starts with #!/usr/bin/env bash or similar."""
    try:
        with open(path, "rb") as f:
            first_line = f.readline()
            return b"bash" in first_line or b"/bin/sh" in first_line
    except Exception:
        return False


class IntegrationCLITests(unittest.TestCase):
    """Test bin wrapper execution."""

    def _run_wrapper(self, name: str, args: list[str] | None = None) -> subprocess.CompletedProcess:
        wrapper = bin_path(name)
        self.assertTrue(wrapper.exists(), f"bin/{name} not found")
        try:
            mode = os.stat(wrapper).st_mode
            os.chmod(wrapper, mode | 0o111)
        except Exception:  # nosec B110 - chmod in tests
            pass

        # Use bash for shell scripts, Python for Python scripts
        if _is_shell_script(wrapper):
            cmd = ["bash", str(wrapper)] + (args or ["--help"])
        else:
            cmd = [sys.executable, str(wrapper)] + (args or ["--help"])
        return subprocess.run(cmd, cwd=str(repo_root()), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)  # nosec B603 - test code with trusted local scripts

    def test_mail_underscore_help(self):
        proc = self._run_wrapper("mail")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("Mail Assistant CLI", proc.stdout)

    def test_mail_hyphen_help(self):
        proc = self._run_wrapper("mail-assistant")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("Mail Assistant CLI", proc.stdout)

    def test_calendar_help(self):
        proc = self._run_wrapper("calendar-assistant")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("calendar", proc.stdout.lower())

    def test_schedule_help(self):
        proc = self._run_wrapper("schedule-assistant")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("schedule", proc.stdout.lower())

    def test_phone_help(self):
        proc = self._run_wrapper("phone")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("phone", proc.stdout.lower())

    def test_whatsapp_help(self):
        proc = self._run_wrapper("whatsapp")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("whatsapp", proc.stdout.lower())

    def test_maker_help(self):
        proc = self._run_wrapper("maker")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("maker", proc.stdout.lower())

    def test_wifi_help(self):
        proc = self._run_wrapper("wifi")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("wifi", proc.stdout.lower())

    def test_llm_help(self):
        proc = self._run_wrapper("llm")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("llm", proc.stdout.lower())


class AssistantDispatcherIntegrationTests(unittest.TestCase):
    """Test the unified assistant dispatcher with real app loading."""

    def _run_assistant(self, args: list[str]) -> subprocess.CompletedProcess:
        wrapper = bin_path("assistant")
        cmd = [sys.executable, str(wrapper)] + args
        return subprocess.run(cmd, cwd=str(repo_root()), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)  # nosec B603 - test code with trusted local scripts

    def test_assistant_no_args(self):
        proc = self._run_assistant([])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("Usage:", proc.stdout)

    def test_assistant_help(self):
        proc = self._run_assistant(["--help"])
        self.assertEqual(proc.returncode, 0)
        self.assertIn("mail", proc.stdout)
        self.assertIn("calendar", proc.stdout)

    def test_assistant_mail_help(self):
        proc = self._run_assistant(["mail", "--help"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("Mail Assistant CLI", proc.stdout)

    def test_assistant_calendar_help(self):
        proc = self._run_assistant(["calendar", "--help"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("calendar", proc.stdout.lower())

    def test_assistant_schedule_help(self):
        proc = self._run_assistant(["schedule", "--help"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("schedule", proc.stdout.lower())

    def test_assistant_phone_help(self):
        proc = self._run_assistant(["phone", "--help"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("phone", proc.stdout.lower())

    def test_assistant_whatsapp_help(self):
        proc = self._run_assistant(["whatsapp", "--help"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("whatsapp", proc.stdout.lower())

    def test_assistant_maker_help(self):
        proc = self._run_assistant(["maker", "--help"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("maker", proc.stdout.lower())

    def test_assistant_wifi_help(self):
        proc = self._run_assistant(["wifi", "--help"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("wifi", proc.stdout.lower())

    def test_assistant_resume_help(self):
        proc = self._run_assistant(["resume", "--help"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("resume", proc.stdout.lower())

    def test_assistant_unknown_app(self):
        proc = self._run_assistant(["nonexistent"])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("Unknown app", proc.stderr)


class LLMCLIIntegrationTests(unittest.TestCase):
    """Test LLM CLI subcommands."""

    def _run_llm(self, args: list[str]) -> subprocess.CompletedProcess:
        wrapper = bin_path("llm")
        cmd = [sys.executable, str(wrapper)] + args
        return subprocess.run(cmd, cwd=str(repo_root()), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)  # nosec B603 - test code with trusted local scripts

    def test_llm_agentic_stdout(self):
        proc = self._run_llm(["agentic", "--stdout"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("agentic", proc.stdout.lower())

    def test_llm_domain_map_stdout(self):
        proc = self._run_llm(["domain-map", "--stdout"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        # Domain map contains CLI tree or flows
        self.assertGreater(len(proc.stdout), 100)

    def test_llm_familiar_stdout(self):
        proc = self._run_llm(["familiar", "--stdout"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("steps:", proc.stdout)

    def test_llm_flows_list(self):
        proc = self._run_llm(["flows", "--list"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        # Should list at least one flow
        self.assertIn("-", proc.stdout)

    def test_llm_stale(self):
        proc = self._run_llm(["stale", "--limit", "5"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        # Should output a table with area headers
        self.assertIn("Area", proc.stdout)

    def test_llm_deps(self):
        proc = self._run_llm(["deps", "--limit", "5"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        # Should output a table with dependency headers
        self.assertIn("Dependencies", proc.stdout)

    def test_llm_app_calendar_agentic(self):
        proc = self._run_llm(["--app", "calendar", "agentic", "--stdout"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("calendar", proc.stdout.lower())

    def test_llm_app_schedule_agentic(self):
        proc = self._run_llm(["--app", "schedule", "agentic", "--stdout"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("schedule", proc.stdout.lower())

    def test_llm_inventory_stdout(self):
        proc = self._run_llm(["inventory", "--stdout"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("inventory", proc.stdout.lower())

    def test_llm_policies_stdout(self):
        proc = self._run_llm(["policies", "--stdout"])
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)
        self.assertIn("policies", proc.stdout.lower())


class IOSWrapperIntegrationTests(unittest.TestCase):
    """Test iOS-related wrappers (help only, no device required)."""

    def _run_wrapper(self, name: str) -> subprocess.CompletedProcess:
        wrapper = bin_path(name)
        if not wrapper.exists():
            self.skipTest(f"bin/{name} not found")
        # iOS wrappers are bash scripts
        cmd = ["bash", str(wrapper), "--help"]
        return subprocess.run(cmd, cwd=str(repo_root()), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)  # nosec B603 - test code with trusted local scripts

    def test_ios_export_help(self):
        proc = self._run_wrapper("ios-export")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)

    def test_ios_plan_help(self):
        proc = self._run_wrapper("ios-plan")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)

    def test_ios_checklist_help(self):
        proc = self._run_wrapper("ios-checklist")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)

    def test_ios_analyze_help(self):
        proc = self._run_wrapper("ios-analyze")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)

    def test_ios_unused_help(self):
        proc = self._run_wrapper("ios-unused")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)

    def test_ios_prune_help(self):
        proc = self._run_wrapper("ios-prune")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)

    def test_ios_profile_build_help(self):
        proc = self._run_wrapper("ios-profile-build")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)

    def test_ios_auto_folders_help(self):
        proc = self._run_wrapper("ios-auto-folders")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)


class OutlookWrapperIntegrationTests(unittest.TestCase):
    """Test Outlook-related wrappers (help only, no auth required)."""

    def _run_wrapper(self, name: str) -> subprocess.CompletedProcess:
        wrapper = bin_path(name)
        if not wrapper.exists():
            self.skipTest(f"bin/{name} not found")
        if _is_shell_script(wrapper):
            cmd = ["bash", str(wrapper), "--help"]
        else:
            cmd = [sys.executable, str(wrapper), "--help"]
        return subprocess.run(cmd, cwd=str(repo_root()), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)  # nosec B603 - test code with trusted local scripts

    def test_outlook_rules_list_help(self):
        proc = self._run_wrapper("outlook-rules-list")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)

    def test_outlook_rules_export_help(self):
        proc = self._run_wrapper("outlook-rules-export")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)

    def test_outlook_categories_list_help(self):
        proc = self._run_wrapper("outlook-categories-list")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)


class GmailWrapperIntegrationTests(unittest.TestCase):
    """Test Gmail-related wrappers (help only, no auth required)."""

    def _run_wrapper(self, name: str) -> subprocess.CompletedProcess:
        wrapper = bin_path(name)
        if not wrapper.exists():
            self.skipTest(f"bin/{name} not found")
        if _is_shell_script(wrapper):
            cmd = ["bash", str(wrapper), "--help"]
        else:
            cmd = [sys.executable, str(wrapper), "--help"]
        return subprocess.run(cmd, cwd=str(repo_root()), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)  # nosec B603 - test code with trusted local scripts

    def test_gmail_labels_export_help(self):
        proc = self._run_wrapper("gmail-labels-export")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)

    def test_gmail_filters_export_help(self):
        proc = self._run_wrapper("gmail-filters-export")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)

    def test_gmail_filters_sync_help(self):
        proc = self._run_wrapper("gmail-filters-sync")
        self.assertEqual(proc.returncode, 0, msg=proc.stderr)


if __name__ == "__main__":
    unittest.main()
