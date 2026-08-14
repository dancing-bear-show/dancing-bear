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
  This covers workflow YAML and `.llm/FLOWS.yaml` too — flow commands and agent
  prompts are checked here rather than in the workflow guides.
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

### missing-csv-format-choice
- **severity**: minor
- **check**: Verify CLIs that add `--format` include `"csv"` in the formats list when output
  is tabular (list of rows with named columns).
- **triggers**: New or modified CLI `build_parser()` methods calling `add_format_argument`;
  `emit_rows(` call sites; CLI classes with `format_choices` that omit `"csv"`.
- **example**: `add_format_argument(parser, formats=["json", "table"])` for a CLI that emits
  row data — callers can't pipe to spreadsheets or `csvkit`. Fix: add `"csv"` to the formats list.

### dead-format-flag
- **severity**: minor
- **check**: Verify `--format` is wired through to `emit_rows`/`emit_one` and not silently
  ignored when `format_choices` is set but the `run()` body hardcodes an output format.
- **triggers**: CLI classes with `format_choices` or `add_format_argument()`; `run()` methods
  that call `emit_rows`/`emit_one` without passing `fmt=args.format`.
- **example**: `add_format_argument(parser, ...)` is called in `build_parser()` but `run()`
  calls `emit_rows(rows, fmt="table")` — `--format json` is silently ignored.
  Fix: `emit_rows(rows, fmt=args.format, ...)`.

### namespace-field-mismatch
- **severity**: major
- **check**: Verify that internal model field names match the external API field names they map to, or that an explicit mapping/alias exists. Silent name divergence causes serialization to produce wrong keys.
- **triggers**: Dataclass or TypedDict fields that will be serialized to or deserialized from an external API (Google, GitHub, Outlook); field names that differ from the documented API field name with no `alias`, `field(metadata=...)`, or explicit mapping function.
- **example**: `@dataclass class EventPlan: event_type: str` — if the API expects `"eventType"` (camelCase). Without a mapping, serialization produces `{"event_type": ...}` which the API rejects silently. Fix: rename to match the API field name or add an explicit key mapping in the serializer.

### schema-version-not-bumped
- **severity**: major
- **check**: Verify that any change to an on-disk schema (adding, removing, or renaming a field in a JSON/YAML structure written to `~/.config/` or a workspace file) is accompanied by a version bump in the corresponding schema version constant. On-disk copies from before the change will be misread without a version guard.
- **triggers**: New fields added to a dataclass or dict that is serialized to disk by a hook or CLI; `HOOK_VERSION`, `SCHEMA_VERSION`, or `FORMAT_VERSION` constants in hook files when the surrounding data structure changes; comments in source that say "bump when schema changes."
- **example**: A new `job_id` field is written to every queue entry but `HOOK_VERSION` is not bumped — existing on-disk queue files lack `job_id`, and code reading them with `chore["job_id"]` raises `KeyError` at runtime. Fix: bump `HOOK_VERSION`, add a migration default (`chore.get("job_id", "")`), and document the new field.

### pruner-path-gap
- **severity**: major
- **check**: Verify that every path a hook or CLI writes to is also listed in the corresponding cleanup/prune list. When a new output path is added on the write side without updating the prune manifest, the path leaks across sessions and accumulates stale files.
- **triggers**: New `Path(...)` assignments or `open(path, "w")` calls in hook files where a sibling `cmd_prune` list, `MANAGED_PATHS`, or cleanup registry exists; PR diffs that add a write path but show no corresponding change to the prune list.
- **example**: `RECOMMENDATIONS_PATH` is appended to by the hook on every run but is absent from the prune list — after many sessions the file grows unbounded while all other managed paths are pruned. Fix: add the new path to the prune list in the same commit.

