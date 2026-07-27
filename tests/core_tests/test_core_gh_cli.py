"""Tests for the GhCLI wrapper (core/gh_cli.py).

Tests cover:
- GhCLI initialization
- ensure_available() method
- auth_status() method
- api() method with params and error handling
- search_prs() method
- api_with_headers() method with header parsing
- graphql() method with temp file handling
- pr_view() method
- pr_list() method
"""
from __future__ import annotations

import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from core.gh_cli import GhCLI


def _proc(returncode: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    """Minimal stand-in for a completed subprocess result."""
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


class TestGhCLIInit(unittest.TestCase):
    """Test GhCLI initialization."""

    def test_init_default_run_func(self):
        """Test that default run function is subprocess.run."""
        cli = GhCLI()
        self.assertIs(cli._run, subprocess.run)

    def test_init_custom_run_func(self):
        """Test that custom run function is used."""
        mock_run = MagicMock()
        cli = GhCLI(run_func=mock_run)
        self.assertEqual(cli._run, mock_run)


class TestGhCLIEnsureAvailable(unittest.TestCase):
    """Test ensure_available() method."""

    @patch('shutil.which')
    def test_ensure_available_gh_found(self, mock_which):
        """Test when gh is available in PATH."""
        mock_which.return_value = "/usr/local/bin/gh"
        cli = GhCLI()
        # Should not raise
        cli.ensure_available()
        mock_which.assert_called_once_with("gh")

    @patch('shutil.which')
    def test_ensure_available_gh_not_found(self, mock_which):
        """Test when gh is not available in PATH."""
        mock_which.return_value = None
        cli = GhCLI()
        with self.assertRaises(SystemExit) as ctx:
            cli.ensure_available()
        self.assertIn("gh CLI not found", str(ctx.exception))


class TestGhCLIAuthStatus(unittest.TestCase):
    """Test auth_status() method."""

    def test_auth_status_success(self):
        """Test auth_status when authenticated."""
        mock_run = MagicMock(return_value=_proc(
            returncode=0,
            stdout="Logged in to github.com as testuser"
        ))
        cli = GhCLI(run_func=mock_run)

        ok, output = cli.auth_status()

        self.assertTrue(ok)
        self.assertIn("Logged in", output)
        mock_run.assert_called_once_with(
            ["gh", "auth", "status"],
            text=True,
            capture_output=True
        )

    def test_auth_status_failure(self):
        """Test auth_status when not authenticated."""
        mock_run = MagicMock(return_value=_proc(
            returncode=1,
            stderr="Not logged in"
        ))
        cli = GhCLI(run_func=mock_run)

        ok, output = cli.auth_status()

        self.assertFalse(ok)
        self.assertIn("Not logged in", output)


class TestGhCLIApi(unittest.TestCase):
    """Test api() method."""

    def test_api_success(self):
        """Test successful API call."""
        mock_run = MagicMock(return_value=_proc(
            returncode=0,
            stdout='{"login": "testuser", "id": 123}'
        ))
        cli = GhCLI(run_func=mock_run)

        result = cli.api("user")

        self.assertEqual(result["login"], "testuser")
        mock_run.assert_called_once_with(
            ["gh", "api", "user"],
            text=True,
            capture_output=True
        )

    def test_api_with_params(self):
        """Test API call with query parameters."""
        mock_run = MagicMock(return_value=_proc(
            returncode=0,
            stdout='[]'
        ))
        cli = GhCLI(run_func=mock_run)

        result = cli.api("/repos/owner/repo/pulls", params={"state": "all", "per_page": 100})

        self.assertEqual(result, [])
        call_args = mock_run.call_args[0][0]
        self.assertIn("-F", call_args)
        self.assertIn("state=all", call_args)
        self.assertIn("per_page=100", call_args)

    def test_api_failure_raises_runtime_error(self):
        """Test that API failure raises RuntimeError."""
        mock_run = MagicMock(return_value=_proc(
            returncode=1,
            stderr="Not Found"
        ))
        cli = GhCLI(run_func=mock_run)

        with self.assertRaises(RuntimeError) as ctx:
            cli.api("/repos/nonexistent/repo")

        self.assertIn("Not Found", str(ctx.exception))

    def test_api_non_json_response(self):
        """Test API call that returns non-JSON response."""
        mock_run = MagicMock(return_value=_proc(
            returncode=0,
            stdout="plain text response"
        ))
        cli = GhCLI(run_func=mock_run)

        result = cli.api("/some/endpoint")

        # Should return raw string when JSON parse fails
        self.assertEqual(result, "plain text response")


class TestGhCLISearchPrs(unittest.TestCase):
    """Test search_prs() method."""

    def test_search_prs_success(self):
        """Test successful PR search."""
        mock_run = MagicMock(return_value=_proc(
            returncode=0,
            stdout='[{"number": 1, "title": "Test PR"}]'
        ))
        cli = GhCLI(run_func=mock_run)

        result = cli.search_prs(author="@me", state="all", limit=5)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["number"], 1)
        call_args = mock_run.call_args[0][0]
        self.assertIn("--author", call_args)
        self.assertIn("@me", call_args)
        self.assertIn("--state", call_args)
        self.assertIn("all", call_args)
        self.assertIn("--limit", call_args)
        self.assertIn("5", call_args)

    def test_search_prs_underscore_to_hyphen(self):
        """Test that kwargs with underscores are converted to hyphens."""
        mock_run = MagicMock(return_value=_proc(
            returncode=0,
            stdout='[]'
        ))
        cli = GhCLI(run_func=mock_run)

        cli.search_prs(review_requested="@me")

        call_args = mock_run.call_args[0][0]
        self.assertIn("--review-requested", call_args)

    def test_search_prs_skips_none_values(self):
        """Test that None-valued kwargs are omitted, not passed as 'None'."""
        mock_run = MagicMock(return_value=_proc(
            returncode=0,
            stdout='[]'
        ))
        cli = GhCLI(run_func=mock_run)

        cli.search_prs(author="@me", assignee=None)

        call_args = mock_run.call_args[0][0]
        self.assertIn("--author", call_args)
        self.assertNotIn("--assignee", call_args)
        self.assertNotIn("None", call_args)

    def test_search_prs_failure_raises_runtime_error(self):
        """Test that search failure raises RuntimeError."""
        mock_run = MagicMock(return_value=_proc(
            returncode=1,
            stderr="Search failed"
        ))
        cli = GhCLI(run_func=mock_run)

        with self.assertRaises(RuntimeError):
            cli.search_prs(author="@me")


