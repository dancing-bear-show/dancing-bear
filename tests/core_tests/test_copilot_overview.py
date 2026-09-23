"""Tests for the Copilot ccr-overview-v2 review-body parser.

Each case pins a defect found on a real PR, not a hypothetical. The parser
exists because two classes of finding live only in the overview body, and the
earlier prose-only specification of it silently returned zero findings twice.
"""

from __future__ import annotations

import argparse
import unittest

from core.copilot_overview import (
    ESCAPES_REPO,
    OVERVIEW_MARKER,
    PROTECTED_PATH,
    classify_repo_path,
    is_copilot_overview,
    parse_overview,
    safe_repo_path,
    strip_zwsp,
)
from core.github.authors import normalize_login

ZWSP = "​"
_ICONS = "https://github.githubassets.com/static/images/icons/copilot-code-review"


def _badge(severity: str) -> str:
    """The severity badge exactly as GitHub renders it in a real overview.

    Two <source> children and a fully-attributed <img>, not a bare
    `<img alt=...>`: the fixtures must be no cleaner than real input, or the
    suite pins an assumption instead of the behaviour.
    """
    level = severity.lower()
    return (
        f'<picture><source media="(prefers-color-scheme: dark)" '
        f'srcset="{_ICONS}/{level}-v2-dark.svg">'
        f'<source media="(prefers-color-scheme: light)" '
        f'srcset="{_ICONS}/{level}-v2-light.svg">'
        f'<img src="{_ICONS}/{level}-v2-light.png" alt="{severity} severity" '
        f'width="62" height="18" align="texttop"></picture>'
    )


def _linked(anchor: str, title: str, severity: str = "High") -> str:
    return f"- {_badge(severity)} [{title}](#discussion_r{anchor}) · New"


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
        f"<summary>{_badge(severity)} {title}</summary>",
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

    def test_author_kind_is_matched_exactly(self):
        """The fetch fragment writes lowercase "bot"; nothing else passes."""
        for kind in ("Bot", "BOT", " bot", "bot "):
            with self.subTest(kind=kind):
                self.assertFalse(is_copilot_overview(_review(_body(), author_kind=kind)))

    def test_bot_suffix_is_stripped_only_in_its_exact_form(self):
        """GitHub spells it `[bot]`; a case variant is a different login."""
        for login in ("copilot-pull-request-reviewer[Bot]",
                      "copilot-pull-request-reviewer[BOT]",
                      "Copilot-Pull-Request-Reviewer"):
            with self.subTest(login=login):
                self.assertFalse(is_copilot_overview(_review(_body(), author=login)))
        self.assertEqual(normalize_login("x[Bot]"), "x[Bot]")

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
        from workflow.cli_dispatch_review import _cmd_parse_overview

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

    def test_null_thread_ids_do_not_crash_the_sort(self):
        """threads.json carries review bodies and issue comments with no id.

        The fetch fragment documents `thread_id: null` for those, and sorting
        None against a str raises TypeError — a guaranteed crash on any real
        payload that has one alongside an uncited thread.
        """
        body = _body(_section("Open", 1, _linked("111", "X")))
        threads = [
            _thread("PRRT_a", 111),
            _thread("PRRT_b", 222),          # real thread, uncited
            {"thread_id": None, "comments": [{"database_id": 333}]},
        ]

        out = parse_overview([_review(body)], threads)

        self.assertEqual(out["threads_not_cited"], ["PRRT_b"])
        self.assertNotIn(None, out["threads_not_cited"])


class TestSectionMatching(unittest.TestCase):
    def test_dismissed_section_is_not_previously_missed(self):
        """"Dismissed" contains "missed" but inverts the meaning."""
        body = _body(_section("Dismissed", 1, _linked("111", "X")))
        out = parse_overview([_review(body)], [_thread("A", 111)])

        self.assertFalse(out["findings"]["111"]["previously_missed"])
        self.assertEqual(out["previously_missed"], [])

    def test_previously_missed_still_matches(self):
        body = _body(_section("Previously missed", 1, _linked("111", "X")))
        out = parse_overview([_review(body)], [_thread("A", 111)])

        self.assertTrue(out["findings"]["111"]["previously_missed"])