### cli-preferences-wrong-separator
- **severity**: major
- **check**: Verify that CLI examples added to `.llm/DOMAIN_MAP.md` use the correct argument form for each CLI — direct argparse CLIs do not accept a `--` separator, and flags listed must exist in the CLI's argument parser.
- **triggers**: New or modified example lines in `.llm/DOMAIN_MAP.md` for CLIs that do not use the unified `--` separator pattern; examples that include `--` before flags for CLIs documented as direct argparse (no `--` in the CLAUDE.md separator table); format choices listed in examples that do not match the CLI's declared `--format` choices.
- **example**: `./bin/calendar outlook list -- --limit 10` — if the calendar CLI is a direct argparse CLI, the `--` causes `--limit` to be parsed as a positional arg and fails. Also: an example shows `--format yaml` but the CLI only registers `json` and `table` as format choices — agents following the example get an `invalid choice` error. Fix: verify against `./bin/<tool> --agentic --agentic-format yaml --agentic-compact` before documenting any example.

### decomposition-dead-symbol
- **severity**: major
- **check**: Verify that private helper functions introduced during file decomposition are actually imported and called by the new module structure — functions that existed in a monolithic file but are not wired into the facade or submodule graph after decomposition become unreachable dead code.
- **triggers**: PRs that decompose a large file into private submodules (`_*.py`); new private functions (names prefixed with `_`) in submodule files; refactor commits that split a `providers.py`, `handlers.py`, or `cli.py` into subdirectories; duplicate function definitions where the same logic appears in both the new submodule and in the module that previously held it.
- **example**:
  ```python
  # bad — _process_results extracted into _results.py during decomposition,
  # but the facade module never imports it; equivalent logic was written
  # directly in the facade instead (function in _results.py is unreachable)
  def _process_results(data): ...

  # good — import and delegate from the facade
  from ._results import _process_results

  # or, if the submodule is redundant, delete it rather than leaving dead code
  ```

### new-cli-bypasses-cliapp
- **severity**: major
- **check**: Verify new CLI entry points build on `core/cli_framework.py`'s `CLIApp`
  (decorator-based command registration) rather than constructing
  `argparse.ArgumentParser` directly. CLIs on `CLIApp` get fuzzy "did you mean"
  suggestions, an optional `--` separator, and auto-derived `--agentic` schema
  support for free; hand-rolled parsers get none of this and drift silently.
- **triggers**: New `*/cli/main.py`, `*/cli.py`, or similar entry-point files
  that call `argparse.ArgumentParser(` directly instead of instantiating
  `CLIApp(...)`; new domains added under `bin/` without a corresponding
  `CLIApp`-based command module.
- **example**: A new `foo/cli.py` with `parser = argparse.ArgumentParser(...)`
  and manual `subparsers.add_parser(...)` calls — misses fuzzy typo suggestions,
  requires `--` before flags, and has no `--agentic` support at all. Fix: use
  `app = CLIApp("foo-assistant", "...")` and `@app.command(...)` decorators;
  see `mail/cli/main.py` or `wifi/cli.py` for the canonical pattern.

### new-cli-missing-agentic-wiring
- **severity**: major
- **check**: Verify new CLI entry points instantiate a `core.assistant.BaseAssistant`
  and call `app.run_with_assistant(...)` (not bare `app.run(...)`) so `--agentic`,
  `--agentic-format json`, `--agentic-compact`, and `--agentic-domain` all work.
  A `CLIApp` alone does not wire agentic support — it must be connected explicitly.
- **triggers**: New CLI entry-point files that call `app.run(argv)` or `app.main(argv)`
  directly without a `BaseAssistant` instance; `CLIApp` usage with no import of
  `core.assistant.BaseAssistant`.
- **example**: `apple_music/cli.py` and `metals/cli/main.py` originally called
  `app.run()` directly and had zero `--agentic` support despite using `CLIApp` —
  agents had no way to introspect their command surface. Fix: `assistant =
  BaseAssistant(app_id="foo", fallback_banner="...")` and
  `app.run_with_assistant(assistant, emit_func=..., argv=argv)`. Minimal `emit_func`
  is acceptable if no hand-authored capsule exists yet — the auto-schema path
  (`--agentic-format json`) works from the live parser regardless.

