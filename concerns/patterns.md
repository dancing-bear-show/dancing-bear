# Patterns Review Guide

## When loaded

Load this guide for any diff — it applies to all file types. Concern
applicability by file type:

- `hardcoded-absolute-path`: `.yaml` and `.md` files
- `pr-desc-title-mismatch`: any PR (always loaded at the review stage)
- all other concerns: `.py` files

## Concerns

### raw-dict-return
- **severity**: minor
- **check**: Verify structured data returned from functions uses frozen
  dataclasses, not plain dicts.
- **triggers**: Functions returning `dict[`, `-> dict`, or `return {` in
  non-CLI, non-serialization code.
- **example**: `return {"id": item.id, "name": item.name}` from a domain
  module method — callers get no type safety and no IDE completion.
  Use a `@dataclass(frozen=True)` instead.

### missing-type-hints
- **severity**: minor
- **check**: Verify all public function signatures carry type hints on every
  parameter and the return type.
- **triggers**: New or modified `def` statements in non-test files; functions
  with `*args` or `**kwargs` that lack annotations.
- **example**: `def fetch(key, limit=10):` — missing parameter and return
  type hints. Fix: `def fetch(key: str, limit: int = 10) -> list[Result]:`.

### bare-generic
- **severity**: minor
- **check**: Verify type hints use parameterized generics (`dict[str, X]`,
  `list[X]`) rather than bare `dict` or `list`.
- **triggers**: Type annotations containing bare `dict`, `list`, `tuple`,
  `set`, or `type` without parameters; `from typing import Dict, List, Optional,
  Union` imports (prefer PEP 585/604 forms for Python 3.11+).
- **example**: `def process(items: list) -> dict:` — bare generics give the
  type checker nothing to verify. Fix: `def process(items: list[Item]) -> dict[str, int]:`.

### mixed-type-hint-style
- **severity**: minor
- **check**: Verify that a module does not mix `Optional[X]` / `Union[X, Y]`
  (legacy `typing` style) with `X | None` / `X | Y` (PEP 604 style) in the
  same file. Partial adoption is harder to audit than either fully typed or
  fully untyped code.
- **triggers**: A `.py` file that imports `Optional` or `Union` from `typing`
  **and** also uses `X | None` or `X | Y` in the same file; files with a mix
  of `List[X]`/`Dict[K, V]` generics and `list[X]`/`dict[K, V]` generics.
- **example**: A module with `def fetch(key: Optional[str]) -> dict` in one
  function and `def store(key: str | None) -> None` in another — flag the
  entire file for a normalisation pass to PEP 585/604 style.

### inaccurate-type-annotations
- **severity**: major
- **check**: Verify type annotations are specific enough to catch real
  attribute-access and key-access errors.
- **triggers**: `list[object]` or `list[Any]` parameters where the function
  body accesses named attributes (`r.field`) on list elements; `-> object`
  return where callers index or attribute-access the result.
- **example**: `def summarize(rows: list[object]) -> None:` where the body
  does `row.domain` — `object` has no `domain` attribute. Use the concrete
  dataclass type.

### comment-drift
- **severity**: minor
- **check**: Verify docstrings and inline comments describe behavior that
  matches the current implementation.
- **triggers**: Any `.py` file with docstrings or inline comments; refactored
  functions whose bodies changed but whose docstrings were not updated.
- **example**: Docstring says `try/except/else` but code uses `try/except`
  with no `else`. Treat comment drift as a lint error — update comments in
  the same commit as the code change.

### missing-none-annotation
- **severity**: major
- **check**: Verify parameters with `default=None` include `| None` in their
  type annotation. A parameter annotated `str` with `default=None` is type-incorrect.
- **triggers**: `def ` with parameters of the form `param: T = None` where `T`
  does not include `| None`; function signatures where `= None` appears but the
  type hint is a bare non-nullable type.
- **example**: `def search(query: str, limit: int = None) -> list:` — `limit`
  can be `None` but is typed as `int`. Fix:
  `def search(query: str, limit: int | None = None) -> list:`.

### instance-classvar-field
- **severity**: minor
- **check**: Verify that constant-like dataclass fields shared across all
  instances (lookup tables, status sets, threshold dicts) are declared as
  `ClassVar` rather than per-instance `field(default_factory=...)` — the
  latter allocates a new copy for every instance.
- **triggers**: `@dataclass` classes with `field(default_factory=lambda: {...})`
  or `field(default_factory=lambda: [...])` where the value is a constant (no
  parameters, same across all instances).
- **example**: `@dataclass class Config: ACTIVE: set[str] = field(default_factory=lambda:
  {"on", "active"})` — allocates a new set per instance. Fix:
  `from typing import ClassVar; ACTIVE: ClassVar[set[str]] = {"on", "active"}`.

### dataclass-should-be-frozen
- **severity**: minor
- **check**: Verify that new dataclasses used purely for data transfer (no
  mutation after construction) are declared `frozen=True` rather than mutable.
- **triggers**: New `@dataclass` declarations (not `@dataclass(frozen=True)`)
  in non-base-class contexts where no field mutation is visible within the same diff.
- **example**: `@dataclass class QueryResult: rows: list[dict]; total: int` —
  if `rows` and `total` are never mutated after construction, add `frozen=True`.
  Exception: base classes and classes with deliberate post-construction mutation.