class TestGhCLIApiWithHeaders(unittest.TestCase):
    """Test api_with_headers() method."""

    def test_api_with_headers_success(self):
        """Test successful API call with headers."""
        response = (
            "HTTP/1.1 200 OK\r\n"
            "X-OAuth-Scopes: repo,read:org\r\n"
            "Content-Type: application/json\r\n"
            "\r\n"
            '{"login": "testuser"}'
        )
        mock_run = MagicMock(return_value=_proc(
            returncode=0,
            stdout=response
        ))
        cli = GhCLI(run_func=mock_run)

        status, headers, body = cli.api_with_headers("/user")

        self.assertEqual(status, 200)
        self.assertEqual(headers["X-OAuth-Scopes"], "repo,read:org")
        self.assertEqual(headers["Content-Type"], "application/json")
        self.assertIn("testuser", body)

    def test_api_with_headers_unix_line_endings(self):
        """Test API call with Unix line endings."""
        response = (
            "HTTP/1.1 201 Created\n"
            "X-Custom: value\n"
            "\n"
            '{"created": true}'
        )
        mock_run = MagicMock(return_value=_proc(
            returncode=0,
            stdout=response
        ))
        cli = GhCLI(run_func=mock_run)

        status, headers, _ = cli.api_with_headers("/repos/owner/repo/issues")

        self.assertEqual(status, 201)
        self.assertEqual(headers["X-Custom"], "value")

    def test_api_with_headers_failure(self):
        """Test API call that fails returns status=-1 and masked body."""
        mock_run = MagicMock(return_value=_proc(
            returncode=1,
            stderr="Not authenticated"
        ))
        cli = GhCLI(run_func=mock_run)

        status, headers, body = cli.api_with_headers("/user")

        # Process failure returns -1, distinct from the success-path status=0
        # default (used when a response has no parseable HTTP/ status line).
        self.assertEqual(status, -1)
        self.assertEqual(headers, {})
        # mask_text does not redact plain strings like "Not authenticated"
        self.assertIn("Not authenticated", body)

    def test_api_with_headers_status_parse_error(self):
        """Test handling of malformed HTTP status line."""
        response = (
            "HTTP/1.1 BAD_STATUS\r\n"
            "\r\n"
            '{"error": true}'
        )
        mock_run = MagicMock(return_value=_proc(
            returncode=0,
            stdout=response
        ))
        cli = GhCLI(run_func=mock_run)

        status, _, _ = cli.api_with_headers("/endpoint")

        # Status should default to 0 on parse error
        self.assertEqual(status, 0)


