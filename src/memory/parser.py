"""Parses a memory markdown file into a Memory dataclass — frontmatter dialect detection, Why/How-to-apply extraction, wikilink and rule-anchor extraction."""

from __future__ import annotations

import re
import string
from datetime import UTC, datetime
from pathlib import Path

from memory.models import (
    IndexEntry,
    Memory,
    MemoryFrontmatter,
    MemoryType,
    SchemaShape,
)

__all__ = [
    "extract_anchors",
    "extract_wikilinks",
    "normalize_slug",
    "parse_frontmatter",
    "parse_memory_file",
]

# Wikilink inner-text acceptance pattern: lowercase words joined by '_'/'-'.
# Written with an explicit [a-z0-9] class (never \w) so it never silently
# broadens to Unicode word characters.
_WIKILINK_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")
_WIKILINK_INCLUSION_RE = re.compile(r"^[a-z]+(?:[_-][a-z0-9]+)+$")
_WIKILINK_EXCLUDED_CHARS = ("/", "!", "$", '"', "'", "`")

_WHY_MARKER = "**Why:**"
_HOW_MARKER = "**How to apply:**"

_BACKTICK_RE = re.compile(r"`([^`]+)`")
_QUOTED_FLAG_RE = re.compile(r"(['\"])(-{1,2}[A-Za-z0-9][A-Za-z0-9-]*)\1")

# Tokens that appear in almost every memory body and in CLAUDE.md, making them
# useless as contradiction signals. All comparisons are lowercase after
# stripping surrounding punctuation — entries here must be lowercase.
# Characters stripped from the outer edges of raw backtick tokens before
# length/stoplist checks. Internal characters are unaffected by strip().
# Removes prose-adjacent noise like trailing commas, periods, colons, etc.
# so that `pytest,` normalizes to `pytest` and hits the stoplist as expected.
_ANCHOR_STRIP_CHARS: str = string.punctuation + string.whitespace

_ANCHOR_STOPLIST: frozenset[str] = frozenset(
    {
        # filesystem / shell generics
        # Note: "bin/", "./bin/", "src/" are intentionally absent — after
        # _ANCHOR_STRIP_CHARS strips '/' and '.', they normalize to 3-char
        # tokens ("bin", "src") that are already filtered by the min-length=4
        # guard in extract_anchors() before the stoplist is ever consulted.
        "find",
        "cat",
        "tail",
        "grep",
        "ls",
        "head",
        # programming generics
        "data",
        "name",
        "main",
        "title",
        "type",
        "path",
        "file",
        "args",
        "output",
        "format",
        "index",
        "module",
        "expr",
        "argparse",
        # boolean / null literals
        "true",
        "false",
        "none",
        "null",
        # format / output tokens
        "json",
        "yaml",
        "table",
        # workflow / agent generics that appear everywhere in CLAUDE.md
        "agent",
        "workflow",
        "pytest",
        "isolation",
        "discover",
        "telemetry",
        "claude",
        # common English words that leak through backtick spans
        "done",
        "complete",
        "events",
    }
)


def parse_frontmatter(text: str) -> MemoryFrontmatter:
    """Parse YAML frontmatter and detect the dialect shape.

    Returns a MemoryFrontmatter with shape set according to the detected schema.
    A missing '---' block yields shape=NO_FRONTMATTER; an unterminated block or
    malformed YAML yields shape=ABSENT with all fields None — the caller cannot
    distinguish "malformed" from "absent" from this return value alone.
    """
    if not text.startswith("---"):
        return MemoryFrontmatter(
            name=None,
            description=None,
            type=None,
            node_type=None,
            origin_session_id=None,
            modified=None,
            shape=SchemaShape.NO_FRONTMATTER,
        )

    lines = text.split("\n")
    closing_idx = next(
        (i for i in range(1, len(lines)) if lines[i].strip() == "---"), None
    )
    if closing_idx is None:
        return MemoryFrontmatter(
            name=None,
            description=None,
            type=None,
            node_type=None,
            origin_session_id=None,
            modified=None,
            shape=SchemaShape.ABSENT,
        )

    yaml_block = "\n".join(lines[1:closing_idx])

    import yaml

    try:
        parsed = yaml.safe_load(yaml_block)
    except yaml.YAMLError:
        return MemoryFrontmatter(
            name=None,
            description=None,
            type=None,
            node_type=None,
            origin_session_id=None,
            modified=None,
            shape=SchemaShape.ABSENT,
        )

    if parsed is None:
        return MemoryFrontmatter(
            name=None,
            description=None,
            type=None,
            node_type=None,
            origin_session_id=None,
            modified=None,
            shape=SchemaShape.ABSENT,
        )

    if not isinstance(parsed, dict):
        # A wrong-shaped document (list/scalar) must not be indistinguishable
        # from a typeless one.
        raise TypeError(
            f"frontmatter must parse to a mapping, got {type(parsed).__name__}"
        )

    metadata = parsed.get("metadata")
    if isinstance(metadata, dict):
        return _frontmatter_from_nested(parsed, metadata)
    if "type" in parsed:
        return _frontmatter_from_flat(parsed)
    return MemoryFrontmatter(
        name=_as_str_or_none(parsed.get("name")),
        description=_as_str_or_none(parsed.get("description")),
        type=None,
        node_type=None,
        origin_session_id=None,
        modified=_as_str_or_none(parsed.get("modified")),
        shape=SchemaShape.ABSENT,
        unknown_keys=dict(parsed),
    )


