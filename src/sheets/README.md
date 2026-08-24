# Sheets

Generate styled `.xlsx` spreadsheets from YAML workbook definitions. Entry point: `./bin/sheets`.

Supports `--agentic --agentic-format json` (auto-derived schema).

## Key Commands

```bash
./bin/sheets generate workbook.yaml
./bin/sheets generate workbook.yaml -o out/report.xlsx
./bin/sheets validate workbook.yaml
```

Without `-o`, the workbook is written to `output_dir("sheets")` — by default
`~/.local/share/dancing-bear/sheets/<name>.xlsx`, outside the checkout
(see `src/core/paths.py`). Pass `-o` for an explicit path.

## Workbook YAML Example

```yaml
title: Q3 Report
author: Brian Sherwin
date: 2026-08-24
sheets:
  - name: Summary
    headers: [Metric, Value, Notes]
    rows:
      - [Revenue, "$1.2M", ""]
      - [Churn, "2%", "Improved"]
    header_style:
      bg_color: "#1A3A5C"
      text_color: "#FFFFFF"
      bold: true
      font_size: 11
    alternating_rows: true
    freeze_rows: 1
    freeze_cols: 0
  - name: Detail
    headers: [Date, Item, Amount]
    rows:
      - ["2026-08-01", Widget, 500]
      - ["2026-08-15", Gadget, 700]
```

## Architecture

```
yaml[workbook.yaml] → cli.py[generate/validate] → generator.py[load_workbook_from_yaml]
                                                 → schema.py[SheetWorkbook/SheetTab/...]
                                                 → SheetGenerator → openpyxl → .xlsx
```

## Key Modules

- `cli.py` — command dispatch: `generate`, `validate`
- `schema.py` — `SheetWorkbook`, `SheetTab`, `HeaderStyle`, `SheetMetadata`
- `generator.py` — `SheetGenerator`, `load_workbook_from_yaml`, `generate_from_yaml`, `generate_xlsx`
- `constants.py` — YAML key names, color defaults, width bounds, freeze defaults
- `agentic.py` — `--agentic` capsule
- `meta.py` — `AppMeta` (app id, purpose, example command)

## Tests

`tests/sheets_tests/`
