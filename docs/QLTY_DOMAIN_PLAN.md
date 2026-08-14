# Plan: `qlty` as a first-class domain

**Status:** proposal, pending review
**Author:** drafted in session `seedbox-ephod-syrup`
**Date:** 2026-08-14

---

## 1. Why

qlty is currently consumed ad-hoc: raw `~/.qlty/bin/qlty ...` invocations scattered
across `CLAUDE.md`, `.llm/PATTERNS.md`, `.llm/DESIGN_CRITERIA.md`, and inline in
workflow stage descriptions. That has produced four concrete failure modes,
every one of which was hit live while triaging findings this session:

| # | Failure mode | Evidence |
|---|---|---|
| F1 | **Silent empty result.** `qlty check` defaults to *changed files only*. On a clean branch it prints "No issues" — indistinguishable from a genuinely clean repo. | Reported `✔ No issues`; `--all` then found 51. |
| F2 | **Fragmented discovery.** Findings are split across `check` (lint/security) and `smells` (structure). Neither is a superset. | 51 lint issues and 70 smells are disjoint sets; the `function-parameters` cluster never appears in `check`. |
| F3 | **Unreadable default output.** `smells` emits heavy ANSI even when piped; needs `sed $'s/\033\\[[0-9;]*m//g'` to read. | Required a strip filter mid-session. |
| F4 | **Undocumented JSON.** `--json` is absent from every `--help`, but works and is already depended on by a shipped workflow. One upstream release silently breaks that workflow. | `qlty-complexity-sweep.yaml:67` uses `--json`; `smells --help` advertises only `--sarif`. |
| F5 | **Per-run issue cap.** radarlint appears to cap reported issues per run, so a high-count cluster **crowds out** lower-ranked findings in other files. Fixing findings can *reveal* others; the count is not monotonic and not a completeness signal. | 2 pre-existing S5655 in `test_cli_reminders.py` were invisible while 44 findings in `calendar.py` dominated; they surfaced only once those were cleared. Verified by stashing the fix and re-scanning — the file is in the baseline scan too. |

**Coverage gap.** At the time of the original survey, 70 smells across 6 rules;
only `file-complexity` (9) had tooling (`qlty-complexity-sweep.yaml`). The other
61 findings had no strategy at all:

```
function-parameters   31   <- no workflow
similar-code          13   <- no workflow  (duplication; highest latent value)
return-statements     12   <- no workflow
file-complexity        9   <- qlty-complexity-sweep.yaml
boolean-logic          3   <- no workflow
function-complexity    2   <- no workflow
```

**Re-baselined after #203 + #204 merged (2026-08-14) — 70 → 37:**

```
function-parameters   16   (was 31)
similar-code          13   (unchanged — 6 groups after dedup)
boolean-logic          3
return-statements      3   (was 12)
function-complexity    2
file-complexity        0   (was 9 — #203 tuned the thresholds)
```

This drop is itself an argument for the wrapper. Two of the three causes are
invisible from the raw counts: #203 retuned `file-complexity` thresholds (a
*config* change that silently zeroed a whole rule), #204 fixed real findings, and
F5 below means some of the delta may be findings that merely became visible or
invisible rather than fixed. Nothing in the current tooling distinguishes these.
`baseline`/`drift` (Phase 4) exists precisely to answer "did this improve, or did
the ruleset move under us?" — and this re-baseline is the concrete motivating
example.

**Also observed at re-baseline:** a new S5655 appeared in
`tests/calendars_tests/test_producer_output_branches.py:520`, previously latent
behind the 44 findings that #204 cleared. Second live instance of F5.

**Goal:** one wrapper that makes the full finding set discoverable in a single
call, with a documented per-rule remediation strategy, so triage stops being
rediscovered from scratch each session.

**Non-goal:** auto-fixing everything. Section 5 is explicit that several rules are
*advisory* and the correct action is often "leave it".

---

## 2. Shape: `src/qlty/` + `bin/qlty-assistant`

Follows the existing `CLIApp` convention (`src/core/cli_framework.py`), so it gets
`--agentic` for free — the point being that an LLM agent can discover the whole
qlty surface without shelling out to `--help`.

> **Naming:** wrapper is `bin/qlty-assistant`, never `bin/qlty` — a wrapper that
> shadows the real binary on `PATH` is a debugging trap. `assistant qlty <cmd>`
> is the primary route.

