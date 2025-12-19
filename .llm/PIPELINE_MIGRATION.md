# Pipeline Migration Plan (Consumer → Processor → Producer)

This checklist tracks the refactor to move every assistant to the new layered design
(`core` pipeline abstractions + per-app CLI/domain shims). Items call out dependencies
so multiple engineers can work in parallel without stepping on each other.

## Phase 0 — Shared Core (blocking for everyone)
- [x] `core/pipeline.py`: base `Consumer`, `Processor`, `Producer`, `ResultEnvelope`.
- [x] `core/context.py`: `AppContext` helper + creds loader.
- [x] `core/testing.py`: fakes/mixins so assistants can unit-test processors.
- [x] Docs: short README in `core/` that explains the pattern.

## Phase 1 — Mail (unblocks dependent assistants)
- Depends on: Phase 0 complete.
- Steps:
  - [x] Introduce `mail/context.py` building `MailContext`.
  - [x] Move filter planning into processors (`filters/processors.py`).
  - [x] Wrap config/IO in consumers (`filters/consumers.py`) and producers (`plan/producers.py`).
  - [x] Refactor filters sync to consumer/processor/producer and delegate via `filters/commands.py`.
  - [x] Filters impact/metrics run through consumers/processors/producers.
  - [x] Labels plan/sync now share `labels/*` pipeline modules and CLI shims.
  - [x] Labels export runs through the same pipeline (consumer + processor + producer).
  - [x] Filters export uses consumers/processors/producers and delegates via `filters/commands.py`.
  - [x] Filters sweep reuses the pipeline (dry-run + apply via `filters/commands.py`).
  - [x] Filters sweep-range moves to the pipeline (windowed instructions + CLI shim).
  - [x] Filters prune-empty uses the pipeline (counts + retry deletes).
  - [x] Filters add-forward-by-label now uses pipeline consumers/processors/producers.
  - [x] Filters add-from-token / rm-from-token now use the pipeline.
  - [ ] Slim `mail_assistant/__main__.py` to CLI shim → domain orchestrator. (Filters + labels now delegate; other commands pending.)
  - [x] Update docs/tests (`tests/test_llm_*`, CLI tests) to cover new pathway.

## Phase 2 — Calendar & Schedule (can proceed once core is ready; mail optional)
- Depends on: Phase 0 (Mail optional but recommended for reference).
- Calendar:
  - [ ] Add `calendar/context.py`.
  - [x] Implement processors for Gmail receipt scans (see `calendar_assistant/pipeline.py`).
  - [x] Outlook verify-from-config now uses pipeline processor/producer.
  - [x] `outlook add-from-config` now runs through `OutlookAddProcessor`/`OutlookAddProducer`.
  - [x] Location sync commands use `OutlookLocations*` processors/producers.
  - [x] Extend pipeline coverage to dedup (Outlook dedup now uses pipeline processors/producers).
  - [x] Extend pipeline coverage to remove-from-config (Outlook remove now uses pipeline processors/producers).
  - [x] Extend pipeline coverage to reminders commands (off + set now share pipeline processors/producers).
  - [x] Outlook settings-apply runs through Settings processor/producer.
  - [x] `list-one-offs` now uses ListOneOffs processor/producer.
  - [x] `calendar-share` handled via pipeline processor/producer.
  - [x] `mail-list` now uses MailList processor/producer.
  - [x] `add` quick-create events use pipeline processor/producer.
  - [x] `add-recurring` uses shared pipeline (create_recurring_event).
  - [x] `locations-enrich` now uses pipeline processor/producer.
  - [x] Gmail `scan-classes` now uses pipeline processor/producer.
  - [x] Gmail `mail-list` now uses pipeline processor/producer.
  - [x] Gmail `sweep-top` now uses pipeline processor/producer.
  - [ ] CLI shim delegates to new domain orchestrator.
- Schedule:
  - [x] Plan command uses dedicated pipeline consumers/processors/producers (`schedule_assistant/pipeline.py` + new tests).
  - [ ] Update remaining commands (verify/sync/apply) + docs once calendar migration is done.

## Phase 3 — Desk & Resume (parallel-friendly)
- Desk:
  - [x] Define consumers for scan/rules YAML, processors for ranking, producers for plan/apply.
  - [x] Wire CLI shim to new orchestrator (`desk_assistant/pipeline.py`, CLI now delegates to pipeline components).
- Resume:
  - [ ] Consumers for LinkedIn/resume sources, processors for summarize/render, producers for DOCX/YAML.

## Phase 4 — Phone & WhatsApp (after core + example apps done)
- Phone:
  - [x] Layout export/plan/checklist now run through pipeline consumers/processors/producers (`phone/pipeline.py`).
- WhatsApp:
  - [ ] Sqlite consumer, search processors, text/JSON producers.

## Phase 5 — Maker & Misc (optional)
- [x] Maker CLI now uses pipeline consumers/processors/producers for listing + tool execution.
- Update `.llm/FLOWS*.yaml` to point at standardized processors once assistants finish.

## Coordination Notes
- Each phase should leave CLI behavior unchanged (backward compatible).
- Ship assistant refactors independently once their tests pass; no need to wait for all phases.
- Keep this file updated with PR links / assignees per step for visibility.
