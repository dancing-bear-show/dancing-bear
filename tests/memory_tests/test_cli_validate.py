"""Coverage for memory.commands.validate (via memory.cli.main):
_exit_code_from_findings (clean/warn/error), _findings_to_rows completeness,
--store load failure, unknown --check IDs (now argparse choices → SystemExit 2),
--fix and --claude-md args forwarded, and multiple-store aggregation.

Patches discover_stores, load_store, and run_checks where they are USED
(memory.commands.validate), per project convention.
"""

from __future__ import annotations

import contextlib
import io
import json
import unittest
from typing import ClassVar
from unittest.mock import patch

import memory.cli as memory_cli
from memory.commands.validate import (
    _exit_code_from_findings,
    _findings_to_rows,
)
from memory.models import MemoryStore
from memory.validation import CHECK_REGISTRY, CheckResult
from tests.memory_tests.fixtures import MemoryTestCase

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_store(slug: str = "test-slug") -> MemoryStore:
    return MemoryStore(
        project_slug=slug,
        root=f"/nonexistent/{slug}",
        memories=(),
        non_memory_files=(),
        index_path=None,
        index_entries=(),
        inferred_repo=None,
        is_worktree_slug=False,
    )


def _make_finding(
    *,
    severity: str = "warn",
    check_id: str = "staleness",
    target: str = "mem.md",
    message: str = "test finding",
    fixable: bool = False,
) -> CheckResult:
    return CheckResult(
        check_id=check_id,
        severity=severity,
        target=target,
        message=message,
        fixable=fixable,
    )


def _run_validate(*argv: str) -> tuple[int, str, str]:
    """Call memory.cli.main(["validate", *argv]) and return (rc, stdout, stderr)."""
    out_buf = io.StringIO()
    err_buf = io.StringIO()
    with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
        rc = memory_cli.main(["validate", *argv])
    return rc, out_buf.getvalue(), err_buf.getvalue()


# ---------------------------------------------------------------------------
# _exit_code_from_findings — all three branches
# ---------------------------------------------------------------------------


class TestExitCodeFromFindings(unittest.TestCase):
    def test_no_findings_returns_zero(self) -> None:
        self.assertEqual(_exit_code_from_findings([]), 0)

    def test_warn_only_findings_return_one(self) -> None:
        findings = [
            _make_finding(severity="warn"),
            _make_finding(severity="info"),
        ]
        self.assertEqual(_exit_code_from_findings(findings), 1)

    def test_any_error_finding_returns_two(self) -> None:
        findings = [
            _make_finding(severity="warn"),
            _make_finding(severity="error"),
        ]
        self.assertEqual(_exit_code_from_findings(findings), 2)

    def test_error_finding_alone_returns_two(self) -> None:
        findings = [_make_finding(severity="error")]
        self.assertEqual(_exit_code_from_findings(findings), 2)

    def test_info_only_returns_one(self) -> None:
        findings = [_make_finding(severity="info")]
        self.assertEqual(_exit_code_from_findings(findings), 1)


# ---------------------------------------------------------------------------
# _findings_to_rows — all keys present
# ---------------------------------------------------------------------------


class TestFindingsToRows(unittest.TestCase):
    _EXPECTED_KEYS: ClassVar[set[str]] = {
        "check_id",
        "severity",
        "target",
        "message",
        "fixable",
    }

    def test_empty_findings_returns_empty_list(self) -> None:
        self.assertEqual(_findings_to_rows([]), [])

    def test_all_keys_present_in_row(self) -> None:
        finding = _make_finding()
        rows = _findings_to_rows([finding])
        self.assertEqual(len(rows), 1)
        self.assertEqual(set(rows[0].keys()), self._EXPECTED_KEYS)

    def test_fixable_field_is_stringified(self) -> None:
        fixable_finding = _make_finding(fixable=True)
        not_fixable = _make_finding(fixable=False)
        rows = _findings_to_rows([fixable_finding, not_fixable])
        self.assertEqual(rows[0]["fixable"], "True")
        self.assertEqual(rows[1]["fixable"], "False")

    def test_multiple_findings_all_converted(self) -> None:
        findings = [
            _make_finding(severity="error", check_id="schema-no-frontmatter"),
            _make_finding(severity="warn", check_id="staleness"),
            _make_finding(severity="info", check_id="index-orphan"),
        ]
        rows = _findings_to_rows(findings)
        self.assertEqual(len(rows), 3)
        severities = [r["severity"] for r in rows]
        self.assertIn("error", severities)
        self.assertIn("warn", severities)
        self.assertIn("info", severities)


# ---------------------------------------------------------------------------
# main() — unknown --check IDs (argparse choices → SystemExit 2)
# ---------------------------------------------------------------------------


