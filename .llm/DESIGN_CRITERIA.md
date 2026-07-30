# Design Criteria

Checkable normalization standard for `src/`. Codifies patterns already proven in mail/calendar/schedule/desk/resume/phone/whatsapp/maker/wifi and extends them to newer packages (telemetry, worker, metals, apple_music, charts, diagrams, workflow) that predate or fell outside the original migration.

This doc is graded against, not aspirational prose — each criterion is written so an audit agent can answer pass/fail with a file:line citation. See `PIPELINE_MIGRATION.md` for the historical migration log and `PATTERNS.md` for copy-paste templates of the patterns referenced below.

## C1 — Data modeling: dataclasses over dicts

- Request/result/config shapes crossing a function or module boundary MUST be `@dataclass`, not bare `dict`/`Namespace`/tuple.
- Immutable config objects use `@dataclass(frozen=True)` (see `workflow/models.py: AgentSpec`, `OutputSpec`).
- Repeated field pairs across sibling dataclasses (e.g. `calendar_id`/`calendar_name` showing up in 3+ classes) MUST be consolidated into a shared value object (`PATTERNS.md` "Dataclass Field Consolidation").
- **Fail example:** a processor accepting `payload: dict` and doing `payload["cache_path"]` instead of a typed `CacheStatsRequest`.

## C2 — Pipeline shape: Consumer → SafeProcessor → BaseProducer

- **Applicability test (check before grading FAIL):** C2 applies to a CLI command if it does at least one of: (a) makes a network/external-API call, (b) reads/writes files or state outside the immediate CLI invocation (config, cache, credentials), (c) shells out via `subprocess`, or (d) has more than one distinct failure mode worth distinguishing to the caller. A command that only transforms an in-memory value already fully validated by argparse (e.g. a pure rendering/formatting pass over data the CLI itself just read once) does not gain safety from the pipeline wrapper and should NOT be graded FAIL for lacking one — note it PASS with a one-line rationale instead of forcing a conversion that adds indirection without reducing risk. When in doubt (a command does file I/O but the failure modes are trivial), grade PARTIAL and let the human decide during plan-normalization, not FAIL.
- Where C2 does apply: every such command MUST be expressed as `RequestConsumer[Request]` → `SafeProcessor[Request, Result]._process_safe()` → `BaseProducer._produce_success()`, wired via `core/pipeline.py`.
- `_process_safe` MUST NOT contain a top-level `try/except` — errors propagate as exceptions; `SafeProcessor` converts them into `ResultEnvelope` automatically. A local `try/except` inside `_process_safe` is only acceptable for a narrow, named failure mode (e.g. skip-and-continue on a malformed record), and must carry a `# nosec B110/B112` comment per CLAUDE.md.
- `_produce_success` MUST NOT branch on error state — `BaseProducer` handles the error path; success-only rendering lives in the override.
- Payload extraction from a `ResultEnvelope` MUST use `.unwrap()`, never a bare `assert` (asserts strip under `-O`).
- **Known gap (as of this audit):** `telemetry/`, `worker/`, `apple_music/`, `charts/`, `diagrams/`, `workflow/` have zero `SafeProcessor`/`BaseProducer` usage. `metals/` has partial adoption (1 of ~29 files) despite being marked complete in `PIPELINE_MIGRATION.md` — newer commands were added after that migration pass and were never brought forward.
- **Applicability test worked example — `diagrams/`:** `diagrams/renderers.py` shells out to `mmdc` via `subprocess.run(...)` — this trips applicability condition (c) even though it's a single, already-well-understood failure mode (`subprocess.TimeoutExpired`, non-zero exit) rather than several distinct ones. The test is intentionally satisfied by condition (c) alone, regardless of failure-mode count — do not read condition (d)'s "more than one distinct failure mode" qualifier back onto (a)/(b)/(c); any one of the four conditions is independently sufficient. `diagrams/` therefore DOES fall under C2 and should be graded on whether it's actually pipeline-wrapped, not exempted. `charts/` (pure in-memory rendering over data already read once, no subprocess) is the contrasting case that IS exempt.
- **Optional enhancement (not required for pass/fail):** `ResultEnvelope[T]` currently exposes `.unwrap()`. Adding `.is_ok()`/`.is_err()`/`.unwrap_or(default)`/`.map(func)` convenience methods (a Result-monad shape) would let call sites avoid re-checking `envelope.ok()` before every `.unwrap()`. Nice-to-have, not a gap the audit should flag as FAIL.

## C3 — Provider/backend abstraction

- Where a domain supports interchangeable backends (Gmail/Outlook today; any future pluggable backend), the CLI and pipeline layers MUST depend on the abstract interface (`BaseProvider` ABC or a `Protocol`), never on a concrete provider class.
- Capability checks MUST go through an explicit gate (`provider.capabilities().get("x")`), not `isinstance()` branching on the concrete provider type.
- Shared cross-cutting behavior (caching, auth refresh) belongs in a mixin composed onto the provider (`CacheMixin` pattern), not duplicated per-provider.

## C4 — Composition over inheritance

- Prefer narrow, composable mixins over deep inheritance chains. A class should not inherit more than 2 levels deep without a documented reason.
- Stateful, config-driven behavior (an object with an `__init__` and multiple related methods, e.g. a strategy implementation or a provider) → class.
- Stateless transforms (formatting, parsing, pure computation, e.g. `_fmt_tokens`, `_sparkline`) → module-level function, not a class with one method.
- **Fail example:** a `Formatter` class instantiated once per call with no state, wrapping a single `format()` method — should be a function.