```
src/qlty/
  __init__.py
  cli.py            # CLIApp wiring; subcommands below
  runner.py         # single choke point for subprocess invocation (F4 lives here)
  models.py         # Finding, Smell, RuleStrategy dataclasses
  strategies.py     # rule -> remediation strategy table (section 5)
  report.py         # text/json/md renderers, ANSI stripped (F3)
```

### Subcommands

| Command | Purpose | Solves |
|---|---|---|
| `scan` | Run `check` **and** `smells`, merge into one finding set | F1, F2 |
| `triage` | Group findings by rule, attach strategy + auto-fixable flag | F2 |
| `strategy <rule>` | Print the remediation strategy for one rule | — |
| `rules` | List known rules, counts, and whether tooling exists | F2 |
| `baseline` | Snapshot current findings to JSON for drift detection | — |
| `drift` | Diff current findings against a baseline | — |

**Defaults that fix F1:** `scan` defaults to `--all`. Diff-only is opt-in via
`--changed`, and when `--changed` yields zero findings the output says so
explicitly ("0 findings in changed files; run with --all to scan the repo")
rather than a bare "no issues".

**`--rescan-until-stable` fixes F5.** Because radarlint caps issues per run, a
single scan under-reports whenever one file dominates the results. `scan` should
support re-running until the finding set stops changing, and `triage` must never
present a count as "all remaining issues" — the correct framing is "all issues
*visible in this run*". Observed live: clearing 44 findings in one file revealed 2
that had been latent in another the whole time.

Corollary for any sweep workflow: **"count went down" is not proof of progress,
and "count reached zero" is not proof of completion.** Verification must re-scan
after fixes and compare finding *identities* (rule + file + line), not totals.

### F4 containment — `runner.py`

Every qlty invocation goes through one function. JSON is attempted first, SARIF is
the fallback, and the degradation is *surfaced*, never silent:

```python
def _invoke(subcmd: str, *args: str) -> tuple[list[dict], OutputMode]:
    """Run qlty, preferring undocumented --json, falling back to --sarif.

    --json is not in any qlty --help output as of CLI v0.x but is relied on by
    workflows/code/qlty-complexity-sweep.yaml. If a future release drops it we
    degrade to --sarif rather than returning an empty finding set, which would
    otherwise read as "clean repo" (F1 all over again).
    """
```

A `--json`-disappeared event must fail loudly. An empty finding list from a parse
error and an empty finding list from a clean repo must never be the same value —
that is the single most important invariant in this design.

**Verified (2026-08-14).** Both modes were tested against this repo and return the
same 70 findings with identical per-rule counts, so the fallback is faithful on
content. But the rule identifiers differ:

| | JSON | SARIF |
|---|---|---|
| shape | flat array | `runs[0].results[]` |
| rule id | `ruleKey: "function-parameters"` | `ruleId: "qlty:function-parameters"` |
| fields | `ruleKey`, `value`, `location.path` | `ruleId`, `level`, `message`, `locations`, `taxa` |

`runner.py` must therefore **normalize, not pass through** — strip the `qlty:`
prefix and map SARIF's `locations[]`/`message` onto the same `Finding` dataclass
as JSON. Without this, a SARIF fallback yields findings whose rule key matches
nothing in the strategy table and every finding silently classifies as "unknown
rule" — the same silent-degradation class this section exists to prevent.

Note also that SARIF has no direct equivalent of JSON's numeric `value` (the
param count / complexity score); it is embedded in `message` text. Rules that
threshold on `value` (`--min-params`, `complexity_floor`) must either parse it out
of the message or degrade to "unfiltered" *and say so* — never to "no matches".

---

## 3. Deliverables

Deliverables are scoped per phase (section 4); the status below tracks what has
actually shipped, so this list is not read as a description of the current state.

