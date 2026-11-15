"""Offline deterministic check registry — staleness, index drift, CLAUDE.md contradiction overlap, schema conformance, and referential integrity.

Exit-code mapping (load-bearing for CI and hook consumers, enforced by the
CLI layer from these results): 0 when clean, 1 when only warn/info-severity
findings are present, 2 when any error-severity finding exists.
"""

from __future__ import annotations

import json
import re
import subprocess
from collections.abc import Callable
from functools import partial
from dataclasses import dataclass
from pathlib import Path

from core.fileutil import atomic_write_text
from core.text_utils import slugify
from memory.index import append_entry, merge_duplicate_sections, remove_entry
from memory.models import MemoryStore, MemoryType, SchemaShape
from memory.parser import extract_anchors, normalize_slug
from memory.staleness import DEFAULT_THRESHOLDS, stale_candidates

__all__ = ["CHECK_REGISTRY", "DEFAULT_CHECKS", "Check", "CheckResult", "run_checks"]


@dataclass(frozen=True)
class CheckResult:
    """One finding from the offline check catalog.

    severity is one of 'error' | 'warn' | 'info'; check_id is the stable
    catalog id used by `validate --check <id>`; target is the memory slug
    or MEMORY.md path the finding attaches to; fixable indicates whether
    --fix can repair it; detail carries optional side-by-side excerpts
    (used by contradiction-topic-overlap).
    """

    check_id: str
    severity: str
    target: str
    message: str
    fixable: bool
    detail: str | None = None


Check = Callable[[MemoryStore, "_CheckContext"], tuple[CheckResult, ...]]

_ARCHIVE_DIRNAME = "_archive"
_DEFAULT_CLAUDE_MD_GLOBS = ("CLAUDE.md", ".llm/*.md")
_TYPE_PREFIX_TO_MEMORY_TYPE = {
    "feedback": MemoryType.FEEDBACK,
    "project": MemoryType.PROJECT,
    "reference": MemoryType.REFERENCE,
    "user": MemoryType.USER,
}


@dataclass(frozen=True)
class _CheckContext:
    """Per-run parameters shared across all dispatched checks."""

    repo: Path | None
    claude_md_paths: tuple[Path, ...]
    fix: bool


def _check_staleness(store: MemoryStore, ctx: _CheckContext) -> tuple[CheckResult, ...]:
    candidates = stale_candidates(store, thresholds=DEFAULT_THRESHOLDS)
    return tuple(
        CheckResult(
            check_id="staleness",
            severity=c.severity,
            target=c.slug,
            message=f"{c.memory_type.value} memory is {c.age_days}d old (threshold {c.threshold_days}d)"
            if c.threshold_days is not None
            else f"{c.memory_type.value} memory is {c.age_days}d old (no threshold)",
            fixable=False,
        )
        for c in candidates
        if c.is_stale
    )


def _check_index_orphan(
    store: MemoryStore, ctx: _CheckContext
) -> tuple[CheckResult, ...]:
    indexed_targets = {e.target for e in store.index_entries}
    return tuple(
        CheckResult(
            check_id="index-orphan",
            severity="warn",
            target=m.slug,
            message=f"{m.slug}.md exists on disk with no MEMORY.md entry",
            fixable=True,
        )
        for m in store.memories
        if f"{m.slug}.md" not in indexed_targets
    )


def _check_index_dangling(
    store: MemoryStore, ctx: _CheckContext
) -> tuple[CheckResult, ...]:
    memories_by_filename = {f"{m.slug}.md" for m in store.memories}
    return tuple(
        CheckResult(
            check_id="index-dangling",
            severity="warn",
            target=entry.target,
            message=f"MEMORY.md entry '{entry.target}' has no corresponding file",
            fixable=True,
        )
        for entry in store.index_entries
        if entry.target not in memories_by_filename
    )


def _check_index_duplicate_entry(
    store: MemoryStore, ctx: _CheckContext
) -> tuple[CheckResult, ...]:
    seen: set[str] = set()
    results = []
    for entry in store.index_entries:
        if entry.target in seen:
            results.append(
                CheckResult(
                    check_id="index-duplicate-entry",
                    severity="warn",
                    target=entry.target,
                    message=f"'{entry.target}' is listed more than once in MEMORY.md",
                    fixable=False,
                )
            )
        seen.add(entry.target)
    return tuple(results)