class TestGhCLIGraphql(unittest.TestCase):
    """Test graphql() method."""

    def test_graphql_success(self):
        """Test successful GraphQL query uses tempfile transport."""
        mock_run = MagicMock(return_value=_proc(
            returncode=0,
            stdout='{"data": {"viewer": {"login": "testuser"}}}'
        ))
        cli = GhCLI(run_func=mock_run)

        result = cli.graphql("query { viewer { login } }")

        self.assertIsNotNone(result)
        self.assertEqual(result["data"]["viewer"]["login"], "testuser")
        # Happy path must use -F query=@<tmpfile> (not inline -f)
        call_args = mock_run.call_args[0][0]
        self.assertTrue(
            any(str(a).startswith("query=@") for a in call_args),
            f"Expected 'query=@<tmpfile>' arg in call_args but got: {call_args}",
        )

    def test_graphql_with_variables(self):
        """Test GraphQL query with variables."""
        mock_run = MagicMock(return_value=_proc(
            returncode=0,
            stdout='{"data": {"repository": {"name": "test-repo"}}}'
        ))
        cli = GhCLI(run_func=mock_run)

        result = cli.graphql(
            "query($owner: String!, $name: String!) { repository(owner: $owner, name: $name) { name } }",
            variables={"owner": "test-org", "name": "test-repo"}
        )

        self.assertIsNotNone(result)
        call_args = mock_run.call_args[0][0]
        self.assertIn("-F", call_args)
        self.assertIn("owner=test-org", call_args)
        self.assertIn("name=test-repo", call_args)

    def test_graphql_null_variables_skipped(self):
        """Test that None-valued variables are omitted from the gh call."""
        mock_run = MagicMock(return_value=_proc(
            returncode=0,
            stdout='{"data": {}}'
        ))
        cli = GhCLI(run_func=mock_run)

        cli.graphql("query { x }", variables={"owner": "test-org", "nullvar": None})

        call_args = mock_run.call_args[0][0]
        # owner=test-org must be present
        self.assertIn("owner=test-org", call_args)
        # nullvar must NOT appear — gh CLI would pass "None" as a string otherwise
        self.assertFalse(
            any("nullvar" in str(a) for a in call_args),
            f"nullvar should be omitted from call_args but found in: {call_args}",
        )

    def test_graphql_failure_returns_none(self):
        """Test that GraphQL failure returns None."""
        mock_run = MagicMock(return_value=_proc(
            returncode=1,
            stderr="GraphQL error"
        ))
        cli = GhCLI(run_func=mock_run)

        result = cli.graphql("query { invalid }")

        self.assertIsNone(result)

    def test_graphql_failure_with_debug(self):
        """Test GraphQL failure with debug flag prints error to stderr."""
        mock_run = MagicMock(return_value=_proc(
            returncode=1,
            stderr="GraphQL error message"
        ))
        cli = GhCLI(run_func=mock_run)

        with patch('sys.stderr') as mock_stderr:
            result = cli.graphql("query { invalid }", debug=True)

        self.assertIsNone(result)
        mock_stderr.write.assert_called()

    def test_graphql_parse_error(self):
        """Test handling of invalid JSON response."""
        mock_run = MagicMock(return_value=_proc(
            returncode=0,
            stdout="not valid json"
        ))
        cli = GhCLI(run_func=mock_run)

        result = cli.graphql("query { test }")

        # Should return None on parse error
        self.assertIsNone(result)

    def test_graphql_parse_error_with_debug(self):
        """Test handling of invalid JSON response with debug prints to stderr."""
        mock_run = MagicMock(return_value=_proc(
            returncode=0,
            stdout="not valid json"
        ))
        cli = GhCLI(run_func=mock_run)

        with patch('sys.stderr') as mock_stderr:
            result = cli.graphql("query { test }", debug=True)

        self.assertIsNone(result)
        mock_stderr.write.assert_called()

    @patch('tempfile.NamedTemporaryFile')
    def test_graphql_tempfile_failure_fallback(self, mock_tempfile):
        """Test that graphql falls back to inline query when tempfile fails."""
        mock_tempfile.side_effect = Exception("Cannot create temp file")
        mock_run = MagicMock(return_value=_proc(
            returncode=0,
            stdout='{"data": {}}'
        ))
        cli = GhCLI(run_func=mock_run)

        result = cli.graphql("query { test }")

        # Should still succeed with inline query
        self.assertIsNotNone(result)
        call_args = mock_run.call_args[0][0]
        # Should use -f (inline) instead of -F with @file
        self.assertIn("-f", call_args)
        self.assertFalse(
            any(str(a).startswith("query=@") for a in call_args),
            f"Fallback should NOT use query=@<tmpfile> but got: {call_args}",
        )


