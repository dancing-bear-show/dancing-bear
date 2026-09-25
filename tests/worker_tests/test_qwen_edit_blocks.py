"""Tests for the qwen_patch edit-block path (worker.qwen_edits): parse SEARCH/REPLACE blocks,
apply them in memory, build the unified diff locally, persist the model's
response on failure.

The diff tests run the REAL git apply against a throwaway repository in the
test's temp dir; handler-level tests inherit QwenHandlerCase, so no network,
queue, collector or real output directory is touched.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess  # nosec B404 - builds throwaway git repos inside the test temp dir
import unittest
import unittest.mock as mock
from collections.abc import Callable
from pathlib import Path

from tests.fixtures import TempDirMixin
from tests.worker_tests.qwen_fixtures import (
    GREET_EDIT,
    GREET_ORIGINAL,
    GREET_PATH,
    REAL_GIT_APPLY_CHECK,
    QwenHandlerCase,
    edit_block,
    model_says,
    require,
)
from worker import qwen, qwen_edits

_FAKE_TOKEN = "ghp_abcdefghijklmnopqrstuvwxyz0123456789"  # nosec B105 - fixture value asserted as masked, not a real credential


def _outcome(fn: Callable[..., object], *args: object) -> str:
    """The outcome string fn raises as an EditBlockError."""
    try:
        fn(*args)
    except qwen_edits.EditBlockError as exc:
        return str(exc)
    raise AssertionError("expected an EditBlockError")


class ParseEditBlocksTests(unittest.TestCase):
    def test_single_block(self) -> None:
        [block] = qwen_edits.parse_edit_blocks(edit_block("src/a.py", "old", "new"))

        self.assertEqual(block, qwen_edits.EditBlock("src/a.py", ("old",), ("new",)))

    def test_multiple_blocks_and_files_keep_their_order(self) -> None:
        text = edit_block("src/a.py", "a1", "A1") + edit_block("src/b.py", "b1\nb2", "") + edit_block("src/a.py", "a2", "A2")

        blocks = qwen_edits.parse_edit_blocks(text)

        self.assertEqual(
            blocks,
            [
                qwen_edits.EditBlock("src/a.py", ("a1",), ("A1",)),
                qwen_edits.EditBlock("src/b.py", ("b1", "b2"), ("",)),
                qwen_edits.EditBlock("src/a.py", ("a2",), ("A2",)),
            ],
        )

    def test_fences_and_prose_around_blocks_are_ignored(self) -> None:
        text = (
            "Sure, here is the change:\n\n```python\n"
            + edit_block("src/a.py", "old", "new")
            + "```\n\nAnd a second one:\n```\n"
            + edit_block("src/b.py", "x", "y")
            + "```\nAnything else?"
        )

        blocks = qwen_edits.parse_edit_blocks(text)

        self.assertEqual([b.path for b in blocks], ["src/a.py", "src/b.py"])
        self.assertEqual(blocks[0].replace, ("new",))

    def test_file_line_applies_to_every_following_block(self) -> None:
        text = "FILE: src/a.py\n<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE\n<<<<<<< SEARCH\nc\n=======\nd\n>>>>>>> REPLACE\n"

        self.assertEqual([b.path for b in qwen_edits.parse_edit_blocks(text)], ["src/a.py", "src/a.py"])

    def test_body_lines_are_verbatim_and_a_divider_in_replace_is_content(self) -> None:
        text = "FILE: docs/x.rst\n<<<<<<< SEARCH\n  Title  \n=======\nTitle\n=======\n>>>>>>> REPLACE\n"

        [block] = qwen_edits.parse_edit_blocks(text)

        self.assertEqual(block.search, ("  Title  ",))
        self.assertEqual(block.replace, ("Title", "======="))

    def test_empty_search_parses_as_an_empty_tuple(self) -> None:
        [block] = qwen_edits.parse_edit_blocks("FILE: src/a.py\n<<<<<<< SEARCH\n=======\nnew\n>>>>>>> REPLACE\n")

        self.assertEqual(block.search, ())

    def test_block_before_any_file_line_has_an_empty_path(self) -> None:
        [block] = qwen_edits.parse_edit_blocks("<<<<<<< SEARCH\na\n=======\nb\n>>>>>>> REPLACE")

        self.assertEqual(block.path, "")

    def test_no_blocks_is_no_edits_found(self) -> None:
        for text in ("", "sorry, I cannot help with that", "FILE: src/a.py\n", "```diff\n--- a/x\n+++ b/x\n```"):
            with self.subTest(text=text):
                self.assertEqual(_outcome(qwen_edits.parse_edit_blocks, text), qwen_edits.NO_EDITS_OUTCOME)

    def test_incomplete_or_disordered_markers_are_malformed(self) -> None:
        cases = {
            "truncated in replace": "FILE: a\n<<<<<<< SEARCH\nx\n=======\ny",
            "truncated in search": "FILE: a\n<<<<<<< SEARCH\nx",
            "replace before divider": "FILE: a\n<<<<<<< SEARCH\nx\n>>>>>>> REPLACE\n",
            "second search inside replace": "FILE: a\n<<<<<<< SEARCH\nx\n=======\ny\n<<<<<<< SEARCH\n",
            "stray replace marker": edit_block("a", "x", "y") + ">>>>>>> REPLACE\n",
            "stray divider": "=======\n" + edit_block("a", "x", "y"),
        }
        for name, text in cases.items():
            with self.subTest(name):
                self.assertEqual(_outcome(qwen_edits.parse_edit_blocks, text), qwen_edits.EDIT_MALFORMED_OUTCOME)


class ApplyEditBlocksTests(unittest.TestCase):
    FILES = {"src/a.py": "one\ntwo\nthree\n", "src/b.py": "alpha\nbeta"}

    def _apply(self, text: str, files: dict[str, str] | None = None) -> dict[str, str]:
        return qwen_edits.apply_edit_blocks(qwen_edits.parse_edit_blocks(text), dict(files or self.FILES))

    def _apply_outcome(self, text: str, files: dict[str, str] | None = None) -> str:
        return _outcome(self._apply, text, files)

    def test_single_edit_returns_only_the_changed_file(self) -> None:
        self.assertEqual(self._apply(edit_block("src/a.py", "two", "TWO")), {"src/a.py": "one\nTWO\nthree\n"})

    def test_edits_across_files(self) -> None:
        text = edit_block("src/a.py", "one", "ONE") + edit_block("src/b.py", "alpha", "ALPHA")

        self.assertEqual(self._apply(text), {"src/a.py": "ONE\ntwo\nthree\n", "src/b.py": "ALPHA\nbeta"})

    def test_blocks_apply_sequentially_to_current_content(self) -> None:
        text = edit_block("src/a.py", "two", "2a\n2b") + edit_block("src/a.py", "2b\nthree", "end")

        self.assertEqual(self._apply(text), {"src/a.py": "one\n2a\nend\n"})

    def test_search_that_only_existed_before_an_earlier_edit_is_not_found(self) -> None:
        text = edit_block("src/a.py", "two", "TWO") + edit_block("src/a.py", "two", "again")

        self.assertEqual(self._apply_outcome(text), qwen_edits.EDIT_NOT_FOUND_OUTCOME)

    def test_final_newline_state_is_preserved(self) -> None:
        cases = (
            (edit_block("src/b.py", "beta", "BETA"), "alpha\nBETA"),
            (edit_block("src/b.py", "beta", "BETA\ngamma"), "alpha\nBETA\ngamma"),
            (edit_block("src/b.py", "alpha", "ALPHA"), "ALPHA\nbeta"),
            (edit_block("src/a.py", "three", "3\n4"), "one\ntwo\n3\n4\n"),
        )
        for text, expected in cases:
            with self.subTest(expected=expected):
                [(_, content)] = self._apply(text).items()
                self.assertEqual(content, expected)

    def test_an_empty_replace_deletes_lines(self) -> None:
        """An empty REPLACE body removes the SEARCH lines; the final-newline
        state still holds (no newline after the new last line of src/b.py)."""
        cases = (
            ("src/b.py", "beta", {"src/b.py": "alpha"}),
            ("src/a.py", "two", {"src/a.py": "one\nthree\n"}),
            ("src/a.py", "one\ntwo\nthree", {"src/a.py": ""}),
        )
        for path, search, expected in cases:
            with self.subTest(path=path, search=search):
                text = f"FILE: {path}\n<<<<<<< SEARCH\n{search}\n=======\n>>>>>>> REPLACE\n"
                self.assertEqual(self._apply(text), expected)

    def test_whole_line_blank_search_matches_a_blank_line(self) -> None:
        files = {"src/c.py": "a\n\nb\n"}

        self.assertEqual(self._apply(edit_block("src/c.py", "", "x"), files), {"src/c.py": "a\nx\nb\n"})

    def test_path_spellings_that_normalise_to_an_input_are_accepted(self) -> None:
        for path in ("./src/a.py", "src//a.py", "`src/a.py`", "src/x/../a.py"):
            with self.subTest(path=path):
                self.assertEqual(self._apply(edit_block(path, "one", "1")), {"src/a.py": "1\ntwo\nthree\n"})

    def test_paths_outside_the_inputs_are_refused(self) -> None:
        for path in ("", "src/c.py", "SRC/a.py", "/src/a.py", "../src/a.py", "src\\a.py", "a.py", ".", "src/a.py/.."):
            with self.subTest(path=path):
                self.assertEqual(self._apply_outcome(edit_block(path, "one", "1")), qwen_edits.EDIT_OUTSIDE_INPUTS_OUTCOME)

    def test_absolute_path_of_an_input_is_refused(self) -> None:
        """The prompt never shows the root, so a model that invents one is off-script."""
        self.assertEqual(
            self._apply_outcome(edit_block("/Users/someone/repo/src/a.py", "one", "1")), qwen_edits.EDIT_OUTSIDE_INPUTS_OUTCOME
        )

    def test_search_not_in_file_is_not_found(self) -> None:
        for search in ("four", "one\nthree", "one ", " one", "two\nthree\n"):
            with self.subTest(search=search):
                self.assertEqual(self._apply_outcome(edit_block("src/a.py", search, "x")), qwen_edits.EDIT_NOT_FOUND_OUTCOME)

    def test_search_matching_twice_is_ambiguous(self) -> None:
        files = {"src/d.py": "x = 1\ny = 2\nx = 1\n"}

        self.assertEqual(self._apply_outcome(edit_block("src/d.py", "x = 1", "x = 3"), files), qwen_edits.EDIT_AMBIGUOUS_OUTCOME)
        self.assertEqual(self._apply(edit_block("src/d.py", "x = 1\ny = 2", "x = 3\ny = 2"), files), {"src/d.py": "x = 3\ny = 2\nx = 1\n"})

    def test_empty_search_is_ambiguous_never_an_insert(self) -> None:
        text = "FILE: src/a.py\n<<<<<<< SEARCH\n=======\nheader\n>>>>>>> REPLACE\n"
        for files in (self.FILES, {"src/a.py": ""}):
            with self.subTest(files=files):
                self.assertEqual(self._apply_outcome(text, files), qwen_edits.EDIT_AMBIGUOUS_OUTCOME)

    def test_edits_that_change_nothing_are_no_change(self) -> None:
        cases = (
            edit_block("src/a.py", "two", "two"),
            edit_block("src/a.py", "two", "2") + edit_block("src/a.py", "2", "two"),
        )
        for text in cases:
            with self.subTest(text=text):
                self.assertEqual(self._apply_outcome(text), qwen_edits.NO_CHANGE_OUTCOME)

    def test_inputs_are_not_mutated(self) -> None:
        files = dict(self.FILES)

        qwen_edits.apply_edit_blocks(qwen_edits.parse_edit_blocks(edit_block("src/a.py", "two", "TWO")), files)

        self.assertEqual(files, self.FILES)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # nosec B603 B607 - fixed git argv inside a test temp dir
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=False
    )


class BuildUnifiedDiffGitApplyTests(TempDirMixin, unittest.TestCase):
    """The locally built diff must be accepted by the REAL git apply --check,
    and applying it must produce exactly the edited content."""

    def setUp(self) -> None:
        super().setUp()
        self.repo = Path(self.tmpdir) / "repo"
        self.repo.mkdir()
        self.assertEqual(_git(self.repo, "init", "-q").returncode, 0)

    def _assert_round_trip(self, original: dict[str, str], response: str) -> str:
        for rel, text in original.items():
            path = self.repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(text.encode("utf-8"))
        updated = qwen_edits.apply_edit_blocks(qwen_edits.parse_edit_blocks(response), original)
        diff = qwen_edits.edits_to_diff(response, original)

        self.assertTrue(REAL_GIT_APPLY_CHECK(diff, self.repo), diff)
        patch = Path(self.tmpdir) / "built.patch"
        patch.write_text(diff, encoding="utf-8")
        applied = _git(self.repo, "apply", str(patch))
        self.assertEqual(applied.returncode, 0, applied.stderr)
        for rel, text in updated.items():
            self.assertEqual((self.repo / rel).read_bytes(), text.encode("utf-8"))
        return diff

    def test_single_edit(self) -> None:
        diff = self._assert_round_trip({GREET_PATH: GREET_ORIGINAL}, GREET_EDIT)

        self.assertTrue(diff.startswith(f"--- a/{GREET_PATH}\n+++ b/{GREET_PATH}\n@@ "))

    def test_no_final_newline_edit_on_the_last_line(self) -> None:
        diff = self._assert_round_trip({"src/n.py": "a\nb\nc"}, edit_block("src/n.py", "c", "C"))

        self.assertEqual(diff.count("\\ No newline at end of file\n"), 2)

    def test_no_final_newline_edit_away_from_the_last_line(self) -> None:
        """The unchanged last line is context; it still needs the marker."""
        self._assert_round_trip({"src/n.py": "a\nb\nc"}, edit_block("src/n.py", "b", "B"))

    def test_no_final_newline_edit_far_from_the_end(self) -> None:
        lines = "\n".join(f"line {i}" for i in range(20))
        diff = self._assert_round_trip({"src/n.py": lines}, edit_block("src/n.py", "line 1", "LINE 1"))

        self.assertNotIn("No newline", diff)

    def test_appending_after_a_last_line_without_newline(self) -> None:
        self._assert_round_trip({"src/n.py": "a\nb"}, edit_block("src/n.py", "b", "b\nc"))

    def test_multi_hunk_single_file(self) -> None:
        text = "".join(f"line {i}\n" for i in range(40))
        response = edit_block("src/m.py", "line 2", "LINE 2") + edit_block("src/m.py", "line 35", "LINE 35\nextra")

        diff = self._assert_round_trip({"src/m.py": text}, response)

        self.assertEqual(diff.count("\n@@ "), 2)

    def test_multiple_files_get_one_section_each(self) -> None:
        response = edit_block("src/a.py", "x", "y") + edit_block("tests/b.py", "p\nq", "q")

        diff = self._assert_round_trip({"src/a.py": "x\n", "tests/b.py": "p\nq\nr", "src/c.py": "same\n"}, response)

        self.assertEqual(qwen.diff_stats(diff), (["src/a.py", "tests/b.py"], 3))
        self.assertIsNone(qwen.check_patch_caps(diff))

    def test_deleting_every_line(self) -> None:
        self._assert_round_trip({"src/e.py": "only\n"}, edit_block("src/e.py", "only", "").replace("=======\n\n", "=======\n"))

    def test_diff_without_the_marker_is_rejected_by_git(self) -> None:
        """Pins why the marker exists: strip it and git apply --check refuses."""
        (self.repo / "src").mkdir()
        (self.repo / "src/n.py").write_text("a\nb", encoding="utf-8")
        diff = qwen_edits.edits_to_diff(edit_block("src/n.py", "b", "B"), {"src/n.py": "a\nb"})

        self.assertFalse(REAL_GIT_APPLY_CHECK(diff.replace("\\ No newline at end of file\n", ""), self.repo))


class PromptLabelTests(QwenHandlerCase):
    def _prompt(self) -> str:
        [(_, body, _)] = self.generate_requests()
        return str(require(body)["prompt"])

    def test_prompt_labels_files_repo_relative_and_never_shows_the_root(self) -> None:
        ok, _ = self.run_handler()

        self.assertTrue(ok)
        prompt = self._prompt()
        self.assertIn(f"FILE: {GREET_PATH}\n{GREET_ORIGINAL}", prompt)
        for root in (str(self.repo_root), str(self.repo_root.resolve()), self.tmpdir):
            self.assertNotIn(root, prompt)

    def test_prompt_asks_for_edit_blocks_not_a_diff(self) -> None:
        self.run_handler()

        prompt = self._prompt()
        for marker in ("<<<<<<< SEARCH", "=======", ">>>>>>> REPLACE"):
            self.assertIn(marker, prompt)
        self.assertNotIn("unified diff", prompt)

    def test_explain_mode_measures_the_prompt_a_real_run_sends(self) -> None:
        ok, report = self.run_handler({"explain": True})
        self.assertTrue(ok)

        self.run_handler()

        estimated = self.as_dict(report)["assembled_prompt_tokens"]
        self.assertEqual(estimated, len(self._prompt()) // 4)


class ResponsePersistenceTests(QwenHandlerCase):
    """A failure after the model answered keeps its masked response."""

    def _secret_response(self) -> str:
        return f"I think token={_FAKE_TOKEN} goes here:\n" + edit_block(GREET_PATH, "not in the file", "x")

    def _response_file(self) -> Path:
        return self.response_dir / "qwen-test-job.txt"

    def test_failure_persists_the_masked_response_with_private_modes(self) -> None:
        self.generate_response = model_says(self._secret_response())

        ok, out = self.run_handler()

        self.assertEqual((ok, out), (False, qwen_edits.EDIT_NOT_FOUND_OUTCOME))
        saved = self._response_file().read_text(encoding="utf-8")
        self.assertNotIn(_FAKE_TOKEN, saved)
        self.assertIn("REDACTED", saved)
        self.assertIn("<<<<<<< SEARCH\nnot in the file\n", saved)
        self.assertEqual(stat.S_IMODE(self._response_file().stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.response_dir.stat().st_mode) & 0o077, 0)
        self.assertNotIn(_FAKE_TOKEN, json.dumps(out))

    def test_every_post_response_failure_persists(self) -> None:
        cases = (
            ("sorry", qwen_edits.NO_EDITS_OUTCOME, None),
            (edit_block("src/other.py", "x", "y"), qwen_edits.EDIT_OUTSIDE_INPUTS_OUTCOME, None),
            (edit_block(GREET_PATH, "def greet(name):", "def greet(name):"), qwen_edits.NO_CHANGE_OUTCOME, None),
            (GREET_EDIT, "terminal-patch-does-not-apply", False),
            (GREET_EDIT, "terminal-patch-too-broad", "caps"),
        )
        for text, expected, variant in cases:
            with self.subTest(expected=expected):
                self._response_file().unlink(missing_ok=True)
                self.generate_response = model_says(text)
                with (
                    mock.patch("worker.qwen._git_apply_check", return_value=variant is not False),
                    mock.patch(
                        "worker.qwen.check_patch_caps",
                        return_value="terminal-patch-too-broad" if variant == "caps" else None,
                    ),
                ):
                    self.assertEqual(self.run_handler(), (False, expected))
                self.assertEqual(self._response_file().read_text(encoding="utf-8"), text)

    def test_response_is_capped_and_masked_across_the_cap(self) -> None:
        """A secret straddling the byte cap is masked, not cut into an
        unmaskable fragment."""
        filler = "no edits here\n" * (qwen.MAX_PERSISTED_RESPONSE_BYTES // 14 - 10)
        # A bare token starting 10 bytes before the cap: cut-then-mask would
        # keep "ghp_abcdef", which mask_text does not recognise on its own.
        pad = " " * (qwen.MAX_PERSISTED_RESPONSE_BYTES - len(filler) - 10)
        text = f"{filler}{pad}{_FAKE_TOKEN}\n" + "tail\n" * 5000
        self.assertEqual(text.index(_FAKE_TOKEN), qwen.MAX_PERSISTED_RESPONSE_BYTES - 10)
        self.generate_response = model_says(text)

        self.assertEqual(self.run_handler(), (False, qwen_edits.NO_EDITS_OUTCOME))

        saved = self._response_file().read_bytes()
        self.assertEqual(len(saved), qwen.MAX_PERSISTED_RESPONSE_BYTES)
        self.assertNotIn(_FAKE_TOKEN[:10].encode("utf-8"), saved)

    def test_success_and_pre_response_failures_persist_nothing(self) -> None:
        self.assertTrue(self.run_handler()[0])
        with mock.patch("worker.qwen._build_prompt", side_effect=ValueError("boom")):
            self.run_handler()
        self.generate_error = OSError("refused")
        self.run_handler()

        self.assertEqual(self.response_files(), [])

    def test_persistence_failure_does_not_change_the_outcome(self) -> None:
        """A regular file where the response directory should be: mkdir fails
        for real, and the job still reports its own outcome."""
        self.response_dir.write_text("in the way", encoding="utf-8")
        self.generate_response = model_says(self._secret_response())

        self.assertEqual(self.run_handler(), (False, qwen_edits.EDIT_NOT_FOUND_OUTCOME))
        self.assertEqual(self.response_dir.read_text(encoding="utf-8"), "in the way")

    def test_symlink_at_the_response_path_is_not_followed(self) -> None:
        self.response_dir.mkdir()
        victim = Path(self.tmpdir) / "victim.txt"
        victim.write_text("keep", encoding="utf-8")
        os.symlink(victim, self._response_file())
        self.generate_response = model_says("sorry")

        self.assertEqual(self.run_handler(), (False, qwen_edits.NO_EDITS_OUTCOME))
        self.assertEqual(victim.read_text(encoding="utf-8"), "keep")


if __name__ == "__main__":
    unittest.main()