class TestClaimedCount(unittest.TestCase):
    """The headline count is a per-severity breakdown, matched to Open."""

    def _multi_severity_body(self, sections: str) -> str:
        return "\n".join([
            OVERVIEW_MARKER, "",
            "**Findings:** 2 <picture>H</picture> · 1 <picture>M</picture>",
            "", sections,
        ])

    def test_every_severity_count_is_summed(self):
        body = self._multi_severity_body(_section(
            "Open", 3,
            _linked("111", "A"), _linked("222", "B"), _linked("333", "C"),
        ))
        threads = [_thread(f"T{i}", d) for i, d in enumerate((111, 222, 333))]

        out = parse_overview([_review(body)], threads)

        self.assertEqual(out["newest"]["findings_claimed"], 3)
        self.assertEqual(out["parse_shortfall"], 0)
        self.assertEqual(out["status"], "ok")

    def test_shortfall_counts_open_findings_only(self):
        """Resolved entries must not mask a missing open one."""
        body = "\n".join([
            OVERVIEW_MARKER, "", "**Findings:** 3 <picture>H</picture>", "",
            _section("Open", 3, _linked("111", "A")),
            _section("Resolved since last review", 2,
                     _linked("222", "B"), _linked("333", "C")),
        ])
        threads = [_thread(f"T{i}", d) for i, d in enumerate((111, 222, 333))]

        out = parse_overview([_review(body)], threads)

        # Three parsed overall, but only one of them is Open against a claim
        # of three — counting all sections would have reported status "ok".
        self.assertEqual(out["parse_shortfall"], 2)
        self.assertEqual(out["status"], "partial")


class TestNewestBlock(unittest.TestCase):
    """The fragment documents these fields, so the parser must emit them."""

    def _verdict_body(self, verdict: str) -> str:
        return "\n".join([
            OVERVIEW_MARKER, "", "## Copilot review overview", "",
            f"### {verdict}", "",
            "**Findings:** 1 <picture></picture>", "",
            _section("Open", 1, _linked("111", "X")),
            _section("Resolved since last review", 2, _linked("222", "Y")),
        ])

    def test_verdict_is_extracted_without_the_status_emoji(self):
        out = parse_overview(
            [_review(self._verdict_body("🟡 Changes recommended"))],
            [_thread("A", 111), _thread("B", 222)],
        )

        self.assertEqual(out["newest"]["verdict"], "Changes recommended")

    def test_verdict_without_an_emoji_is_unchanged(self):
        out = parse_overview(
            [_review(self._verdict_body("Looks good"))],
            [_thread("A", 111), _thread("B", 222)],
        )

        self.assertEqual(out["newest"]["verdict"], "Looks good")

    def test_section_counts_come_from_the_overview_not_the_parse(self):
        """These are what the overview CLAIMS each section holds."""
        out = parse_overview(
            [_review(self._verdict_body("🟢 Approved"))],
            [_thread("A", 111), _thread("B", 222)],
        )

        self.assertEqual(
            out["newest"]["sections"],
            {"Open": 1, "Resolved since last review": 2},
        )


