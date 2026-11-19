"""Shared fixtures for the memory tests: isolated HOME, synthetic stores, bundles, dirty text.

Every memory test should inherit ``MemoryTestCase`` (or call
``isolate_home``) so nothing it runs can read or write the real
``~/.claude`` or the real dancing-bear data home: discovery resolves
``Path.home()`` at call time, and ``Path.home()`` honours ``$HOME``.
"""

from __future__ import annotations

import contextlib
import io
import os
import tempfile
import unittest
import unittest.mock
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from memory.models import (
    BUNDLE_VERSION,
    ExportedMemory,
    ExportProvenance,
    IndexEntry,
    Memory,
    MemoryBundle,
    MemoryFrontmatter,
    MemoryStore,
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
    patcher = unittest.mock.patch.dict(os.environ, env)
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


def run_memory_cli(argv: list[str]) -> tuple[int, str, str]:
    """Call ``memory.cli.main(argv)`` with output captured; return (rc, stdout, stderr).

    ``memory.cli`` is resolved at call time so a patch of ``memory.cli.main`` applies.
    """
    import memory.cli

    out_buf = io.StringIO()
    err_buf = io.StringIO()
    with contextlib.redirect_stdout(out_buf), contextlib.redirect_stderr(err_buf):
        rc = memory.cli.main(argv)
    return rc, out_buf.getvalue(), err_buf.getvalue()


def make_store(
    slug: str = "test-slug",
    *,
    root: str | None = None,
    memories: tuple[Memory, ...] = (),
    non_memory_files: tuple[str, ...] = (),
    index_path: str | None = None,
    index_entries: tuple[IndexEntry, ...] = (),
    inferred_repo: str | None = None,
    is_worktree_slug: bool = False,
) -> MemoryStore:
    """An in-memory MemoryStore; ``root`` defaults to ``/nonexistent/<slug>``."""
    return MemoryStore(
        project_slug=slug,
        root=f"/nonexistent/{slug}" if root is None else root,
        memories=memories,
        non_memory_files=non_memory_files,
        index_path=index_path,
        index_entries=index_entries,
        inferred_repo=inferred_repo,
        is_worktree_slug=is_worktree_slug,
    )


def write_store(
    base: Path,
    slug: str,
    files: Iterable[tuple[str, str]],
    *,
    inferred_repo: str | None = None,
    is_worktree_slug: bool = False,
    with_index: bool = False,
) -> MemoryStore:
    """Write ``files`` to ``<base>/<slug>/memory/`` and return a MemoryStore of the parsed memories.

    With ``with_index``, each memory is appended to a MEMORY.md and ``index_path`` set.
    """
    from memory.index import append_entry
    from memory.parser import parse_memory_file

    store_root = base / slug
    mem_dir = store_root / "memory"
    mem_dir.mkdir(parents=True)

    memories = []
    for filename, content in files:
        f = mem_dir / filename
        f.write_text(content, encoding="utf-8")
        memories.append(parse_memory_file(f, project_slug=slug))

    index_path = None
    if with_index:
        index_file = mem_dir / "MEMORY.md"
        for mem in memories:
            append_entry(index_file, mem)
        index_path = str(index_file)

    return make_store(
        slug,
        root=str(store_root),
        memories=tuple(memories),
        index_path=index_path,
        inferred_repo=inferred_repo,
        is_worktree_slug=is_worktree_slug,
    )


def make_memory(
    slug: str = "mem",
    *,
    mtime: datetime | None = None,
    indexed: bool = False,
    mem_type: MemoryType | None = MemoryType.FEEDBACK,
    description: str | None = None,
    shape: SchemaShape = SchemaShape.NESTED,
    body: str = "**Why:** Test.\n\n**How to apply:** Use in tests.",
    why: str | None = "Test.",
    how_to_apply: str | None = "Use in tests.",
) -> Memory:
    """An in-memory Memory at ``/nonexistent/<slug>.md``; description defaults per slug."""
    fm = MemoryFrontmatter(
        name=slug,
        description=f"description for {slug}" if description is None else description,
        type=mem_type,
        node_type="memory",
        origin_session_id=None,
        modified=None,
        shape=shape,
        unknown_keys={},
    )
    return Memory(
        slug=slug,
        path=f"/nonexistent/{slug}.md",
        project_slug="test-slug",
        frontmatter=fm,
        body=body,
        why=why,
        how_to_apply=how_to_apply,
        wikilinks=(),
        mtime=datetime.now(UTC) if mtime is None else mtime,
        size_bytes=100,
        indexed=indexed,
        index_hook=None,
        index_section=None,
    )


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
            Redaction(
                rule_id="abs-home-path", severity="scrub", line_no=1, matched="~/", replacement="~/"
            ),
        ),
    )
    return MemoryBundle(
        bundle_version=BUNDLE_VERSION, created_at=now, memories=(em,), notes="test bundle"
    )


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