def _as_str_or_none(raw: object) -> str | None:
    """Coerce a YAML-parsed scalar to str, preserving None.

    YAML frontmatter values are not guaranteed to already be strings (e.g.
    `modified: 2026-08-06` parses to a date object) — every field on
    MemoryFrontmatter is typed str | None, so this normalizes at the
    boundary rather than pushing the coercion onto callers.
    """
    if raw is None:
        return None
    return str(raw)


def _coerce_memory_type(raw: object) -> MemoryType | None:
    if not raw:
        return None
    try:
        return MemoryType(str(raw))
    except ValueError:
        return None


def _frontmatter_from_nested(
    parsed: dict[str, object], metadata: dict[str, object]
) -> MemoryFrontmatter:
    known_metadata_keys = {"type", "originSessionId", "node_type", "modified"}
    known_top_keys = {"metadata", "name", "description", "modified"}
    unknown_keys: dict[str, object] = {
        f"metadata.{k}": v for k, v in metadata.items() if k not in known_metadata_keys
    }
    unknown_keys.update({k: v for k, v in parsed.items() if k not in known_top_keys})

    return MemoryFrontmatter(
        name=_as_str_or_none(parsed.get("name")),
        description=_as_str_or_none(parsed.get("description")),
        type=_coerce_memory_type(metadata.get("type")),
        node_type=_as_str_or_none(metadata.get("node_type")),
        origin_session_id=_as_str_or_none(metadata.get("originSessionId")),
        modified=_as_str_or_none(parsed.get("modified", metadata.get("modified"))),
        shape=SchemaShape.NESTED,
        unknown_keys=unknown_keys,
    )


def _frontmatter_from_flat(parsed: dict[str, object]) -> MemoryFrontmatter:
    known_flat_keys = {
        "type",
        "originSessionId",
        "node_type",
        "name",
        "description",
        "modified",
    }
    unknown_keys = {k: v for k, v in parsed.items() if k not in known_flat_keys}

    return MemoryFrontmatter(
        name=_as_str_or_none(parsed.get("name")),
        description=_as_str_or_none(parsed.get("description")),
        type=_coerce_memory_type(parsed.get("type")),
        node_type=_as_str_or_none(parsed.get("node_type")),
        origin_session_id=_as_str_or_none(parsed.get("originSessionId")),
        modified=_as_str_or_none(parsed.get("modified")),
        shape=SchemaShape.FLAT,
        unknown_keys=unknown_keys,
    )


def normalize_slug(slug: str) -> str:
    """Fold '-' to '_' so ``feedback-x`` and ``feedback_x`` compare equal.

    Wikilink targets are normalized this way by ``extract_wikilinks``; compare
    them against ``normalize_slug(memory.slug)``, never the raw slug, because
    on-disk filenames use either separator.
    """
    return slug.replace("-", "_")


def extract_wikilinks(body: str) -> tuple[str, ...]:
    """Extract normalized wikilink targets from a memory body.

    A [[...]] token is a candidate only if its inner text matches
    ``^[a-z]+(?:[_-][a-z0-9]+)+$`` and contains none of the excluded
    characters — this excludes bash test syntax (``[[ ! -d "$PWD" ]]``)
    and path references (``[[.llm/OTEL_GUIDE.md]]``). Accepted tokens have
    every '-' folded to '_' before being returned, so
    [[feedback-worktree-isolation]] normalizes to feedback_worktree_isolation.
    """
    result: list[str] = []
    for candidate in _WIKILINK_PATTERN.findall(body):
        if any(ch in candidate for ch in _WIKILINK_EXCLUDED_CHARS):
            continue
        if any(ch.isspace() for ch in candidate):
            continue
        if not _WIKILINK_INCLUSION_RE.match(candidate):
            continue
        result.append(candidate.replace("-", "_"))
    return tuple(result)