class TestDriftMerge(unittest.TestCase):
    def test_newer_body_wins_when_lines_drift(self):
        """The merged finding is the one triage and the fixer act on."""
        older = _review(
            _body(_section("Previously missed", 1,
                           _unlinked("Same", "a.py", 100, text="OLD BODY"))),
            review_id=1, submitted_at="2026-09-22T22:00:00Z")
        newer = _review(
            _body(_section("Open", 1,
                           _unlinked("Same", "a.py", 140, text="NEW BODY"))),
            review_id=2, submitted_at="2026-09-22T23:00:00Z")

        out = parse_overview([older, newer], [])

        entry = next(v for v in out["findings"].values() if not v["linked"])
        self.assertEqual(entry["line"], 140)
        self.assertIn("NEW BODY", entry["body"])
        self.assertNotIn("OLD BODY", entry["body"])
        self.assertTrue(entry["previously_missed"])

    def test_titleless_findings_in_one_file_are_not_merged(self):
        """(path, "") is no identity: two unrelated findings would collapse."""
        titleless = (
            "<details>\n"
            f"<summary>{_badge('Medium')}</summary>\n"
            "\n`src/foo.py:{line}`\n\n{text}\n</details>"
        )
        older = _review(
            _body(_section("Previously missed", 1,
                           titleless.format(line=10, text="Issue about A"))),
            review_id=1, submitted_at="2026-09-22T22:00:00Z")
        newer = _review(
            _body(_section("Previously missed", 1,
                           titleless.format(line=20, text="Issue about B"))),
            review_id=2, submitted_at="2026-09-22T23:00:00Z")

        out = parse_overview([older, newer], [])

        bodies = sorted(v["body"] for v in out["findings"].values())
        self.assertEqual(bodies, ["Issue about A", "Issue about B"])

    def test_same_title_findings_from_one_review_are_not_merged(self):
        """Drift is cross-review; side-by-side findings are distinct."""
        review = _review(_body(_section(
            "Previously missed", 2,
            _unlinked("Same", "a.py", 10, text="first"),
            _unlinked("Same", "a.py", 30, text="second"),
        )))

        out = parse_overview([review], [])

        self.assertEqual(len(out["findings"]), 2)


