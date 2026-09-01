# CLI Standard

The canonical definition of a conformant dancing-bear CLI. Every rule below is
stated as a **testable assertion** with the shared contract that proves it, so
conformance is machine-checkable rather than a matter of opinion.

Rules were derived by **running all 18 apps**, not by reading them. Where apps
legitimately differ, the rule names the exemption rather than pretending
uniformity.

Status legend: **MUST** = conformance gate. **SHOULD** = adopt unless the
exemption below applies. **MAY** = permitted variation.

---

## Tier 0 — Structure (every app)

**S1. MUST build on `CLIApp`** (`core.cli_framework`), not a hand-rolled argparse
tree. Supplies subcommand dispatch, the common flag set, `normalize_argv`, and
uniform exception→exit-code mapping.
*Conformant (18):* all 18 apps now build on CLIApp.

**S2. MUST declare app identity in `<app>/meta.py` as an `AppMeta`.**
`AppMeta` derives every fallback string (agentic, domain-map, inventory,
familiarize) from one `app_id` + `purpose`. Hand-written fallback literals
duplicate that derivation and drift from it.
*Conformant (18):* every app. Confirm on merged `main` with
`ls src/*/meta.py | wc -l` rather than trusting this line — it is a snapshot,
not a gate, and it sat stale through three merges before anyone checked.

The last seven adopted in #332. Six were byte-identical substitutions,
confirmed by diffing `AppMeta(...).agentic_fallback` against each app's live
`assistant.fallback_banner`. Two carried a wrinkle worth remembering if a
similar sweep comes up:

- `maker`'s literal lived behind `FALLBACK_AGENTIC_HEADER`, imported at two
  call sites. Identical in content, but the constant had to be deleted rather
  than left as a dead alias.
- `mail`'s was a bullet list `AppMeta` does not generate, so adopting it
  **changed the emitted fallback text**. Safe only because nothing asserted on
  the old string — checked before changing, not after.

**S3. MUST dispatch through `run_with_assistant(...)` with a real `emit_func`**
that builds a capsule. An `emit_func` that prints `assistant.fallback_banner`
emits the *failure* output unconditionally, by construction.

**S4. MUST expose `main(argv) -> int`**, importable and testable without
`subprocess`.

---

## Tier 1 — Agentic CLI surface

Applies to **every app** for A1–A7.

Proven by three contracts:
- `tests/agentic_cli_contract.py` → `AgenticCLIContractMixin` — **A1–A5**
- `tests/cli_separator_contract.py` → `SeparatorContractMixin` — **A6**
  (18 CLIApp apps; `telemetry` now adopts this contract)
- `tests/cli_no_subcommand_contract.py` → `NoSubcommandContractMixin` — **A7**
  (18 adopters; each declares its own expected exit code and stream)

Every rule in this tier is now guarded by a contract.

**A1. MUST exit 0 on `--agentic`** and announce `agentic: <app_id>` on line 1.

**A2. MUST emit a substantial capsule (> `MIN_CAPSULE_BYTES`, 200).**
This is the single most important rule in this document. See "The rc=0 trap".

**A3. MUST parse under `--agentic-format json`** and expose exactly:
`{prog, description, usage, options, subcommands, epilog}`.
*Conformant (18):* all 18 apps now emit this key set via `core.agentic_schema`.

**A4. MUST declare subcommands or options** — a schema with neither is a parser
that failed to introspect.

**A5. MUST make `--agentic-compact` strictly smaller** than full output, while
still naming `prog`. The flag exists to save tokens; it must actually do so.

**A6. MUST treat the `--` separator as optional**: `app -- --flag` ≡
`app --flag`, via `CLIApp.normalize_argv`. Proven by
`tests/cli_separator_contract.py` → `SeparatorContractMixin` (rc 0 both ways,
byte-identical stdout).
*Applies to all 18 CLIApp apps.* All apps route through `normalize_argv` in
`run_with_assistant`, which strips the first bare `--` before parsing.
Only the *first* bare `--` is stripped; a later or trailing `--` is preserved
(POSIX end-of-options). Those two cases are covered at the unit level in
`tests/core_tests/test_cli_framework.py::TestNormalizeArgv` and deliberately
not repeated per app.