def extract_anchors(body: str) -> tuple[str, ...]:
    """Extract backtick-quoted identifiers and quoted CLI flags from a body.

    Lexical extraction only — no semantic interpretation, no LLM call. Feeds
    the mechanical contradiction-topic-overlap check, which greps CLAUDE.md
    for the same anchors. De-duplicates while preserving first-seen order.

    Filters applied before returning:
    - Minimum length of 4 characters (eliminates ``--``, ``ls``, ``ok``, etc.)
    - ``_ANCHOR_STOPLIST``: common shell/CLI tokens that appear in almost every
      memory body and in CLAUDE.md, making them useless contradiction signals.
    """
    backtick_anchors = _BACKTICK_RE.findall(body)
    quoted_flags = [flag for _, flag in _QUOTED_FLAG_RE.findall(body)]

    # Normalize backtick tokens only: quoted CLI flags are already clean (the
    # regex enforces [-A-Za-z0-9]+ syntax), but backtick spans may contain
    # trailing prose punctuation like `pytest,` or `yaml.` that prevents
    # stoplist hits. The docstring promises "all comparisons are lowercase
    # after stripping surrounding punctuation" — this makes the code match.
    normalized_backticks = [t.strip(_ANCHOR_STRIP_CHARS) for t in backtick_anchors]

    seen: set[str] = set()
    result: list[str] = []
    for anchor in normalized_backticks + quoted_flags:
        if len(anchor) < 4:
            continue
        if anchor.lower() in _ANCHOR_STOPLIST:
            continue
        if anchor not in seen:
            seen.add(anchor)
            result.append(anchor)
    return tuple(result)


def _split_why_how(body: str) -> tuple[str | None, str | None]:
    """Locate the Why/How-to-apply markers in a body.

    Returns (why, how_to_apply). Missing markers yield None, never an empty
    string, so downstream checks can distinguish "missing" from "present but
    blank".
    """
    why: str | None = None
    how_to_apply: str | None = None

    how_idx = body.find(_HOW_MARKER)
    why_idx = body.find(_WHY_MARKER)

    if why_idx != -1:
        why_end = how_idx if how_idx > why_idx else len(body)
        why_text = body[why_idx + len(_WHY_MARKER) : why_end].strip()
        why = why_text or None

    if how_idx != -1:
        how_text = body[how_idx + len(_HOW_MARKER) :].strip()
        how_to_apply = how_text or None

    return why, how_to_apply


def parse_memory_file(
    path: str | Path,
    *,
    project_slug: str,
    index_entries: tuple[IndexEntry, ...] = (),
) -> Memory:
    """Parse a memory file into a Memory dataclass instance.

    Splits the body into why/how_to_apply via the '**Why:**' / '**How to
    apply:**' markers. index_entries is keyword-only and matched against
    IndexEntry.target by basename so a caller cannot seed it positionally
    by accident.
    """
    path = Path(path)

    with open(path, encoding="utf-8") as f:
        content = f.read()

    if content.startswith("---"):
        lines = content.split("\n")
        closing_idx = next(
            (i for i in range(1, len(lines)) if lines[i].strip() == "---"), None
        )
        if closing_idx is not None:
            frontmatter_text = "\n".join(lines[: closing_idx + 1])
            body = "\n".join(lines[closing_idx + 1 :]).lstrip("\n")
        else:
            frontmatter_text = ""
            body = content
    else:
        frontmatter_text = ""
        body = content

    frontmatter = parse_frontmatter(frontmatter_text)
    why, how_to_apply = _split_why_how(body)

    wikilinks = extract_wikilinks(body)

    stat = path.stat()
    mtime = datetime.fromtimestamp(stat.st_mtime, tz=UTC)

    indexed = False
    index_hook: str | None = None
    index_section: str | None = None
    for entry in index_entries:
        if entry.target == path.name:
            indexed = True
            index_hook = entry.hook
            index_section = entry.section
            break

    slug = path.stem

    return Memory(
        slug=slug,
        path=str(path),
        project_slug=project_slug,
        frontmatter=frontmatter,
        body=body,
        why=why,
        how_to_apply=how_to_apply,
        wikilinks=wikilinks,
        mtime=mtime,
        size_bytes=stat.st_size,
        indexed=indexed,
        index_hook=index_hook,
        index_section=index_section,
    )
