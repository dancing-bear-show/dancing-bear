"""Shared fixtures for the memory tests: isolated HOME, synthetic stores, bundles, dirty text.

Every memory test should inherit ``MemoryTestCase`` (or call
``isolate_home``) so nothing it runs can read or write the real
``~/.claude`` or the real dancing-bear data home: discovery resolves
``Path.home()`` at call time, and ``Path.home()`` honours ``$HOME``.
"""

from __future__ import annotations

import os
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from unittest import mock

from memory.models import (
    BUNDLE_VERSION,
    ExportedMemory,
    ExportProvenance,
    MemoryBundle,
    MemoryFrontmatter,
    MemoryType,
    Redaction,
    SchemaShape,
)

# Slugs follow the -Users-<name>-code-<repo> encoding so decode_project_slug
# and is_worktree_slug behave as they do on a real machine.
SLUG_MAIN = "-Users-alice-code-proj"
SLUG_WORKTREE = "-Users-alice-code-proj--claude-worktrees-my-feature-run"
SLUG_UNDECODABLE = "-Users-alice-nocode-something"
SLUG_EMPTY = "-Users-alice-code-empty-project"


def isolate_home(test: unittest.TestCase) -> Path:
    """Point HOME and the data/config roots at a fresh temp dir for ``test``.

    Returns the temp HOME. Cleanup is registered on ``test``.
    """
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    home = Path(tmp.name)
    env = {
        "HOME": str(home),
        "DANCING_BEAR_DATA_HOME": str(home / "data"),
        "DANCING_BEAR_CONFIG_HOME": str(home / "config"),
    }
    patcher = mock.patch.dict(os.environ, env)
    patcher.start()
    test.addCleanup(patcher.stop)
    for var in ("XDG_DATA_HOME", "XDG_CONFIG_HOME"):
        os.environ.pop(var, None)
    return home


class MemoryTestCase(unittest.TestCase):
    """TestCase with an isolated HOME and a scratch directory at ``self.tmp``."""

    def setUp(self) -> None:
        super().setUp()
        self.home = isolate_home(self)
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        self.tmp = Path(scratch.name)


def write_memory_dir(projects_dir: Path, slug: str, memories: list[tuple[str, str]]) -> Path:
    """Create ``<projects_dir>/<slug>/memory/`` holding ``memories``; return the memory dir."""
    memory_dir = projects_dir / slug / "memory"
    memory_dir.mkdir(parents=True)
    for filename, text in memories:
        (memory_dir / filename).write_text(text, encoding="utf-8")
    return memory_dir


def make_projects_root(base: Path) -> Path:
    """Build a projects root with normal, worktree, undecodable, and empty stores."""
    projects_dir = base / "projects"
    projects_dir.mkdir()
    write_memory_dir(
        projects_dir,
        SLUG_MAIN,
        [
            (
                "feedback_worktree.md",
                "---\n"
                "name: feedback_worktree\n"
                "description: feedback about worktree isolation\n"
                "metadata:\n"
                "  type: feedback\n"
                "  node_type: memory\n"
                "---\n\n"
                "**Why:** Test fixture.\n\n"
                "**How to apply:** Use in tests.\n",
            )
        ],
    )
    write_memory_dir(
        projects_dir,
        SLUG_WORKTREE,
        [
            (
                "project_state.md",
                "---\n"
                "name: project_state\n"
                "description: current state of the feature branch\n"
                "metadata:\n"
                "  type: project\n"
                "  node_type: memory\n"
                "---\n\n"
                "**Why:** Tracks feature work.\n\n"
                "**How to apply:** Read before continuing.\n",
            )
        ],
    )
    write_memory_dir(
        projects_dir,
        SLUG_UNDECODABLE,
        [
            (
                "reference_notes.md",
                "---\n"
                "name: reference_notes\n"
                "description: reference notes for non-decodable project\n"
                "type: reference\n"
                "---\n\n"
                "Some reference content.\n",
            )
        ],
    )
    (projects_dir / SLUG_EMPTY / "memory").mkdir(parents=True)
    return projects_dir


