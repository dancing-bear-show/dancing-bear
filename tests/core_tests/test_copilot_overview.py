"""Tests for the Copilot ccr-overview-v2 review-body parser.

Each case pins a defect found on a real PR, not a hypothetical. The parser
exists because two classes of finding live only in the overview body, and the
earlier prose-only specification of it silently returned zero findings twice.
"""

from __future__ import annotations

import argparse
import unittest

from core.copilot_overview import (
    OVERVIEW_MARKER,
    is_copilot_overview,
    normalize_login,
    parse_overview,
    strip_zwsp,
)

ZWSP = "​"


def _linked(anchor: str, title: str, severity: str = "High") -> str:
    return (
        f'- <picture><img alt="{severity} severity"></picture> '
        f"[{title}](#discussion_r{anchor}) · New"
    )


def _body(*sections: str, claimed: int = 1) -> str:
    return "\n".join(
        [OVERVIEW_MARKER, "", "## Copilot review overview", "",
         f"**Findings:** {claimed} <picture></picture>", "", *sections]
    )


def _section(name: str, count: int, *lines: str) -> str:
    return "\n".join(
        ["<details open>",
         f"<summary><strong>{name} ({count})</strong></summary>",
         "", *lines, "</details>"]
    )


def _unlinked(title: str, path: str, line: int, severity: str = "Medium",
              text: str = "The finding body.") -> str:
    """An inline finding: no anchor, nested details, ZWSP-injected path."""
    zwsp_path = path.replace("/", f"/{ZWSP}")
    return "\n".join([
        "<details>",
        f'<summary><picture><img alt="{severity} severity"></picture> {title}</summary>',
        "",
        f"`{zwsp_path}:{line}`",
        "",
        text,
        "</details>",
    ])


def _review(body: str, *, review_id: int = 1, author: str = "copilot-pull-request-reviewer",
            author_kind: str = "bot", submitted_at: str = "2026-09-23T00:00:00Z") -> dict:
    return {
        "review_id": review_id, "author": author, "author_kind": author_kind,
        "state": "COMMENTED", "submitted_at": submitted_at, "body": body,
    }


def _thread(thread_id: str, *database_ids: int, resolved: bool = False) -> dict:
    return {
        "thread_id": thread_id,
        "is_resolved": resolved,
        "path": "src/foo.py",
        "line": 1,
        "comments": [{"database_id": d, "author": "bot", "body": ""} for d in database_ids],
    }


class TestAuthorGate(unittest.TestCase):
    """Only Copilot's own overview may steer triage."""

    def test_copilot_bot_body_is_accepted(self):
        self.assertTrue(is_copilot_overview(_review(_body())))

    def test_rest_bot_suffix_is_accepted(self):
        review = _review(_body(), author="copilot-pull-request-reviewer[bot]")
        self.assertTrue(is_copilot_overview(review))

    def test_human_body_with_marker_is_rejected(self):
        """A human pasting the marker must not become authoritative."""
        review = _review(_body(), author="some-person", author_kind="human")
        self.assertFalse(is_copilot_overview(review))

    def test_other_bot_with_marker_is_rejected(self):
        review = _review(_body(), author="github-actions", author_kind="bot")
        self.assertFalse(is_copilot_overview(review))

    def test_body_without_marker_is_rejected(self):
        self.assertFalse(is_copilot_overview(_review("LGTM")))

    def test_human_account_using_the_copilot_login_is_rejected(self):
        """Both halves of the gate are load-bearing, not just the login.

        A login check alone would accept this. author_kind comes from the API's
        own account type, which a user-controlled display name cannot forge.
        """
        review = _review(_body(), author="copilot-pull-request-reviewer",
                         author_kind="human")
        self.assertFalse(is_copilot_overview(review))

    def test_a_human_review_never_reaches_the_findings_map(self):
        """End-to-end: a forged body must not steer triage."""
        forged = _review(
            _body(_section("Open", 1, _linked("111", "Reopen this"))),
            author="attacker", author_kind="human",
        )
        out = parse_overview([forged], [_thread("PRRT_a", 111)])

        self.assertFalse(out["present"])
        self.assertEqual(out["findings"], {})

    def test_normalize_login_strips_only_bot_suffix(self):
        self.assertEqual(normalize_login("x[bot]"), "x")
        self.assertEqual(normalize_login("x"), "x")
        self.assertEqual(normalize_login(None), "")


