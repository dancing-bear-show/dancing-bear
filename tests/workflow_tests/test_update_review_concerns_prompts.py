"""Rendered-prompt checks for update-review-concerns' rereview mode.

These render the real YAML through the engine, as an agent would receive it,
and execute the rendered jq lines against a fixture workspace. The rereview
stages are shell-heavy and gate the run on exit status, so a read-through is
not enough: the commands have to be shown to pass on good data and fail on
empty or partial data.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess  # nosec B404 - runs the workflow's own rendered jq lines in a temp dir
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from workflow.compiler import WorkflowCompileError, compile_workflow, match_when_expression
from workflow.dispatch import build_agent_prompt
from workflow.models import WorkflowDefinition, WorkflowManifest
from workflow.parser import parse_workflow

_ROOT = Path(__file__).resolve().parents[2]
_WORKFLOW = _ROOT / "workflows/code/update-review-concerns.yaml"
_PROMPT_FILE = _ROOT / "workflows/code/prompts/classify-rereview.md"

_TOPIC_STAGES = {
    "init", "fetch-findings", "fetch-review-threads", "cluster-gaps",
    "propose-concerns", "human-gate", "update-guides",
}
_REREVIEW_ONLY = {"fetch-round-history", "seed-class-list", "classify-rereview", "aggregate-rereview"}
_PLACEHOLDER_RE = re.compile(r"\{[a-z_][a-z0-9_]*\}")
#: Input round per fixture thread: 406 has a round-0 and a round-2 thread,
#: 395 has one unplaced (null) thread.
_ROUNDS: dict[str, int | None] = {"T406-0": 0, "T406-1": 2, "T395-0": None}
#: A full commit OID, the only commit shape review-rounds writes.
_OID = "0123456789abcdef0123456789abcdef01234567"
_CATEGORY_FOR_ROUND: dict[int | None, str] = {0: "ROUND0", None: "NOISE"}


def _compile(**params: str) -> tuple[WorkflowDefinition, WorkflowManifest]:
    defn = parse_workflow(str(_WORKFLOW))
    return defn, compile_workflow(defn, project_root=_ROOT, trigger_params=params)


def _prompts(workspace: str, **params: str) -> dict[str, str]:
    defn, manifest = _compile(**params)
    return {name: build_agent_prompt(stage, defn.name, workspace)
            for name, stage in manifest.resolved_stages.items()}


def _running(**params: str) -> set[str]:
    defn, manifest = _compile(**params)
    effective = {**defn.trigger.params, **params}
    return {name for name, stage in manifest.resolved_stages.items()
            if stage.spec.when is None or match_when_expression(stage.spec.when, effective)}


class TestParamRules(unittest.TestCase):
    """A caller-controlled param substituted into shell text was the largest
    defect class on PR #391. Every rereview param is rejected before
    substitution when it is not the shape the shell commands expect."""

    def test_both_modes_compile(self) -> None:
        _compile(mode="topics")
        _compile(mode="rereview")
        _compile(mode="rereview", pr_number="406", min_threads="20")

    def test_bad_min_threads_rejected(self) -> None:
        for bad in ("15;id", "0", "015", "1000", "$(id)", ""):
            with self.subTest(value=bad), self.assertRaises(WorkflowCompileError) as ctx:
                _compile(mode="rereview", min_threads=bad)
            self.assertIn("min_threads", str(ctx.exception))
            if "id" in bad:  # a rejected value is untrusted and is never echoed
                self.assertNotIn(bad, str(ctx.exception))

    def test_bad_pr_number_rejected(self) -> None:
        for bad in ("$(id)", "406;id", "0", "406,395", "12a", '406"'):
            with self.subTest(value=bad), self.assertRaises(WorkflowCompileError) as ctx:
                _compile(mode="rereview", pr_number=bad)
            self.assertIn("pr_number", str(ctx.exception))

    def test_bad_mode_rejected(self) -> None:
        for bad in ("both", "topicsrereview", "rereview;id", ""):
            with self.subTest(value=bad), self.assertRaises(WorkflowCompileError):
                _compile(mode=bad)

    def test_in_stage_checks_repeat_engine_rules(self) -> None:
        defn, _ = _compile()
        rules = {c.name: c.pattern for c in defn.trigger.rules.checks}
        text = _WORKFLOW.read_text(encoding="utf-8")
        found = re.findall(r"--check '([a-z_]+)=([^']*)'", text)
        self.assertEqual({n for n, _ in found}, {"mode", "min_threads", "max_prs", "pr_number"})
        for name, pattern in found:
            self.assertEqual(pattern, rules[name], name)


class TestModeRouting(unittest.TestCase):
    """topics must run exactly the stages it ran before rereview existed."""

    def test_topics_runs_the_original_stages(self) -> None:
        self.assertEqual(_running(mode="topics"), _TOPIC_STAGES)
        self.assertEqual(_running(), _TOPIC_STAGES)  # topics is the default

    def test_rereview_adds_its_stages_and_drops_thread_fetch(self) -> None:
        self.assertEqual(
            _running(mode="rereview"),
            (_TOPIC_STAGES - {"fetch-review-threads"}) | _REREVIEW_ONLY,
        )


class TestRenderedPrompts(unittest.TestCase):
    def setUp(self) -> None:
        self.prompts = _prompts("/ws", mode="rereview", pr_number="406", min_threads="20")

    def test_no_unsubstituted_placeholders(self) -> None:
        # {pr} and {fan_out_index} belong to the fan-out: dispatch fills them
        # per item, and the engine leaves them literal on purpose.
        allowed = {"classify-rereview": {"{pr}", "{fan_out_index}"}}
        for name in _REREVIEW_ONLY | {"cluster-gaps", "propose-concerns", "update-guides"}:
            with self.subTest(stage=name):
                left = set(_PLACEHOLDER_RE.findall(self.prompts[name])) - allowed.get(name, set())
                self.assertEqual(left, set())
                self.assertNotIn("{{", self.prompts[name])

    def test_params_reach_shell_quoted(self) -> None:
        text = self.prompts["fetch-round-history"]
        self.assertIn('review-rounds --prs "406" --out-dir "/ws/outputs/rounds"', text)
        self.assertIn('--min-threads "20"', text)
        self.assertIn('--argjson min "20"', text)

    def test_classifier_reads_checked_in_prompt(self) -> None:
        text = self.prompts["classify-rereview"]
        self.assertIn("workflows/code/prompts/classify-rereview.md", text)
        self.assertIn("Input:  /ws/outputs/rounds-safe/pr{pr}.json", text)
        self.assertIn('> "/ws/outputs/rounds-safe/pr{pr}.json"', text)
        self.assertIn("Never read outputs/rounds/pr{pr}.json", text)
        self.assertIn("/ws/outputs/classified/pr{pr}.json", text)
        self.assertLess(text.index("rm -f"), text.index("--arg pr "))
        self.assertTrue(_PROMPT_FILE.is_file())

    def test_prompt_file_is_workspace_relative_and_bans_catch_alls(self) -> None:
        body = _PROMPT_FILE.read_text(encoding="utf-8")
        for leaked in ("/private/tmp", "scratchpad", "/Users/"):
            self.assertNotIn(leaked, body)
        self.assertIn("outputs/rounds-safe/prN.json", body)
        self.assertIn("`spec-or-logic-error`", body)
        for category in ("FIX_REGRESSION", "SIBLING", "INCOMPLETE_FIX", "COLLATERAL_DOC",
                         "NEW_SURFACE", "LATE_DISCOVERY", "NOISE", "ROUND0"):
            self.assertIn(category, body)

    def test_cluster_gaps_rejects_with_reasons(self) -> None:
        text = self.prompts["cluster-gaps"]
        for code in ("`catch-all`", "`single-pr`", "`covered`", "`no-sweep`", "`sweep-too-broad`",
                     "`procedure-not-mechanical`"):
            self.assertIn(code, text)
        self.assertIn("## Rejected clusters", text)
        self.assertIn('"sweep":', text)

    def test_blank_pr_number_scans_max_prs_recent_prs(self) -> None:
        text = _prompts("/ws", mode="rereview", max_prs="30")["fetch-round-history"]
        self.assertIn('review-rounds --recent "30" --out-dir "/ws/outputs/rounds" --min-threads "15"', text)
        self.assertNotIn("--recent 60", text)

    def test_empty_scan_advice_sits_in_step_4(self) -> None:
        text = self.prompts["fetch-round-history"]
        step4, step5 = text.index("Step 4"), text.index("Step 5")
        advice = text.index("suggest a lower min_threads")
        self.assertLess(step4, advice)
        self.assertLess(advice, step5)

    def test_classifier_deletes_its_own_output_first(self) -> None:
        text = self.prompts["classify-rereview"]
        rm = text.index('rm -f "/ws/outputs/classified/pr{pr}.json"')
        self.assertLess(rm, text.index("Write only your own output file"))

    def test_fetch_findings_names_no_guide_list(self) -> None:
        """Guides are found by glob; a hand list drifts (it missed resume-copy.md)."""
        text = _prompts("/ws", mode="topics")["fetch-findings"]
        named = set(re.findall(r"concerns/[A-Za-z0-9_-]+\.md", text))
        self.assertEqual(named, {"concerns/README.md"})
        self.assertIn("concerns/*.md", text)

    def test_writes_to_names_only_workspace_paths(self) -> None:
        """The engine resolves every writes_to entry under the workspace, so a
        repo path such as concerns/x.md becomes {workspace}/outputs/concerns/x.md
        in the prompt: a file nothing writes, which completion then waits on."""
        for mode in ("topics", "rereview"):
            _, manifest = _compile(mode=mode)
            for name, stage in manifest.resolved_stages.items():
                for path in stage.spec.writes_to:
                    with self.subTest(mode=mode, stage=name, path=path):
                        self.assertTrue("/" not in path or path.startswith(("outputs/", "validation/", "stages/")))
                        self.assertFalse(path.startswith("concerns/"))
            self.assertEqual(manifest.resolved_stages["update-guides"].spec.writes_to,
                             ("outputs/update-summary.md",))

    def test_human_gate_writes_selection_on_none(self) -> None:
        text = self.prompts["human-gate"]
        self.assertIn("'none'        — reject all; approved-concern-ids.json is []", text)
        self.assertNotIn("exit without changes", text)

    def test_update_guides_counts_readme_row_after_appending(self) -> None:
        text = self.prompts["update-guides"]
        self.assertLess(text.index("Step 3 — append"), text.index("Step 3b —"))
        self.assertLess(text.index("Step 3b —"), text.index("Step 4"))
        self.assertIn("grep -c '^### ' concerns/collateral-damage.md", text)

    def test_prompt_file_describes_full_oids_and_both_lines(self) -> None:
        body = _PROMPT_FILE.read_text(encoding="utf-8")
        self.assertNotIn("10-character", body)
        self.assertIn("full OID", body)
        self.assertIn("`original_line`", body)
        self.assertIn("`git show '<commit>:<path>' --`", body)
        self.assertIn("aggregate-rereview fails the run", body)
        self.assertNotIn("cluster-gaps' aggregate check", body)

    def test_topics_pr_templates_are_quoted(self) -> None:
        text = _prompts("/ws", mode="topics")["fetch-review-threads"]
        calls = re.findall(r"\./bin/github [^\n]*<PR>[^\n]*", text)
        self.assertEqual(len(calls), 4)
        for call in calls:
            with self.subTest(call=call):
                self.assertIn("--pr '<PR>'", call)
                rest = call.replace("'<PR>'", "").replace('"/ws/outputs/threads-<PR>.json"', "")
                self.assertNotIn("<PR>", rest)
        self.assertIn('--out "/ws/outputs/threads-<PR>.json"', text)

    def test_prompt_git_templates_are_quoted_and_end_options(self) -> None:
        body = _PROMPT_FILE.read_text(encoding="utf-8")
        allowed = ("git show --stat '<commit>' --`", "git show '<commit>' -- '<path>'`",
                   "git show '<commit>:<path>' --`")
        starts = [m.start() for m in re.finditer(r"git show", body)]
        self.assertGreaterEqual(len(starts), 3)
        for at in starts:
            with self.subTest(at=body[at:at + 40]):
                self.assertTrue(body.startswith(allowed, at))
        self.assertEqual(re.findall(r"gh api [^`]*", body), ["gh api 'repos/OWNER/NAME/commits/<commit>'"])
        flat = " ".join(body.split())
        self.assertIn("Every value these take has passed the fetch-round-history gate", flat)
        self.assertIn("A thread whose `path` or `commit` is `null` gets no git inspection", flat)

    def test_topics_prompt_routes_away_from_rereview(self) -> None:
        text = _prompts("/ws", mode="topics")["cluster-gaps"]
        self.assertIn('this run\'s mode is "topics"', text)


def _jq_lines(prompt: str) -> list[str]:
    return [ln.strip() for ln in prompt.splitlines() if ln.strip().startswith("jq ")]


@unittest.skipUnless(shutil.which("jq") and shutil.which("bash"), "needs jq and bash")
class TestRenderedJqExecutes(unittest.TestCase):
    """Run the rendered jq lines, one Bash call each, as the agent would."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.ws = Path(tmp.name)
        (self.ws / "outputs/rounds").mkdir(parents=True)
        (self.ws / "outputs/classified").mkdir(parents=True)
        summary = [{"pr": 406, "threads": 2}, {"pr": 395, "threads": 1}, {"pr": 12, "threads": 0}]
        self._write("outputs/rounds/summary.json", summary)
        for pr, n in ((406, 2), (395, 1), (12, 0)):
            self._write(f"outputs/rounds/pr{pr}.json",
                        {"pr": pr, "threads": [{"thread_id": f"T{pr}-{i}", "round": _ROUNDS[f"T{pr}-{i}"]}
                                               for i in range(n)]})
        prompts = _prompts(str(self.ws), mode="rereview", min_threads="1")
        fetch = _jq_lines(prompts["fetch-round-history"])
        self.refuse_empty = next(c for c in fetch if "length > 0' " in c and "items" not in c)
        self.build_index = next(c for c in fetch if "--argjson min" in c)
        (self.gate,) = [c for c in fetch if "def okc" in c]
        (self.sanitise,) = [c for c in fetch if "--slurpfile u " in c]
        (self.extract,) = [c for c in _jq_lines(prompts["classify-rereview"]) if "--arg pr " in c]
        agg = _jq_lines(prompts["aggregate-rereview"])
        self.merge, self.counts, self.check, self.explain, self.invariants = agg

    def _write(self, rel: str, doc: object) -> None:
        (self.ws / rel).write_text(json.dumps(doc), encoding="utf-8")

    def _run(self, cmd: str) -> subprocess.CompletedProcess[str]:
        argv = [str(shutil.which("bash")), "-c", cmd]
        return subprocess.run(argv, capture_output=True, text=True, check=False)  # nosec B603 - rendered workflow lines against a temp dir

    def _classify(self, pr: int, n: int, override: Mapping[str, Mapping[str, object]] | None = None) -> None:
        """Write a valid classified file for the first n input threads of ``pr``.

        thread_ids match the source rounds data (T{pr}-{i}) so the multiset
        comparison passes; round, category and class obey the prompt's rules.
        ``override`` maps a thread_id to fields replacing the valid ones, and
        ``counts`` is always the true tally of what is written.
        """
        threads: list[dict[str, object]] = []
        for i in range(n):
            tid = f"T{pr}-{i}"
            rnd = _ROUNDS.get(tid)
            category = _CATEGORY_FOR_ROUND.get(rnd, "LATE_DISCOVERY")
            entry: dict[str, object] = {"thread_id": tid, "round": rnd, "category": category,
                                        "class": "no-defect" if rnd is None else "unquoted-shell-var"}
            entry.update((override or {}).get(tid, {}))
            threads.append(entry)
        counts: dict[str, int] = {}
        for entry in threads:
            counts[str(entry["category"])] = counts.get(str(entry["category"]), 0) + 1
        self._write(f"outputs/classified/pr{pr}.json", {"pr": pr, "threads": threads, "counts": counts})

    def _index(self) -> None:
        self.assertEqual(self._run(self.build_index).returncode, 0)

    def test_index_applies_thread_floor(self) -> None:
        self._index()
        index = json.loads((self.ws / "outputs/rereview-index.json").read_text())
        self.assertEqual(index, {"items": [{"pr": "406"}, {"pr": "395"}]})

    def test_index_keys_must_be_pr_numbers(self) -> None:
        fetch = _jq_lines(_prompts(str(self.ws), mode="rereview", min_threads="1")["fetch-round-history"])
        (check,) = [c for c in fetch if "all(.pr | test(" in c]
        self._index()
        self.assertEqual(self._run(check).returncode, 0)
        for bad in ("$(id)", "../x", "0", "406 ", "a"):
            with self.subTest(key=bad):
                self._write("outputs/rereview-index.json", {"items": [{"pr": "406"}, {"pr": bad}]})
                self.assertNotEqual(self._run(check).returncode, 0)

    def _seed_block(self) -> str:
        """The rendered seed-class-list Step 1 `if ls ... fi` block, dedented."""
        lines = _prompts(str(self.ws), mode="rereview", min_threads="1")["seed-class-list"].splitlines()
        start = next(i for i, ln in enumerate(lines) if ln.strip().startswith("if ls "))
        end = next(i for i in range(start, len(lines)) if lines[i].strip() == "fi")
        return "\n".join(ln.strip() for ln in lines[start:end + 1])

    def test_seed_list_reads_earlier_classified_files(self) -> None:
        # A quoted glob ("…/pr*.json") never expands, so the seed list came back
        # [] even when an earlier run had left classified files behind.
        self._classify(406, 2)
        self.assertEqual(self._run(self._seed_block()).returncode, 0)
        seed = json.loads((self.ws / "outputs/seed-classes.json").read_text())
        self.assertEqual(seed, ["unquoted-shell-var"])

    def test_seed_list_is_empty_on_a_fresh_workspace(self) -> None:
        self.assertEqual(self._run(self._seed_block()).returncode, 0)
        self.assertEqual(json.loads((self.ws / "outputs/seed-classes.json").read_text()), [])

    def test_empty_summary_halts(self) -> None:
        self._write("outputs/rounds/summary.json", [])
        self.assertNotEqual(self._run(self.refuse_empty).returncode, 0)
        self.assertNotEqual(self._run(self.build_index).returncode, 0)

    def test_nothing_over_the_floor_halts(self) -> None:
        self._write("outputs/rounds/summary.json", [{"pr": 12, "threads": 0}])
        self.assertEqual(self._run(self.refuse_empty).returncode, 0)
        self.assertNotEqual(self._run(self.build_index).returncode, 0)

    def test_aggregate_passes_when_complete_and_ignores_stale_files(self) -> None:
        self._index()
        self._classify(406, 2)
        self._classify(395, 1)
        self._classify(12, 0)  # outside the index: a stale file from an earlier run
        for cmd in (self.merge, self.counts, self.check):
            self.assertEqual(self._run(cmd).returncode, 0, cmd)
        merged = json.loads((self.ws / "outputs/rereview-classified.json").read_text())
        self.assertEqual(sorted(d["pr"] for d in merged), [395, 406])

    def test_aggregate_halts_on_missing_pr(self) -> None:
        self._index()
        self._classify(406, 2)
        for cmd in (self.merge, self.counts):
            self.assertEqual(self._run(cmd).returncode, 0, cmd)
        self.assertNotEqual(self._run(self.check).returncode, 0)
        self.assertIn("395: 0 classified files", self._run(self.explain).stdout)

    def test_pr_number_mode_keeps_a_pr_under_the_floor(self) -> None:
        """#429 has 5 threads; with pr_number set, Step 4 and Step 5 must pass it."""
        self._write("outputs/rounds/summary.json", [{"pr": 429, "threads": 5}])
        fetch = _jq_lines(_prompts(str(self.ws), mode="rereview", pr_number="429")["fetch-round-history"])
        refuse_empty = next(c for c in fetch if "length > 0' " in c and "items" not in c)
        build_index = next(c for c in fetch if "select(.items" in c and "--argjson" not in c)
        self.assertEqual(self._run(refuse_empty).returncode, 0)
        self.assertEqual(self._run(build_index).returncode, 0)
        index = json.loads((self.ws / "outputs/rereview-index.json").read_text())
        self.assertEqual(index, {"items": [{"pr": "429"}]})

    def test_cluster_totals_are_computed_by_jq(self) -> None:
        self._write("outputs/rereview-classified.json", [
            {"pr": 406, "threads": [{"category": "SIBLING"}, {"category": "ROUND0"}, {"category": "SIBLING"}]},
            {"pr": 395, "threads": [{"category": "NOISE"}]},
        ])
        self._write("outputs/known-concern-ids.json", ["a", "b", "c"])
        text = _prompts(str(self.ws), mode="rereview")["cluster-gaps"]
        (totals,) = [c for c in _jq_lines(text) if "known concern ids" in c]
        res = self._run(totals)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout.splitlines(), [
            "PRs: 2", "threads: 4", "NOISE: 1", "ROUND0: 1", "SIBLING: 2", "known concern ids: 3",
        ])

    def test_classifier_count_jq_executes(self) -> None:
        body = _PROMPT_FILE.read_text(encoding="utf-8")
        (line,) = [ln.strip() for ln in body.splitlines() if ln.strip().startswith("jq '[.threads")]
        out = self.ws / "outputs/classified/pr1.json"
        self._write("outputs/classified/pr1.json",
                    {"pr": 1, "threads": [{"category": "SIBLING"}, {"category": "SIBLING"}, {"category": "NOISE"}]})
        self.assertIn('"<your output file>"', line)
        res = self._run(line.replace("<your output file>", str(out)))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(json.loads(res.stdout), {"NOISE": 1, "SIBLING": 2})

    def test_aggregate_halts_on_partial_classification(self) -> None:
        self._index()
        self._classify(406, 1)
        self._classify(395, 1)
        for cmd in (self.merge, self.counts):
            self.assertEqual(self._run(cmd).returncode, 0, cmd)
        self.assertNotEqual(self._run(self.check).returncode, 0)
        self.assertIn("406: thread_id mismatch", self._run(self.explain).stdout)

    def _invariants_after(self, override: Mapping[str, Mapping[str, object]] | None = None,
                          ) -> subprocess.CompletedProcess[str]:
        """Classify both indexed PRs validly except ``override``, pass Steps 1-3, run Step 4."""
        self._index()
        self._classify(406, 2, override)
        self._classify(395, 1, override)
        for cmd in (self.merge, self.counts, self.check):
            self.assertEqual(self._run(cmd).returncode, 0, cmd)  # thread_ids are right in every case
        return self._run(self.invariants)

    def test_invariants_pass_on_clean_files(self) -> None:
        res = self._invariants_after()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(res.stdout.strip(), "true")

    def test_later_round_thread_labelled_round0_fails(self) -> None:
        """PR 400: 11 later-round threads on round-0 code were filed as ROUND0."""
        res = self._invariants_after({"T406-1": {"category": "ROUND0"}})
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("406 T406-1: category ROUND0 with input round 2", res.stdout)

    def test_round0_thread_labelled_late_discovery_fails(self) -> None:
        res = self._invariants_after({"T406-0": {"category": "LATE_DISCOVERY"}})
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("406 T406-0: category LATE_DISCOVERY with input round 0", res.stdout)

    def test_unplaced_thread_must_be_noise(self) -> None:
        for category, needle in (("ROUND0", "category ROUND0 with input round null"),
                                 ("LATE_DISCOVERY", "category LATE_DISCOVERY with input round null (must be NOISE)")):
            with self.subTest(category=category):
                res = self._invariants_after({"T395-0": {"category": category, "class": "unquoted-shell-var"}})
                self.assertNotEqual(res.returncode, 0)
                self.assertIn(f"395 T395-0: {needle}", res.stdout)

    def test_round_miscopied_fails_even_when_category_matches_the_copy(self) -> None:
        """The gate reads the INPUT round, so a copied round of 0 cannot launder ROUND0."""
        res = self._invariants_after({"T406-1": {"round": 0, "category": "ROUND0"}})
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("406 T406-1: category ROUND0 with input round 2; round 0 copied, input has 2", res.stdout)

    def test_unknown_category_and_bad_class_fail(self) -> None:
        for fields, needle in (({"category": "UNPLACED"}, 'category "UNPLACED" is not allowed'),
                               ({"class": "spec-or-logic-error"}, "class spec-or-logic-error is a forbidden catch-all"),
                               ({"class": ""}, "class is missing"),
                               ({"class": "no-defect"}, "class no-defect with category LATE_DISCOVERY")):
            with self.subTest(fields=fields):
                res = self._invariants_after({"T406-1": fields})
                self.assertNotEqual(res.returncode, 0)
                self.assertIn(f"406 T406-1: {needle}", res.stdout)

    def test_counts_disagreeing_with_tally_fail(self) -> None:
        self._invariants_after()
        doc = json.loads((self.ws / "outputs/rereview-classified.json").read_text())
        doc[0]["counts"] = {"ROUND0": 2, "LATE_DISCOVERY": 0, "NOISE": 0}
        self._write("outputs/rereview-classified.json", doc)
        res = self._run(self.invariants)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn(f"{doc[0]['pr']}: counts ", res.stdout)
        self.assertIn("!= tally", res.stdout)

    def test_banned_classes_match_the_prompt_list(self) -> None:
        body = _PROMPT_FILE.read_text(encoding="utf-8")
        section = body[body.index("**Forbidden catch-alls**"):body.index("and any name ending in")]
        from_prompt = set(re.findall(r"`([a-z-]+)`", section))
        in_gate = set(re.findall(r'"([a-z-]+)"', self.invariants.split("as $cats")[1].split("as $banned")[0]))
        self.assertTrue(from_prompt)
        self.assertEqual(from_prompt, in_gate)

    def _rounds_406(self, paths: tuple[object, object], thread_commit: object = _OID,
                    round_commit: object = _OID) -> None:
        """Rewrite pr406.json with a commit and a path on each of its two threads."""
        threads = [{"thread_id": f"T406-{i}", "round": _ROUNDS[f"T406-{i}"], "commit": thread_commit,
                    "path": path, "body": "b"} for i, path in enumerate(paths)]
        self._write("outputs/rounds/pr406.json", {"pr": 406, "rounds": [{"round": 0, "commit": round_commit}],
                                                  "threads": threads})

    def _gate_and_sanitise(self) -> tuple[list[object], dict[str, Any]]:
        for cmd in (self.gate, self.sanitise):
            res = self._run(cmd)
            self.assertEqual(res.returncode, 0, res.stderr)
        unsafe = json.loads((self.ws / "outputs/rounds/unsafe-paths.json").read_text())
        return unsafe, json.loads((self.ws / "outputs/rounds-sanitised.json").read_text())

    def test_gate_nulls_shell_unfriendly_paths_without_failing(self) -> None:
        bad = ["src/$(id).py", "docs/my file.md", "src/`id`.py", "../etc/passwd", "a/./b",
               ".github/workflows/ci.yml", ".claude/settings.json", "src/.GIT/hooks", "src/.envrc",
               "-rf", "/etc/passwd", "it's.py", "café.py"]
        for path in bad:
            with self.subTest(path=path):
                self._rounds_406((path, "src/core/ok_file-1.py"))
                unsafe, safe = self._gate_and_sanitise()
                self.assertEqual(unsafe, [{"pr": 406, "thread_id": "T406-0", "path": path}])
                self.assertEqual([t["path"] for t in safe["406"]["threads"]], [None, "src/core/ok_file-1.py"])

    def test_gate_fails_on_a_short_or_missing_commit(self) -> None:
        for label, kwargs in (("thread short", {"thread_commit": "abc123"}),
                              ("thread uppercase", {"thread_commit": _OID.upper()}),
                              ("round short", {"round_commit": "abc123"}),
                              ("round null", {"round_commit": None})):
            with self.subTest(case=label):
                self._rounds_406(("src/a.py", "src/b.py"), **kwargs)
                res = self._run(self.gate)
                self.assertNotEqual(res.returncode, 0)
                self.assertIn("commit is not a full OID", res.stderr)

    def test_valid_data_passes_unchanged(self) -> None:
        self._rounds_406(("src/a.py", None), thread_commit=None)
        originals = {p: json.loads((self.ws / f"outputs/rounds/pr{p}.json").read_text()) for p in (406, 395, 12)}
        unsafe, safe = self._gate_and_sanitise()
        self.assertEqual(unsafe, [])
        self.assertEqual(safe, {str(p): doc for p, doc in originals.items()})
        self.assertEqual(json.loads((self.ws / "outputs/rounds/pr406.json").read_text()), originals[406])

    def test_classifier_extract_is_the_sanitised_copy(self) -> None:
        self._rounds_406(("src/$(id).py", "src/a.py"))
        _, safe = self._gate_and_sanitise()
        (self.ws / "outputs/rounds-safe").mkdir()
        res = self._run(self.extract.replace("{pr}", "406"))
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(json.loads((self.ws / "outputs/rounds-safe/pr406.json").read_text()), safe["406"])
        self.assertNotEqual(self._run(self.extract.replace("{pr}", "999")).returncode, 0)

    def test_aggregate_multiset_passes_on_sanitised_data(self) -> None:
        self._rounds_406(("src/$(id).py", "docs/my file.md"))
        _, safe = self._gate_and_sanitise()
        self.assertTrue(all(t["path"] is None for t in safe["406"]["threads"]))
        res = self._invariants_after()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def _propose_line(self, needle: str) -> str:
        (line,) = [c for c in _jq_lines(_prompts(str(self.ws), mode="rereview")["propose-concerns"]) if needle in c]
        return line

    def _group(self, clusters: list[dict[str, object]]) -> list[dict[str, object]]:
        self._write("outputs/gap-clusters.json", clusters)
        res = self._run(self._propose_line("rereview-concern-groups.json"))
        self.assertEqual(res.returncode, 0, res.stderr)
        groups: list[dict[str, object]] = json.loads((self.ws / "outputs/rereview-concern-groups.json").read_text())
        return groups

    def test_one_class_in_three_categories_yields_one_group(self) -> None:
        """The live run promoted incomplete-guard-coverage under four categories."""
        procedure = {"procedure": _procedure()}
        pattern = {"pattern": "check-params[^|]*--check", "paths": ["workflows/"]}
        clusters = [
            _cluster("incomplete-guard-coverage", "LATE_DISCOVERY", ["406", "395"], 5, "security.md", procedure,
                     ["#406 a.py:1 — x", "#406 a.py:9 — y", "#395 b.py:2 — z"]),
            _cluster("incomplete-guard-coverage", "SIBLING", ["395", "400"], 4, "collateral-damage.md", pattern,
                     ["#395 c.py:3 — w", "#400 d.py:4 — v"], hits=7),
            _cluster("incomplete-guard-coverage", "FIX_REGRESSION", ["400", "412"], 3, "security.md",
                     {"structural": "every guard lists its input forms"}, ["#412 e.py:5 — u"]),
            _cluster("unquoted-shell-var", "SIBLING", ["406", "412"], 2, "security.md", pattern, ["#406 f.sh:1 — t"]),
        ]
        groups = {g["class"]: g for g in self._group(clusters)}
        self.assertEqual(set(groups), {"incomplete-guard-coverage", "unquoted-shell-var"})
        g = groups["incomplete-guard-coverage"]
        self.assertEqual(g["cause_categories"], ["FIX_REGRESSION", "LATE_DISCOVERY", "SIBLING"])
        self.assertEqual(g["pr_numbers"], ["395", "400", "406", "412"])
        self.assertEqual(g["occurrences"], 4)
        self.assertEqual(g["thread_count"], 12)
        self.assertEqual(g["cluster_count"], 3)
        self.assertEqual(g["guide_file"], "collateral-damage.md")
        self.assertEqual(g["sweep"], pattern)  # a pattern beats the earlier procedure
        self.assertEqual(g["sweep_hits"], 7)
        examples = g["example_comments"]
        if not isinstance(examples, list):
            self.fail(f"example_comments is {examples!r}")
        self.assertEqual(len(examples), 3)
        self.assertEqual({str(e).split()[0] for e in examples}, {"#395", "#400", "#406"})
        self.assertEqual(groups["unquoted-shell-var"]["cause_categories"], ["SIBLING"])

    def test_group_guide_is_the_most_common_without_collateral(self) -> None:
        sweep = {"structural": "x"}
        clusters = [
            _cluster("k", "SIBLING", ["1"], 1, "tests.md", sweep, []),
            _cluster("k", "LATE_DISCOVERY", ["2"], 1, "security.md", sweep, []),
            _cluster("k", "FIX_REGRESSION", ["3"], 1, "security.md", {"procedure": _procedure()}, []),
        ]
        (g,) = self._group(clusters)
        self.assertEqual(g["guide_file"], "security.md")
        self.assertEqual(g["sweep"], sweep)  # structural beats procedure
        self.assertIsNone(g["sweep_hits"])

    def test_proposal_id_gate(self) -> None:
        gate = self._propose_line("collides with a known concern id")
        self._write("outputs/known-concern-ids.json", ["unquoted-shell-var-in-stage"])
        good = [{"concern_id": "guard-input-forms-listed", "class": "incomplete-guard-coverage"},
                {"concern_id": "topic-entry"}]  # topics entries carry no class
        self._write("outputs/proposed-concerns.json", good)
        res = self._run(gate)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        self.assertEqual(res.stdout.strip(), "true")
        bad = {
            "duplicate id": ([*good, {"concern_id": "guard-input-forms-listed", "class": "other-class"}],
                             "guard-input-forms-listed: proposed 2 times"),
            "known id": ([*good, {"concern_id": "unquoted-shell-var-in-stage"}],
                         "unquoted-shell-var-in-stage: collides with a known concern id"),
            "same class twice": ([*good, {"concern_id": "second-id", "class": "incomplete-guard-coverage"}],
                                 "class incomplete-guard-coverage: 2 proposals, expected 1"),
            "missing id": ([*good, {"class": "z"}], "?: concern_id is missing"),
        }
        for label, (doc, needle) in bad.items():
            with self.subTest(case=label):
                self._write("outputs/proposed-concerns.json", doc)
                res = self._run(gate)
                self.assertNotEqual(res.returncode, 0)
                self.assertIn(needle, res.stdout)

    def _sweep_gate(self, stage: str, file: str) -> str:
        prompts = _prompts(str(self.ws), mode="rereview")
        (line,) = [c for c in _jq_lines(prompts[stage]) if f"outputs/{file}" in c and "structural" in c]
        return line

    def test_sweep_gate_accepts_data_and_refuses_shell_or_unsafe_paths(self) -> None:
        gate = self._sweep_gate("cluster-gaps", "gap-clusters.json")
        good = [
            {"class": "a", "sweep": {"pattern": "check-params[^|]*--check", "paths": ["workflows/", "src/core"]}},
            {"class": "b", "sweep": {"structural": "every isolated stage that names the workspace"}},
        ]
        self._write("outputs/gap-clusters.json", good)
        res = self._run(gate)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        bad_sweeps = {
            "command-string": "grep -rnE 'x' workflows/; id",
            "dotdot": {"pattern": "x", "paths": ["workflows/../../etc"]},
            "absolute": {"pattern": "x", "paths": ["/etc"]},
            "home": {"pattern": "x", "paths": ["~/x"]},
            "option": {"pattern": "x", "paths": ["-rf"]},
            "substitution": {"pattern": "x", "paths": ["src/$(id)"]},
            "github": {"pattern": "x", "paths": [".github/workflows"]},
            "claude": {"pattern": "x", "paths": [".claude/settings.json"]},
            "git-segment": {"pattern": "x", "paths": ["src/.GIT/hooks"]},
            "envrc": {"pattern": "x", "paths": ["src/.envrc"]},
            "no-paths": {"pattern": "x", "paths": []},
            "extra-key": {"pattern": "x", "paths": ["src"], "cmd": "id"},
            "empty-structural": {"structural": ""},
            "single-quote": {"pattern": "it's", "paths": ["src"]},
            "newline": {"pattern": "a\nb", "paths": ["src"]},
        }
        for label, sweep in bad_sweeps.items():
            with self.subTest(case=label):
                self._write("outputs/gap-clusters.json", [*good, {"class": label, "sweep": sweep}])
                res = self._run(gate)
                self.assertNotEqual(res.returncode, 0)
                self.assertIn(f"{label}: ", res.stdout)
                self.assertNotIn("a: ", res.stdout)

    def test_proposal_gate_is_the_cluster_gate(self) -> None:
        cluster = self._sweep_gate("cluster-gaps", "gap-clusters.json")
        proposal = self._sweep_gate("propose-concerns", "proposed-concerns.json")
        self.assertIn('has("procedure")', cluster)
        self.assertEqual(proposal, cluster.replace("gap-clusters.json", "proposed-concerns.json")
                         .replace('(.class // "?")', '(.concern_id // "?")'))

    def _gate_both(self, entry_sweep: dict[str, object], label: str) -> list[subprocess.CompletedProcess[str]]:
        """Run the cluster gate and the proposal gate over one extra entry."""
        results = []
        for stage, file, key in (("cluster-gaps", "gap-clusters.json", "class"),
                                 ("propose-concerns", "proposed-concerns.json", "concern_id")):
            gate = self._sweep_gate(stage, file)
            self._write(f"outputs/{file}", [
                {key: "a", "sweep": {"pattern": "x", "paths": ["src"]}},
                {key: label, "sweep": entry_sweep},
            ])
            results.append(self._run(gate))
        return results

    def test_sweep_gate_accepts_a_valid_procedure(self) -> None:
        for res in self._gate_both({"procedure": _procedure()}, "guard"):
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
            self.assertEqual(res.stdout.strip(), "true")

    def test_worked_example_in_the_prompt_passes_the_gate(self) -> None:
        """The example R5 teaches must itself be a valid procedure."""
        text = _prompts(str(self.ws), mode="rereview")["cluster-gaps"]
        (line,) = [ln.strip() for ln in text.splitlines()
                   if ln.strip().startswith('{"procedure": {"trigger": "a function')]
        for res in self._gate_both(json.loads(line), "example"):
            self.assertEqual(res.returncode, 0, res.stdout + res.stderr)

    def test_sweep_gate_refuses_non_mechanical_procedures(self) -> None:
        steps = _STEPS
        bad = {
            "one-step": _procedure(steps=steps[:1]),
            "seven-steps": _procedure(steps=[f"Is item {i} tested?" for i in range(7)]),
            "no-steps": _procedure(steps=[]),
            "empty-step": _procedure(steps=[steps[0], ""]),
            "blank-step": _procedure(steps=[steps[0], "   "]),
            "not-a-question": _procedure(steps=[steps[0], "List every entry point."]),
            "non-string-step": _procedure(steps=[steps[0], 3]),
            "judgement": _procedure(steps=[steps[0], "Was the guard checked carefully?"]),
            "accuracy": _procedure(evidence="review for accuracy"),
            "blank-trigger": _procedure(trigger=" "),
            "no-trigger": {k: v for k, v in _procedure().items() if k != "trigger"},
            "no-evidence": {k: v for k, v in _procedure().items() if k != "evidence"},
            "extra-key": {**_procedure(), "cmd": "id"},
            "steps-as-string": _procedure(steps="Is it tested?"),
        }
        for label, proc in bad.items():
            with self.subTest(case=label):
                for res in self._gate_both({"procedure": proc}, label):
                    self.assertNotEqual(res.returncode, 0)
                    self.assertIn(f"{label}: ", res.stdout)
                    self.assertNotIn("a: ", res.stdout)
        with self.subTest(case="procedure-beside-pattern"):
            for res in self._gate_both({"procedure": _procedure(), "pattern": "x", "paths": ["src"]}, "mixed"):
                self.assertNotEqual(res.returncode, 0)

    def _enforcement_lines(self) -> tuple[str, str]:
        text = _prompts(str(self.ws), mode="rereview")["cluster-gaps"]
        lines = [c for c in _jq_lines(text) if "outputs/enforcement-gaps.json" in c]
        (gate,) = [c for c in lines if "--slurpfile k" in c]
        (table,) = [c for c in lines if "None." in c]
        return gate, table

    def test_enforcement_gap_gate_requires_a_known_concern_and_two_prs(self) -> None:
        gate, _ = self._enforcement_lines()
        self._write("outputs/known-concern-ids.json", ["stale-prose-after-behavior-change", "silent-failure"])
        self._write("outputs/enforcement-gaps.json", [])
        self.assertEqual(self._run(gate).returncode, 0)
        self._write("outputs/enforcement-gaps.json", [_gap()])
        res = self._run(gate)
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        bad = {
            "unknown-id": _gap(concern_id="unknown-id"),
            "one-pr": _gap(concern_id="silent-failure", pr_numbers=["406", "406"]),
            "bad-guide": _gap(concern_id="silent-failure", guide_file="../x.md"),
            "no-example": _gap(concern_id="silent-failure", example=""),
        }
        for label, entry in bad.items():
            with self.subTest(case=label):
                self._write("outputs/enforcement-gaps.json", [_gap(), entry])
                res = self._run(gate)
                self.assertNotEqual(res.returncode, 0)
                self.assertEqual(res.stdout.count("\n"), 2, res.stdout)  # one bad line, then false

    def test_enforcement_gap_table_is_rendered_by_jq(self) -> None:
        _, table = self._enforcement_lines()
        self._write("outputs/enforcement-gaps.json", [])
        self.assertEqual(self._run(table).stdout.strip(), "None.")
        self._write("outputs/enforcement-gaps.json", [_gap(example="a.md:3 — x | y")])
        res = self._run(table)
        self.assertEqual(res.returncode, 0, res.stderr)
        rows = res.stdout.splitlines()
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[2], "| `stale-prose-after-behavior-change` | patterns.md | doc-claims-drift-from-code"
                                  " | COLLATERAL_DOC | 406, 395 | 8 | a.md:3 — x   y |")


