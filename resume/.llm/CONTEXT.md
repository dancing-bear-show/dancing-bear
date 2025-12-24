Resume Assistant — LLM Working Context
Last Reviewed: 2025-10-28

Imperatives
- Eliminate unused whitespace in all rendered outputs; prefer tight spacing and compact layouts.
- Optimize to fit content on a single page by default (when feasible) without sacrificing readability.
- Use concise, high-value bullets over prose; group and compress where practical.
- Keep Skills dense: grouped, single-column bulleted items; each item can include a brief descriptor when helpful.
- Preserve PII hygiene: store personal artifacts under `_data/` (gitignored).
- Default to profile-based outputs; generated files nest under `_out/<profile>/` (e.g., `data.json`, `resume.docx`, `structure.json`).
- Reuse saved structure from `_out/<profile>/structure.(json|yaml)` to avoid extraneous writes.

Formatting Rules
- Tighten paragraph spacing (no extra before/after) and minimize bullet indentation.
- Prefer inline date-location lines for roles (e.g., "Title at Company — Start – End · Location").
- Prefer hyphenated year ranges for education (e.g., "2003-2007").
- Use compact page settings when appropriate (narrow margins, modest font sizes) to encourage one-page fit.

Current Abstractions (use consistently)
- Header lines: `_add_header_line` builds `Title at Company — [Location] — (Duration)` and is also used for Education `Degree at Institution — (Dates)`.
- Bullet rendering:
  - Page/section defaults control bullet style and glyph: `page.bullets` / `section.bullets` with `style: plain|list`, `glyph`.
  - Plain bullets are flush-left with zero indent; use everywhere for alignment unless list bullets are explicitly requested.
  - Named bullets: for `NAME: description`, use bold+colored left side and normal right side.
- Group title rendering: `_render_group_title` applies bold and color; falls back to `item_color` for visual harmony with job/education lines.

Section Defaults & Keys
- Global (page): `header_level`, `bullets`, fonts, margins, heading color
- Experience/Education: `item_color`, `location_color`, `duration_color`, `location_brackets`, `duration_brackets`, `meta_pt`, `recent_roles_count`, `recent_max_bullets`, `prior_max_bullets`
- Skills/Technologies: `show_desc`, `desc_separator`, `separator`, `columns`, `compact`, `plain_bullets`

Scope Filters
- Filter Skills and Experience to matched keywords via alignment JSON: `--filter-skills-alignment`, `--filter-exp-alignment`; supply job YAML for synonyms.

Overlays
- Apply profile, grouped skills, experience, and optional lists from `config/profiles/<prefix>/` when `--profile <prefix>` is used.
- Legacy flat naming under `config/` (e.g., `profile.<prefix>.yaml`) is still honored for back-compat.

Proposal Guidance
- Recommend templates and examples that explicitly mention one-page intent, compact bullets, and header/bullet abstractions.
- Prefer `NAME: description` for Skills/Technologies and quantified bullets for Experience (lever + metric + context).

Workflow Hints
- `cd ~/code/cars-sre-utils/resume`
- Extract → curate → align → render.
- Use `--profile <prefix>` to overlay `config/profiles/<prefix>/`.
- Tidy old artifacts with `resume files tidy` (archive or delete), optionally `--purge-temp`.

Alignment Pattern (RBC SRE example)
- Align: `python -m resume align --data _out/brian_sherwin/data.json --job config/job.rbc_sre.yaml --out _out/brian_sherwin/alignment.rbc.json --tailored _out/brian_sherwin/tailored.rbc.json --profile brian_sherwin`
- Render: `python -m resume render --data _out/brian_sherwin/data.json --template config/template.onepage.yaml --profile brian_sherwin --structure-from _out/brian_sherwin/structure.json --filter-skills-alignment _out/brian_sherwin/alignment.rbc.json --filter-exp-alignment _out/brian_sherwin/alignment.rbc.json --min-priority 0.9 --out _out/brian_sherwin/resume.rbc.onepage.docx`

Proposals & Examples
- When proposing examples or templates, explicitly call out whitespace minimization and one-page intent.
- Prefer compact Skills groups with short descriptors (e.g., "OTel — standards-based telemetry; tracing + metrics").