### graceful-degradation-breaks-format-contract
- **severity**: major
- **check**: Verify that CLI graceful-degradation paths ("no data in window", "no metadata found") still emit a valid structured payload to stdout via `emit_rows(..., empty_msg=...)` when `--format json` or `--format csv` is active, rather than printing a human-readable note directly to stdout or emitting nothing at all.
- **triggers**: CLI `run()` branches handling an empty-result or no-data condition that call bare `print("...")` (no `file=sys.stderr`) or return without calling any output helper; graceful-degradation branches in the same file as a sibling branch that correctly calls an output helper for the empty case, creating an inconsistency.
- **example**:
  ```python
  # bad — human note on stdout corrupts json/csv output
  if not results:
      print("No data found in this window.")
      return 0

  # good — empty_msg goes to stderr; stdout still gets valid structured output
  if not results:
      emit_rows([], fmt=args.format, headers=["name", "count"], empty_msg="No data found.")
      return 0
  ```
  A caller running `./bin/tool --format json | jq .` gets a `jq` parse error in the bad case (mixed text) or nothing at all (missing stdout) — both are indistinguishable from a hang or crash to a non-interactive caller.

### cliapp-command-name-collision
- **severity**: major
- **check**: Verify that no two `@app.command(...)` registrations in the same `CLIApp` instance resolve to the same full name. `CLIApp.command()` (`core/cli_framework.py`) computes `full_name = f"{parent}.{name}"` and stores it as `self._commands[full_name] = cmd_def` — the dict assignment silently overwrites any prior registration with the same key, with no error or warning at import time or at `--help`. Because `"outlook.add"`, `"outlook add"`, and `parent="outlook"` + `name="add"` all normalize to the identical key, a second command written in a different dotted/spaced form than an existing one collides invisibly.
- **triggers**: New `@app.command(` decorators added to a CLI module that already has commands under the same parent group; a PR that copies an existing command as a starting point and forgets to change its `name` string; commands registered via `parent=` kwarg alongside commands using dot/space notation for the same group.
- **example**: `@app.command("outlook.add")` exists, and a later PR adds `@app.command("outlook add", ...)` intending a distinct command — both normalize to `full_name = "outlook.add"`, so the second decorator's registration silently replaces the first in `self._commands`. The original `outlook add` handler becomes unreachable with no import error, no duplicate-command warning, and no test failure unless a test specifically exercises the now-shadowed command. Fix: grep `self._commands` keys (or run `--agentic --agentic-format json` and check for exactly one entry per intended command) before merging a new command in an existing parent group.

### producer-bypasses-output-writer
- **severity**: major
- **check**: Verify that producer classes (BaseProducer subclasses) and CLI output helpers route all user-facing output through an injected OutputWriter rather than calling bare print() directly.
- **triggers**: BaseProducer subclasses with `print(` in `_produce_success()` or `produce()`; CLI command handlers that call `print()` for structured output instead of `emit_rows`/`emit_one`/`OutputWriter`; producer `__init__` that does not accept a `writer` parameter; diff adding a new producer class without an OutputWriter injection site.
- **example**:
  ```python
  # bad — bare print() bypasses stream injection and format routing
  class FiltersPlanProducer(BaseProducer):
      def _produce_success(self, result, envelope):
          for entry in result.creates:
              print(f'  + {entry.label}')

  # good — OutputWriter injected, defaults to OutputWriter(); routes through configured stream
  class FiltersPlanProducer(BaseProducer):
      def __init__(self, writer=None):
          self._writer = writer or OutputWriter()
      def _produce_success(self, result, envelope):
          for entry in result.creates:
              self._writer.print(f'  + {entry.label}')
  ```

