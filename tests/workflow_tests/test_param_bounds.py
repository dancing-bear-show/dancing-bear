"""Bounds on what a caller can inject: override KEYS and workspace PATHS.

``test_param_rules`` covers override VALUES. Two further routes put caller
text into stage prompts that agents run as shell:

* an undeclared override key -- ``resolve_params`` replaced ``{key}`` for
  every key it was handed, so ``--params 2,40=x`` rewrote a regex quantifier
  ``{2,40}`` in stage text;
* the workspace path -- substituted as ``{workspace}``, where quoting does
  not neutralise ``$(...)`` or a backtick, and a space splits the word.

Both are rejected before anything is compiled into a manifest or created on
disk, and neither the rejected key's text nor the path is ever echoed.
"""

from __future__ import annotations

import json
import subprocess  # nosec B404 - runs the repo's own ./bin/workflow wrapper
import tempfile
import unittest
from pathlib import Path

from core.cli_errors import CLIError
from workflow.cli_dispatch import _resolve_base_dir
from workflow.compiler import WorkflowCompileError, compile_workflow, resolve_params
from workflow.orchestrator import OrchestratorConfig, WorkflowExecutionError, WorkflowOrchestrator
from workflow.param_rules import ENGINE_BUILTIN_PARAMS, UnsafePathError
from workflow.parser import parse_workflow, parse_workflow_str
from workflow.persistence import init_workspace

_REPO_ROOT = Path(__file__).resolve().parents[2]
_WRAPPER = str(_REPO_ROOT / "bin" / "workflow")

#: Finite cap per wrapper subprocess so a hang fails the test, not the suite.
_WRAPPER_TIMEOUT_S = 60

#: A value an attacker would like to land in stage text.
_SECRET_VALUE = "ZZ-INJECTED-VALUE-ZZ"  # nosec B105 - probe marker for no-echo assertions, not a secret

_YAML = (
    "name: bounds\n"
    'version: "1"\n'
    "description: bounds\n"
    "trigger:\n"
    "  source: manual\n"
    "  params:\n"
    '    pr_number: "1"\n'
    "stages:\n"
    "  - name: s1\n"
    "    kind: gather\n"
    "    description: \"pr={pr_number} slug=[a-z]{2,40} undeclared={ghost} wd={work_dir}\"\n"
    "    agent: {role: researcher}\n"
)

_FRAGMENT = (
    "fragment: true\n"
    "trigger:\n"
    "  source: manual\n"
    "  params:\n"
    '    frag_param: "ok"\n'
    "stages:\n"
    "  - name: f1\n"
    "    kind: gather\n"
    '    description: "frag={frag_param}"\n'
    "    agent: {role: researcher}\n"
)


def _desc(manifest: object, stage: str = "s1") -> str:
    return manifest.resolved_stages[stage].spec.description  # type: ignore[attr-defined]