**A7. MUST make no-subcommand behaviour deliberate** — help + 0 by default, or
an explicit `on_no_command` whose non-zero code is *documented in the source*.
Proven by `tests/cli_no_subcommand_contract.py` → `NoSubcommandContractMixin`
(18 adopters), which pins each app's exit code **and which stream carries the
output**.

*Conformant (16):* help to stdout, exit 0 — every app except the two below.

*Documented exceptions (2):* `worker` (1) and `workflow` (2) print a one-line
usage to **stderr**. Both carry a docstring on `_no_command_usage()` saying they
preserve legacy behaviour "since this is a public CLI surface". That written
rationale is what makes them exceptions rather than drift.

`charts` (was 1) and `telemetry` (was 2) were normalised to help + 0. Neither
had any stated rationale: charts was a bare `return 1` predating the `src/` move
(#147), and telemetry's 2 was incidental to Click, preserved by the argparse
port without anyone choosing it. A7 asks that the value be *chosen*; an
undocumented non-zero is the drift the rule exists to catch, so the fix was to
align them rather than enshrine them.

The **stream is part of the contract**, not just the code. help-on-stdout and
usage-on-stderr are different interfaces, and an exit-code-only assertion cannot
tell them apart — verified by probe: moving `worker`'s usage to stdout fails the
contract with `'stdout' != 'stderr'` while its exit code stays 1.

One framework inconsistency this surfaced, left as-is: `CLIApp.run()` returns
`ExitCode.USAGE` (2) for a missing subcommand while `run_with_assistant()`
returns 0. Every app here uses the latter, so the contract pins observed
behaviour; reconciling the two is a separate change.

---

## Tier 2 — Domain capsule builders

Applies to apps with `<domain>/agentic.py`. Proven by
`tests/agentic_builder_contract.py` → `AgenticBuilderContractMixin`.

There are **two legitimate tiers**, and conflating them is why the minimal-tier
domains appear "unadopted" when they are merely a different shape.

Two counts that are easy to conflate, and are both correct:
**8 domains are minimal by shape** (charts, diagrams, sheets, slides,
telemetry, worker, workflow, apple_music) and **all 8 now adopt the builder
contract**. `apple_music` joined this tier when its capsule was fixed;
`telemetry` joined when it migrated from Click to CLIApp.

### 2a — Full tier (10 domains)
calendars, desk, mail, maker, phone, qlty, resume, schedule, whatsapp, wifi

**B1. `build_agentic_capsule()`** → non-empty; line 1 is `agentic: <app_id>`;
contains `purpose:`.
**B2. `emit_agentic_context(fmt, compact)`** → returns 0, writes the capsule to
stdout, output byte-identical to the builder, accepts both params
**positionally** (nine domains name the second `_compact`, `mail` names it
`compact` and consumes it — positional calling makes the difference invisible).
**B3. `build_domain_map()`** → line 1 is `Top-Level`; never the
`"Domain Map not available"` fallback.
**B4. Capsule embeds a CLI tree.** A missing tree means the parser import was
swallowed by `cached_parser_loader`. *Opt out:* `maker`, `qlty` build no tree
deliberately (`EXPECT_CLI_TREE = False`).

### 2b — Minimal tier (8 by shape, 8 adopting)
charts, diagrams, sheets, slides, telemetry, worker, workflow, apple_music

**B1** and **B2** apply unchanged. **B3/B4 do not** — these domains define no
`build_domain_map` and embed no CLI tree, by design.

The opt-out is `EXPECT_DOMAIN_MAP = False`, and it is **not a bare skip**:
`test_domain_map_presence_matches_flag` asserts the function is *genuinely
absent* when the flag is False, and *present* when True. That two-directional
assertion is what makes this tier a legitimate exemption rather than a way to
silence a failing test — a map-defining domain that lost its function still
fails, and a minimal domain that grew one fails too. Any future opt-out flag
added to a contract in this repo should follow the same rule.

---

## Tier 3 — LLM dispatch modules

Applies to the **9 domain apps** with an `<app>/llm_cli.py`. `ls src/*/llm_cli.py`
returns 10 paths, but one is `src/core/llm_cli.py` — the shared implementation
the others are built from, not a domain module. Proven by
`tests/llm_cli_contract.py` → `LLMCLIContractMixin`.

**L1. MUST be built on `core.llm_cli.make_domain_llm_module`.**
**L2. `CONFIG.prog == "llm-<app>"`**, with the `DOC_SUFFIX` filename convention.
**L3. `main(["agentic","--stdout"])` returns 0** and announces the app;
`--help` exits 0.

*Adopted (8):* calendars, desk, maker, phone, resume, schedule, whatsapp, wifi.

*Exempt (1):* `mail`. Verified by reading both: `src/mail/llm_cli.py` is a
**re-export shim** of `core.llm_cli` (it rebinds `LlmConfig`, `build_parser`,
`run`, `main`) and never calls `make_domain_llm_module`, so it has **no
`CONFIG`** — and therefore no `CONFIG.prog` and no `DOC_SUFFIX` for
`EXPECTED_PROG` to assert against. `build_parser` there also requires a config
argument, unlike the bound entrypoint the contract expects.

This is a genuinely different shape, not an unadopted abstraction. Forcing the
mixin on it would assert attributes that do not exist. `tests/mail_tests/llm/`
already covers the shim on its own terms.

Two separate cautions about this module, both real:
  - It is a **live `llm --app mail` dispatch target referenced by a string
    literal**, so it is not a removable facade despite looking like one to an
    AST-based facade detector.
  - Its shim shape is the reason it is exempt here. Do not "fix" either
    property.

---

## The rc=0 trap — why byte counts matter more than exit codes

`core/assistant.py::maybe_emit_agentic` wraps `emit_func` in a bare
`except Exception` that prints `fallback_banner` and **returns 0**.

Demonstrated, not assumed — patching `wifi.cli._lazy_agentic` to raise
`ImportError` yields:

```
rc=0  bytes=78
'agentic: wifi\npurpose: Wi-Fi and LAN diagnostics (gateway vs upstream vs DNS)\n'
```

A totally broken capsule builder is **indistinguishable from success** by exit
code, and it still passes an `agentic: <app_id>` first-line assertion. Real
capsules run ~380 bytes (sheets) to ~37 KB (mail); a banner is < 100.

Consequences for every test in this repo:

- **Never assert only `rc == 0`** on a capsule path.
- **Never assert only the first line** — the banner has the same first line.
- The `MIN_CAPSULE_BYTES` floor is the only reliable detector.

This is the same family as the swallowed `cached_parser_loader` import. It has
now produced three separate defects; treat any bare `except Exception` around
capsule construction as suspect.

---

## The `telemetry` Click migration (completed)

`telemetry` was previously Click-based and failed **A3** (5 keys vs 6) and
**A6** (separator not stripped). It has been ported to CLIApp in this branch.

The one genuinely tricky mapping was the `otel` passthrough: the Click UNPROCESSED
approach was replaced by intercepting `"otel"` in `main()` before `parse_args` runs,
then forwarding `_argv[1:]` directly to `telemetry.otel.cli.main`. This ensures
`telemetry otel --help` emits OTEL's help, not telemetry's.

A stub `cmd_otel_stub` is registered with the CLIApp so the subcommand appears
in help text and agentic schema introspection, but the actual dispatch bypasses it.

All Click-walking code (`_describe_click_group`, `_describe_click_options`,
`_choices`, `_jsonable`, `build_agentic_json`) has been deleted from `agentic.py`.
The JSON schema is now generated by `core.agentic_schema.build_schema_json` via
`BaseAssistant.maybe_emit_agentic`, matching all other 17 apps.

---

## The governing rule

> If a behaviour is shared by more than one app, it is tested **once** in a
> contract mixin and adopted by every app — never re-asserted per app.
> Per-app test files assert only what is genuinely unique to that app.

Two corollaries, both learned the hard way here:

1. **Derive invariants by running the apps, not reading them.** This caught
   `calendars` announcing `agentic: calendar` (singular), the
   `compact`/`_compact` split, and the two-tier `agentic.py` shape.
2. **Assert on content, not exit codes.** Several failure modes in this codebase
   exit 0: a swallowed parser import, a stub capsule, a domain-map fallback.