class TestPathSafety(unittest.TestCase):
    """Unlinked paths come from review-body HTML and reach an editing agent."""

    def test_repo_relative_paths_are_accepted(self):
        for raw, expected in (
            ("src/foo.py", "src/foo.py"),
            ("./src/foo.py", "src/foo.py"),
            ("src//foo.py", "src/foo.py"),
            (f"src/{ZWSP}foo.py", "src/foo.py"),
            ("docs/.github-notes.md", "docs/.github-notes.md"),
            ("src/claude/x.py", "src/claude/x.py"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(safe_repo_path(raw), expected)

    def test_escaping_paths_are_rejected(self):
        for raw in (
            "../../../.github/workflows/ci.yml",
            "src/../../etc/passwd",
            "/etc/passwd",
            "~/.ssh/id_rsa",
            "C:/Windows/win.ini",
            "src\\..\\secret",
            "..",
            ".",
            "",
            "src/foo\x00.py",
        ):
            with self.subTest(raw=raw):
                self.assertIsNone(safe_repo_path(raw))

    def test_traversal_path_is_reported_but_never_dispatchable(self):
        review = _review(_body(_section(
            "Previously missed", 1,
            _unlinked("Crafted", "../../../.github/workflows/ci.yml", 1),
        )))

        out = parse_overview([review], [])

        (entry,) = out["findings"].values()
        self.assertIsNone(entry["path"])
        self.assertEqual(entry["path_rejected"], "../../../.github/workflows/ci.yml")
        self.assertFalse(entry["resolvable"])
        self.assertEqual(entry["title"], "Crafted")

    def test_cited_path_is_normalised_into_path_and_id(self):
        """`./src//foo.py` and `src/foo.py` are one file and must be one id,
        or a single finding splits in two across reviews."""
        review = _review(_body(_section(
            "Previously missed", 1, _unlinked("Fine", "./src//foo.py", 3))))

        out = parse_overview([review], [])

        self.assertEqual(list(out["findings"]), ["unlinked:src/foo.py:3"])
        self.assertEqual(out["findings"]["unlinked:src/foo.py:3"]["path"], "src/foo.py")

    def test_safe_path_leaves_path_rejected_null(self):
        review = _review(_body(_section(
            "Previously missed", 1, _unlinked("Fine", "src/foo.py", 3))))

        (entry,) = parse_overview([review], [])["findings"].values()

        self.assertEqual(entry["path"], "src/foo.py")
        self.assertIsNone(entry["path_rejected"])


class TestProtectedPaths(unittest.TestCase):
    """In-repo infrastructure a fixer must never edit — its edits are pushed
    before verification runs."""

    def test_protected_paths_are_classified(self):
        for raw, normalised in (
            (".git/hooks/pre-commit", ".git/hooks/pre-commit"),
            (".git/config", ".git/config"),
            (".GIT/hooks/pre-commit", ".GIT/hooks/pre-commit"),
            ("vendor/lib/.git/config", "vendor/lib/.git/config"),
            (".github/workflows/ci.yml", ".github/workflows/ci.yml"),
            (".claude/settings.json", ".claude/settings.json"),
            (".Claude/hooks/x.sh", ".Claude/hooks/x.sh"),
            (".envrc", ".envrc"),
            ("sub/dir/.envrc", "sub/dir/.envrc"),
            ("./.git/config", ".git/config"),
        ):
            with self.subTest(raw=raw):
                self.assertEqual(classify_repo_path(raw), (normalised, PROTECTED_PATH))
                self.assertIsNone(safe_repo_path(raw))

    def test_escaping_paths_are_classified_apart_from_protected_ones(self):
        self.assertEqual(classify_repo_path("../x"), (None, ESCAPES_REPO))
        self.assertEqual(classify_repo_path("/etc/passwd"), (None, ESCAPES_REPO))

    def test_lookalike_names_are_not_protected(self):
        """Only whole segments match: `.github` at the top, not `.github-x`."""
        for raw in ("docs/.github-notes.md", "src/git/x.py", "notes/.envrc.md",
                    "src/.claude_helper.py"):
            with self.subTest(raw=raw):
                self.assertEqual(classify_repo_path(raw), (raw, None))

    def test_protected_finding_is_reported_with_a_stable_id(self):
        review = _review(_body(_section(
            "Previously missed", 1,
            _unlinked("Hook edge case", ".claude/hooks/guard.sh", 12),
        )))

        out = parse_overview([review], [])

        entry = out["findings"]["unlinked:.claude/hooks/guard.sh:12"]
        self.assertIsNone(entry["path"])
        self.assertEqual(entry["path_rejected"], ".claude/hooks/guard.sh")
        self.assertEqual(entry["path_rejected_reason"], PROTECTED_PATH)
        self.assertEqual(entry["line"], 12)

    def test_escaping_finding_records_its_reason(self):
        review = _review(_body(_section(
            "Previously missed", 1, _unlinked("Bad", "../../x.py", 1))))

        (entry,) = parse_overview([review], [])["findings"].values()

        self.assertEqual(entry["path_rejected_reason"], ESCAPES_REPO)


class TestCrossReviewIdentity(unittest.TestCase):
    """path:line is a location, not an identity."""

    def test_new_finding_on_an_old_line_does_not_take_over(self):
        """A fix frees a line; the next finding lands there. The newcomer must
        neither erase the old finding nor inherit its history."""
        older = _review(
            _body(_section("Previously missed", 1,
                           _unlinked("Missing null check", "src/a.py", 10, text="old"))),
            review_id=1, submitted_at="2026-09-22T22:00:00Z")
        newer = _review(
            _body(_section("Open", 1,
                           _unlinked("SQL injection risk", "src/a.py", 10, text="new"))),
            review_id=2, submitted_at="2026-09-22T23:00:00Z")

        out = parse_overview([older, newer], [])

        old = out["findings"]["unlinked:src/a.py:10"]
        new = out["findings"]["unlinked:src/a.py:10#2"]
        self.assertEqual(old["title"], "Missing null check")
        self.assertTrue(old["previously_missed"])
        self.assertEqual(new["title"], "SQL injection risk")
        self.assertEqual(new["sections"], ["Open"])
        self.assertFalse(new["previously_missed"])
        self.assertEqual(out["previously_missed"], ["unlinked:src/a.py:10"])

    def test_ids_do_not_depend_on_listing_order(self):
        def review(order, review_id, stamp):
            blocks = {"A": _unlinked("Alpha", "src/a.py", 10, text="alpha"),
                      "B": _unlinked("Beta", "src/a.py", 10, text="beta")}
            return _review(_body(_section("Previously missed", 2,
                                          *(blocks[k] for k in order))),
                           review_id=review_id, submitted_at=stamp)

        out = parse_overview([review("AB", 1, "2026-09-22T22:00:00Z"),
                              review("BA", 2, "2026-09-22T23:00:00Z")], [])

        titles = {k: v["title"] for k, v in out["findings"].items()}
        self.assertEqual(titles, {"unlinked:src/a.py:10": "Alpha",
                                  "unlinked:src/a.py:10#2": "Beta"})
        self.assertEqual(out["findings"]["unlinked:src/a.py:10"]["body"], "alpha")


class TestDegradedOverview(unittest.TestCase):
    """The shape Copilot posts when its full suite fails, as seen on PR #400."""

    def _degraded(self) -> str:
        return "\n".join([
            "> [!NOTE]",
            "> Copilot was unable to run its full agentic suite in this review.",
            "",
            OVERVIEW_MARKER,
            "",
            "## Copilot review overview",
            "",
            "**Review effort:** Lite  ",
            f"**Findings:** 2 {_badge('High')} · 1 {_badge('Medium')}",
            "",
            _section("Open", 3,
                     _linked("111", "A", "High"),
                     _linked("222", "B", "High"),
                     _linked("333", "C", "Medium")),
        ])

    def test_note_before_marker_and_no_verdict_still_parses(self):
        threads = [_thread(f"T{i}", d) for i, d in enumerate((111, 222, 333))]

        out = parse_overview([_review(self._degraded())], threads)

        self.assertTrue(out["present"])
        self.assertIsNone(out["newest"]["verdict"])
        self.assertEqual(out["newest"]["findings_claimed"], 3)
        self.assertEqual(out["newest"]["sections"], {"Open": 3})
        self.assertEqual(out["status"], "ok")
        self.assertEqual(len(out["findings"]), 3)


class TestCheckPathsCli(unittest.TestCase):
    """The backstop commit-and-push runs before staging anything."""

    def _run(self, *paths):
        import contextlib
        import io

        from workflow.cli_dispatch_review import _cmd_check_paths

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = _cmd_check_paths(argparse.Namespace(paths=list(paths)))
        return code, out.getvalue()

    def test_safe_paths_pass(self):
        code, printed = self._run("src/core/x.py", "tests/core_tests/test_x.py")

        self.assertEqual(code, 0)
        self.assertEqual(printed, "")

    def test_any_refused_path_fails_the_whole_check(self):
        code, printed = self._run("src/ok.py", ".git/hooks/pre-commit", "../escape.py")

        self.assertNotEqual(code, 0)
        self.assertIn("REFUSED protected-path: .git/hooks/pre-commit", printed)
        self.assertIn("REFUSED escapes-repo: ../escape.py", printed)
        self.assertNotIn("src/ok.py", printed)


class TestSameLineFindings(unittest.TestCase):
    def test_two_findings_on_one_line_both_survive(self):
        """The second must not overwrite the first — status stays ok, so
        nothing else would ever reveal the loss."""
        review = _review(_body(_section(
            "Previously missed", 2,
            _unlinked("Missing docstring", "src/foo.py", 10, text="first issue"),
            _unlinked("Missing docstring", "src/foo.py", 10, text="second issue"),
        )))

        out = parse_overview([review], [])

        self.assertEqual(
            sorted(out["findings"]),
            ["unlinked:src/foo.py:10", "unlinked:src/foo.py:10#2"],
        )
        bodies = sorted(v["body"] for v in out["findings"].values())
        self.assertEqual(bodies, ["first issue", "second issue"])
        file_ids = {v["file_id"] for v in out["findings"].values()}
        self.assertEqual(len(file_ids), 2)

    def test_ids_are_stable_when_a_later_review_repeats_the_pair(self):
        pair = _section(
            "Previously missed", 2,
            _unlinked("Missing docstring", "src/foo.py", 10, text="first issue"),
            _unlinked("Missing docstring", "src/foo.py", 10, text="second issue"),
        )
        older = _review(_body(pair), review_id=1, submitted_at="2026-09-22T22:00:00Z")
        newer = _review(_body(pair), review_id=2, submitted_at="2026-09-22T23:00:00Z")

        out = parse_overview([older, newer], [])

        self.assertEqual(len(out["findings"]), 2)


class TestBracketTitles(unittest.TestCase):
    def test_title_containing_brackets_is_parsed(self):
        """`list[str]` in a title must not end the capture at the first `]`."""
        body = _body(_section(
            "Open", 2,
            _linked("444", "Handle `list[str]` return type"),
            _linked("445", "Plain title"),
        ), claimed=2)

        out = parse_overview([_review(body)], [_thread("A", 444), _thread("B", 445)])

        self.assertEqual(out["findings"]["444"]["title"], "Handle `list[str]` return type")
        self.assertEqual(out["findings"]["444"]["thread_id"], "A")
        self.assertEqual(out["parse_shortfall"], 0)
        self.assertEqual(out["status"], "ok")


class TestNullThreadCitation(unittest.TestCase):
    def test_citation_landing_on_a_null_thread_entry_is_not_resolvable(self):
        """Review bodies and issue comments carry thread_id: null.

        A citation matching a comment inside one of those has no thread to
        reply to or resolve. Indexing it anyway yields thread_id "None" and
        resolvable: true — a resolve stage would then act on nothing.
        """
        body = _body(_section("Open", 1, _linked("111", "X")))
        threads = [{"thread_id": None, "comments": [{"database_id": 111}]}]

        out = parse_overview([_review(body)], threads)

        entry = out["findings"]["111"]
        self.assertIsNone(entry["thread_id"])
        self.assertFalse(entry["resolvable"])
        self.assertEqual([c["database_id"] for c in out["cited_not_found"]], ["111"])


class TestParseOverviewCli(unittest.TestCase):
    """The CLI handler: every shape it refuses, and both output modes."""

    def _run(self, payload, *, out: bool = True, pr_number: str = "1"):
        import contextlib
        import io
        import json
        import tempfile
        from pathlib import Path

        from core.cli_errors import CLIError
        from workflow.cli_dispatch_review import _cmd_parse_overview

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "threads.json"
            path.write_text(
                payload if isinstance(payload, str) else json.dumps(payload),
                encoding="utf-8",
            )
            out_path = Path(tmp) / "nested" / "out.json"
            args = argparse.Namespace(
                threads_json=str(path), pr_number=pr_number,
                out_path=str(out_path) if out else "",
            )
            stdout = io.StringIO()
            try:
                with contextlib.redirect_stdout(stdout):
                    code = _cmd_parse_overview(args)
            except CLIError as exc:
                return int(exc.code), str(exc), None
            written = json.loads(out_path.read_text()) if out else json.loads(stdout.getvalue())
            return code, "", written

    def test_refused_shapes(self):
        cases = {
            "not json": "{nope",
            "top level list": [],
            "review_bodies not a list": {"threads": [], "review_bodies": "x"},
            "threads not a list": {"threads": {}, "review_bodies": []},
            "review_bodies element not an object": {"threads": [], "review_bodies": ["x"]},
            "threads element not an object": {"threads": [None], "review_bodies": []},
            "threads key missing": {"review_bodies": []},
        }
        for label, payload in cases.items():
            with self.subTest(label):
                code, message, _ = self._run(payload)
                self.assertNotEqual(code, 0)
                self.assertTrue(message)

    def test_missing_file_is_refused(self):
        from core.cli_errors import CLIError
        from workflow.cli_dispatch_review import _cmd_parse_overview

        args = argparse.Namespace(threads_json="/nonexistent/threads.json",
                                  pr_number="1", out_path="")
        with self.assertRaises(CLIError):
            _cmd_parse_overview(args)

    def test_out_file_is_written_with_the_parse(self):
        body = _body(_section("Open", 1, _linked("111", "X")))
        payload = {"threads": [_thread("A", 111)], "review_bodies": [_review(body)]}

        code, _, written = self._run(payload)

        self.assertEqual(code, 0)
        self.assertEqual(written["findings"]["111"]["thread_id"], "A")

    def test_stdout_mode_prints_the_parse(self):
        payload = {"threads": [], "review_bodies": []}

        code, _, written = self._run(payload, out=False)

        self.assertEqual(code, 0)
        self.assertFalse(written["present"])

    def test_pr_number_falls_back_to_the_file(self):
        payload = {"pr_number": 395, "threads": [], "review_bodies": []}

        _, _, written = self._run(payload, pr_number="")

        self.assertEqual(written["pr_number"], "395")


class TestRealPayload(unittest.TestCase):
    """Pin the parse of a real captured PR, not only synthetic fixtures.

    data/copilot_overview_pr395.json is PR #395's seven Copilot overview
    bodies verbatim, trimmed to the fields the parser reads. It holds two real
    "Previously missed" findings that have no review thread anywhere on the PR
    — the case this parser exists for.
    """

    def test_pr395_parses_to_its_known_counts(self):
        import json
        from pathlib import Path

        data = json.loads(
            (Path(__file__).parent / "data" / "copilot_overview_pr395.json")
            .read_text(encoding="utf-8")
        )

        out = parse_overview(data["review_bodies"], data["threads"], pr_number="395")

        findings = out["findings"]
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["newest"]["findings_claimed"], 4)
        self.assertEqual(len(findings), 21)
        self.assertEqual(sum(f["linked"] for f in findings.values()), 19)
        self.assertEqual(out["cited_not_found"], [])
        self.assertEqual(out["threads_not_cited"], [])
        self.assertEqual(out["previously_missed"], [
            "unlinked:.claude/hooks/block-readonly-role-writes.sh:357",
            "unlinked:src/workflow/linter.py:408",
        ])
        # A real finding in an ordinary source file: dispatchable.
        linter = findings["unlinked:src/workflow/linter.py:408"]
        self.assertEqual(linter["path"], "src/workflow/linter.py")
        self.assertIsNone(linter["path_rejected"])
        self.assertEqual(linter["severity"], "Medium")
        self.assertEqual(linter["section"], "Previously missed")

        # A real finding about a hook script: genuine, but protected, so its
        # location is reported and never handed to a fixer.
        hooks = findings["unlinked:.claude/hooks/block-readonly-role-writes.sh:357"]
        self.assertIsNone(hooks["path"])
        self.assertEqual(hooks["path_rejected"], ".claude/hooks/block-readonly-role-writes.sh")
        self.assertEqual(hooks["path_rejected_reason"], "protected-path")
        self.assertNotIn(ZWSP, hooks["path_rejected"])
        self.assertEqual(hooks["line"], 357)

        # Spot-check linked findings against the real shape, not only counts:
        # a severity or section regression must fail here, on real markup.
        first = findings["4077827266"]
        self.assertEqual(
            (first["severity"], first["section"], first["thread_id"]),
            ("High", "Open", "PRRT_kwDOQr1kjM6k9-X0"),
        )
        self.assertEqual(
            sorted({f["severity"] for f in findings.values()}),
            ["High", "Low", "Medium"],
        )
        self.assertEqual(out["newest"]["verdict"], "Changes recommended")
        self.assertEqual(
            out["newest"]["sections"], {"Open": 4, "Resolved since last review": 2},
        )


if __name__ == "__main__":
    unittest.main()