1. ✅ **Phase 1** — `src/qlty/` package + `bin/qlty-assistant` wrapper
2. ✅ **Phase 1** — `tests/qlty_tests/` — fixture-driven, **no live qlty calls in
   unit tests** (captured JSON/SARIF fixtures; qlty is an external binary whose
   output format is exactly what we don't control)
3. ⬜ **Phase 3** — `workflows/code/qlty-sweep.yaml` — generalizes
   `qlty-complexity-sweep.yaml` from one rule to rule-dispatched (section 6)
4. ✅ **Phase 1** — Docs: `.llm/PATTERNS.md` qlty section pointing at the wrapper;
   `CLAUDE.md` linting section updated; `src/qlty/README.md`; domain listed in
   `README.md`, `CLAUDE.md`, and `.llm/CONTEXT.md`
5. ⬜ **Phase 2** — `.llm/QLTY_STRATEGIES.md` — the section 5 table as a
   maintained artifact (the table itself ships in Phase 1 as
   `src/qlty/strategies.py`, reachable via `./bin/qlty-assistant rules`)

---

## 4. Phasing

Each phase is independently shippable; stop after any one.

- **Phase 1 — `scan` + `triage` + `rules`.** Kills F1–F4. Highest value, ~1 PR.
- **Phase 2 — `strategies.py` + `QLTY_STRATEGIES.md`.** Encodes section 5.
- **Phase 3 — `qlty-sweep.yaml`.** Rule-dispatched workflow.
- **Phase 4 — `baseline` / `drift`.** Ratchet; optional CI gate.

---

## 5. Per-rule remediation strategies

The core of the proposal. Three tiers by **action class** — the tier, not the
count, decides what happens to a finding.

### Tier A — mechanical, safe to fan out

| Rule | n | Strategy | Auto-fix? |
|---|---|---|---|
| `file-complexity` | 9 | Split into focused modules. Existing `qlty-complexity-sweep.yaml`. | No — needs plan + human gate |
| `function-complexity` | 2 | Extract helpers, dispatch tables, early returns. | No |
| `return-statements` | 12 | Usually a guard-clause/dispatch rewrite. Low risk, high churn. | Partial |
| `boolean-logic` | 3 | De Morgan simplification, extract named predicates. | Partial |

### Tier B — judgment required, triage before acting

| Rule | n | Strategy |
|---|---|---|
| `function-parameters` | 31 | **Split by call-site role.** Test-fixture factories (`_make_*`, `make_*` in `tests/**/fixtures.py`, `shared_fixtures.py`) are *correct* with many defaulted kwargs — collapsing them makes tests worse. Production functions near an existing params-object pattern (`EventCreationParams`, `MobileConfigOptions`, `ListEventsRequest`) are real candidates. Default action: **LEAVE**; fix only with a named params object already in the domain. |
| `similar-code` | 13 | Highest latent value, highest risk. Duplication is only worth collapsing when the copies share a *reason to change*. Incidental similarity (two parsers that happen to look alike) must be left alone. Requires reading all clones before acting — never fan out blind. |

#### Tier B validated against reality (2026-08-14)

A read-only triage pass over all 31 `function-parameters` findings returned
**29 LEAVE / 2 FIX**, which confirms the "default to LEAVE" posture above and is
the strongest evidence in this document that a wrapper should *classify* rather
than *auto-fix*. Breakdown of the LEAVEs:

- 12 test-fixture factories (7–12 params) — the override-one-field pattern.
  `tests/telemetry_tests/otel_analytics/_shared_helpers.py` was *recently created*
  to consolidate duplicates; "fixing" it would undo that work.
- 2 Click-decorated handlers (`agents`, `parse_transcripts`) — params are
  framework-injected; changing the signature breaks Click wiring **silently**.
- 3 `CLIApp` methods — 38 / 225 / 19 call sites, all params at threshold (6) with
  no natural grouping.
- The rest already use `*` keyword-only splits or an existing params object.

The 2 FIXes are **an inconsistency, not a param count**: `update_event_location`
(`calendar.py:325`) and `update_event_subject` (`:369`) still take bare kwargs
carrying the same `event_id / calendar_id / calendar_name` triple that
`update_event_reminder` (`UpdateEventReminderRequest`) and `update_event_settings`
(`EventSettingsPatch`) already wrap.

**Design consequence.** The signal was *drift from an established local pattern*,
not the metric qlty measured. A wrapper that ranks by param count surfaces 31
findings of which 29 are noise. `triage` should therefore report, alongside each
finding, whether sibling functions in the same module already use a params object
— that single cross-reference is what separates the 2 from the 29. Ranking by
raw `value` is close to useless for this rule.

#### `return-statements` — demoted to Tier D (advisory only)

Triaged as **noise**. The findings are dominated by CLI registration functions
(`register_filters_commands`, 13 returns) that build a subcommand tree, and
validation functions that early-exit per error path — both cases where multiple
returns are the *clear* form. Recommendation: the wrapper should report this rule
but never propose action on it, and `qlty-sweep.yaml` should not staff it.

#### `similar-code` — fully triaged: 6 groups, 6 LEAVE. Demote to Tier D.

13 findings de-duplicate to **6 clone groups** (qlty reports each pair twice, once
per location — the wrapper must dedupe or it will overstate this rule by 2×).
A clone-by-clone read of all 6, with spot-verification of 3:

| Clone group | Mass | Verdict |
|---|---|---|
| `core/date_utils.py:32` + `telemetry/otel/cli/__init__.py:120` | 157 | **False positive.** day→RRULE dict vs. subcommand→help-text dict. |
| `desk/llm_cli.py` + `resume/llm_cli.py` | 141 | **Intentional.** Adapters over `core/llm_cli.make_domain_llm_module`. |
| `agentic.py` × 3 (`desk`, `resume`, `schedule`) | 98 | **Intentional.** Abstraction already exists as `_build_capsule`. |
| `phone/classify.py:71` + `:158` | 94 | **False positive.** Two sibling keys in ONE `_PATTERNS` dict. |
| `whatsapp/meta.py` + `wifi/meta.py` | 89 | **Intentional.** Per-domain `AppMeta` singletons. |
| `metals/vendors.py:31` + `metals_tests/fixtures.py:19` | 80 | **False positive.** Two `__all__` lists, zero symbol overlap. |

**Correction worth recording.** A first-pass scan called the `DAY_MAP` group the
"clearest win — shared constant with one obvious home." That was wrong, and the
deeper pass reversed it. Verified directly: `date_utils.py:32` maps day names to
RRULE codes (`"monday": "MO"`); `telemetry/otel/cli/__init__.py:120` maps
subcommand names to help strings (`"health": "Check OTEL..."`). Two same-shaped
`str→str` dicts of similar size, nothing else in common. **Extracting a shared
constant would have merged two unrelated things** — a refactor strictly worse than
doing nothing, produced by trusting the metric over the content.

**Design consequence — the single most important finding for this wrapper.**
qlty's `similar-code` hasher matches on *structure and size*, not meaning. It fires
on any two similarly-sized dict/list literals and on small adapter modules
implementing a shared interface. Mass is a proxy for *size*, not for *debt* — the
highest-mass finding in the repo (157) was a false positive. A wrapper that ranks
`similar-code` by mass and hands the top N to an agent will confidently propose
harmful merges.

Therefore: **`similar-code` never gets an auto-proposed fix.** `triage` reports the
group, both locations, and requires a human to read them. Demoted from Tier B to
Tier D (advisory).

#### Tier D — advisory: report, never action

| Rule | n | Basis |
|---|---|---|
| `return-statements` | 12 | 12/12 LEAVE. Guard chains, exhaustive case coercers, CLI registration stubs — all clearer with multiple returns. |
| `similar-code` | 13 (6 groups) | 6/6 LEAVE. Structural hasher; see above. |

**Combined result across every smell rule triaged so far: 56 findings examined,
2 worth fixing** — and those 2 were flagged for *pattern drift*, not for the
metric qlty measured. This is the empirical justification for §8's recommendation
to build classification (Phase 1) and stop, rather than any auto-fix machinery.

### Tier C — false positives, suppress with reason

Not a rule class but an outcome class; any rule can land here.

| Pattern | Correct action |
|---|---|
| `S5754` re-raise `SystemExit` in a test asserting it is *not* raised | Inline suppression + reason |
| `S125` "commented out code" on trailing explanatory comments | Inline suppression + reason |
| `S5655` `self:` annotation vs. structural test double | Fix the *annotation* (Protocol), not the test |

**Rule:** a suppression without a stated reason is a defect. The wrapper's
`triage` output should flag any existing suppression lacking a comment.

---

## 6. `qlty-sweep.yaml` — generalized workflow

`qlty-complexity-sweep.yaml` is well-built but hardcodes one rule. Generalize by
**dispatching on tier**, since the tiers already encode the safe execution mode:

```
discover (qlty-assistant scan --format json)
    |
classify (attach tier + strategy; Tier C -> suppress-with-reason list)
    |
plan  [human gate]   <- Tier B findings REQUIRE explicit per-item approval
    |
    +-- Tier A: fan out per directory group (parallel — see worktree warning)
    +-- Tier B: sequential, one agent, reads all sites before editing
    +-- Tier C: single agent applies suppressions + reasons
    +-- Tier D: REPORTED ONLY — no agent, no proposed fix
    |
verify (make test + qlty rescan)   <- must show findings DOWN, tests still green
    |
human-gate
```

Reuse verbatim from the existing workflow: the `PYTHONPATH="$(pwd)/src"` guard,
per-group test resolution, and the before/after finding comparison in `recheck`.

> ### ⚠️ Blocking constraint: isolated worktrees cannot run qlty
>
> `.qlty/qlty.toml` `exclude_patterns` contains `**/.claude/**`. Agents spawned
> with `isolation: "worktree"` land in `.claude/worktrees/<name>/`, so **qlty
> excludes every file they can see and reports a near-empty scan.**
>
> Observed 2026-08-14: an isolated agent reported 1 issue where the session
> worktree reported a stable 50 (three consecutive runs: 50/50/50). It concluded
> the findings were "not reproducible" and — correctly, given what it could
> observe — declined to refactor against them. It also misattributed the cause to
> radarlint non-determinism and `test_patterns` suppression; neither holds.
>
> The failure is **silent and shaped exactly like success**: a clean scan is
> indistinguishable from clean code. This is the same F1 failure mode as
> `qlty check` defaulting to diff-only, one layer down.
>
> **This affects the existing `qlty-complexity-sweep.yaml` today** — scoped
> precisely, after checking the file:
>
> - **Affected:** `decompose-groups` (L243) spawns agents with
>   `isolation:worktree`, and those same agents run `qlty check` on their split
>   files at L286 as a per-file gate. That gate is vacuous — it always passes.
> - **Not affected:** `discover-candidates` (L67, `qlty smells --all --json`) and
>   `validate-imports` (L434, `qlty check` on modified files) are separate stages
>   with no `isolation:worktree`, so they run in the session workspace and scan
>   correctly.
>
> So the workflow still *discovers* and *validates* correctly; what it loses is
> the inner per-file check inside the fan-out. Lower severity than a blanket
> "the workflow is broken," but it is a gate that reports success without
> testing anything, which is worse than having no gate at all.
>
> Mitigations, in preference order:
> 1. Don't isolate agents that must run qlty; partition by file in the session
>    worktree instead (file scopes here are naturally disjoint by domain).
> 2. Have every qlty-running stage assert a **nonzero expected finding count
>    before editing**; treat a suspiciously clean scan as a broken environment,
>    not a clean repo.
> 3. Narrow `exclude_patterns` from `**/.claude/**` to the config dir only — the
>    proper fix, but it touches shared qlty config used by CI and Qlty Cloud, so
>    it needs its own change and review.
>
> The wrapper should enforce (2) directly: `qlty-assistant scan` gains
> `--expect-min N`, exiting nonzero when fewer than N findings are returned, so a
> path-excluded scan fails loudly instead of reading as success.

**Open question for review:** whether to *replace* `qlty-complexity-sweep.yaml` or
run both. Recommendation: keep it, have `qlty-sweep.yaml` delegate the
`file-complexity` tier to it, so a working workflow isn't destabilized.

---

## 7. Risks

| Risk | Mitigation |
|---|---|
| `--json` removed upstream (F4) | `runner.py` fallback + loud failure; fixtures pin the contract |
| Wrapper drifts from qlty's real surface | Unit tests on captured fixtures; `rules` cross-checks against live output in an opt-in integration test |
| Tier B fan-out does damage | Tier B is sequential + human-gated by construction |
| `bin/qlty` shadows the real binary | Named `bin/qlty-assistant` |
| Scope creep into a general lint framework | Explicitly qlty-only; no plugin abstraction |

---

## 8. Recommendation

Build **Phase 1 only**, then reassess. It resolves all four failure modes, is
roughly one PR, and makes the remaining 61 untriaged smells visible — which is
the information needed to decide whether Phases 2–4 are worth it.

Phase 3 (`qlty-sweep.yaml`) is the most speculative and should not be built until
Phase 1 has been used on a couple of real sweeps and the tier model has been
tested against reality.