_STEPS = [
    "Does the diff list every input form the guard receives?",
    "Does each listed input form have its own test?",
]


def _procedure(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "trigger": "a function that rejects, filters or authorises input is added or modified in `src/**/*.py`",
        "steps": list(_STEPS),
        "evidence": "each input form, paired with the test that covers it",
    }
    return {**base, **over}


def _cluster(cls: str, category: str, prs: list[str], threads: int, guide: str,
             sweep: Mapping[str, object], examples: list[str], hits: int | None = None) -> dict[str, object]:
    """One promoted gap-clusters.json entry in the R7 shape."""
    return {"theme": f"{cls} ({category})", "occurrences": len(prs), "pr_numbers": prs, "file_types": [".py"],
            "guide_file": guide, "example_comments": examples, "source": "rereview", "class": cls,
            "cause_category": category, "thread_count": threads, "sweep": sweep, "sweep_hits": hits,
            "sweep_hits_reason": None if hits is not None else "no tree count"}


def _gap(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "concern_id": "stale-prose-after-behavior-change", "guide_file": "patterns.md",
        "class": "doc-claims-drift-from-code", "cause_category": "COLLATERAL_DOC",
        "pr_numbers": ["406", "395"], "thread_count": 8, "example": "README.md:12 — stale claim",
    }
    return {**base, **over}


