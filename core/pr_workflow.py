"""PR workflow automation: create, review Copilot feedback, resolve conversations, update PR."""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class PrInfo:
    """PR metadata."""

    number: int
    title: str
    body: str
    url: str
    head_branch: str
    base_branch: str
    state: str


@dataclass
class ReviewComment:
    """Review comment metadata."""

    id: int
    body: str
    path: str
    line: Optional[int]
    author: str
    conversation_id: Optional[str]
    resolved: bool


@dataclass
class QltyIssue:
    """Qlty linting issue."""

    file: str
    line: int
    severity: str
    message: str
    rule: str


@dataclass
class CiCheck:
    """CI/CD check status."""

    name: str
    status: str  # completed, in_progress, queued, etc.
    conclusion: Optional[str]  # success, failure, cancelled, etc.
    details_url: Optional[str]
    started_at: Optional[str]
    completed_at: Optional[str]


def _run_gh(args: list[str], check: bool = True) -> tuple[int, str, str]:
    """Run gh CLI command and return (exit_code, stdout, stderr)."""
    try:
        result = subprocess.run(  # nosec B603 - gh CLI is a trusted tool for GitHub API access
            ["gh"] + args,
            capture_output=True,
            text=True,
            check=False,
        )
        if check and result.returncode != 0:
            raise RuntimeError(f"gh command failed: {result.stderr}")
        return result.returncode, result.stdout, result.stderr
    except FileNotFoundError:
        raise RuntimeError("gh CLI not found. Install from https://cli.github.com/")


def get_current_pr() -> Optional[PrInfo]:
    """Get PR for current branch."""
    code, stdout, _ = _run_gh(["pr", "view", "--json", "number,title,body,url,headRefName,baseRefName,state"], check=False)
    if code != 0:
        return None

    data = json.loads(stdout)
    return PrInfo(
        number=data["number"],
        title=data["title"],
        body=data.get("body", ""),
        url=data["url"],
        head_branch=data["headRefName"],
        base_branch=data["baseRefName"],
        state=data["state"],
    )


def create_pr(title: Optional[str] = None, body: Optional[str] = None, base: str = "main") -> PrInfo:
    """Create a new PR."""
    args = ["pr", "create", "--base", base]

    if title:
        args.extend(["--title", title])
    if body:
        args.extend(["--body", body])

    # If title/body not provided, gh will use interactive mode or generate from commits
    _run_gh(args)

    # Fetch the created PR info
    pr = get_current_pr()
    if not pr:
        raise RuntimeError("Failed to retrieve created PR")

    return pr


def get_review_comments(pr_number: int) -> list[ReviewComment]:
    """Get all review comments on a PR."""
    _, stdout, _ = _run_gh([
        "api",
        f"repos/{{owner}}/{{repo}}/pulls/{pr_number}/comments",
        "--jq", ".[] | {id, body, path, line, user: .user.login, in_reply_to_id}"
    ])

    comments = []
    for line in stdout.strip().split("\n"):
        if not line:
            continue
        try:
            data = json.loads(line)
            # Conversation is considered resolved if it has a resolution status
            # We'll fetch this separately
            comments.append(ReviewComment(
                id=data["id"],
                body=data["body"],
                path=data["path"],
                line=data.get("line"),
                author=data["user"],
                conversation_id=None,  # Will be populated if needed
                resolved=False,  # Will be updated
            ))
        except (json.JSONDecodeError, KeyError):
            continue  # nosec B112 - skip malformed comment entries

    return comments


def get_copilot_comments(pr_number: int) -> list[ReviewComment]:
    """Get Copilot review comments specifically."""
    all_comments = get_review_comments(pr_number)
    # Filter for Copilot comments (author is typically 'github-copilot' or 'copilot')
    return [c for c in all_comments if "copilot" in c.author.lower()]


def _get_repo_info() -> tuple[Optional[str], Optional[str]]:
    """Get repository owner and name."""
    code, stdout, _ = _run_gh(["repo", "view", "--json", "owner,name"], check=False)
    if code != 0:
        return None, None

    try:
        data = json.loads(stdout)
        return data["owner"]["login"], data["name"]
    except (json.JSONDecodeError, KeyError):
        return None, None  # nosec B112 - graceful failure on malformed repo info