## C5 — Error handling: exception hierarchy + exit codes

- Domain errors MUST subclass the `CLIError` hierarchy in `core/cli_errors.py` (`ConfigError`, `AuthError`, `NetworkError`, `NotFoundError`, `UsageError`), not raise bare `Exception`/`ValueError` at the CLI boundary.
- Every `CLIApp` command path MUST terminate through the shared `ExitCode(IntEnum)` mapping — no ad hoc `sys.exit(1)` with an unmapped code.
- Bare `except Exception: pass/continue` requires a `# nosec B110/B112` comment naming the intentional failure mode (CLAUDE.md, already enforced by qlty/bandit).

## C6 — Output formatting

- User-facing output goes through `OutputWriter`/`OutputFormat` (`core/cli_output.py`), not ad hoc `print()` scattered through command logic. `OutputFormat` (TEXT/JSON/YAML/TABLE) is injected, not branched on inline with `if fmt == "json": ...` repeated per command.

## C7 — Centralized core, no re-derivation

- Before adding a helper to a domain package, check `src/core/` (`collections.py`, `text_utils.py`, `date_utils.py`, `fileutil.py`, `yamlio.py`, `http.py`, `parallel.py`, `secrets.py`, `patterns.py`) for an existing equivalent. Reimplementing a core helper locally is a duplication defect, not a style preference.
- A helper used by 2+ domain packages MUST be promoted to `core/`, not copy-pasted. (This is the "minimize duplication" side of DRY — maximize reuse of shared code, not minimize cross-module dependency.)
- Lazy-import optional/heavy dependencies (Google APIs, PyYAML) at point of use, matching the existing `try/except ImportError` + `ensure_*()` gate pattern in `mail/gmail_api.py` — never a bare top-level `import` of an optional dependency.

## C8 — Test coverage: happy path AND sad path

For every `SafeProcessor`/`BaseProducer` pair (or, pre-migration, every command handler):
- **Happy path**: at least one test exercising the successful case end-to-end (consumer → processor → producer), asserting on the produced output, not just "no exception raised."
- **Sad path**: at least one test per distinct failure mode the processor can raise (`ConfigError`, `AuthError`, `NetworkError`, `NotFoundError`, validation failure) asserting the correct `ExitCode` / `CLIError` subtype surfaces — not merely that *some* error was raised.
- Provider-backed commands MUST test both providers where both are supported (Gmail-path test + Outlook-path test), using the existing fake clients (`FakeGmailClient`, `FakeOutlookClient` in `tests/mail_tests/fixtures.py` / `tests/calendars_tests/fixtures.py`) rather than live network calls.
- **Fail example:** a processor with 3 raise sites but only one test asserting `envelope.ok() is True`.

## C9 — Test abstraction: fixtures and factories, not copy-paste setup

- Reuse existing shared fixtures before writing new ones: `tests/fixtures.py` (`TempDirMixin`, `make_mock_envelope`, `make_mock_processor`, `capture_stdout`, `temp_yaml_file`/`temp_json_file`/`temp_csv`) and per-domain `tests/<domain>_tests/fixtures.py`.
- A new domain's test suite lacking a `fixtures.py` (or `shared_fixtures.py`/`helpers.py`) once it has 3+ test files MUST get one — mirroring `tests/wifi_tests/shared_fixtures.py`, `tests/telemetry_tests/shared_fixtures.py`, `tests/worker_tests/helpers.py`.
- Repeated inline `Namespace(...)`/mock-object construction across test functions in the same file (3+ occurrences of near-identical setup) MUST be extracted to a factory function in that domain's fixtures module.
- Fakes for external systems (Gmail/Outlook clients, filesystem, subprocess) belong in fixtures, not redefined per test file.

## C10 — Naming and interface consistency

- Processor classes: `<Verb><Noun>Processor` (e.g. `CacheStatsProcessor`, `OutlookAddProcessor`). Producers: `<Verb><Noun>Producer`. Requests/Results: `<Verb><Noun>Request`/`<Verb><Noun>Result`. Deviating names make cross-domain grep/audit unreliable.
- CLI subcommand verbs stay consistent across domains for equivalent operations: `plan` → `sync`/`apply` → `verify` is the standard triad (per CLAUDE.md's plan/dry-run/apply rule); don't invent domain-specific synonyms (`push`, `commit`, `execute`) for the same lifecycle stage.

## Non-goals (explicitly out of scope for normalization)

- Renaming or moving public `bin/*` entry points or CLI flags — backwards compatibility is load-bearing (CLAUDE.md).
- Introducing new external dependencies to achieve any of the above.
- Retrofitting `maker/`, `_disasm/`, `out/`, `backups/` (excluded scan paths per CLAUDE.md "Ignore During Scanning").
- Rewriting already-migrated pipelines (mail, calendar, schedule, desk, resume, phone, whatsapp, wifi core commands) — audit should confirm compliance, not churn working code without a found defect.

## How this doc is used

1. **Audit workflow** grades each `src/<domain>/` package against C1–C10, producing a per-module findings list (pass/fail + citation) — no code changes.
2. **Apply workflow** takes reviewed/approved findings and spawns `code-writer` agents (worktree-isolated) per module to close gaps, with `tester` adding the happy/sad-path tests required by C8 before the change is considered done, verified via `qlty check` + `make test`.