class TestPromotionRule(unittest.TestCase):
    """The promotion rule must admit defects no grep can find, and must not
    silently drop a covered class that keeps recurring."""

    def setUp(self) -> None:
        self.prompts = _prompts("/ws", mode="rereview")

    def test_ladder_reason_codes_and_order(self) -> None:
        flat = " ".join(self.prompts["cluster-gaps"].split())
        for code in ("`procedure-not-mechanical`", "`no-sweep`", "`sweep-too-broad`", "`covered`"):
            self.assertIn(code, flat)
        self.assertLess(flat.index("1. pattern"), flat.index("2. structural"))
        self.assertLess(flat.index("2. structural"), flat.index("3. procedure"))
        self.assertIn("Never reject with `no-sweep` or `sweep-too-broad` before attempting a procedure", flat)
        self.assertIn("neither a pattern, a structural check, nor a mechanical procedure could be written", flat)

    def test_catch_all_and_single_pr_precede_covered(self) -> None:
        text = self.prompts["cluster-gaps"]
        r5 = text[text.index("R5 —"):text.index("R6 —")]
        self.assertLess(r5.index("`catch-all`"), r5.index("`single-pr`"))
        self.assertLess(r5.index("`single-pr`"), r5.index("`covered`"))
        self.assertLess(r5.index("`covered`"), r5.index("the sweep ladder"))

    def test_enforcement_gaps_declared(self) -> None:
        for mode in ("topics", "rereview"):
            _, manifest = _compile(mode=mode)
            self.assertIn("outputs/enforcement-gaps.json",
                          manifest.resolved_stages["cluster-gaps"].spec.writes_to)

    def test_every_exit_writes_every_declared_output(self) -> None:
        _, manifest = _compile(mode="rereview")
        declared = [Path(p).name for p in manifest.resolved_stages["cluster-gaps"].spec.writes_to]
        for mode in ("topics", "rereview"):
            flat = " ".join(_prompts("/ws", mode=mode)["cluster-gaps"].split())
            with self.subTest(mode=mode, check="exit rule"):
                start = flat.index("Every exit from this stage, early or not and in either mode")
                rule = flat[start:flat.index("A missing file", start)]
                for name in declared:
                    self.assertIn(name, rule)
            with self.subTest(mode=mode, check="topics path"):
                topics = flat[:flat.index("REREVIEW MODE (only")]
                self.assertIn("write [] to /ws/outputs/enforcement-gaps.json", topics)
            with self.subTest(mode=mode, check="empty-array exits"):
                exits = [m.start() for m in re.finditer(r"write \[\] to gap-clusters\.json", flat, re.IGNORECASE)]
                self.assertEqual(len(exits), 2)  # topics Step 5 and rereview R7
                for at in exits:
                    self.assertIn("enforcement-gaps.json", flat[at:at + 250])
            with self.subTest(mode=mode, check="single-PR rereview"):
                self.assertIn("Write [] when there are none, which is always the case when pr_number is set", flat)

    def test_every_stage_early_exit_writes_every_declared_output(self) -> None:
        """Beyond cluster-gaps: any paragraph that exits 0 early must still
        write each of its stage's writes_to files, or completion never passes."""
        seen = 0
        for mode in ("topics", "rereview"):
            _, manifest = _compile(mode=mode)
            for name, stage in manifest.resolved_stages.items():
                for para in stage.spec.description.split("\n\n"):
                    if not re.search(r"\bexit 0\b", para, re.IGNORECASE):
                        continue
                    seen += 1
                    for path in stage.spec.writes_to:
                        with self.subTest(mode=mode, stage=name, path=path):
                            self.assertIn(Path(path).name, para)
        self.assertGreaterEqual(seen, 3)  # fetch-review-threads, propose-concerns, update-guides

    def test_propose_concerns_forwards_enforcement_gaps_and_never_proposes_them(self) -> None:
        flat = " ".join(self.prompts["propose-concerns"].split())
        self.assertIn('Copy the "## Enforcement gaps" section', flat)
        self.assertIn("never add one to proposed-concerns.json", flat)
        self.assertLess(flat.index('"## Enforcement gaps"'), flat.index('"## Rejected clusters"'))
        self.assertIn("plus those three sections", flat)

    def test_procedure_entry_format(self) -> None:
        flat = " ".join(self.prompts["propose-concerns"].split())
        self.assertIn('**check** is "Answer yes to each step: "', flat)
        self.assertIn("**triggers** is the procedure trigger verbatim", flat)
        self.assertIn("numbered list", flat)
        self.assertIn('{"procedure"} object', flat)

    def test_lint_kind_is_deferred_to_pr_433(self) -> None:
        self.assertIn("PR #433", _WORKFLOW.read_text(encoding="utf-8"))
        self.assertNotIn('"lint":', self.prompts["cluster-gaps"])


