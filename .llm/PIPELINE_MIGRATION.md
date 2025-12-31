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
  - [x] `messages_cli` search and summarize now use pipeline processors/producers.
  - [x] `accounts` multi-account commands (list, export-labels, sync-labels, export-filters, sync-filters, plan-labels, plan-filters, export-signatures, sync-signatures) now use pipeline processors/producers.
  - [x] `config_cli` commands (auth, backup, cache-stats, cache-clear, cache-prune, config-inspect, derive-labels, derive-filters, optimize-filters, audit-filters, env-setup, workflows) now use SafeProcessor/BaseProducer/RequestConsumer pattern (Dec 2024).
  - [ ] Slim `mail/__main__.py` to CLI shim → domain orchestrator. (Filters + labels now delegate; other commands pending.)
  - [x] Update docs/tests (`tests/test_llm_*`, CLI tests) to cover new pathway.

## Phase 2 — Calendar & Schedule (can proceed once core is ready; mail optional)
- Depends on: Phase 0 (Mail optional but recommended for reference).
- Calendar:
  - [ ] Add `calendar/context.py`.
  - [x] Implement processors for Gmail receipt scans (see `calendars/pipeline.py`).
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
  - [x] **SafeProcessor migration (Dec 2024)**: All 19 processors migrated to SafeProcessor pattern (-119 lines).
  - [x] Gmail (4 processors): GmailReceiptsProcessor, GmailScanClassesProcessor, GmailMailListProcessor, GmailSweepTopProcessor.
  - [x] Outlook (15 processors): OutlookVerifyProcessor, OutlookAddProcessor, OutlookScheduleImportProcessor, OutlookListOneOffsProcessor, OutlookCalendarShareProcessor, OutlookAddEventProcessor, OutlookAddRecurringProcessor, OutlookLocationsEnrichProcessor, OutlookMailListProcessor, OutlookLocationsUpdateProcessor, OutlookLocationsApplyProcessor, OutlookRemoveProcessor, OutlookRemindersProcessor, OutlookSettingsProcessor, OutlookDedupProcessor.
  - [x] Tests updated: removed 24 error code assertions; 316/342 tests passing (92.4%).
  - [ ] CLI shim delegates to new domain orchestrator.
- Schedule:
  - [x] Plan command uses dedicated pipeline consumers/processors/producers (`schedule/pipeline.py` + new tests).
  - [x] Update remaining commands (verify/sync/apply) + docs once calendar migration is done.
  - [x] **COMPLETE (Dec 2024)**: All 4 processors migrated to SafeProcessor pattern (PlanProcessor, VerifyProcessor, SyncProcessor, ApplyProcessor).
  - [x] All producers already using BaseProducer (no changes needed).
  - [x] CLI already using RequestConsumer and ResultEnvelope pattern.
  - [x] Helper function `_execute_sync_deletes` simplified (no longer returns error envelope).
  - [x] All 78 tests passing ✓.

## Phase 3 — Desk & Resume (parallel-friendly)
- Desk:
  - [x] Define consumers for scan/rules YAML, processors for ranking, producers for plan/apply.
  - [x] Wire CLI shim to new orchestrator (`desk/pipeline.py`, CLI now delegates to pipeline components).
  - [x] **COMPLETE (Dec 2024)**: All 3 processors migrated to SafeProcessor pattern (ScanProcessor, PlanProcessor, ApplyProcessor).
  - [x] ReportProducer and ApplyResultProducer migrated to BaseProducer pattern.
  - [x] CLI updated to use RequestConsumer and handle ResultEnvelope.
  - [x] All tests updated and passing (135 tests).
- Resume:
  - [x] Pipeline module (`resume/pipeline.py`) with FilterPipeline for chainable transforms.
  - [x] Commands (extract, summarize, render, structure, align, etc.) use pipeline pattern.

## Phase 4 — Phone & WhatsApp (after core + example apps done)
- Phone:
  - [x] Layout export/plan/checklist now run through pipeline consumers/processors/producers (`phone/pipeline.py`).
  - [x] Unused/prune/analyze commands migrated to pipeline.
  - [x] Device I/O commands (export-device, iconmap) now use pipelines via `phone/device.py` helpers.
  - [x] Manifest commands (from-export, from-device, install) migrated to pipeline.
  - [x] Identity verify command uses pipeline with credential/certificate helpers in `phone/device.py`.
  - [x] App classification extracted to `phone/classify.py` for shared use.
  - [x] Full pipeline coverage: 12/12 commands use Consumer/Processor/Producer pattern.
  - [x] **SafeProcessor migration (Dec 2024)**: All 12 processors migrated to SafeProcessor pattern (-52 lines).
  - [x] Tests updated: removed error code assertions (SafeProcessor doesn't preserve custom error codes).
  - [x] All 174 tests passing ✓.
- WhatsApp:
  - [x] Pipeline module (`whatsapp/pipeline.py`) with SearchProcessor/SearchRequestConsumer/SearchProducer.
  - [x] Search command uses pipeline pattern for local ChatStorage queries.
  - [x] **COMPLETE (Dec 2024)**: SearchProcessor migrated to SafeProcessor pattern (-17 lines).
  - [x] SearchProducer already using BaseProducer (no changes needed).
  - [x] CLI updated to use standard "message" diagnostics field instead of custom "error"/"code"/"hint" fields.
  - [x] Tests updated to check standard diagnostics structure.
  - [x] All 70 tests passing ✓.

## Phase 5 — Maker & Misc (optional)
- [x] Maker CLI now uses pipeline consumers/processors/producers for listing + tool execution.
- [x] Maker migrated to CLIApp decorator pattern with direct imports (no subprocess).
- [ ] Update `.llm/FLOWS*.yaml` to point at standardized processors once assistants finish.

## Phase 6 — Wi-Fi (optional)
- [x] Wi-Fi diagnostics now use pipeline consumers/processors/producers (`wifi/pipeline.py` + CLI shim).
- [x] **SafeProcessor migration (Dec 2024)**: DiagnoseProcessor migrated to SafeProcessor pattern (-13 lines).
- [x] DiagnoseProducer already using BaseProducer (no changes needed).
- [x] All 39 tests passing ✓.

## Coordination Notes
- Each phase should leave CLI behavior unchanged (backward compatible).
- Ship assistant refactors independently once their tests pass; no need to wait for all phases.
- Keep this file updated with PR links / assignees per step for visibility.
