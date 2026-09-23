"""Tests for workflow.param_guard and the `workflow check-params` subcommand.

These guards protect caller-overridable trigger params from reaching a shell.
Assertions are on EXIT STATUS, never on printed text: the exit status is the
contract the workflow YAML branches on, and a guard that prints a rejection
while exiting 0 is exactly the inert-but-green failure this replaces.

`HEREDOC_ESCAPE` is the payload that disproved the single-quoted-heredoc
mechanism: substituted into script text, its newline plus the literal
delimiter closed the heredoc early, ran the remainder, and then let the regex
pass on the truncated remnant.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import subprocess  # nosec B404 - runs the repo's own ./bin/workflow wrapper
import tempfile
import unittest
from pathlib import Path

from workflow.cli_dispatch import _cmd_check_params
from workflow.param_guard import (
    ParamCheck,
    check_params,
    load_params,
    parse_check,
    select_printable,
)

HEREDOC_ESCAPE = "http://ok\nRAW\ntouch /tmp/PWNED_param_guard\ncat > /dev/null <<'RAW'\nx"
SUBSHELL = "http://h$(echo PWNED)"

HOST_PATTERN = r"https?://[A-Za-z0-9._-]+(:[0-9]{1,5})?/?"
JOB_TYPE_PATTERN = r"[a-z][a-z0-9_]{2,40}"
SHA_PATTERN = r"[0-9a-f]{40}"

_REPO_ROOT = Path(__file__).resolve().parents[2]

#: Cap on the wrapper subprocess. Generous for a JSON read plus a regex, but
#: finite: an unpinned timeout means a hung wrapper hangs the whole suite.
_WRAPPER_TIMEOUT_S = 60


def _args(
    file: str,
    check: list[str],
    *,
    top_level: bool = False,
    print_param: str | None = None,
) -> argparse.Namespace:
    """Build real CLI args.

    Deliberately an argparse.Namespace rather than a MagicMock: a mock would
    auto-stub any attribute the handler gains later, so a wiring mistake would
    read as a pass.
    """
    return argparse.Namespace(
        file=file, check=check, top_level=top_level, print_param=print_param
    )


class ParamGuardTempMixin(unittest.TestCase):
    """Provides a temp dir and a helper that writes a params document."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)

    def write_manifest(self, params: object, *, key: str | None = "trigger_params") -> str:
        doc = params if key is None else {"trigger_params": params}
        path = self.tmp / "manifest.json"
        path.write_text(json.dumps(doc), encoding="utf-8")
        return str(path)

    def write_raw(self, text: str) -> str:
        path = self.tmp / "manifest.json"
        path.write_text(text, encoding="utf-8")
        return str(path)


class TestParseCheck(unittest.TestCase):
    """parse_check turns a name=pattern spec into a ParamCheck."""

    def test_splits_on_first_equals_only(self) -> None:
        """A pattern containing '=' survives intact."""
        check = parse_check("job_type=[a-z]{2,4}=x")
        self.assertEqual(check, ParamCheck(name="job_type", pattern="[a-z]{2,4}=x"))

    def test_rejects_spec_without_equals(self) -> None:
        with self.assertRaises(ValueError):
            parse_check("job_type")

    def test_rejects_empty_name_or_pattern(self) -> None:
        with self.assertRaises(ValueError):
            parse_check("=[a-z]+")
        with self.assertRaises(ValueError):
            parse_check("job_type=")

    def test_rejects_invalid_regex(self) -> None:
        """A malformed pattern fails at parse time, not silently at match time."""
        with self.assertRaises(ValueError):
            parse_check("job_type=[unclosed")