def _check_index_duplicate_section(
    store: MemoryStore, ctx: _CheckContext
) -> tuple[CheckResult, ...]:
    """Detect a '## ' header line that occurs more than once in MEMORY.md.

    Must count HEADER LINE occurrences, not how many index_entries share a
    section name — every section with 2+ entries shares that name across
    all its entries, which would make this check fire on any normal section,
    not just a genuinely repeated header. Re-scans the raw file directly
    (mirroring index.py's own _SECTION_RE) rather than relying on
    store.index_entries, which does not distinguish "many entries under one
    header" from "entries split across two occurrences of the same header".
    """
    if not store.index_path:
        return ()
    path = Path(store.index_path)
    if not path.exists():
        return ()

    header_counts: dict[str, int] = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            match = re.match(r"^## (.+)$", line.rstrip("\n"))
            if match:
                name = match.group(1).strip().casefold()
                header_counts[name] = header_counts.get(name, 0) + 1

    duplicated = {name for name, count in header_counts.items() if count > 1}
    return tuple(
        CheckResult(
            check_id="index-duplicate-section",
            severity="warn",
            target=store.index_path or "MEMORY.md",
            message=f"section '## {section}' appears more than once in MEMORY.md",
            fixable=True,
        )
        for section in sorted(duplicated)
    )


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _check_index_hook_drift(
    store: MemoryStore, ctx: _CheckContext
) -> tuple[CheckResult, ...]:
    by_target = {e.target: e for e in store.index_entries}
    results = []
    for memory in store.memories:
        entry = by_target.get(f"{memory.slug}.md")
        if entry is None or not memory.frontmatter.description:
            continue
        hook_tokens = _tokenize(entry.hook)
        desc_tokens = _tokenize(memory.frontmatter.description)
        if not hook_tokens or not desc_tokens:
            continue
        overlap = hook_tokens & desc_tokens
        if not overlap:
            results.append(
                CheckResult(
                    check_id="index-hook-drift",
                    severity="info",
                    target=memory.slug,
                    message=f"index hook for '{memory.slug}' shares no tokens with its description",
                    fixable=False,
                    detail=f"hook={entry.hook!r} description={memory.frontmatter.description!r}",
                )
            )
    return tuple(results)


def _load_claude_md_texts(ctx: _CheckContext) -> dict[Path, str]:
    texts: dict[Path, str] = {}
    for path in ctx.claude_md_paths:
        if path.is_file():
            texts[path] = path.read_text(encoding="utf-8", errors="ignore")
    return texts


def _check_contradiction_topic_overlap(
    store: MemoryStore, ctx: _CheckContext
) -> tuple[CheckResult, ...]:
    """Mechanical anchor co-mention check. NOT semantic contradiction detection,
    makes no LLM call, and never edits CLAUDE.md. CLAUDE.md wins in any conflict.
    """
    claude_texts = _load_claude_md_texts(ctx)
    if not claude_texts:
        return ()

    results = []
    for memory in store.memories:
        anchors = extract_anchors(memory.body)
        for anchor in anchors:
            for path, text in claude_texts.items():
                if anchor in text:
                    mem_idx = memory.body.find(anchor)
                    excerpt_memory = memory.body[
                        max(0, mem_idx - 40) : mem_idx + len(anchor) + 40
                    ]
                    idx = text.find(anchor)
                    excerpt_claude = text[max(0, idx - 40) : idx + len(anchor) + 40]
                    results.append(
                        CheckResult(
                            check_id="contradiction-topic-overlap",
                            severity="info",
                            target=memory.slug,
                            message=f"'{anchor}' is mentioned in both {memory.slug}.md and {path.name} — CLAUDE.md wins in any conflict",
                            fixable=False,
                            detail=f"memory: ...{excerpt_memory}...\nclaude_md: ...{excerpt_claude}...",
                        )
                    )
    return tuple(results)


def _check_schema_no_frontmatter(
    store: MemoryStore, ctx: _CheckContext
) -> tuple[CheckResult, ...]:
    return tuple(
        CheckResult(
            check_id="schema-no-frontmatter",
            severity="warn",
            target=name,
            message=f"'{Path(name).name}' has no --- frontmatter block",
            fixable=True,
        )
        for name in store.non_memory_files
        if _shape_of_path(name) == SchemaShape.NO_FRONTMATTER
    )


