# WhatsApp Assistant

## Overview

Local-only CLI for searching ChatStorage message archives. Entry point: `./bin/whatsapp`

## Architecture

```mermaid
---
title: WhatsApp Search Pipeline
---
flowchart LR
    cli["./bin/whatsapp search"]
    req["SearchRequest\n(contains, contact, from_me,\nsince_days, limit, output_format)"]
    proc["SearchProcessor\n(SafeProcessor)\npipeline.py"]
    search["search_messages()\nsearch.py\nMessageQuery → sqlite3"]
    db["ChatStorage.sqlite\n~/Library/Group Containers/\ngroup.net.whatsapp.WhatsApp.shared/"]
    result["SearchResult\n(rows, output_format)"]
    prod["SearchProducer\n(BaseProducer)\npipeline.py"]
    out["stdout\n(text table or JSON)"]

    cli --> req
    req --> proc
    proc --> search
    search --> db
    db --> search
    search --> result
    result --> prod
    prod --> out
```

## Key Commands

- Search messages: `./bin/whatsapp search --contains "keyword" --limit 50`
- JSON output: `./bin/whatsapp search --contains "keyword" --json`

## Key Modules

- `cli/main.py` — command dispatch; `cmd_search` builds `SearchRequest` with `OutputFormat`
- `pipeline.py` — `SearchProcessor(SafeProcessor)` / `SearchProducer(BaseProducer)`; `SearchRequest` / `SearchResult`
- `search.py` — `search_messages()` against local ChatStorage; raises `NotFoundError` on missing DB

## Pipeline Pattern

- Commands route through `SafeProcessor`/`BaseProducer` — see `core/pipeline.py`.
- `SearchRequest.output_format: OutputFormat` (replaces removed `emit_json` field).
- `SearchProducer` injects `OutputWriter`; output format driven by `OutputFormat`.
- Missing DB raises `NotFoundError` (from `core.cli_errors`).

## Tests

- `tests/whatsapp_tests/`