class TestLinkedFindings(unittest.TestCase):
    def test_linked_finding_joins_to_its_thread(self):
        body = _body(_section("Open", 1, _linked("111", "Fix the thing")))
        out = parse_overview([_review(body)], [_thread("PRRT_a", 111)], pr_number="1")

        self.assertTrue(out["present"])
        self.assertEqual(out["findings"]["111"]["thread_id"], "PRRT_a")
        self.assertTrue(out["findings"]["111"]["resolvable"])
        self.assertEqual(out["findings"]["111"]["severity"], "High")
        self.assertEqual(out["cited_not_found"], [])

    def test_citation_to_a_reply_inside_a_thread_is_found(self):
        """An anchor may name a reply, not the opening comment."""
        body = _body(_section("Open", 1, _linked("222", "Nested")))
        out = parse_overview([_review(body)], [_thread("PRRT_a", 111, 222)])

        self.assertEqual(out["findings"]["222"]["thread_id"], "PRRT_a")
        self.assertEqual(out["cited_not_found"], [])

    def test_uncited_citation_is_reported(self):
        body = _body(_section("Open", 1, _linked("999", "Missing")))
        out = parse_overview([_review(body)], [_thread("PRRT_a", 111)])

        self.assertEqual(len(out["cited_not_found"]), 1)
        self.assertEqual(out["cited_not_found"][0]["database_id"], "999")
        self.assertFalse(out["findings"]["999"]["resolvable"])

    def test_nested_details_do_not_leak_across_sections(self):
        """A whole-body regex attributes findings to the wrong section."""
        body = _body(
            _section("Open", 1, _linked("111", "Still open")),
            _section("Resolved since last review", 1, _linked("222", "Done")),
        )
        out = parse_overview([_review(body)], [_thread("PRRT_a", 111), _thread("PRRT_b", 222)])

        self.assertEqual(out["findings"]["111"]["section"], "Open")
        self.assertEqual(out["findings"]["222"]["section"], "Resolved since last review")


class TestUnlinkedFindings(unittest.TestCase):
    """Findings with no anchor and no thread anywhere on the PR."""

    def test_unlinked_finding_is_parsed(self):
        body = _body(_section("Previously missed", 1,
                              _unlinked("Bad guard", "src/workflow/linter.py", 408)))
        out = parse_overview([_review(body)], [])

        key = "unlinked:src/workflow/linter.py:408"
        self.assertIn(key, out["findings"])
        entry = out["findings"][key]
        self.assertFalse(entry["linked"])
        self.assertFalse(entry["resolvable"])
        self.assertIsNone(entry["thread_id"])
        self.assertEqual(entry["severity"], "Medium")
        self.assertEqual(entry["title"], "Bad guard")
        self.assertTrue(entry["previously_missed"])

    def test_zero_width_spaces_are_stripped_from_paths(self):
        body = _body(_section("Previously missed", 1,
                              _unlinked("T", "a/b/c.py", 10)))
        out = parse_overview([_review(body)], [])

        path = out["findings"]["unlinked:a/b/c.py:10"]["path"]
        self.assertNotIn(ZWSP, path)
        self.assertEqual(path, "a/b/c.py")

    def test_unlinked_findings_are_not_reported_as_uncited(self):
        """They have no thread by construction; flagging them trains readers to ignore the field."""
        body = _body(_section("Previously missed", 1, _unlinked("T", "a.py", 1)))
        out = parse_overview([_review(body)], [])

        self.assertEqual(out["cited_not_found"], [])

    def test_strip_zwsp_helper(self):
        self.assertEqual(strip_zwsp(f"a{ZWSP}b"), "ab")