### class-should-be-dataclass
- **severity**: minor
- **check**: Verify that plain classes whose `__init__` assigns 3+ parameters
  directly to `self` with no other logic are converted to `@dataclass`.
- **triggers**: `class Foo:` with `def __init__(self, a, b, c):` followed by
  3+ bare `self.x = x` assignments and no validation logic.
- **example**: `class FilterConfig: def __init__(self, team, window, fmt):
  self.team = team; self.window = window; self.fmt = fmt` — 3 bare assignments.
  Fix: `@dataclass(frozen=True) class FilterConfig: team: str; window: str; fmt: str`.

### pr-desc-title-mismatch
- **severity**: minor
- **check**: Verify the PR title scope/type matches the primary changed domain
  and the PR body accurately describes what changed — no claims about files,
  test counts, or behaviors that the diff does not support.
- **triggers**: Any PR.
- **example**: Title says `fix(mail)` but the diff only touches `calendars/`;
  body claims "adds 10 new tests" but `git diff --stat` shows 4. Treat
  mismatches as minor issues requiring correction before merge.

### hardcoded-absolute-path
- **severity**: major
- **check**: Verify no absolute paths are committed in YAML or markdown files —
  paths like `/Users/...` or `/opt/homebrew/...` are non-portable and bake
  personal usernames or OS-specific layouts into shared config.
- **triggers**: Any `.yaml` or `.md` file containing `/Users/`, `/opt/homebrew/`,
  `/home/`, or other filesystem-rooted paths that are not workspace-relative.
- **example**: `./bin/mail-assistant` replaced by `/Users/bcs/code/dancing-bear/bin/mail-assistant`
  — the path breaks on any other machine. Use workspace-relative or PATH-resolved
  commands instead.

### core-helper-bypassed
- **severity**: minor
- **check**: Verify that new code uses `core/` helpers rather than re-implementing
  equivalent functionality inline. The most common bypass patterns: (1) manual YAML
  read/write instead of `core/` YAML helpers, (2) manual argparse `--output` flag
  instead of using the framework's output format support, (3) custom credential
  loading instead of the profile-based credentials pattern, (4) `python -m` subprocess
  invocations instead of `./bin/` entry points.
- **triggers**: `import yaml; yaml.safe_load(open(...))` inline in CLI handlers when
  a project YAML helper exists; `parser.add_argument("--output"` manually declared
  when the `CLIApp` framework provides this via `add_common_args`; credential loading
  that does not use `~/.config/credentials.ini` profile lookup.
- **example**: `data = yaml.safe_load(open(args.config))` in a CLI handler —
  replace with the `read_yaml()` helper from `core/` which handles the `or {}`
  fallback and consistent error reporting. Also: constructing `argparse.ArgumentParser`
  directly in a new CLI instead of using the `CLIApp` framework from `core/cli_framework.py`.

### lazy-import-violation
- **severity**: major
- **check**: Verify that optional dependencies (Google APIs, PyYAML, third-party
  libraries) are imported lazily inside the function that uses them, not at module
  top-level. Global imports of optional deps break the CLI for users who lack that
  dependency even when they are not using the feature.
- **triggers**: Top-level `import yaml`, `from googleapiclient`, `import msal`,
  `import openpyxl`, or any other optional dependency import outside a function body
  in a domain or CLI module; new `import` statements at module level for packages
  not guaranteed to be installed.
- **example**: `import yaml` at the top of `mail/config_resolver.py` — any import
  of this module (including for `--help`) fails with `ModuleNotFoundError` if PyYAML
  is not installed. Fix: move `import yaml` inside the function that calls `yaml.safe_load`.
  See `.llm/PATTERNS.md` "Lazy Imports for Optional Deps" for the canonical pattern.

### plan-apply-safety
- **severity**: major
- **check**: Verify that commands that modify external state (mail labels, filters,
  calendar events) require explicit opt-in (`--apply`, `--force`, or similar) and
  default to a preview/dry-run mode. Safe-by-default is a core project constraint.
- **triggers**: New CLI subcommands in `mail/`, `calendars/`, `schedule/`, or `phone/`
  that write, delete, or modify external state; command handlers that perform destructive
  operations without checking `args.dry_run` or `args.apply`.
- **example**: A new `filters sync` subcommand that applies changes immediately without
  a `--dry-run` flag — agents or users calling it lose the preview step. Fix: default
  to dry-run, require `--apply` for real execution. See `.llm/PATTERNS.md`
  "Plan/Apply Flow (Safe by Default)" for the canonical pattern.

### agentic-schema-stale
- **severity**: minor
- **check**: Verify that the `--agentic` schema output of a modified CLI accurately
  reflects its current flags and subcommands. Stale agentic schemas mislead LLM agents
  into using wrong invocations.
- **triggers**: A PR adds or removes CLI flags, subcommands, or entry points without
  verifying the agentic output; changes to `build_parser()` or command handler
  registration that are not reflected in the `--agentic` output.
- **example**: PR adds `--delete-missing` flag to `labels sync` but the `--agentic`
  schema cached in `.llm/` still shows the old flag list — agents calling
  `./bin/llm agentic --stdout` get a stale schema. Fix: run
  `./bin/llm derive-all --out-dir .llm --include-generated` after changing any
  CLI surface and include the updated `.llm/` artifacts in the PR.