class TestCheckParams(unittest.TestCase):
    """check_params applies full-match semantics and reports every failure."""

    def test_accepts_valid_value(self) -> None:
        result = check_params(
            {"job_type": "qwen_local"}, [ParamCheck("job_type", JOB_TYPE_PATTERN)]
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.failures, ())

    def test_rejects_heredoc_escape_payload(self) -> None:
        result = check_params(
            {"ollama_host": HEREDOC_ESCAPE}, [ParamCheck("ollama_host", HOST_PATTERN)]
        )
        self.assertFalse(result.ok)

    def test_rejects_command_substitution_payload(self) -> None:
        result = check_params(
            {"ollama_host": SUBSHELL}, [ParamCheck("ollama_host", HOST_PATTERN)]
        )
        self.assertFalse(result.ok)

    def test_match_is_anchored_at_both_ends(self) -> None:
        """A valid prefix followed by a payload must not pass.

        re.match would accept this; re.fullmatch is what makes the guard real.
        """
        result = check_params(
            {"job_type": "good_type; rm -rf /"}, [ParamCheck("job_type", JOB_TYPE_PATTERN)]
        )
        self.assertFalse(result.ok)

    def test_missing_param_is_a_failure(self) -> None:
        result = check_params({}, [ParamCheck("job_type", JOB_TYPE_PATTERN)])
        self.assertFalse(result.ok)
        self.assertIn("missing", result.failures[0])

    def test_non_string_param_is_a_failure(self) -> None:
        """A JSON number must not be coerced to str and then matched."""
        result = check_params({"job_type": 12345}, [ParamCheck("job_type", r"\d+")])
        self.assertFalse(result.ok)

    def test_reports_every_failing_param_not_just_the_first(self) -> None:
        result = check_params(
            {"ollama_host": SUBSHELL, "job_type": "BAD"},
            [ParamCheck("ollama_host", HOST_PATTERN), ParamCheck("job_type", JOB_TYPE_PATTERN)],
        )
        self.assertFalse(result.ok)
        self.assertEqual(len(result.failures), 2)

    def test_failure_text_does_not_echo_the_rejected_value(self) -> None:
        """A hostile value must not be reproduced into logs."""
        result = check_params(
            {"ollama_host": SUBSHELL}, [ParamCheck("ollama_host", HOST_PATTERN)]
        )
        self.assertNotIn("PWNED", " ".join(result.failures))

    def test_all_checks_pass_together(self) -> None:
        result = check_params(
            {"ollama_host": "http://localhost:11434", "job_type": "qwen_local"},
            [ParamCheck("ollama_host", HOST_PATTERN), ParamCheck("job_type", JOB_TYPE_PATTERN)],
        )
        self.assertTrue(result.ok)


class TestLoadParams(ParamGuardTempMixin):
    """load_params reads the mapping out of an engine-written JSON document."""

    def test_reads_trigger_params_section(self) -> None:
        path = self.write_manifest({"job_type": "qwen_local"})
        self.assertEqual(load_params(path), {"job_type": "qwen_local"})

    def test_reads_document_root_when_key_is_none(self) -> None:
        """Stage outputs such as handler.json carry fields at the top level."""
        path = self.write_manifest({"commit_sha": "a" * 40}, key=None)
        self.assertEqual(load_params(path, key=None), {"commit_sha": "a" * 40})

    def test_preserves_hostile_value_byte_for_byte(self) -> None:
        """The payload must survive the round trip so the regex sees the truth."""
        path = self.write_manifest({"ollama_host": HEREDOC_ESCAPE})
        self.assertEqual(load_params(path)["ollama_host"], HEREDOC_ESCAPE)

    def test_missing_file_raises(self) -> None:
        with self.assertRaises(ValueError):
            load_params(str(self.tmp / "nope.json"))

    def test_malformed_json_raises(self) -> None:
        with self.assertRaises(ValueError):
            load_params(self.write_raw("{not json"))

    def test_non_object_document_raises(self) -> None:
        with self.assertRaises(ValueError):
            load_params(self.write_raw("[1, 2, 3]"))

    def test_absent_trigger_params_section_raises(self) -> None:
        with self.assertRaises(ValueError):
            load_params(self.write_raw(json.dumps({"run_id": "x"})))

    def test_non_object_trigger_params_raises(self) -> None:
        with self.assertRaises(ValueError):
            load_params(self.write_raw(json.dumps({"trigger_params": "oops"})))