class TestGhCLIPrView(unittest.TestCase):
    """Test pr_view() method."""

    def test_pr_view_basic(self):
        """Test basic PR view without fields."""
        mock_run = MagicMock(return_value=_proc(
            returncode=0,
            stdout="PR #123 Title: Test PR\nAuthor: testuser"
        ))
        cli = GhCLI(run_func=mock_run)

        result = cli.pr_view("123")

        self.assertIn("PR #123", result)
        call_args = mock_run.call_args[0][0]
        self.assertEqual(call_args, ["gh", "pr", "view", "123"])

    def test_pr_view_with_repo(self):
        """Test PR view with repo specified."""
        mock_run = MagicMock(return_value=_proc(
            returncode=0,
            stdout="PR details"
        ))
        cli = GhCLI(run_func=mock_run)

        cli.pr_view("456", repo="owner/repo")

        call_args = mock_run.call_args[0][0]
        self.assertIn("--repo", call_args)
        self.assertIn("owner/repo", call_args)

    def test_pr_view_with_fields(self):
        """Test PR view with JSON fields."""
        mock_run = MagicMock(return_value=_proc(
            returncode=0,
            stdout='{"number": 789, "title": "Test", "state": "OPEN"}'
        ))
        cli = GhCLI(run_func=mock_run)

        result = cli.pr_view("789", fields=["number", "title", "state"])

        self.assertEqual(result["number"], 789)
        call_args = mock_run.call_args[0][0]
        self.assertIn("--json", call_args)
        self.assertIn("number,title,state", call_args)

    def test_pr_view_with_fields_parse_error(self):
        """Test PR view when JSON parse fails."""
        mock_run = MagicMock(return_value=_proc(
            returncode=0,
            stdout="not valid json"
        ))
        cli = GhCLI(run_func=mock_run)

        result = cli.pr_view("123", fields=["number"])

        # Should return raw text on parse error
        self.assertEqual(result, "not valid json")

    def test_pr_view_failure_raises_runtime_error(self):
        """Test that PR view failure raises RuntimeError."""
        mock_run = MagicMock(return_value=_proc(
            returncode=1,
            stderr="PR not found"
        ))
        cli = GhCLI(run_func=mock_run)

        with self.assertRaises(RuntimeError):
            cli.pr_view("999")


class TestGhCLIPrList(unittest.TestCase):
    """Test pr_list() method."""

    def test_pr_list_success(self):
        """Test successful PR list with full command verification."""
        mock_run = MagicMock(return_value=_proc(
            returncode=0,
            stdout='[{"number": 1}, {"number": 2}]'
        ))
        cli = GhCLI(run_func=mock_run)

        result = cli.pr_list(["pr", "list", "--state", "all", "--json", "number"])

        self.assertIn("[", result)
        call_args = mock_run.call_args[0][0]
        self.assertEqual(
            call_args,
            ["gh", "pr", "list", "--state", "all", "--json", "number"],
        )

    def test_pr_list_failure_raises_runtime_error(self):
        """Test that PR list failure raises RuntimeError."""
        mock_run = MagicMock(return_value=_proc(
            returncode=1,
            stderr="Failed to list PRs"
        ))
        cli = GhCLI(run_func=mock_run)

        with self.assertRaises(RuntimeError):
            cli.pr_list(["pr", "list"])


if __name__ == '__main__':
    unittest.main()