class _TmpMixin(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.wf = self.tmp / "wf.yaml"
        self.wf.write_text(_YAML, encoding="utf-8")

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def wrapper(self, *argv: str, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
        return subprocess.run(  # nosec B603 - fixed argv, no shell, repo-owned binary
            [_WRAPPER, *argv],
            capture_output=True, text=True, cwd=str(cwd or _REPO_ROOT), check=False,
            timeout=_WRAPPER_TIMEOUT_S,
        )


# ---------------------------------------------------------------------------
# Hole A: undeclared override keys
# ---------------------------------------------------------------------------


class TestUndeclaredOverrideKeys(unittest.TestCase):
    def _compile(self, overrides: dict[str, str]) -> object:
        return compile_workflow(parse_workflow_str(_YAML), trigger_params=overrides)

    def test_quantifier_key_is_rejected_without_echoing_the_value(self) -> None:
        with self.assertRaises(WorkflowCompileError) as ctx:
            self._compile({"2,40": _SECRET_VALUE})
        msg = str(ctx.exception)
        self.assertIn("a non-identifier param name", msg)
        self.assertNotIn(_SECRET_VALUE, msg)
        self.assertNotIn("2,40", msg)

    def test_undeclared_identifier_is_rejected_by_name_only(self) -> None:
        with self.assertRaises(WorkflowCompileError) as ctx:
            self._compile({"ghost": _SECRET_VALUE})
        self.assertIn("ghost", str(ctx.exception))
        self.assertNotIn(_SECRET_VALUE, str(ctx.exception))

    def test_workspace_is_not_an_overridable_param(self) -> None:
        # {workspace} comes from init-workspace, never params; accepting it
        # would bypass the workspace path check.
        with self.assertRaises(WorkflowCompileError):
            self._compile({"workspace": "/tmp/x"})  # nosec B108 - test string only, never created

    def test_declared_override_still_works(self) -> None:
        self.assertIn("pr=42 ", _desc(self._compile({"pr_number": "42"})))

    def test_param_declared_only_by_a_fragment_may_be_overridden(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "frag.yaml").write_text(_FRAGMENT, encoding="utf-8")
            wf = Path(tmp, "wf.yaml")
            wf.write_text(
                _YAML.replace(
                    "stages:\n",
                    "include:\n  - path: frag.yaml\n    prefix: fr\n    depends_on: [s1]\nstages:\n",
                    1,
                ),
                encoding="utf-8",
            )
            manifest = compile_workflow(parse_workflow(str(wf)), trigger_params={"frag_param": "yes"})
        frag_stage = next(n for n in manifest.resolved_stages if n != "s1")
        self.assertIn("frag=yes", _desc(manifest, frag_stage))

    def test_every_builtin_is_accepted(self) -> None:
        self.assertEqual(ENGINE_BUILTIN_PARAMS, frozenset({"work_dir"}))
        manifest = self._compile({"work_dir": "/safe/out"})
        self.assertIn("wd=/safe/out", _desc(manifest))

    def test_unsafe_builtin_value_is_rejected_without_echo(self) -> None:
        with self.assertRaises(WorkflowCompileError) as ctx:
            self._compile({"work_dir": f"/x/$(touch {_SECRET_VALUE})"})
        self.assertIn("work_dir", str(ctx.exception))
        self.assertNotIn(_SECRET_VALUE, str(ctx.exception))

    def test_orchestrator_recheck_rejects_an_undeclared_key(self) -> None:
        manifest = compile_workflow(parse_workflow_str(_YAML))
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(WorkflowExecutionError) as ctx:
                WorkflowOrchestrator(OrchestratorConfig(
                    manifest=manifest, workspace_dir=tmp, dry_run=True,
                    trigger_params={"2,40": _SECRET_VALUE},
                ))
            self.assertEqual(list(Path(tmp).iterdir()), [])
        self.assertNotIn(_SECRET_VALUE, str(ctx.exception))
        self.assertNotIn("2,40", str(ctx.exception))


class TestResolveParamsIdentifierOnly(unittest.TestCase):
    def test_non_identifier_keys_are_ignored(self) -> None:
        out = resolve_params("q{2,40} a={a} s={a b}", {"2,40": "X", "a": "1", "a b": "Y"})
        self.assertEqual(out, "q{2,40} a=1 s={a b}")


class TestUndeclaredKeyThroughWrapper(_TmpMixin):
    def _assert_rejected(self, proc: subprocess.CompletedProcess[str]) -> None:
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        out = proc.stdout + proc.stderr
        self.assertIn("a non-identifier param name", out)
        self.assertNotIn(_SECRET_VALUE, out)

    def test_compile_subcommand_rejects_quantifier_key(self) -> None:
        self._assert_rejected(self.wrapper(
            "compile", str(self.wf), "--no-compile-cache", "--params", f"2,40={_SECRET_VALUE}",
        ))

    def test_init_workspace_rejects_quantifier_key_and_writes_nothing(self) -> None:
        base = self.tmp / "base"
        proc = self.wrapper(
            "init-workspace", str(self.wf), "--base-dir", str(base),
            "--params", f"2,40={_SECRET_VALUE}",
        )
        self._assert_rejected(proc)
        self.assertFalse(base.exists())

    def test_init_workspace_default_work_dir_builtin_is_substituted(self) -> None:
        base = self.tmp / "base"
        proc = self.wrapper("init-workspace", str(self.wf), "--base-dir", str(base))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        manifest = json.loads((Path(proc.stdout.strip()) / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["trigger_params"]["work_dir"], str(_REPO_ROOT / "out"))


# ---------------------------------------------------------------------------
# Hole B: unsafe workspace paths
# ---------------------------------------------------------------------------


class TestUnsafeWorkspacePathUnits(unittest.TestCase):
    _UNSAFE = ("a$(touch x)", "a`id`", "a;b", "a b", "a\nb", "a'b", "a|b", "a*")

    def test_resolve_base_dir_rejects_unsafe_override(self) -> None:
        defn = parse_workflow_str(_YAML)
        for seg in self._UNSAFE:
            with self.subTest(seg=seg), self.assertRaises(CLIError) as ctx:
                _resolve_base_dir(f"/tmp/{seg}", defn, {})  # nosec B108 - rejected before any path is created
            self.assertIn("unsafe for shell rendering", str(ctx.exception))
            self.assertNotIn(seg, str(ctx.exception))

    def test_resolve_base_dir_rejects_unsafe_workspace_dir_template(self) -> None:
        defn = parse_workflow_str(_YAML + "workspace_dir: \"{pr_number}/run\"\n")
        with self.assertRaises(CLIError) as ctx:
            _resolve_base_dir(None, defn, {"pr_number": "a b"})
        self.assertIn("workspace_dir", str(ctx.exception))

    def test_init_workspace_rejects_unsafe_run_id_before_creating_anything(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(UnsafePathError):
                init_workspace("wf", "r$(id)", base_dir=tmp)
            self.assertEqual(list(Path(tmp).iterdir()), [])

    def test_init_workspace_accepts_the_orchestrator_default_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = init_workspace("wf", "wf-2026-09-23T14:37:00Z-abcd1234", base_dir=tmp)
            self.assertTrue((root / "stages").is_dir())

    def test_resume_rejects_unsafe_workspace(self) -> None:
        manifest = compile_workflow(parse_workflow_str(_YAML))
        with self.assertRaises(WorkflowExecutionError) as ctx:
            WorkflowOrchestrator.resume(manifest, "/tmp/a b")  # nosec B108 - rejected before any path is created
        self.assertIn("unsafe for shell rendering", str(ctx.exception))


class TestUnsafeWorkspaceThroughWrapper(_TmpMixin):
    def _unsafe_paths(self, marker: Path) -> tuple[str, ...]:
        return (
            f"ws$(touch {marker})",
            f"ws`touch {marker}`",
            f"ws;touch {marker}",
            "ws dir",
            "ws\ndir",
        )

    def _assert_rejected(self, proc: subprocess.CompletedProcess[str], seg: str, marker: Path) -> None:
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        out = proc.stdout + proc.stderr
        self.assertIn("unsafe for shell rendering", out)
        self.assertNotIn(seg, out)
        self.assertNotIn(str(marker), out)
        self.assertFalse(marker.exists())
        # Nothing but the workflow file itself exists under the temp dir.
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir()), ["wf.yaml"])

    def test_init_workspace_rejects_unsafe_base_dir(self) -> None:
        marker = self.tmp / "PWNED"
        for seg in self._unsafe_paths(marker):
            with self.subTest(seg=seg):
                proc = self.wrapper("init-workspace", str(self.wf), "--base-dir", str(self.tmp / seg))
                self._assert_rejected(proc, seg, marker)

    def test_run_rejects_unsafe_workspace(self) -> None:
        marker = self.tmp / "PWNED"
        for seg in self._unsafe_paths(marker):
            with self.subTest(seg=seg):
                proc = self.wrapper("run", str(self.wf), "--workspace", str(self.tmp / seg))
                self._assert_rejected(proc, seg, marker)

    def test_run_rejects_unsafe_run_id(self) -> None:
        marker = self.tmp / "PWNED"
        seg = f"r$(touch {marker})"
        proc = self.wrapper(
            "run", str(self.wf), "--workspace", str(self.tmp / "ok"), "--run-id", seg,
        )
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("unsafe for shell rendering", proc.stdout + proc.stderr)
        self.assertNotIn(seg, proc.stdout + proc.stderr)
        self.assertFalse(marker.exists())
        self.assertFalse((self.tmp / "ok").exists())

    def test_safe_paths_work(self) -> None:
        proc = self.wrapper("init-workspace", str(self.wf), "--base-dir", str(self.tmp / "b1"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue((Path(proc.stdout.strip()) / "manifest.json").is_file())
        proc = self.wrapper("run", str(self.wf), "--workspace", str(self.tmp / "b2"))
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue((self.tmp / "b2").is_dir())

    def test_cwd_with_space_is_rejected_and_named_as_the_cause(self) -> None:
        spaced = self.tmp / "has space"
        spaced.mkdir()
        proc = self.wrapper(
            "init-workspace", str(self.wf), "--base-dir", str(self.tmp / "b"), cwd=spaced,
        )
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        self.assertIn("current working directory", proc.stderr)
        self.assertNotIn("has space", proc.stdout + proc.stderr)
        self.assertFalse((self.tmp / "b").exists())


if __name__ == "__main__":
    unittest.main()
