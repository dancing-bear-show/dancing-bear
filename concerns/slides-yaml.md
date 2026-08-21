# Slides Deck YAML Review Guide

## When loaded

Load this guide when authoring or reviewing a slide deck YAML definition, when
editing `src/slides/parsers.py` or `src/slides/schema.py`, or when a generated
`.pptx` does not match what the YAML appears to describe.

Most failures in this domain are **silent**: the deck generates successfully,
exits 0, and produces a file with missing or wrong content. The concerns below
are ordered with the silent-data-loss cases first, because those are the ones a
passing exit code will not catch.

## Deck structure reference

```yaml
title: Deck Title              # deck metadata
author: Author Name            # optional
date: 2026-08-21               # optional; coerced to str
theme_color: LIGHT_2           # MSO_THEME_COLOR name
template_path: path/to/x.pptx  # optional here; can be supplied via --template
layout_map:                    # optional; maps layout name -> template slide index
  bullet: 1
  table: 2
slides:
  - title: Slide One
    subtitle: Optional
    layout: bullet             # bullet | table | title_only | section | breaker
    bullets:
      - Plain string bullet
      - text: Dict bullet
        level: 1
        bold: true
        highlight: ["word"]
        url: https://example.com
      - ["List bullet", 1]     # [text, level?]
    notes: Speaker notes
  - title: Data Table
    layout: table
    headers: [Name, Value]
    rows: [[A, 1], [B, 2]]
```

## Concerns

### bullet-silently-dropped-by-type
- **severity**: critical
- **check**: Verify every entry under `bullets:` is a string, a dict, or a
  list/tuple. Any other YAML type is skipped with no error and no warning.
- **triggers**: Any deck YAML with a `bullets:` list; any edit to `_parse_bullets`
  in `src/slides/parsers.py`.
- **example**: `_parse_bullets` dispatches on `isinstance` for dict, list/tuple,
  and str — a value matching none of these falls off the end of the loop and is
  never appended. A bare number (`- 42`) or a YAML null (`- `) therefore vanishes
  from the rendered slide while generation still exits 0. This is the single
  easiest way to lose deck content without noticing. If you add a branch to
  `_parse_bullets`, keep the fallthrough explicit — either raise, or log the
  skipped value; do not extend the silent-skip behaviour to new types.

### slides-key-wrong-type
- **severity**: critical
- **check**: Verify `slides:` is a YAML list of mappings. A mapping or scalar
  raises; a missing key silently yields an empty deck.
- **triggers**: Any new deck YAML; any deck that generates a file with only the
  title slide.
- **example**: `load_deck_from_dict` raises a clear `ValueError` when `slides` is
  present but not a list — that case is safe. The dangerous case is `slides`
  being **absent or misspelled** (`slide:`, `Slides:`), which resolves to `None`
  and is coerced to `[]`. The deck generates successfully with zero content
  slides. When a generated deck looks empty, check the key spelling before
  debugging the generator.

### bullet-level-bool-coercion
- **severity**: major
- **check**: Verify `level:` values are non-negative integers, never YAML
  booleans.
- **triggers**: Any dict-format bullet with a `level:` key.
- **example**: `_validate_bullet_level` explicitly rejects `bool` before the
  `int()` coercion, because Python's `int(True) == 1` would otherwise silently
  turn `level: true` into a valid sub-bullet. YAML parses `yes`, `on`, and `true`
  as booleans, so `level: yes` is a realistic typo. The validator raises with the
  offending value — keep that bool check if you refactor; removing it
  reintroduces a silent wrong-indent bug.

### bullet-list-form-arity
- **severity**: major
- **check**: Verify list-format bullets have exactly 1 or 2 elements
  (`[text]` or `[text, level]`).
- **triggers**: Any bullet written in list form.
- **example**: `_parse_list_bullet` raises on empty lists and on any list longer
  than 2 elements. A three-element bullet (`["text", 1, "extra"]`) is a hard
  error, not a truncation — this is correct behaviour, but authors coming from
  other deck formats often expect extra positional fields to be ignored.

### url-autodetect-on-plain-strings
- **severity**: minor
- **check**: Be aware that a plain-string bullet whose text begins with
  `http://` or `https://` is automatically turned into a hyperlink whose text is
  the raw URL.