_UNPARSEABLE_ERRORS = (TypeError, ValueError, OSError)  # ValueError covers UnicodeDecodeError


def _shape_of_path(path_str: str) -> SchemaShape | None:
    # non_memory_files stores raw paths; re-derive shape cheaply by reading
    # the file's own leading bytes rather than re-parsing the whole memory.
    # None for a missing file or one whose frontmatter cannot be parsed
    # (non-mapping YAML, non-UTF-8); schema-unparseable reports those.
    from memory.parser import parse_frontmatter

    path = Path(path_str)
    if not path.is_file():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            head = f.read(4096)
        return parse_frontmatter(head if head.startswith("---") else "").shape
    except _UNPARSEABLE_ERRORS:
        return None


def _check_schema_unparseable(
    store: MemoryStore, ctx: _CheckContext
) -> tuple[CheckResult, ...]:
    from memory.parser import parse_frontmatter

    results = []
    for name in store.non_memory_files:
        path = Path(name)
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
            parse_frontmatter(text if text.startswith("---") else "")
        except _UNPARSEABLE_ERRORS:
            results.append(
                CheckResult(
                    check_id="schema-unparseable",
                    severity="warn",
                    target=path.name,
                    message=f"'{path.name}' frontmatter is not a mapping or the file is not UTF-8",
                    fixable=False,
                )
            )
    return tuple(results)


def _is_unterminated_file(path_str: str) -> bool:
    try:
        text = Path(path_str).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return False
    return _has_unterminated_frontmatter(text)


def _check_schema_missing_type(
    store: MemoryStore, ctx: _CheckContext
) -> tuple[CheckResult, ...]:
    return tuple(
        CheckResult(
            check_id="schema-missing-type",
            severity="warn",
            target=m.slug,
            message=f"'{m.slug}.md' has frontmatter but no type in either dialect",
            fixable=not _is_unterminated_file(m.path),
        )
        for m in store.memories
        if m.frontmatter.shape != SchemaShape.NO_FRONTMATTER
        and m.frontmatter.type is None
    )


def _check_schema_ambiguous(
    store: MemoryStore, ctx: _CheckContext
) -> tuple[CheckResult, ...]:
    results = []
    for m in store.memories:
        node_type_ok = m.frontmatter.node_type == "memory"
        has_why_how = bool(m.why or m.how_to_apply)
        has_name_desc = bool(m.frontmatter.name or m.frontmatter.description)
        if not node_type_ok and not has_why_how and not has_name_desc:
            results.append(
                CheckResult(
                    check_id="schema-ambiguous",
                    severity="warn",
                    target=m.slug,
                    message=f"'{m.slug}.md' passes is_memory but lacks node_type, Why/How-to-apply, and name/description",
                    fixable=False,
                )
            )
    return tuple(results)


def _check_schema_flat_dialect(
    store: MemoryStore, ctx: _CheckContext
) -> tuple[CheckResult, ...]:
    return tuple(
        CheckResult(
            check_id="schema-flat-dialect",
            severity="info",
            target=m.slug,
            message=f"'{m.slug}.md' uses the flat dialect (drift metric, not a defect)",
            fixable=False,
        )
        for m in store.memories
        if m.frontmatter.shape == SchemaShape.FLAT
    )


def _check_schema_unknown_key(
    store: MemoryStore, ctx: _CheckContext
) -> tuple[CheckResult, ...]:
    return tuple(
        CheckResult(
            check_id="schema-unknown-key",
            severity="info",
            target=m.slug,
            message=f"'{m.slug}.md' has {len(m.frontmatter.unknown_keys)} unrecognized frontmatter key(s), preserved via unknown_keys",
            fixable=False,
        )
        for m in store.memories
        if m.frontmatter.unknown_keys
    )


def _check_schema_name_slug_mismatch(
    store: MemoryStore, ctx: _CheckContext
) -> tuple[CheckResult, ...]:
    results = []
    for m in store.memories:
        if not m.frontmatter.name:
            continue
        expected_slug = slugify(m.frontmatter.name)
        # A "<type>-" filename prefix is a naming convention, not a mismatch.
        accepted = {expected_slug}
        if m.frontmatter.type is not None:
            accepted.add(f"{m.frontmatter.type.value}_{expected_slug}")
        if expected_slug and normalize_slug(m.slug) not in accepted:
            results.append(
                CheckResult(
                    check_id="schema-name-slug-mismatch",
                    severity="info",
                    target=m.slug,
                    message=f"frontmatter name '{m.frontmatter.name}' does not slugify to filename '{m.slug}'",
                    fixable=False,
                )
            )
    return tuple(results)


