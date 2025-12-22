# LLM Agent Inventory

## Assistants

| Name | Entry Point | Purpose |
|------|-------------|---------|
| mail | `./bin/mail-assistant` | Gmail/Outlook labels, filters, signatures |
| calendar | `./bin/calendar-assistant` | Outlook calendar operations |
| schedule | `./bin/schedule-assistant` | Plan/apply calendar events from CSV |
| resume | `./bin/resume-assistant` | Extract/summarize/render resumes |
| phone | `./bin/phone` | iOS home screen layout tooling |
| whatsapp | `./bin/whatsapp` | Local-only ChatStorage search |
| maker | `./bin/maker` | Utility generators |
| desk | `./bin/desk-assistant` | Desktop file organization |
| wifi | `./bin/wifi` | WiFi network utilities |

## LLM Context Files

| File | Purpose |
|------|---------|
| `CONTEXT.md` | System overview, architecture, rules |
| `DOMAIN_MAP.md` | CLI tree, flows index, binaries |
| `PATTERNS.md` | Copy-paste code templates |
| `COMMANDS.md` | Curated command reference |
| `MIGRATION_STATE.md` | Provider abstraction status |
| `FAMILIARIZE_CORE.md` | Familiarization mode policy |

## Key Directories

| Path | Purpose |
|------|---------|
| `config/` | Canonical YAML inputs (source of truth) |
| `out/` | Derived outputs, plans, exports |
| `bin/` | CLI wrapper scripts |
| `core/` | Shared helpers (textio, yamlio, auth) |
| `tests/` | Unittest suite |

## Regenerate

```bash
./bin/llm inventory --write .llm/INVENTORY.md
```