- **triggers**: Any plain-string bullet starting with a URL scheme.
- **example**: `_parse_str_bullet` sets `url=b` when the string starts with a
  scheme. To show link text different from the target, use the dict form with
  explicit `text:` and `url:` keys. To show a URL as literal non-linked text,
  the dict form with no `url:` key is the only option.

### layout-name-not-in-valid-layouts
- **severity**: major
- **check**: Verify each slide's `layout:` is one of `bullet`, `table`,
  `title_only`, `section`, `breaker`.
- **triggers**: Any slide with an explicit `layout:` key; any deck using
  `layout_map`.
- **example**: `VALID_LAYOUTS` in `src/slides/constants.py` is the authoritative
  list. A typo (`layout: bullets`) does not raise at parse time — the slide falls
  through to default handling and renders with the wrong template layout. Check
  the constant rather than trusting recall; the plural/singular distinction
  (`bullet`, not `bullets`) is the common slip.

### layout-map-reserved-key
- **severity**: major
- **check**: Verify `layout_map:` does not use `__fallback__` as a semantic
  layout name.
- **triggers**: Any deck defining a `layout_map:`.
- **example**: `RESERVED_LAYOUT_KEY = "__fallback__"` is used internally for
  fallback resolution. Defining it as a normal entry collides with that
  mechanism. Layout-map values are **template slide indices** (integers), not
  layout names — `bullet: 1` means "use template slide 1 for bullet slides".

### table-slide-missing-headers
- **severity**: major
- **check**: Verify `layout: table` slides define both `headers:` and `rows:`.
- **triggers**: Any slide with `layout: table`.
- **example**: The generator's `_populate_slide` dispatches to the table path only
  when the content is a `TableSlide` **and** `content.headers` is non-empty. A
  table slide with `rows:` but no `headers:` silently falls through to the bullet
  renderer, which produces an empty or malformed slide rather than a table. Rows
  are not validated for consistent column count against headers — a short row
  renders with blank trailing cells.

### template-path-required
- **severity**: critical
- **check**: Verify a template is supplied either via `template_path:` in the
  deck YAML or via `--template` on the command line.
- **triggers**: Any generate invocation.
- **example**: The generator raises when no template resolves. This is deliberate
  — no default template ships with the repo, because any usable template carries
  organisation-specific branding. `--template` overrides `template_path:` in the
  YAML when both are present.

### mermaid-requires-external-binary
- **severity**: major
- **check**: Verify the `mmdc` (mermaid-cli) binary is installed before using
  `mermaid:` on any slide.
- **triggers**: Any slide with a `mermaid:` key.
- **example**: Mermaid slides shell out to `mmdc` to render a PNG at generation
  time. When the binary is absent the generator raises a `RuntimeError` naming
  the npm install command — it does not silently skip the diagram. This is
  correct and should be preserved: a deck that quietly drops its architecture
  diagram is worse than one that fails loudly. Note this is a **generation-time**
  dependency, not an import-time one, so a deck without mermaid slides needs
  nothing installed.

### image-and-mermaid-precedence
- **severity**: minor
- **check**: Be aware that `mermaid:` takes precedence over `image:` when both
  are present on the same slide, and that either suppresses bullets and tables.
- **triggers**: Any slide combining `mermaid:`/`image:` with `bullets:` or table
  keys.
- **example**: `_populate_slide` checks `mermaid` first, then `image`, and returns
  immediately after rendering either. Bullets defined alongside an image are
  silently ignored — not merged, not appended. Split the content across two
  slides if both are needed.

### theme-color-must-be-mso-name
- **severity**: minor
- **check**: Verify `theme_color:` is a valid `MSO_THEME_COLOR` member name, not
  a hex value or CSS colour.
- **triggers**: Any deck setting `theme_color:`.
- **example**: The default is `LIGHT_2`. Values are resolved against python-pptx's
  `MSO_THEME_COLOR` enum, so `#FFFFFF` or `white` are not valid. Table colours are
  separately hard-coded as RGB constants in `constants.py` and are not affected
  by `theme_color:`.

### date-coerced-to-string
- **severity**: minor
- **check**: Be aware that an unquoted ISO date in `date:` is parsed by YAML as a
  `datetime.date` and then coerced with `str()`.
- **triggers**: Any deck setting `date:`.
- **example**: `date: 2026-08-21` becomes the string `"2026-08-21"` after
  coercion, which is usually what you want. For any other display format, quote
  the value (`date: "August 21, 2026"`) so YAML keeps it as a string and the
  coercion is a no-op.