def _check_ref_broken_wikilink(
    store: MemoryStore, ctx: _CheckContext
) -> tuple[CheckResult, ...]:
    known_slugs = {normalize_slug(m.slug) for m in store.memories}
    results = []
    for m in store.memories:
        for link in m.wikilinks:
            if link not in known_slugs:
                results.append(
                    CheckResult(
                        check_id="ref-broken-wikilink",
                        severity="warn",
                        target=m.slug,
                        message=f"[[{link}]] in '{m.slug}.md' does not resolve to any known memory",
                        fixable=False,
                    )
                )
    return tuple(results)


_DEAD_PATH_PREFIXES = ("src/", ".llm/", "workflows/")
# Repo-relative mentions only: the lookbehind keeps "out/src/x" or
# "/abs/workflows/y" from being read as a path under the repo root.
_PATH_MENTION_RE = re.compile(r"(?<![\w./-])(?:src|\.llm|workflows)/[A-Za-z0-9_./-]+")
_CLI_MENTION_RE = re.compile(r"\./bin/([A-Za-z0-9_-]+)")


def _check_ref_dead_path(
    store: MemoryStore, ctx: _CheckContext
) -> tuple[CheckResult, ...]:
    # A repo that does not exist (deleted project, worktree slug decoded to a
    # garbled path) cannot tell us which paths are dead; skip rather than flag all.
    if ctx.repo is None or not ctx.repo.is_dir():
        return ()
    results = []
    for m in store.memories:
        for match in _PATH_MENTION_RE.findall(m.body):
            if not match.startswith(_DEAD_PATH_PREFIXES):
                continue
            if not (ctx.repo / match).exists():
                results.append(
                    CheckResult(
                        check_id="ref-dead-path",
                        severity="warn",
                        target=m.slug,
                        message=f"'{m.slug}.md' references path '{match}' which no longer exists under {ctx.repo}",
                        fixable=False,
                    )
                )
    return tuple(results)


def _git_toplevel() -> Path | None:
    """Git toplevel of the current directory, or None outside a checkout."""
    try:
        out = subprocess.check_output(  # nosec B603 B607 - fixed git argv, no shell
            ["git", "rev-parse", "--show-toplevel"],
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        ).strip()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        # Not in a git checkout (or git missing): callers skip their check
        # rather than flagging every mention as dead.
        return None
    return Path(out) if out else None


def _resolve_repo_root(
    repo: Path | None, marker: str, *, allow_toplevel_fallback: bool = True
) -> Path | None:
    """Repo root containing ``marker``: ``repo`` itself, else the git toplevel.

    ``repo`` for worktree slugs decodes to a non-existent garbled path (e.g.
    /Users/name/code/repo--claude-worktrees-<name>), so fall back to the git
    toplevel rather than Path.cwd(), which only works from the repo root.
    Callers that execute something under the root pass
    ``allow_toplevel_fallback=False`` so the cwd's checkout is never trusted.
    """
    if repo is not None and (repo / marker).exists():
        return repo
    if not allow_toplevel_fallback:
        return None
    top = _git_toplevel()
    if top is not None and (top / marker).exists():
        return top
    return None


def _check_ref_dead_cli(
    store: MemoryStore, ctx: _CheckContext
) -> tuple[CheckResult, ...]:
    if ctx.repo is None:
        return ()
    root = _resolve_repo_root(ctx.repo, "bin")
    if root is None:
        return ()
    bin_dir = root / "bin"
    results = []
    for m in store.memories:
        for cli_name in _CLI_MENTION_RE.findall(m.body):
            if not (bin_dir / cli_name).exists():
                results.append(
                    CheckResult(
                        check_id="ref-dead-cli",
                        severity="warn",
                        target=m.slug,
                        message=f"'{m.slug}.md' references './bin/{cli_name}' which does not exist",
                        fixable=False,
                    )
                )
    return tuple(results)