class TestCheckParamsCommand(ParamGuardTempMixin):
    """The CLI handler's exit status is the contract the YAML branches on."""

    def test_valid_value_exits_zero(self) -> None:
        path = self.write_manifest({"job_type": "qwen_local"})
        self.assertEqual(_cmd_check_params(_args(path, [f"job_type={JOB_TYPE_PATTERN}"])), 0)

    def test_heredoc_escape_payload_exits_nonzero(self) -> None:
        path = self.write_manifest({"ollama_host": HEREDOC_ESCAPE})
        self.assertEqual(_cmd_check_params(_args(path, [f"ollama_host={HOST_PATTERN}"])), 1)

    def test_command_substitution_payload_exits_nonzero(self) -> None:
        path = self.write_manifest({"ollama_host": SUBSHELL})
        self.assertEqual(_cmd_check_params(_args(path, [f"ollama_host={HOST_PATTERN}"])), 1)

    def test_missing_param_exits_nonzero(self) -> None:
        path = self.write_manifest({"job_type": "qwen_local"})
        self.assertEqual(_cmd_check_params(_args(path, [f"ollama_host={HOST_PATTERN}"])), 1)

    def test_malformed_manifest_exits_nonzero(self) -> None:
        path = self.write_raw("{not json")
        self.assertEqual(_cmd_check_params(_args(path, [f"job_type={JOB_TYPE_PATTERN}"])), 1)

    def test_missing_manifest_file_exits_nonzero(self) -> None:
        path = str(self.tmp / "absent.json")
        self.assertEqual(_cmd_check_params(_args(path, [f"job_type={JOB_TYPE_PATTERN}"])), 1)

    def test_malformed_check_spec_exits_nonzero(self) -> None:
        path = self.write_manifest({"job_type": "qwen_local"})
        self.assertEqual(_cmd_check_params(_args(path, ["job_type"])), 1)

    def test_one_failure_among_several_checks_exits_nonzero(self) -> None:
        """A partially valid set must not pass on the strength of the good one."""
        path = self.write_manifest({"ollama_host": "http://localhost:11434", "job_type": "BAD"})
        code = _cmd_check_params(
            _args(path, [f"ollama_host={HOST_PATTERN}", f"job_type={JOB_TYPE_PATTERN}"])
        )
        self.assertEqual(code, 1)

    def test_top_level_flag_reads_document_root(self) -> None:
        path = self.write_manifest({"commit_sha": "a" * 40}, key=None)
        code = _cmd_check_params(_args(path, [f"commit_sha={SHA_PATTERN}"], top_level=True))
        self.assertEqual(code, 0)

    def test_short_sha_exits_nonzero(self) -> None:
        """The commit_sha guard must reject anything but a full 40-char hex."""
        path = self.write_manifest({"commit_sha": "a" * 7}, key=None)
        code = _cmd_check_params(_args(path, [f"commit_sha={SHA_PATTERN}"], top_level=True))
        self.assertEqual(code, 1)

    def test_null_commit_sha_exits_nonzero(self) -> None:
        """handler.json carries a null commit_sha when the agent never committed."""
        path = self.write_manifest({"commit_sha": None}, key=None)
        code = _cmd_check_params(_args(path, [f"commit_sha={SHA_PATTERN}"], top_level=True))
        self.assertEqual(code, 1)


