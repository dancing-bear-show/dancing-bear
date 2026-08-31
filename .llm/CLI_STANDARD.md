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
*Exempt:* `telemetry` (Click). See "Click exemption" below.

**S2. MUST declare app identity in `<app>/meta.py` as an `AppMeta`.**
`AppMeta` derives every fallback string (agentic, domain-map, inventory,
familiarize) from one `app_id` + `purpose`. Hand-written fallback literals
duplicate that derivation and drift from it.
*Conformant (10):* apple_music, charts, diagrams, qlty, sheets, slides,
whatsapp, wifi, worker, workflow.
*Non-conformant (8):* calendars, desk, mail, maker, phone, resume, schedule,
telemetry — each hand-writes the string. Five are byte-identical to what
`AppMeta.agentic_fallback` generates, so the substitution is mechanical;
`maker` hides it behind a constant (`FALLBACK_AGENTIC_HEADER`) imported at two
call sites; `mail`'s is a bullet list that does not follow the format at all,
so adopting `AppMeta` there **changes the emitted fallback text** and needs a
check that nothing asserts on the old string.

Counts verified by `ls src/*/meta.py` after the apple_music fix landed. Re-run
that command rather than trusting this list — it is a snapshot, not a gate.

**S3. MUST dispatch through `run_with_assistant(...)` with a real `emit_func`**
that builds a capsule. An `emit_func` that prints `assistant.fallback_banner`
emits the *failure* output unconditionally, by construction.

**S4. MUST expose `main(argv) -> int`**, importable and testable without
`subprocess`.

---

## Tier 1 — Agentic CLI surface

Applies to **every app** for A1–A5 and A7. **A6 excludes `telemetry`** (Click;
see the exemption at the end of this document) — so "every app" is not a
uniform claim across this tier, and the two contracts below have deliberately
different adopter sets.

Proven by two contracts, not one:
- `tests/agentic_cli_contract.py` → `AgenticCLIContractMixin` — **A1–A5**
- `tests/cli_separator_contract.py` → `SeparatorContractMixin` — **A6**
  (17 CLIApp apps; `telemetry` correctly absent from its adopters)

A7 is currently unguarded by any contract; it is a SHOULD for that reason.

**A1. MUST exit 0 on `--agentic`** and announce `agentic: <app_id>` on line 1.

**A2. MUST emit a substantial capsule (> `MIN_CAPSULE_BYTES`, 200).**
This is the single most important rule in this document. See "The rc=0 trap".

**A3. MUST parse under `--agentic-format json`** and expose exactly:
`{prog, description, usage, options, subcommands, epilog}`.
*Exempt:* `telemetry` emits `{app_id, commands, notes, prog, purpose}`.

**A4. MUST declare subcommands or options** — a schema with neither is a parser
that failed to introspect.

**A5. MUST make `--agentic-compact` strictly smaller** than full output, while
still naming `prog`. The flag exists to save tokens; it must actually do so.

**A6. MUST treat the `--` separator as optional**: `app -- --flag` ≡
`app --flag`, via `CLIApp.normalize_argv`. Proven by
`tests/cli_separator_contract.py` → `SeparatorContractMixin` (rc 0 both ways,
byte-identical stdout).
*Applies to the 17 CLIApp apps only — **`telemetry` is exempt**.* Measured:
`telemetry.main(["--","--agentic"])` returns **rc=2 with 0 bytes** (vs rc=0,
1041 bytes without). Click never routes through `normalize_argv`, so this is a
parser fact, not a defect to fix. All 17 CLIApp apps honoured this before the
contract existed, so it is a **regression guard**, not a migration.
Only the *first* bare `--` is stripped; a later or trailing `--` is preserved
(POSIX end-of-options). Those two cases are covered at the unit level in
`tests/core_tests/test_cli_framework.py::TestNormalizeArgv` and deliberately
not repeated per app.

**A7. SHOULD make no-subcommand behaviour deliberate** — either help + 0, or an
explicit `on_no_command` preserving a legacy exit code. charts (1), diagrams (0),
worker (1) and workflow (2) intentionally differ; the point is that the value is
chosen, not accidental.

---

## Tier 2 — Domain capsule builders

Applies to apps with `<domain>/agentic.py`. Proven by
`tests/agentic_builder_contract.py` → `AgenticBuilderContractMixin`.

There are **two legitimate tiers**, and conflating them is why the minimal-tier
domains appear "unadopted" when they are merely a different shape.

Two counts that are easy to conflate, and are both correct:
**8 domains are minimal by shape** (charts, diagrams, sheets, slides,
telemetry, worker, workflow, apple_music) but only **7 adopt the builder
contract** — `telemetry` is Click and covered separately. `apple_music` joined
this tier when its capsule was fixed.

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

### 2b — Minimal tier (8 by shape, 7 adopting)
charts, diagrams, sheets, slides, worker, workflow, apple_music
(+ `telemetry`, minimal by shape but Click — see the exemption below)

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

## The Click exemption (`telemetry`)

`telemetry` is Click-based and fails **A3** (5 keys vs 6). Converting it to
argparse is **explicitly out of scope** and not recommended:

Measured scope, for whoever runs the migration:

- 43 `@click` decorators (36 in `cli_sessions.py`, 7 in `parse_transcripts.py`)
- 38 `click.option`, 8 `click.Choice`, 2 groups, 11 subcommands
- `click` imported in 5 files, including `parse_transcripts.py` /
  `parse_transcripts_io.py` — beyond the CLI layer
- **only 4 of 79** telemetry test files use `CliRunner`

That last number corrects an earlier claim in this document that "many" of the
79 files assert Click behaviour. They do not, and the mistake mattered: it was
the main argument for leaving telemetry alone.

Neither feature expected to block a port actually does — `pass_context` maps to
threading the argparse `Namespace`, and `UNPROCESSED` + `allow_extra_args` maps
to `parse_known_args` (with the `otel` passthrough caveat below).

**Decision: migrate.** `workflows/code/cli-standard-conformance.yaml` carries a
`migrate_click` work stream that ports telemetry onto `CLIApp`. Converting also
*deletes* code: `agentic.py`'s `_describe_click_group` /
`_describe_click_options` exist only to walk a `click.Group`, and
`core.agentic_schema.build_schema_json` already builds the capsule generically
for the other 17 apps.

**The one genuinely tricky mapping** is the `otel` passthrough.
`nargs=REMAINDER` makes the parent intercept `--help` / `--agentic`
(`SystemExit(2)`); `parse_known_args` splits argv across two variables
(`["otel","query","--format","json"]` → `args=["query"]`,
`rest=["--format","json"]`). Forward `args + rest` concatenated in original
order, and verify `telemetry otel --help` still prints *OTEL's* help rather
than telemetry's — a partial port swaps them silently while still exiting 0.

**Until that migration lands**, the exemptions in A3 and A6 above hold and this
section stays. When it lands, this section and both carve-outs must be deleted:
a standard documenting an exemption the code no longer needs will lead a later
reader to reintroduce Click on its authority.

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