# Require explicit PR context — bare "#NNN" matches issues, step numbers, etc.
_PR_NUMBER_RE = re.compile(r"(?:PR\s*#|pull/)(\d+)")


_GITHUB_CALL_TIMEOUT_SECONDS = 30


def _default_github_caller(github_bin: Path, pr_number: int) -> dict:
    """Call ``github_bin pr view`` for one PR number; return parsed JSON."""
    result = subprocess.run(  # nosec B603 - fixed argv, no shell; pr_number is an int
        [str(github_bin), "pr", "view", "--pr", str(pr_number), "--fields", "state"],
        capture_output=True,
        text=True,
        check=False,
        cwd=github_bin.parent.parent,
        timeout=_GITHUB_CALL_TIMEOUT_SECONDS,
    )
    return json.loads(result.stdout)


def _pr_state(caller: Callable[[int], dict], pr_num: int) -> str:
    """Upper-cased PR state, or "" when the lookup fails or returns a non-object."""
    try:
        data = caller(pr_num)
    except Exception:  # nosec B110 - network failure must not abort the other PR lookups
        return ""
    if not isinstance(data, dict):
        return ""
    return str(data.get("state") or "").upper()


def _check_stale_superseded_pr(
    store: MemoryStore,
    ctx: _CheckContext,
    *,
    github_caller: Callable[[int], dict] | None = None,
) -> tuple[CheckResult, ...]:
    """Scan project memories for PR references and flag closed/merged PRs.

    Skips silently if bin/github cannot be found under the explicit/inferred
    repo (the cwd's git toplevel is never used: the script is executed), or the call fails or returns a non-object — network may be
    unavailable in offline contexts. Only runs on PROJECT memories.
    """
    caller = github_caller
    if caller is None:
        root = _resolve_repo_root(
            ctx.repo, "bin/github", allow_toplevel_fallback=False
        )
        if root is None:
            return ()
        caller = partial(_default_github_caller, root / "bin" / "github")

    results = []
    for m in store.memories:
        if m.frontmatter.type != MemoryType.PROJECT:
            continue
        pr_numbers = {int(n) for n in _PR_NUMBER_RE.findall(m.body)}
        for pr_num in sorted(pr_numbers):
            state = _pr_state(caller, pr_num)
            if state in ("CLOSED", "MERGED"):
                results.append(
                    CheckResult(
                        check_id="stale-superseded-pr",
                        severity="warn",
                        target=m.slug,
                        message=f"project memory references closed/merged PR #{pr_num} (state: {state.lower()})",
                        fixable=False,
                    )
                )
    return tuple(results)


CHECK_REGISTRY: dict[str, Check] = {
    "staleness": _check_staleness,
    "index-orphan": _check_index_orphan,
    "index-dangling": _check_index_dangling,
    "index-duplicate-entry": _check_index_duplicate_entry,
    "index-duplicate-section": _check_index_duplicate_section,
    "index-hook-drift": _check_index_hook_drift,
    "contradiction-topic-overlap": _check_contradiction_topic_overlap,
    "schema-no-frontmatter": _check_schema_no_frontmatter,
    "schema-unparseable": _check_schema_unparseable,
    "schema-missing-type": _check_schema_missing_type,
    "schema-ambiguous": _check_schema_ambiguous,
    "schema-flat-dialect": _check_schema_flat_dialect,
    "schema-unknown-key": _check_schema_unknown_key,
    "schema-name-slug-mismatch": _check_schema_name_slug_mismatch,
    "ref-broken-wikilink": _check_ref_broken_wikilink,
    "ref-dead-path": _check_ref_dead_path,
    "ref-dead-cli": _check_ref_dead_cli,
    "stale-superseded-pr": _check_stale_superseded_pr,
}

# Checks run when the caller names none. stale-superseded-pr calls GitHub, so
# it runs only when requested by id — the default catalog stays offline.
_NETWORK_CHECKS = frozenset({"stale-superseded-pr"})
DEFAULT_CHECKS: tuple[str, ...] = tuple(c for c in CHECK_REGISTRY if c not in _NETWORK_CHECKS)


def _default_claude_md_paths(repo: Path | None, *, cwd_default: bool = True) -> tuple[Path, ...]:
    if repo is None and not cwd_default:
        return ()
    base = repo or Path.cwd()
    paths: list[Path] = []
    for pattern in _DEFAULT_CLAUDE_MD_GLOBS:
        if "*" in pattern:
            paths.extend(sorted(base.glob(pattern)))
        else:
            candidate = base / pattern
            if candidate.is_file():
                paths.append(candidate)
    return tuple(paths)