class TestCheckParamsEndToEnd(ParamGuardTempMixin):
    """Drive the real wrapper, the way the workflow YAML invokes it.

    The in-process handler tests cannot prove the value stays out of the shell,
    because they never build a command line. This does: the payload goes on
    disk, only the engine-controlled PATH is passed as an argument, and the
    side effect the payload would cause is asserted absent.
    """

    def _run(
        self, path: str, checks: list[str], *, print_param: str | None = None
    ) -> subprocess.CompletedProcess[str]:
        argv = [str(_REPO_ROOT / "bin" / "workflow"), "check-params", path]
        for spec in checks:
            argv += ["--check", spec]
        if print_param is not None:
            argv += ["--print", print_param]
        return subprocess.run(  # nosec B603 - fixed argv, no shell, repo-owned binary
            argv, capture_output=True, text=True, cwd=str(_REPO_ROOT), check=False,
            timeout=_WRAPPER_TIMEOUT_S,
        )

    def test_valid_value_exits_zero_through_the_wrapper(self) -> None:
        path = self.write_manifest({"job_type": "qwen_local"})
        self.assertEqual(self._run(path, [f"job_type={JOB_TYPE_PATTERN}"]).returncode, 0)

    def test_heredoc_payload_is_rejected_and_never_executes(self) -> None:
        marker = self.tmp / "PWNED"
        payload = f"http://ok\nRAW\ntouch {marker}\ncat > /dev/null <<'RAW'\nx"
        path = self.write_manifest({"ollama_host": payload})
        proc = self._run(path, [f"ollama_host={HOST_PATTERN}"])
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(marker.exists(), "payload executed: the guard is inert")

    def test_subshell_payload_is_rejected_and_never_executes(self) -> None:
        marker = self.tmp / "PWNED_SUBSHELL"
        path = self.write_manifest({"ollama_host": f"http://h$(touch {marker})"})
        proc = self._run(path, [f"ollama_host={HOST_PATTERN}"])
        self.assertEqual(proc.returncode, 1)
        self.assertFalse(marker.exists(), "payload executed: the guard is inert")

    def test_rejection_names_the_param_on_stderr(self) -> None:
        """stdout stays clean; the diagnostic goes to stderr."""
        path = self.write_manifest({"ollama_host": SUBSHELL})
        proc = self._run(path, [f"ollama_host={HOST_PATTERN}"])
        self.assertEqual(proc.returncode, 1)
        self.assertIn("ollama_host", proc.stderr)
        self.assertEqual(proc.stdout, "")


class TestSelectPrintable(unittest.TestCase):
    """select_printable is the gate on --print: it refuses more than it allows."""

    def test_returns_value_when_a_check_covers_and_accepts_it(self) -> None:
        value = select_printable(
            "ollama_host",
            {"ollama_host": "http://localhost:11434"},
            [ParamCheck("ollama_host", HOST_PATTERN)],
        )
        self.assertEqual(value, "http://localhost:11434")

    def test_refuses_a_name_no_check_covers(self) -> None:
        """The whole point: an unvalidated param is never printable.

        Without this the command would still exit 0 on the strength of the
        OTHER params' checks, and hand back the one nobody validated.
        """
        with self.assertRaises(ValueError):
            select_printable(
                "model_tag",
                {"model_tag": SUBSHELL, "ollama_host": "http://localhost:11434"},
                [ParamCheck("ollama_host", HOST_PATTERN)],
            )

    def test_refuses_a_covered_name_whose_value_fails(self) -> None:
        with self.assertRaises(ValueError):
            select_printable(
                "ollama_host", {"ollama_host": SUBSHELL}, [ParamCheck("ollama_host", HOST_PATTERN)]
            )

    def test_refuses_a_missing_param(self) -> None:
        with self.assertRaises(ValueError):
            select_printable("ollama_host", {}, [ParamCheck("ollama_host", HOST_PATTERN)])

    def test_refuses_a_non_string_param(self) -> None:
        with self.assertRaises(ValueError):
            select_printable("port", {"port": 11434}, [ParamCheck("port", r"\d+")])

    def test_requires_every_pattern_for_a_repeated_name(self) -> None:
        """Two --check specs for one name must BOTH hold before printing.

        Honouring only the first would let a caller widen a narrow check by
        appending a permissive one.
        """
        with self.assertRaises(ValueError):
            select_printable(
                "ollama_host",
                {"ollama_host": "http://evil.example"},
                [
                    ParamCheck("ollama_host", HOST_PATTERN),
                    ParamCheck("ollama_host", r"https?://localhost(:[0-9]+)?/?"),
                ],
            )

    def test_refusal_does_not_echo_the_rejected_value(self) -> None:
        with self.assertRaises(ValueError) as ctx:
            select_printable(
                "ollama_host", {"ollama_host": SUBSHELL}, [ParamCheck("ollama_host", HOST_PATTERN)]
            )
        self.assertNotIn("PWNED", str(ctx.exception))