# The on-disk format Claude Code writes today: nested metadata carrying
# node_type/type/originSessionId/modified, kebab-case filenames, a flat
# MEMORY.md of "- [Title](file.md) — hook" lines, and [[slug]] links.
CURRENT_FORMAT_MEMORY = (
    "---\n"
    "name: feedback-run-it\n"
    'description: "Run the thing once instead of reasoning about it"\n'
    "metadata:\n"
    "  node_type: memory\n"
    "  type: feedback\n"
    "  originSessionId: 00000000-0000-4000-8000-000000000000\n"
    "  modified: 2026-11-11T21:38:57.947Z\n"
    "---\n\n"
    "One dry run beats five review rounds. See [[project-dry-run-notes]].\n\n"
    "**Why:** Reading misses runtime behaviour.\n\n"
    "**How to apply:** Execute before reviewing.\n"
)
CURRENT_FORMAT_INDEX = (
    "# Memory Index\n\n"
    "- [Run It](feedback-run-it.md) — run the thing once instead of reasoning\n"
    "- [Dry Run Notes](project-dry-run-notes.md) — notes from a dry run\n"
)


def sample_bundle() -> MemoryBundle:
    """A one-memory bundle with provenance, a redaction, and unknown keys."""
    now = datetime.now(UTC)
    fm = MemoryFrontmatter(
        name="test_memory",
        description="a test memory for bundle round-trip tests",
        type=MemoryType.FEEDBACK,
        node_type="memory",
        origin_session_id=None,
        modified=None,
        shape=SchemaShape.NESTED,
        unknown_keys={"future_field": "future_value", "beta_feature": True},
    )
    provenance = ExportProvenance(
        origin_project_slug=SLUG_MAIN,
        origin_repo=None,
        origin_user="alice",
        origin_host=None,
        origin_session_id=None,
        exported_at=now,
        exported_by_version=str(BUNDLE_VERSION),
        source_sha256="abc123def456abc123def456abc123def456abc123def456abc123def456abc1",
    )
    em = ExportedMemory(
        frontmatter=fm,
        body="**Why:** Testing.\n\n**How to apply:** Use in tests.",
        provenance=provenance,
        redactions=(
            Redaction(rule_id="abs-home-path", severity="scrub", line_no=1, matched="~/", replacement="~/"),
        ),
    )
    return MemoryBundle(bundle_version=BUNDLE_VERSION, created_at=now, memories=(em,), notes="test bundle")


def dirty_memory_text() -> str:
    """Text that hits every non-anonymize-only redaction rule exactly once.

    The benign prose line about password policy must NOT trip credential-assignment —
    that rule requires assignment syntax (password=value), not plain prose.
    """
    lines = [
        "AKIA" + "0123456789ABCDEF",  # aws-access-key
        # private-key-block, assembled so secret scanners do not flag the source
        "-----BEGIN " + "RSA PRIVATE KEY" + "-----",
        "Authorization: Bearer eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9.abc123.sig",  # bearer-token
        "token: ghp_" + "a" * 37,  # github-token
        "slack: xoxb-" + "a1b2c3d4e5f6" * 7,  # slack-token
        "api_key = sk_" + "test_" + "fakefake" * 3,  # credentials-ini-content
        "working at /Users/alice/code/myproject/src",  # abs-home-path
        "slug: -Users-alice-code-myproject",  # abs-home-path-slug-form
        "origin_session_id: aabbccdd-1122-3344-5566-778899aabbcc",  # origin-session-id
        "path: .claude/worktrees/my-feature-branch",  # worktree-path
        "Hostname: my-laptop.local",  # machine-hostname
        "data at ~/.local/share/dancing-bear/my-workflow-run",  # data-home-path
        "tmp: /private/tmp/claude-501/session-abc123/scratchpad",  # scratchpad-path
        "api host: db.example.internal",  # internal-hostname
        "db host: 10.0.1.42",  # rfc1918-ip
        "incident: INC-12345",  # incident-id
        "merged by Alice Example",  # person-name
        "env: password=hunter2secret",  # credential-assignment
        "ticket TEAM-456 was resolved",  # jira-key
        "PR: https://github.com/myorg/myrepo/pull/999",  # pr-url
        "data: " + "A" * 64,  # long-b64
        "username: alice",  # local-username (anonymize only)
        "the password rotation policy requires 12+ characters and monthly updates.",
    ]
    return "\n".join(lines)