def _apply_fix_index_orphan(
    store: MemoryStore, findings: tuple[CheckResult, ...]
) -> None:
    if not store.index_path:
        return
    by_slug = {m.slug: m for m in store.memories}
    for finding in findings:
        if finding.check_id == "index-orphan" and finding.target in by_slug:
            append_entry(store.index_path, by_slug[finding.target])


def _apply_fix_index_dangling(
    store: MemoryStore, findings: tuple[CheckResult, ...]
) -> None:
    if not store.index_path:
        return
    for finding in findings:
        if finding.check_id == "index-dangling":
            remove_entry(store.index_path, finding.target)


def _apply_fix_index_duplicate_section(
    store: MemoryStore, findings: tuple[CheckResult, ...]
) -> None:
    if not store.index_path:
        return
    if any(f.check_id == "index-duplicate-section" for f in findings):
        merge_duplicate_sections(store.index_path)


def _apply_fix_schema_missing_type(
    store: MemoryStore, findings: tuple[CheckResult, ...]
) -> None:
    by_slug = {m.slug: m for m in store.memories}
    for finding in findings:
        if finding.check_id != "schema-missing-type" or not finding.fixable:
            continue
        memory = by_slug.get(finding.target)
        if memory is None:
            continue
        prefix = re.split(r"[_-]", memory.slug, maxsplit=1)[0]
        inferred = _TYPE_PREFIX_TO_MEMORY_TYPE.get(prefix)
        if inferred is None:
            continue
        _rewrite_frontmatter_type(Path(memory.path), inferred)


def _free_archive_path(archive_dir: Path, name: str) -> Path:
    """``archive_dir/name``, or ``<stem>.<n><suffix>`` when that already exists."""
    candidate = archive_dir / name
    if not (candidate.exists() or candidate.is_symlink()):
        return candidate
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 1
    while True:
        candidate = archive_dir / f"{stem}.{n}{suffix}"
        if not (candidate.exists() or candidate.is_symlink()):
            return candidate
        n += 1


def _apply_fix_schema_no_frontmatter(
    store: MemoryStore, findings: tuple[CheckResult, ...]
) -> None:
    for finding in findings:
        if finding.check_id != "schema-no-frontmatter":
            continue
        src = Path(finding.target)
        if not src.is_file():
            continue
        archive_dir = src.parent / _ARCHIVE_DIRNAME
        archive_dir.mkdir(exist_ok=True)
        _write_backup(src)
        dest = _free_archive_path(archive_dir, src.name)
        # Atomic write + unlink instead of shutil.move: never overwrites an
        # existing archive entry and never leaves a half-written destination.
        atomic_write_text(dest, src.read_text(encoding="utf-8"), refuse_symlink=True)
        src.unlink()


def _write_backup(path: Path) -> None:
    # NOSONAR - path is memory.path/finding.target from a store already
    # discovered and parsed by discover_stores() off local disk, not an
    # HTTP-sourced value; write targets the same file's own .bak sibling.
    backup_path = path.with_suffix(path.suffix + ".bak")
    if backup_path.is_symlink():
        # Replace the link itself; writing through it would clobber its target.
        backup_path.unlink()
    backup_path.write_bytes(path.read_bytes())  # NOSONAR - see above


def _has_unterminated_frontmatter(text: str) -> bool:
    if not text.startswith("---"):
        return False
    return not any(line.strip() == "---" for line in text.split("\n")[1:])


def _metadata_child_indent(lines: list[str], metadata_idx: int, end_idx: int) -> str:
    """Indent of the first child line under ``metadata:``; two spaces if none."""
    for line in lines[metadata_idx + 1 : end_idx]:
        stripped = line.lstrip()
        if stripped and len(stripped) < len(line):
            return line[: len(line) - len(stripped)]
        if stripped:
            break
    return "  "