def resolve_conversation(pr_number: int, comment_id: int) -> bool:
    """Mark a review conversation as resolved using GraphQL API."""
    # Get repo owner and name
    owner, repo = _get_repo_info()
    if not owner or not repo:
        return False

    # Get the conversation thread ID for this comment
    query = """
    query($owner: String!, $repo: String!, $prNumber: Int!) {
      repository(owner: $owner, name: $repo) {
        pullRequest(number: $prNumber) {
          reviewThreads(first: 100) {
            nodes {
              id
              isResolved
              comments(first: 10) {
                nodes {
                  databaseId
                }
              }
            }
          }
        }
      }
    }
    """

    code, stdout, _ = _run_gh([
        "api", "graphql",
        "-f", f"query={query}",
        "-F", f"owner={owner}",
        "-F", f"repo={repo}",
        "-F", f"prNumber={pr_number}"
    ], check=False)

    if code != 0:
        return False

    try:
        data = json.loads(stdout)
        threads = data["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]

        # Find the thread containing our comment
        thread_id = None
        for thread in threads:
            if thread["isResolved"]:
                continue
            for comment in thread["comments"]["nodes"]:
                if comment["databaseId"] == comment_id:
                    thread_id = thread["id"]
                    break
            if thread_id:
                break

        if not thread_id:
            return False

        # Resolve the thread using mutation
        mutation = """
        mutation($threadId: ID!) {
          resolveReviewThread(input: {threadId: $threadId}) {
            thread {
              id
              isResolved
            }
          }
        }
        """

        code, _, _ = _run_gh([
            "api", "graphql",
            "-f", f"query={mutation}",
            "-F", f"threadId={thread_id}"
        ], check=False)

        return code == 0
    except (json.JSONDecodeError, KeyError):
        return False  # nosec B112 - graceful failure on malformed response


def update_pr(pr_number: int, title: Optional[str] = None, body: Optional[str] = None) -> bool:
    """Update PR title and/or body."""
    args = ["pr", "edit", str(pr_number)]

    if title:
        args.extend(["--title", title])
    if body:
        args.extend(["--body", body])

    code, _, _ = _run_gh(args, check=False)
    return code == 0


def add_pr_comment(pr_number: int, body: str) -> bool:
    """Add a comment to the PR."""
    code, _, _ = _run_gh(["pr", "comment", str(pr_number), "--body", body], check=False)
    return code == 0


def get_pr_changed_files(pr_number: int) -> list[str]:
    """Get list of files changed in PR."""
    _, stdout, _ = _run_gh([
        "pr", "view", str(pr_number),
        "--json", "files",
        "--jq", ".files[].path"
    ])
    return [line.strip() for line in stdout.strip().split("\n") if line.strip()]


def get_ci_checks(pr_number: int) -> list[CiCheck]:
    """Get CI/CD check status for PR."""
    _, stdout, _ = _run_gh([
        "pr", "checks", str(pr_number),
        "--json", "name,status,conclusion,detailsUrl,startedAt,completedAt"
    ], check=False)

    if not stdout:
        return []

    checks = []
    try:
        data = json.loads(stdout)
        for check in data:
            checks.append(CiCheck(
                name=check.get("name", "Unknown"),
                status=check.get("status", "unknown"),
                conclusion=check.get("conclusion"),
                details_url=check.get("detailsUrl"),
                started_at=check.get("startedAt"),
                completed_at=check.get("completedAt"),
            ))
    except json.JSONDecodeError:
        pass  # nosec B112 - graceful failure on malformed check data

    return checks


def _format_check_section(title: str, checks: list[CiCheck], include_urls: bool = False, limit: int = 0) -> list[str]:
    """Format a section of CI checks."""
    if not checks:
        return []

    lines = [f"### {title} ({len(checks)})", ""]

    display_checks = checks[:limit] if limit > 0 else checks
    for check in display_checks:
        if include_urls and check.details_url:
            lines.append(f"- **{check.name}** - [Details]({check.details_url})")
        else:
            lines.append(f"- {check.name}")

    if limit > 0 and len(checks) > limit:
        lines.append(f"- ... and {len(checks) - limit} more")

    lines.append("")
    return lines


def summarize_ci_checks(checks: list[CiCheck]) -> str:
    """Generate a summary of CI/CD checks."""
    if not checks:
        return "No CI/CD checks found."

    # Group by status
    groups = {
        "failed": [c for c in checks if c.conclusion == "failure"],
        "in_progress": [c for c in checks if c.status == "in_progress"],
        "pending": [c for c in checks if c.status in ("queued", "pending")],
        "cancelled": [c for c in checks if c.conclusion == "cancelled"],
        "skipped": [c for c in checks if c.conclusion == "skipped"],
        "passed": [c for c in checks if c.conclusion == "success"],
    }

    summary_parts = [
        "## CI/CD Checks",
        "",
        f"**Status:** {len(checks)} total check(s)",
        "",
    ]

    # Add sections in priority order
    summary_parts.extend(_format_check_section("❌ Failed", groups["failed"], include_urls=True))
    summary_parts.extend(_format_check_section("🔄 In Progress", groups["in_progress"]))
    summary_parts.extend(_format_check_section("⏳ Pending", groups["pending"]))
    summary_parts.extend(_format_check_section("⚠️ Cancelled", groups["cancelled"]))
    summary_parts.extend(_format_check_section("⏭️ Skipped", groups["skipped"]))
    summary_parts.extend(_format_check_section("✅ Passed", groups["passed"], limit=5))

    return "\n".join(summary_parts)


def check_qlty_issues(files: list[str]) -> list[QltyIssue]:
    """Run qlty check on files and return issues."""
    qlty_bin = Path.home() / ".qlty" / "bin" / "qlty"
    if not qlty_bin.exists():
        return []

    issues = []
    for file_path in files:
        if not Path(file_path).exists():
            continue  # nosec B112 - skip deleted files

        try:
            result = subprocess.run(  # nosec B603 - qlty is a trusted linting tool
                [str(qlty_bin), "check", file_path, "--format", "json"],
                capture_output=True,
                text=True,
                check=False,
            )

            if result.stdout:
                try:
                    data = json.loads(result.stdout)
                    for issue in data.get("issues", []):
                        issues.append(QltyIssue(
                            file=file_path,
                            line=issue.get("line", 0),
                            severity=issue.get("level", "unknown"),
                            message=issue.get("message", ""),
                            rule=issue.get("rule_id", ""),
                        ))
                except json.JSONDecodeError:
                    continue  # nosec B112 - skip malformed qlty output
        except Exception:  # nosec B110, B112 - graceful failure on qlty execution errors
            continue

    return issues


def summarize_qlty_issues(issues: list[QltyIssue]) -> str:
    """Generate a summary of qlty issues."""
    if not issues:
        return "✓ No qlty issues found."

    # Group by severity
    by_severity = {"high": [], "medium": [], "low": []}
    for issue in issues:
        severity = issue.severity.lower()
        if severity in by_severity:
            by_severity[severity].append(issue)
        else:
            by_severity["low"].append(issue)

    summary_parts = [
        "## Qlty Linting Issues",
        "",
        f"Found {len(issues)} issue(s):",
        "",
    ]

    for severity in ["high", "medium", "low"]:
        severity_issues = by_severity[severity]
        if not severity_issues:
            continue

        summary_parts.append(f"### {severity.upper()} ({len(severity_issues)})")
        summary_parts.append("")

        for issue in severity_issues[:10]:  # Limit to 10 per severity
            summary_parts.append(f"- `{issue.file}:{issue.line}` - {issue.message} ({issue.rule})")

        if len(severity_issues) > 10:
            summary_parts.append(f"- ... and {len(severity_issues) - 10} more")

        summary_parts.append("")

    return "\n".join(summary_parts)


def summarize_copilot_feedback(comments: list[ReviewComment]) -> str:
    """Generate a summary of Copilot feedback."""
    if not comments:
        return "No Copilot feedback found."

    summary_parts = [
        "## Copilot Review Summary",
        "",
        f"Found {len(comments)} Copilot review comment(s):",
        "",
    ]

    for idx, comment in enumerate(comments, 1):
        summary_parts.extend([
            f"### {idx}. {comment.path}:{comment.line or '?'}",
            f"{comment.body[:200]}{'...' if len(comment.body) > 200 else ''}",
            "",
        ])

    return "\n".join(summary_parts)


def _handle_pr_creation(auto_create: bool, base_branch: str, title: Optional[str], body: Optional[str], dry_run: bool) -> Optional[PrInfo]:
    """Handle PR creation if needed."""
    pr = get_current_pr()

    if not pr:
        if not auto_create:
            print("No PR found for current branch. Use --create to create one.")
            return None

        print("No PR found for current branch. Creating one...")
        if dry_run:
            print(f"[DRY RUN] Would create PR with base={base_branch}")
            return None

        pr = create_pr(title=title, body=body, base=base_branch)
        print(f"Created PR #{pr.number}: {pr.url}")
    else:
        print(f"Found PR #{pr.number}: {pr.title}")
        print(f"URL: {pr.url}")

    return pr


def _handle_copilot_feedback(pr: PrInfo, resolve_copilot: bool, dry_run: bool) -> str:
    """Process Copilot review comments. Returns summary text."""
    print("\nFetching Copilot review comments...")
    copilot_comments = get_copilot_comments(pr.number)

    if not copilot_comments:
        print("No Copilot comments found.")
        return ""

    print(f"Found {len(copilot_comments)} Copilot comment(s)")

    # Display summary
    summary = summarize_copilot_feedback(copilot_comments)
    print("\n" + summary)

    # Resolve conversations
    if resolve_copilot:
        _resolve_copilot_conversations(pr.number, copilot_comments, dry_run)

    # Note: summary is returned for combining with qlty issues
    # Individual Copilot summary posting is handled in run_pr_workflow
    return summary


def _resolve_copilot_conversations(pr_number: int, comments: list[ReviewComment], dry_run: bool) -> None:
    """Resolve Copilot review conversations."""
    print("\nResolving Copilot conversations...")
    for comment in comments:
        if dry_run:
            print(f"[DRY RUN] Would resolve comment {comment.id} in {comment.path}")
        else:
            success = resolve_conversation(pr_number, comment.id)
            status = "✓" if success else "✗"
            print(f"{status} Comment {comment.id} in {comment.path}")


def _add_pr_summary(pr_number: int, summary: str, dry_run: bool) -> None:
    """Add summary comment to PR."""
    print("\nUpdating PR with summary...")
    if dry_run:
        print("[DRY RUN] Would add summary comment to PR")
    else:
        add_pr_comment(pr_number, summary)
        print("✓ Added summary comment")


def _handle_qlty_issues(pr: PrInfo, _dry_run: bool) -> str:
    """Check for qlty issues on PR files. Returns summary text.

    Args:
        pr: PR information
        _dry_run: Reserved for future auto-fix functionality (unused)
    """
    print("\nChecking qlty issues on PR files...")

    # Get changed files
    changed_files = get_pr_changed_files(pr.number)
    if not changed_files:
        print("No changed files found.")
        return ""

    print(f"Checking {len(changed_files)} file(s)...")

    # Check for issues
    issues = check_qlty_issues(changed_files)

    # Display summary
    summary = summarize_qlty_issues(issues)
    print("\n" + summary)

    return summary


def _handle_ci_checks(pr: PrInfo, _dry_run: bool) -> str:
    """Check CI/CD status for PR. Returns summary text.

    Args:
        pr: PR information
        _dry_run: Reserved for future functionality (unused)
    """
    print("\nChecking CI/CD status...")

    # Get CI checks
    checks = get_ci_checks(pr.number)

    # Display summary
    summary = summarize_ci_checks(checks)
    print("\n" + summary)

    return summary


def _update_pr_metadata(pr: PrInfo, title: Optional[str], body: Optional[str], dry_run: bool) -> bool:
    """Update PR title/body if provided."""
    if not (title or body):
        return True

    print("\nUpdating PR metadata...")
    if dry_run:
        print(f"[DRY RUN] Would update PR with title={title}, body={bool(body)}")
        return True

    success = update_pr(pr.number, title=title, body=body)
    if success:
        print("✓ Updated PR")
    else:
        print("✗ Failed to update PR")
    return success


def run_pr_workflow(
    auto_create: bool = True,
    resolve_copilot: bool = True,
    update_summary: bool = True,
    check_qlty: bool = True,
    check_ci: bool = True,
    base_branch: str = "main",
    title: Optional[str] = None,
    body: Optional[str] = None,
    dry_run: bool = False,
) -> int:
    """
    Run the PR workflow.

    Args:
        auto_create: Create PR if it doesn't exist
        resolve_copilot: Auto-resolve Copilot conversations
        update_summary: Add/update PR with summary
        check_qlty: Check for qlty linting issues
        check_ci: Check CI/CD status
        base_branch: Base branch for new PRs
        title: Override PR title
        body: Override PR body
        dry_run: Don't make any changes, just report what would happen

    Returns:
        Exit code (0 for success)
    """
    # Handle PR creation
    pr = _handle_pr_creation(auto_create, base_branch, title, body, dry_run)
    if not pr:
        return 0 if dry_run else 1

    # Collect summaries
    summaries = []

    # Process Copilot feedback
    copilot_summary = _handle_copilot_feedback(pr, resolve_copilot, dry_run)
    if copilot_summary:
        summaries.append(copilot_summary)

    # Check qlty issues
    if check_qlty:
        qlty_summary = _handle_qlty_issues(pr, dry_run)
        if qlty_summary:
            summaries.append(qlty_summary)

    # Check CI/CD status
    if check_ci:
        ci_summary = _handle_ci_checks(pr, dry_run)
        if ci_summary:
            summaries.append(ci_summary)

    # Add combined summary to PR
    if update_summary and summaries:
        combined = "\n\n".join(summaries)
        _add_pr_summary(pr.number, combined, dry_run)

    # Update PR metadata
    if not _update_pr_metadata(pr, title, body, dry_run):
        return 1

    print(f"\n✓ Workflow complete. PR: {pr.url}")
    return 0