class TestFileIds(unittest.TestCase):
    def test_sanitised_ids_that_would_collide_stay_distinct(self):
        """`a/b.py` and `a-b.py` sanitise identically; the hash separates them."""
        body = _body(_section("Previously missed", 2,
                              _unlinked("One", "a/b.py", 10),
                              _unlinked("Two", "a-b.py", 10)))
        out = parse_overview([_review(body)], [])

        file_ids = [v["file_id"] for v in out["findings"].values()]
        self.assertEqual(len(file_ids), 2)
        self.assertEqual(len(set(file_ids)), 2, "file_ids must not collide")

    def test_file_id_is_filename_safe(self):
        body = _body(_section("Open", 1, _unlinked("T", "a/b.py", 3)))
        out = parse_overview([_review(body)], [])

        for value in out["findings"].values():
            self.assertNotIn("/", value["file_id"])
            self.assertNotIn(":", value["file_id"])


class TestFold(unittest.TestCase):
    def test_newest_review_wins_the_section(self):
        older = _review(_body(_section("Open", 1, _linked("111", "X"))),
                        review_id=1, submitted_at="2026-09-22T22:17:00Z")
        newer = _review(_body(_section("Resolved since last review", 1, _linked("111", "X"))),
                        review_id=2, submitted_at="2026-09-22T22:32:00Z")
        out = parse_overview([older, newer], [_thread("PRRT_a", 111)])

        self.assertEqual(out["findings"]["111"]["section"], "Resolved since last review")
        self.assertEqual(
            sorted(out["findings"]["111"]["sections"]),
            ["Open", "Resolved since last review"],
        )

    def test_identical_timestamps_break_on_review_id(self):
        same = "2026-09-22T22:17:00Z"
        a = _review(_body(_section("Open", 1, _linked("111", "X"))),
                    review_id=1, submitted_at=same)
        b = _review(_body(_section("Resolved since last review", 1, _linked("111", "X"))),
                    review_id=2, submitted_at=same)
        out = parse_overview([b, a], [_thread("PRRT_a", 111)])

        self.assertEqual(out["findings"]["111"]["section"], "Resolved since last review")

    def test_previously_missed_survives_later_resolution(self):
        older = _review(_body(_section("Previously missed", 1, _linked("111", "X"))),
                        review_id=1, submitted_at="2026-09-22T22:00:00Z")
        newer = _review(_body(_section("Resolved since last review", 1, _linked("111", "X"))),
                        review_id=2, submitted_at="2026-09-22T23:00:00Z")
        out = parse_overview([older, newer], [_thread("PRRT_a", 111)])

        self.assertTrue(out["findings"]["111"]["previously_missed"])
        self.assertIn("111", out["previously_missed"])

    def test_source_timestamp_is_per_finding_not_global(self):
        """A later review that omits a finding must not restamp it."""
        older = _review(_body(_section("Open", 1, _linked("111", "X"))),
                        review_id=1, submitted_at="2026-09-22T22:00:00Z")
        newer = _review(_body(_section("Open", 1, _linked("222", "Y"))),
                        review_id=2, submitted_at="2026-09-22T23:00:00Z")
        out = parse_overview([older, newer], [_thread("A", 111), _thread("B", 222)])

        self.assertEqual(out["findings"]["111"]["source_submitted_at"], "2026-09-22T22:00:00Z")
        self.assertEqual(out["findings"]["222"]["source_submitted_at"], "2026-09-22T23:00:00Z")
        self.assertEqual(out["newest"]["review_id"], 2)

    def test_line_drift_does_not_split_one_unlinked_finding(self):
        """A fix round moves the cited line; the history must stay together."""
        older = _review(
            _body(_section("Previously missed", 1, _unlinked("Same title", "a.py", 100))),
            review_id=1, submitted_at="2026-09-22T22:00:00Z")
        newer = _review(
            _body(_section("Open", 1, _unlinked("Same title", "a.py", 140))),
            review_id=2, submitted_at="2026-09-22T23:00:00Z")
        out = parse_overview([older, newer], [])

        unlinked = [v for v in out["findings"].values() if not v["linked"]]
        self.assertEqual(len(unlinked), 1, "line drift must not create a second entry")
        self.assertTrue(unlinked[0]["previously_missed"])
        self.assertEqual(unlinked[0]["line"], 140)