def _rewrite_frontmatter_type(path: Path, memory_type: MemoryType) -> bool:
    """Add ``type`` to a memory's frontmatter; True when the file was changed.

    Leaves an unterminated frontmatter block untouched (returns False) rather
    than prepending a second block. A ``.bak`` is written before any change.
    """
    # NOSONAR - path is memory.path from a store already discovered and
    # parsed by discover_stores() off local disk, not an HTTP-sourced value.
    text = path.read_text(encoding="utf-8")
    if _has_unterminated_frontmatter(text):
        return False
    if text.startswith("---"):
        lines = text.split("\n")
        closing_idx = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
        # Detect nested dialect by presence of 'metadata:' line
        metadata_idx = next(
            (i for i in range(1, closing_idx) if lines[i].strip() == "metadata:"),
            None,
        )
        if metadata_idx is not None:
            indent = _metadata_child_indent(lines, metadata_idx, closing_idx)
            lines.insert(metadata_idx + 1, f"{indent}type: {memory_type.value}")
        else:
            lines.insert(closing_idx, f"type: {memory_type.value}")
        new_text = "\n".join(lines)
    else:
        new_text = f"---\ntype: {memory_type.value}\n---\n\n{text}"
    _write_backup(path)
    atomic_write_text(path, new_text)
    return True


_FIXERS: dict[str, Callable[[MemoryStore, tuple[CheckResult, ...]], None]] = {
    "index-orphan": _apply_fix_index_orphan,
    "index-dangling": _apply_fix_index_dangling,
    "index-duplicate-section": _apply_fix_index_duplicate_section,
    "schema-missing-type": _apply_fix_schema_missing_type,
    "schema-no-frontmatter": _apply_fix_schema_no_frontmatter,
}


def _resolve_repo_path(store: MemoryStore, repo: str | Path | None) -> Path | None:
    """Explicit repo wins; else the store's own inferred repo; else None."""
    if repo is not None:
        return Path(repo)
    return Path(store.inferred_repo) if store.inferred_repo else None


def run_checks(
    store: MemoryStore,
    *,
    checks: tuple[str, ...] | None = None,
    repo: str | Path | None = None,
    claude_md: tuple[str, ...] = (),
    fix: bool = False,
    dry_run: bool = False,
    cwd_default: bool = True,
) -> tuple[CheckResult, ...]:
    """Dispatch each selected check from CHECK_REGISTRY and return flattened findings.

    checks=None runs DEFAULT_CHECKS (every offline check). When fix=True, applies only the
    repairs marked fixable (index orphan/dangling/duplicate-section,
    schema-missing-type inference, schema-no-frontmatter archival) — a .bak
    of any modified file is written first (a symlinked .bak is replaced, never
    written through), every rewrite is atomic (temp file + rename), archival
    never overwrites an earlier _archive/ entry (it appends .<n> to the stem),
    and a file with an unterminated frontmatter block is left alone and not
    reported fixable. Never
    rewrites an index hook line, and never edits CLAUDE.md under any flag.
    Returns an empty tuple for a clean store, never None; a check that
    raises surfaces as an error-severity CheckResult rather than silently
    reducing the finding count.

    dry_run=True with fix=True reports findings (fixable ones are flagged) but
    writes nothing. cwd_default=False stops a store with no known repo from
    inheriting the current directory's CLAUDE.md files (multi-store scans).
    """
    selected = checks if checks is not None else DEFAULT_CHECKS
    unknown = set(selected) - set(CHECK_REGISTRY.keys())
    if unknown:
        raise ValueError(f"unknown check id(s): {', '.join(sorted(unknown))}")

    repo_path = _resolve_repo_path(store, repo)
    claude_md_paths = (
        tuple(Path(p) for p in claude_md)
        if claude_md
        else _default_claude_md_paths(repo_path, cwd_default=cwd_default)
    )
    ctx = _CheckContext(repo=repo_path, claude_md_paths=claude_md_paths, fix=fix)

    findings: list[CheckResult] = []
    for check_id in selected:
        check_fn = CHECK_REGISTRY[check_id]
        try:
            findings.extend(check_fn(store, ctx))
        except Exception as exc:  # NOSONAR - a check failure must surface, never vanish
            findings.append(
                CheckResult(
                    check_id=check_id,
                    severity="error",
                    target=store.project_slug,
                    message=f"check '{check_id}' raised: {exc}",
                    fixable=False,
                )
            )

    if fix and not dry_run:
        results_tuple = tuple(findings)
        for check_id, fixer in _FIXERS.items():
            if check_id in selected:
                fixer(store, results_tuple)

    return tuple(findings)