class TestMainUnknownCheckIds(MemoryTestCase):
    def test_unknown_check_raises_system_exit_2(self) -> None:
        # --check has argparse choices=sorted(CHECK_REGISTRY), so an unknown
        # ID is rejected by argparse with SystemExit(2) before run() is called.
        with self.assertRaises(SystemExit) as ctx:
            _run_validate("--check", "completely-bogus-check-id")
        self.assertEqual(ctx.exception.code, 2)

    def test_unknown_check_writes_to_stderr(self) -> None:
        err_buf = io.StringIO()
        with contextlib.redirect_stderr(err_buf), self.assertRaises(SystemExit):
            memory_cli.main(["validate", "--check", "does-not-exist"])
        err = err_buf.getvalue()
        self.assertIn("invalid choice", err)
        self.assertIn("does-not-exist", err)

    def test_multiple_unknown_checks_exit_nonzero(self) -> None:
        # Both IDs are invalid; argparse reports the first unknown choice.
        with self.assertRaises(SystemExit) as ctx:
            _run_validate("--check", "bogus-a", "--check", "bogus-b")
        self.assertEqual(ctx.exception.code, 2)

    def test_valid_check_id_accepted(self) -> None:
        store = _make_store()
        # First alphabetically-sorted check ID must pass argparse choices
        valid_check_id = sorted(CHECK_REGISTRY)[0]
        with (
            patch(
                "memory.commands.validate.discover_stores", return_value=(store,)
            ),
            patch(
                "memory.commands.validate.run_checks", return_value=()
            ) as mock_run,
        ):
            rc, _, _ = _run_validate("--check", valid_check_id)
        self.assertIsInstance(rc, int)
        mock_run.assert_called_once()
        _, kwargs = mock_run.call_args
        self.assertEqual(kwargs.get("checks"), (valid_check_id,))


# ---------------------------------------------------------------------------
# main() — --store load failure
# ---------------------------------------------------------------------------


class TestMainStoreLoadFailure(MemoryTestCase):
    def test_store_load_failure_returns_exit_code_1(self) -> None:
        with (
            patch("memory.commands.validate.discover_stores", return_value=()),
            patch(
                "memory.commands.validate.load_store",
                side_effect=Exception("store not found"),
            ),
        ):
            rc, _, _ = _run_validate("--store=nonexistent")
        self.assertEqual(rc, 1)

    def test_store_load_failure_writes_to_stderr(self) -> None:
        with (
            patch("memory.commands.validate.discover_stores", return_value=()),
            patch(
                "memory.commands.validate.load_store",
                side_effect=Exception("boom"),
            ),
        ):
            _, _, err = _run_validate("--store=bad-slug")
        self.assertTrue(
            "store" in err.lower() or "boom" in err.lower(),
            f"expected store/error mention in stderr, got: {err!r}",
        )


# ---------------------------------------------------------------------------
# main() — auto-discover path (no --store)
# ---------------------------------------------------------------------------


class TestMainAutoDiscoverPath(MemoryTestCase):
    def test_discover_stores_used_when_no_store_flag(self) -> None:
        store = _make_store()
        with (
            patch(
                "memory.commands.validate.discover_stores", return_value=(store,)
            ) as mock_discover,
            patch("memory.commands.validate.run_checks", return_value=()),
        ):
            _run_validate()
        mock_discover.assert_called_once()

    def test_clean_store_returns_exit_code_0(self) -> None:
        store = _make_store()
        with (
            patch(
                "memory.commands.validate.discover_stores", return_value=(store,)
            ),
            patch("memory.commands.validate.run_checks", return_value=()),
        ):
            rc, _, _ = _run_validate()
        self.assertEqual(rc, 0)

    def test_warn_findings_return_exit_code_1(self) -> None:
        store = _make_store()
        finding = _make_finding(severity="warn")
        with (
            patch(
                "memory.commands.validate.discover_stores", return_value=(store,)
            ),
            patch("memory.commands.validate.run_checks", return_value=(finding,)),
        ):
            rc, _, _ = _run_validate()
        self.assertEqual(rc, 1)

    def test_error_finding_returns_exit_code_2(self) -> None:
        store = _make_store()
        finding = _make_finding(severity="error")
        with (
            patch(
                "memory.commands.validate.discover_stores", return_value=(store,)
            ),
            patch("memory.commands.validate.run_checks", return_value=(finding,)),
        ):
            rc, _, _ = _run_validate()
        self.assertEqual(rc, 2)


# ---------------------------------------------------------------------------
# main() — --fix arg forwarded to run_checks
# ---------------------------------------------------------------------------