class TestCheckParamsPrintHandler(ParamGuardTempMixin):
    """The --print branch of the handler, in process."""

    def test_prints_accepted_value_to_stdout(self) -> None:
        path = self.write_manifest({"ollama_host": "http://localhost:11434"})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = _cmd_check_params(
                _args(path, [f"ollama_host={HOST_PATTERN}"], print_param="ollama_host")
            )
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue(), "http://localhost:11434")

    def test_prints_nothing_when_validation_fails(self) -> None:
        path = self.write_manifest({"ollama_host": SUBSHELL})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(io.StringIO()):
            rc = _cmd_check_params(
                _args(path, [f"ollama_host={HOST_PATTERN}"], print_param="ollama_host")
            )
        self.assertEqual(rc, 1)
        self.assertEqual(buf.getvalue(), "")

    def test_prints_nothing_for_an_unchecked_name(self) -> None:
        """model_tag passes no check, so it must not be printable."""
        path = self.write_manifest(
            {"ollama_host": "http://localhost:11434", "model_tag": "x; rm -rf /"}
        )
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(err):
            rc = _cmd_check_params(
                _args(path, [f"ollama_host={HOST_PATTERN}"], print_param="model_tag")
            )
        self.assertEqual(rc, 1)
        self.assertEqual(buf.getvalue(), "")
        self.assertIn("no --check covers it", err.getvalue())

    def test_without_print_nothing_reaches_stdout(self) -> None:
        """The default stays exit-status-only; --print is strictly opt-in."""
        path = self.write_manifest({"ollama_host": "http://localhost:11434"})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = _cmd_check_params(_args(path, [f"ollama_host={HOST_PATTERN}"]))
        self.assertEqual(rc, 0)
        self.assertEqual(buf.getvalue(), "")

    def test_value_is_emitted_without_a_trailing_newline(self) -> None:
        """$(...) strips one, but a redirect to a file would keep it."""
        path = self.write_manifest({"ollama_host": "http://localhost:11434"})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            _cmd_check_params(
                _args(path, [f"ollama_host={HOST_PATTERN}"], print_param="ollama_host")
            )
        self.assertFalse(buf.getvalue().endswith("\n"))


class TestCheckParamsPrintEndToEnd(TestCheckParamsEndToEnd):
    """--print through the real wrapper, in the $(...) form the YAML uses.

    Inherits the parent's payload cases so the plain path keeps its coverage;
    these add the shell-capture contract on top.
    """

    def test_accepted_value_prints_intact_through_the_wrapper(self) -> None:
        path = self.write_manifest({"ollama_host": "http://localhost:11434"})
        proc = self._run(path, [f"ollama_host={HOST_PATTERN}"], print_param="ollama_host")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(proc.stdout, "http://localhost:11434")

    def test_subshell_payload_prints_nothing_and_never_executes(self) -> None:
        marker = self.tmp / "PWNED_PRINT"
        path = self.write_manifest({"ollama_host": f"http://h$(touch {marker})"})
        proc = self._run(path, [f"ollama_host={HOST_PATTERN}"], print_param="ollama_host")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, "")
        self.assertFalse(marker.exists(), "payload executed: the guard is inert")

    def test_heredoc_payload_prints_nothing_and_never_executes(self) -> None:
        marker = self.tmp / "PWNED_PRINT_HEREDOC"
        payload = f"http://ok\nRAW\ntouch {marker}\ncat > /dev/null <<'RAW'\nx"
        path = self.write_manifest({"ollama_host": payload})
        proc = self._run(path, [f"ollama_host={HOST_PATTERN}"], print_param="ollama_host")
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, "")
        self.assertFalse(marker.exists(), "payload executed: the guard is inert")

    def test_one_failing_param_blocks_printing_a_passing_sibling(self) -> None:
        """A rejected ollama_host must withhold the valid model_tag too.

        Otherwise a caller learns the stage ran far enough to read the file,
        and the exit status stops being the single contract the YAML branches
        on.
        """
        path = self.write_manifest(
            {"ollama_host": SUBSHELL, "model_tag": "qwen2.5-coder:14b"}
        )
        proc = self._run(
            path,
            [f"ollama_host={HOST_PATTERN}", r"model_tag=[A-Za-z0-9._-]+(:[A-Za-z0-9._-]+)?"],
            print_param="model_tag",
        )
        self.assertEqual(proc.returncode, 1)
        self.assertEqual(proc.stdout, "")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