_COUNT_SWEEP_CALL = "./bin/workflow count-sweep --pattern='<pattern>' --path='<path>'"
#: Stages whose text builds a count-sweep command. Asserted equal to the set
#: found by scanning every rendered prompt, so a new caller cannot skip the
#: quoting checks below.
_COUNT_SWEEP_STAGES = {"cluster-gaps", "propose-concerns"}


class TestSweepCounting(unittest.TestCase):
    """Sweeps are counted in-process by count-sweep, never via a spec file and a shell grep."""

    def test_no_stage_prompt_names_the_spec_file_flow(self) -> None:
        for mode in ("topics", "rereview"):
            for name, text in _prompts("/ws", mode=mode).items():
                with self.subTest(mode=mode, stage=name):
                    for banned in ("sweep-spec", "/tmp/", "grep-sweep"):  # nosec B108 - asserted absent, never used as a path
                        self.assertNotIn(banned, text)

    def test_every_stage_building_the_command_is_checked(self) -> None:
        for mode in ("topics", "rereview"):
            with self.subTest(mode=mode):
                found = {name for name, text in _prompts("/ws", mode=mode).items() if "count-sweep --" in text}
                self.assertEqual(found, _COUNT_SWEEP_STAGES)

    def test_sweeping_stages_single_quote_the_pattern_and_every_path(self) -> None:
        prompts = _prompts("/ws", mode="rereview")
        for name in sorted(_COUNT_SWEEP_STAGES):
            with self.subTest(stage=name):
                text = prompts[name]
                self.assertIn(_COUNT_SWEEP_CALL, text)
                for leaked in ("wc -l", "Grep tool", "grep -rn", "python3 -I -S -c"):
                    self.assertNotIn(leaked, text)
                calls = re.findall(r"count-sweep --pattern[^\n`]*", text)
                self.assertTrue(calls)
                for call in calls:
                    self.assertTrue(call.startswith("count-sweep --pattern='<pattern>' --path='<path>'"), call)
                    # Every --path in the call, including the repeat form, is quoted.
                    self.assertEqual(re.findall(r"--path(?!=')", call), [], call)
                self.assertNotIn("--path <", text)

    def test_quote_and_newline_refusal_is_in_the_stage_text(self) -> None:
        prompts = _prompts("/ws", mode="rereview")
        for name in sorted(_COUNT_SWEEP_STAGES):
            with self.subTest(stage=name):
                flat = " ".join(prompts[name].split())
                self.assertIn("a pattern containing a single quote or a newline is REFUSED", flat)

    def test_unsafe_path_refusal_precedes_the_command_in_the_stage_text(self) -> None:
        prompts = _prompts("/ws", mode="rereview")
        cluster = " ".join(prompts["cluster-gaps"].split())
        self.assertIn("Check each path against these rules BEFORE writing the command", cluster)
        self.assertIn("is REFUSED, not escaped or quoted around", cluster)
        for char in ("`$`", "a backtick", "`;`", "`|`", "`&`", "a space", "a quote"):
            with self.subTest(char=char):
                self.assertIn(char, cluster)
        propose = " ".join(prompts["propose-concerns"].split())
        self.assertIn("Check every path BEFORE writing the command", propose)
        self.assertIn("is REFUSED, not escaped", propose)

    def test_rendered_call_runs_and_refuses_an_escaping_path(self) -> None:
        text = _prompts("/ws", mode="rereview")["cluster-gaps"]
        self.assertIn(_COUNT_SWEEP_CALL, text)
        argv = [str(_ROOT / "bin/workflow"), "count-sweep", "--pattern=check-params", "--path", "workflows/"]
        res = subprocess.run(argv, cwd=_ROOT, capture_output=True, text=True, check=False)  # nosec B603 - fixed argv, repo's own wrapper
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertGreater(json.loads(res.stdout)["hits"], 0)
        argv[-1] = "../x"
        res = subprocess.run(argv, cwd=_ROOT, capture_output=True, text=True, check=False)  # nosec B603 - fixed argv, repo's own wrapper
        self.assertEqual((res.returncode, res.stdout), (2, ""))
        self.assertIn("escapes-repo", res.stderr)

    def test_rendered_call_refuses_shell_metacharacter_paths(self) -> None:
        for bad in ("src/$(id)", "src/`id`", "src;id", "src|id", "src&id", "src id", "-src", "src'x"):
            with self.subTest(path=bad):
                argv = [str(_ROOT / "bin/workflow"), "count-sweep", "--pattern=x", f"--path={bad}"]
                res = subprocess.run(argv, cwd=_ROOT, capture_output=True, text=True, check=False)  # nosec B603 - fixed argv, repo's own wrapper
                self.assertEqual((res.returncode, res.stdout), (2, ""))
                self.assertIn("refused path", res.stderr)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