class TestMainFixArgForwarded(MemoryTestCase):
    def test_fix_flag_forwarded(self) -> None:
        store = _make_store()
        with (
            patch(
                "memory.commands.validate.discover_stores", return_value=(store,)
            ),
            patch(
                "memory.commands.validate.run_checks", return_value=()
            ) as mock_run,
        ):
            _run_validate("--fix")
        _, kwargs = mock_run.call_args
        self.assertTrue(kwargs.get("fix"))

    def test_no_fix_flag_defaults_to_false(self) -> None:
        store = _make_store()
        with (
            patch(
                "memory.commands.validate.discover_stores", return_value=(store,)
            ),
            patch(
                "memory.commands.validate.run_checks", return_value=()
            ) as mock_run,
        ):
            _run_validate()
        _, kwargs = mock_run.call_args
        self.assertFalse(kwargs.get("fix"))


# ---------------------------------------------------------------------------
# main() — --claude-md extra paths forwarded
# ---------------------------------------------------------------------------


class TestMainClaudeMdPaths(MemoryTestCase):
    def test_claude_md_paths_forwarded_to_run_checks(self) -> None:
        store = _make_store()
        with (
            patch(
                "memory.commands.validate.discover_stores", return_value=(store,)
            ),
            patch(
                "memory.commands.validate.run_checks", return_value=()
            ) as mock_run,
        ):
            _run_validate(
                "--claude-md", "/nonexistent/CLAUDE.md", "--claude-md", "/nonexistent/.llm/guide.md"
            )
        _, kwargs = mock_run.call_args
        self.assertEqual(
            kwargs.get("claude_md"), ("/nonexistent/CLAUDE.md", "/nonexistent/.llm/guide.md")
        )

    def test_no_claude_md_sends_empty_tuple(self) -> None:
        store = _make_store()
        with (
            patch(
                "memory.commands.validate.discover_stores", return_value=(store,)
            ),
            patch(
                "memory.commands.validate.run_checks", return_value=()
            ) as mock_run,
        ):
            _run_validate()
        _, kwargs = mock_run.call_args
        self.assertEqual(kwargs.get("claude_md"), ())


# ---------------------------------------------------------------------------
# main() — JSON output contains rows for findings
# ---------------------------------------------------------------------------


class TestMainJsonOutput(MemoryTestCase):
    def test_json_output_contains_findings(self) -> None:
        store = _make_store()
        finding = _make_finding(severity="warn", check_id="staleness", target="old.md")
        with (
            patch(
                "memory.commands.validate.discover_stores", return_value=(store,)
            ),
            patch("memory.commands.validate.run_checks", return_value=(finding,)),
        ):
            _, out, _ = _run_validate("--format", "json")
        rows = json.loads(out.strip())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["check_id"], "staleness")
        self.assertEqual(rows[0]["severity"], "warn")
        self.assertEqual(rows[0]["target"], "old.md")

    def test_json_output_clean_run(self) -> None:
        store = _make_store()
        with (
            patch(
                "memory.commands.validate.discover_stores", return_value=(store,)
            ),
            patch("memory.commands.validate.run_checks", return_value=()),
        ):
            _, out, _ = _run_validate("--format", "json")
        out_stripped = out.strip()
        if out_stripped:
            data = json.loads(out_stripped)
            self.assertIsInstance(data, list)


# ---------------------------------------------------------------------------
# main() — multiple stores (all checked)
# ---------------------------------------------------------------------------


class TestMainMultipleStores(MemoryTestCase):
    def test_all_stores_passed_to_run_checks(self) -> None:
        store_a = _make_store("slug-a")
        store_b = _make_store("slug-b")
        call_count: list[int] = []

        def _counting_run_checks(*_a, **_kw):
            call_count.append(1)
            return ()

        with (
            patch(
                "memory.commands.validate.discover_stores",
                return_value=(store_a, store_b),
            ),
            patch(
                "memory.commands.validate.run_checks",
                side_effect=_counting_run_checks,
            ),
        ):
            _run_validate()

        self.assertEqual(len(call_count), 2)

    def test_findings_from_multiple_stores_aggregated(self) -> None:
        store_a = _make_store("slug-a")
        store_b = _make_store("slug-b")
        finding_a = _make_finding(severity="warn", target="a.md")
        finding_b = _make_finding(severity="warn", target="b.md")

        def run_checks_side_effect(store, **kwargs):
            if store.project_slug == "slug-a":
                return (finding_a,)
            return (finding_b,)

        with (
            patch(
                "memory.commands.validate.discover_stores",
                return_value=(store_a, store_b),
            ),
            patch(
                "memory.commands.validate.run_checks",
                side_effect=run_checks_side_effect,
            ),
        ):
            _, out, _ = _run_validate("--format", "json")

        rows = json.loads(out.strip())
        targets = {r["target"] for r in rows}
        self.assertIn("a.md", targets)
        self.assertIn("b.md", targets)


if __name__ == "__main__":
    unittest.main()