class TestShortfall(unittest.TestCase):
    """The only tripwire for a shape change in Copilot's HTML."""

    def test_matching_count_is_ok(self):
        body = _body(_section("Open", 1, _linked("111", "X")), claimed=1)
        out = parse_overview([_review(body)], [_thread("A", 111)])

        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["parse_shortfall"], 0)

    def test_parsing_fewer_than_claimed_flags_partial(self):
        body = _body(_section("Open", 1, _linked("111", "X")), claimed=4)
        out = parse_overview([_review(body)], [_thread("A", 111)])

        self.assertEqual(out["parse_shortfall"], 3)
        self.assertEqual(out["status"], "partial")

    def test_zero_parsed_against_a_claim_is_partial(self):
        """A shape change returns nothing; that must not read as a clean PR."""
        body = "\n".join([OVERVIEW_MARKER, "**Findings:** 4 <picture></picture>",
                          "<totally-new-markup/>"])
        out = parse_overview([_review(body)], [])

        self.assertTrue(out["present"])
        self.assertEqual(out["findings"], {})
        self.assertEqual(out["parse_shortfall"], 4)
        self.assertEqual(out["status"], "partial")


class TestAbsentOverview(unittest.TestCase):
    def test_human_only_pr_reports_absent_not_failed(self):
        out = parse_overview([_review("LGTM", author="p", author_kind="human")], [])

        self.assertFalse(out["present"])
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["findings"], {})
        self.assertEqual(out["previously_missed"], [])
        self.assertEqual(out["cited_not_found"], [])

    def test_no_reviews_at_all(self):
        out = parse_overview([], [])
        self.assertFalse(out["present"])


class TestStaleFetchGuard(unittest.TestCase):
    """A threads.json with no review_bodies key cannot answer the question.

    Its parse would return present:false — identical to a PR that genuinely
    has no Copilot overview — so the CLI refuses rather than reporting a
    clean result from a file that was never asked to carry review bodies.
    """

    def _run(self, payload: dict) -> tuple[int, str]:
        import json
        import tempfile
        from pathlib import Path

        from core.cli_errors import CLIError
        from workflow.cli_dispatch import _cmd_parse_overview

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "threads.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            args = argparse.Namespace(
                threads_json=str(path), pr_number="1",
                out_path=str(Path(tmp) / "out.json"),
            )
            try:
                return _cmd_parse_overview(args), ""
            except CLIError as exc:
                return int(exc.code), str(exc)

    def test_missing_review_bodies_key_is_refused(self):
        code, message = self._run({"pr_number": "1", "threads": []})

        self.assertNotEqual(code, 0)
        self.assertIn("review_bodies", message)

    def test_empty_review_bodies_list_is_accepted(self):
        """A human-only PR is the common case, not a failure."""
        code, _ = self._run({"pr_number": "1", "threads": [], "review_bodies": []})

        self.assertEqual(code, 0)


class TestThreadsNotCited(unittest.TestCase):
    def test_human_thread_is_listed_as_uncited(self):
        body = _body(_section("Open", 1, _linked("111", "X")))
        out = parse_overview([_review(body)], [_thread("A", 111), _thread("B", 222)])

        self.assertEqual(out["threads_not_cited"], ["B"])


if __name__ == "__main__":
    unittest.main()