### pipeline-naming-inconsistency
- **severity**: minor
- **check**: Verify that pipeline class pairs follow the `<Verb><Noun>Processor` / `<Verb><Noun>Producer` naming convention, that input dataclasses use a `Request` suffix, output dataclasses use a `Result` suffix, and that no legacy `Payload` suffix survives in modules that have adopted `SafeProcessor`.
- **triggers**: Processor/Producer subclasses whose names deviate from `<Verb><Noun>Processor`/`<Verb><Noun>Producer`; dataclasses passed to `SafeProcessor` or `BaseProducer` with a `Payload` suffix; dataclasses returned from `_process_safe` without a `Result` suffix; a module mixing `Payload` (old pattern) and `Request` (new pattern) naming; result type names that don't derive from the paired class name (e.g. `MatchResult` without `Keyword` prefix).
- **example**:
  ```python
  # bad — Payload suffix on input, Plan is noun not verb, MatchResult drops class prefix
  class FiltersSyncPayload: ...
  class GmailPlanProducer: ...
  class MatchResult: ...  # returned by KeywordMatcher

  # good — Request/Result suffixes, verb-noun class names
  class FiltersSyncRequest: ...
  class GmailScanProducer: ...
  class KeywordMatchResult: ...  # prefix matches KeywordMatcher domain
  ```

### truthiness-blocks-empty-clear
- **severity**: major
- **check**: Verify that optional override parameters test `is None` rather than truthiness. A truthiness test silently ignores an intentional empty-string or empty-list override, so a caller cannot clear a field that has a non-empty default.
- **triggers**: Functions or `__post_init__` methods applying an optional parameter with `if param:` where `None` means "use default" but `""`/`[]` means "clear this field"; config-merge helpers that fold overrides with `or`.
- **example**: `src/resume/docx_base.py` applies `metadata_title` only when truthy, so `metadata_title: ""` — an explicit request to clear the DOCX title — leaves the existing title in place. The same bug applies to `metadata_keywords: []`. Fix: `if metadata_title is not None:`.

### unnecessary-lambda-in-dispatch
- **severity**: minor
- **check**: Verify dispatch tables and handler maps do not wrap a callable in a `lambda` that forwards its arguments unchanged. The wrapper adds a frame, hides the target's name in tracebacks, and weakens the signature for type checkers.
- **triggers**: `{key: lambda a, b: func(a, b)}` in dispatch tables where the argument list is identical and in order; lambdas retained after a signature-unification refactor removed the difference they existed to smooth over.
- **example**: `SidebarResumeWriter._MAIN_SECTION_RENDERERS["experience"]` held `lambda cell, data, page_cfg, sec: _render_main_experience(cell, data, page_cfg, sec)` — a pure pass-through. All four entries in that table had the same shape once every renderer accepted `sec`. Fix: reference `_render_main_experience` directly.

### builtin-callable-annotation
- **severity**: minor
- **check**: Verify type annotations use `Callable[[Arg], Ret]` rather than the built-in `callable`, which is a function, not a type. Annotating with `callable` conveys no signature information and misleads type checkers.
- **triggers**: Parameter or field annotations written as bare `callable` (lowercase, no subscript); a module annotating a predicate parameter without importing `Callable`.
- **example**: `src/telemetry/pricing.py` annotated a predicate as `callable`, which a checker reads as the built-in function object rather than "accepts a str, returns bool". Fix: `from typing import Callable` and annotate `Callable[[str], bool]`.

### config-comment-contradicts-value
- **severity**: minor
- **check**: Verify inline comments in config and template files describe the value actually configured. These comments are treated as load-bearing documentation, so a stale one misdirects the next edit.
- **triggers**: YAML/TOML config where a comment annotating a field names a different literal than the field's value; template comments describing when a renderer consults a setting; comments asserting a key is honored by code that ignores it.
- **example**: `template.scannable.yaml` commented "Heading 1 (14pt)" beside `h1_pt: 12`. Related shapes: `template.brian.yaml` set `item_color` on the summary section, which `SummarySectionRenderer` never applies; and a comment claimed `get_bullet_config()` is consulted only on the bulleted branch when it in fact runs whenever `summary` is a list. Fix: align the comment with real behavior, or delete the setting the code ignores.
