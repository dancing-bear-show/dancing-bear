Resume Assistant

Overview
- CLI to extract and summarize resume data from LinkedIn profile text and existing resumes, and render a tailored DOCX resume from a simple YAML template.
 - Formatting emphasizes compact, one‑page output with no unused whitespace.
 - Header and bullet rendering are abstracted for consistent, tunable styling.

Quick Start
- Repo path: `cd resume_assistant`
- Show help: `./bin/resume-assistant -h` (preferred) or `python -m resume_assistant -h`
- Make targets:
  - `make venv` — create `.venv`
  - `make deps` — install optional deps (python-docx, pyyaml, pdfminer.six)
- `make test` — run unit tests
  - `make sample-docx` — build a sample DOCX from examples
  - `make clean` — remove caches, `*.pyc`, `.DS_Store`, `~$*.docx` locks, and `out/`
  - `make purge-temp` — remove only `~$*.docx` locks and `.DS_Store`
  - `make distclean` — also remove `out/` (generated artifacts; may include personal data)
  - `make deepclean` — `distclean` + remove `.venv`
- Output naming: add `--profile <prefix>` to auto-write into `out/<prefix>/<kind>.<ext>` (default profile: `brian_sherwin`)

Testing
- Run from this subdirectory so module resolution matches tests:
  - `cd resume_assistant && python3 -m unittest -v`
  - Or invoke a single file: `cd resume_assistant && python3 -m unittest tests/test_cli.py -v`

Source Normalization
- Move transcript files into `_data/sources/` with clear names:
  - `./bin/normalize-sources --prefix brian_sherwin --root .`
  - Produces names like: `_data/sources/brian_sherwin.transcript.official.2020-05.pdf`

Commands
- `extract` — Parse LinkedIn and resume sources into unified YAML/JSON
  - Example: `python -m resume_assistant extract --linkedin linkedin.txt --resume resume.txt --out out/data.json`
- `summarize` — Build a concise summary from unified data
  - Example: `python -m resume_assistant summarize --data out/data.json --seed 'keywords=Python Kubernetes AWS' --out out/summary.md`
  - With profile overlays: add `--profile <prefix>` to overlay `config/profiles/<prefix>/profile.yaml` (plus grouped skills and experience). Legacy `config/profile.<prefix>.yaml` is still supported.
- `render` — Render a `.docx` using a YAML/JSON template (optionally mimic a reference resume’s structure)
  - Example: `python -m resume_assistant render --data out/data.json --template config/template.yaml --seed 'keywords=Python AWS' --out out/jane_doe.docx`
  - Mimic structure: add `--structure-from reference.docx` to align section order and headings.
  - With profile prefix (writes to `out/<prefix>/`): `python -m resume_assistant render --data out/brian_sherwin/data.json --template config/template.example.yaml --profile brian_sherwin`
  - Priority cutoff (dynamic sizing): add `--min-priority 0.8` to keep only items with `priority >= 0.8` across Skills/Technologies, summary lists, and experience roles/bullets.
  - Reuse saved structure automatically: when `--profile <prefix>` is set and `out/<prefix>/structure.(json|yaml)` exists, render will apply it unless `--structure-from` is provided. Fallback to legacy `out/<prefix>.structure.*` is supported.
  - Alignment-based filtering (optional): provide `--filter-skills-alignment align.json` and/or `--filter-exp-alignment align.json` (optionally with `--filter-*-job job.yaml`) to filter Skills/Experience to matched keywords from an alignment report.
  - RBC example (align + render, priority-trim):
    - `python -m resume_assistant align --data out/brian_sherwin/data.json --job config/job.rbc_sre.yaml --out out/brian_sherwin/alignment.rbc.json --tailored out/brian_sherwin/tailored.rbc.json --profile brian_sherwin`
    - `python -m resume_assistant render --data out/brian_sherwin/data.json --template config/template.onepage.yaml --profile brian_sherwin --structure-from out/brian_sherwin/structure.json --filter-skills-alignment out/brian_sherwin/alignment.rbc.json --filter-exp-alignment out/brian_sherwin/alignment.rbc.json --min-priority 0.9 --out out/brian_sherwin/resume.rbc.onepage.docx`
- `structure` — Infer section order and headings from a reference `.docx`
  - Example: `python -m resume_assistant structure --source reference.docx --out out/structure.yaml`
- `align` — Align candidate data to a job posting and produce a tailored dataset
  - Example: `python -m resume_assistant align --data out/data.json --job config/job.yaml --out out/alignment.json --tailored out/tailored.json`
  - With profile overlays: add `--profile <prefix>` to align using the overlaid candidate (profile + grouped skills + canonical experience).
 - LLM capsules (agentic/domain-map/familiar/policies): `./bin/llm --app resume agentic --stdout`, `./bin/llm --app resume domain-map --stdout`, and `./bin/llm --app resume derive-all --out-dir .llm --include-generated --stdout`.
- `candidate-init` — Generate a candidate skills YAML from unified data for curation
  - Example: `python -m resume_assistant candidate-init --data out/data.json --out config/candidate.yaml --include-experience --max-bullets 3`
  - With profile overlays: add `--profile <prefix>` to seed from overlaid data.
- `experience` — Tools for job history summaries
  - Export summary: `python -m resume_assistant experience export --data out/<prefix>/data.json --out config/experience.<prefix>.yaml`
  - Or parse from resume: `python -m resume_assistant experience export --resume ~/Downloads/your_resume.docx --out config/experience.<prefix>.yaml`
- `experience` — Tools for job history summaries
  - Export summary: `python -m resume_assistant experience export --data out/<prefix>/data.json --out config/experience.<prefix>.yaml`
  - Or parse from resume: `python -m resume_assistant experience export --resume ~/Downloads/your_resume.docx --out config/experience.<prefix>.yaml`

Template (YAML)
- Minimal example (keys are canonical; titles are display text):
```
sections:
  - key: summary
    title: Professional Summary
  - key: skills
    title: Core Skills
  - key: experience
    title: Experience
    max_items: 5
  - key: education
    title: Education
```

Contact fields
- Top-level or under `contact`: `email`, `phone`, `location`, `website`, `linkedin`, `github`, plus an optional `links` list. Example:
```
name: Jane Doe
headline: Senior SRE
email: jane@example.com
phone: "+15551234567"
location: Austin, TX
website: https://janedoe.dev
linkedin: https://www.linkedin.com/in/janedoe
github: https://github.com/janedoe
links:
  - https://cal.com/janedoe
  - https://speakerdeck.com/janedoe
# Alternatively, nest under `contact:`
contact:
  email: jane@example.com
  phone: "+15551234567"
  location: Austin, TX
  website: https://janedoe.dev
  linkedin: https://www.linkedin.com/in/janedoe
  github: https://github.com/janedoe
  links: [https://cal.com/janedoe]
```
These appear on the subtitle line as `email | phone | location | website | linkedin | github | links…` with URLs shown without scheme (`https://`), `www.`, or trailing slash.

Notes
- Keep outputs separate from source content.
- Avoid committing personal data beyond what is necessary for examples.
- Optional deps:
  - `python-docx` for `.docx` read/write.
  - `pyyaml` for YAML I/O.
  - `pdfminer.six` for `.pdf` text extraction.
  - PDF resume rendering planned for future releases.

Modern Template
- Use `config/template.modern.yaml` for a streamlined, modern layout emphasizing profile, core skills, and quantified experience.
- Render: `./bin/resume_assistant render --data out/<prefix>/data.json --template config/template.modern.yaml --structure-from ~/Downloads/your_resume.docx --profile <prefix>`

Abilities + One‑Page Templates
- Abilities: `config/template.abilities.yaml` (descriptive Skills/Technologies, compact bullets, identical job/education headers)
- One‑Page: `config/template.onepage.yaml` (limits roles/bullets, smaller fonts/margins to fit one page)

Current State (Formatting + Features)
- Headers
  - Jobs and Education use the same header line abstraction: `Title at Company — [Location] — (Start – End)` and `Degree at Institution — (Start – End)`.
  - Title/Company (Degree/Institution) are bold + colored; Location and Duration are visually distinct (brackets, smaller gray text).
- Bullets
  - Plain bullets (flush‑left, tight spacing) by default; configurable via `page.bullets` or per‑section `bullets`.
  - Profile, Skills, Technologies, Experience bullets are aligned to section headings with zero indent.
- Skills/Technologies
  - Rendered as `NAME: description` when `show_desc: true` (configurable `desc_separator`, default `": "`).
  - Group titles (e.g., Platform) are bold and can use background shading via `group_title_bg`; text color uses `group_title_color` or auto‑contrasts against the background.
- Experience
  - Per‑recency bullet controls (most recent first): recent N roles show up to X bullets; prior roles up to Y bullets.
  - Identical header formatting to Education.
- Technologies Section
  - Dedicated section added; pulls from `data.technologies` or the `Technology/Technologies/Tooling` skills group; supports `NAME: description`.
- Metadata
  - Document metadata includes job locations and contact info for searchability; category lists unique locations.
- Page Defaults
  - `page.header_level`: default section heading level.
  - `page.bullets`: `{ style: plain|list, glyph: "•" }` with per‑section override.

Template Keys (high‑value)
- Global (page)
  - `header_level`: 1 (default heading level)
  - `bullets.style`: `plain` (flush‑left) or `list` (uses Word list style)
  - `bullets.glyph`: e.g., `"•"`
  - `margins_in`, `body_pt`, `h1_pt`, `title_pt`, `h1_color`, `h1_bg` (auto‑contrasts heading text if `h1_color` omitted)
- Experience / Education
  - `item_color`, `location_color`, `duration_color`
  - `location_brackets`, `duration_brackets`, `meta_pt`
  - `recent_roles_count`, `recent_max_bullets`, `prior_max_bullets`
- Skills / Technologies
  - `bullets` (style/glyph), `plain_bullets`, `columns`, `compact`
  - `show_desc`, `desc_separator`, `separator` (for inline lists), `group_title_color`
  - `group_title_bg`: shaded background behind group titles; when set, text color auto‑contrasts if `group_title_color` is omitted
  - `priority`/`usefulness` (float 0–1): optional; used with `--min-priority` to include only higher‑importance items

- Optional sections
  - `interests` (Personal Interests): list of strings or dicts `{ text, priority? }`; add to template with `key: interests` and `bullets: true`.
    - Overlay from profile (`interests:` list) or `config/interests.<profile>.yaml`.
  - `presentations` (Public Presentations): list of strings or dicts `{ title?, event?, year?, link?, priority? }`; add to template with `key: presentations`.
    - Overlay from profile (`presentations:` list) or `config/presentations.<profile>.yaml`.
  - `languages` (Languages): list of strings or dicts `{ name?/language?, level?/proficiency?, priority? }`; add to template with `key: languages`.
    - Overlay from profile or `config/languages.<profile>.yaml`.
  - `coursework` (Selected Coursework): list of strings or dicts `{ name?/course?, desc?, priority? }`; add to template with `key: coursework`.
    - Overlay from profile or `config/coursework.<profile>.yaml`.

Priority‑Based Sizing (optional)
- Add `priority` (or `usefulness`) to any of the following and filter at render time with `--min-priority <cutoff>`:
  - Skills groups: each item may specify `priority: 0.0–1.0`
  - Technologies: each item (string or dict) may specify priority
  - Summary: if provided as a list, items may specify priority; strings default to 1.0
  - Experience: roles can include `priority`; bullets can be strings or dicts with `text/line/name` and an optional `priority`
- Example:
```
skills_groups:
  - title: Technology
    items:
      - name: OpenTelemetry (OTel)
        desc: standards‑based telemetry
        priority: 1.0
      - name: Jira/Atlassian tooling
        desc: workflows and integrations
        priority: 0.6

summary:
  - { text: "Drive SLO adoption", priority: 1.0 }
  - { text: "Automate with Python CLIs", priority: 0.8 }

experience:
  - title: Senior SRE
    company: ExampleCo
    priority: 0.9
    bullets:
      - { text: "Cut MTTR 30% via runbooks", priority: 0.9 }
      - "Built Terraform modules"
```
- Compact render (keep higher‑priority only):
  - `./bin/resume-assistant render --data out/data.json --template config/template.yaml --min-priority 0.8 --out out/jane_doe.compact.docx`

Overlays + Filtering
- Overlays (auto‑applied with `--profile <prefix>`) via `config/profiles/<prefix>/`:
  - `profile.yaml` (name/email/phone/location)
  - `skills_groups.yaml` (grouped skills; supports `name` + `desc`)
  - `experience.yaml` (canonical job history list)
  - Optional: `interests.yaml`, `presentations.yaml`, `languages.yaml`, `coursework.yaml`
  - Legacy flat naming under `config/` (e.g., `profile.<prefix>.yaml`) remains supported and will be picked up if present.
- Targeted scope (optional):
  - `--filter-skills-alignment` and `--filter-exp-alignment` filter to matched keywords from an alignment JSON; `--filter-*-job` supplies synonyms.

Tidy + Make Targets
- `make tidy-data` / `make tidy-out` — archive/delete older artifacts; `--purge-temp` removes `~$*.docx`, `.DS_Store`.
- `make tidy-temp` — purge only temp/lock files in `_data/` and `out/` using the CLI (`files tidy --purge-temp`).
- `make exp-export` — export `config/experience.$(TIDY_PREFIX).yaml` from `out/$(TIDY_PREFIX)/data.json`.

Tests
- Run local tests for this module only to avoid namespace collisions with parent repos:
  - `python -m unittest discover -s ./tests -p 'test_*.py' -v`

Examples
- Template: `config/template.example.yaml`
- Sample inputs: `examples/linkedin.sample.txt`, `examples/resume.sample.txt`

Profiles & Outputs
- Profiles live under `config/profiles/<prefix>/` and may contain: `profile.yaml`, `skills_groups.yaml`, `experience.yaml`, `interests.yaml`, `presentations.yaml`, `languages.yaml`, `coursework.yaml`, `structure.yaml`.
- Outputs are nested by profile in `out/<prefix>/` with conventional names: `data.json`, `summary.md`, `resume.docx`, `structure.json`, `alignment.json`, `style.json`.
- Default profile is `brian_sherwin`; override with `--profile <prefix>`.

Internals
- Overlays: `resume_assistant/overlays.py` centralizes profile/grouped-skills/experience overlays.
- Priority filtering: `resume_assistant/priority.py` applies `--min-priority` cutoff across known lists.
- Build sample DOCX: `make sample-docx` (outputs `out/sample/data.json` and `out/sample/resume.docx`)
- Export experience summary: `make exp-export` (writes `config/experience.$(TIDY_PREFIX).yaml`)

PII Handling
- Use `_data/` (gitignored) for any personal artifacts:
  - Extract to `_data/`: `./bin/resume_assistant extract --resume ~/Downloads/your_resume.docx --out _data/candidate.json`
  - Curate skills YAML: `./bin/resume_assistant candidate-init --data _data/candidate.json --out _data/candidate.yaml --include-experience`
  - Align: `./bin/resume_assistant align --data _data/candidate.yaml --job config/job.yaml --out _data/alignment.json --tailored _data/tailored.json`
  - Render: `./bin/resume_assistant render --data _data/tailored.json --template config/template.example.yaml --structure-from ~/Downloads/your_resume.docx --out _data/your_name.tailored.docx`
- Keep `out/` gitignored for generated artifacts. Use `out/` for curated outputs you want to keep (tracked at repo root policy).

Workflow (skills-first → job → tailored)
- Build skills input:
  - Extract baseline: `./bin/resume_assistant extract --resume ~/Downloads/your_resume.docx --out out/candidate.json`
  - Generate skills YAML: `./bin/resume_assistant candidate-init --data out/candidate.json --out config/candidate.yaml --include-experience`
  - Manually curate `config/candidate.yaml` (focus on keywords; avoid prose)
- Provide a job posting YAML (see example under Job Posting YAML), save as `config/job.yaml`
- Align and tailor:
  - `./bin/resume_assistant align --data config/candidate.yaml --job config/job.yaml --out out/alignment.json --tailored out/tailored.json --max-bullets 4`
- Render tailored DOCX:
  - `./bin/resume_assistant render --data out/tailored.json --template config/template.example.yaml --structure-from ~/Downloads/your_resume.docx --out out/your_name.tailored.docx`

Job Posting YAML
- Minimal example to drive alignment and tailoring:
```
title: Senior SRE
company: ExampleCo
keywords:
  required:
    - skill: Kubernetes
      weight: 3
    - skill: AWS
      weight: 3
  preferred:
    - skill: Grafana
      weight: 2
  soft_skills:
    - Communication
    - Collaboration
  tech_skills:
    - Python
    - Docker
  technologies:
    - EKS
  nice_to_have:
    - skill: Terraform
      weight: 1
  synonyms:
    Kubernetes: [k8s, EKS]
```
- Use `align` to generate an alignment report (matched/missing keywords, experience scores) and an optional `tailored` candidate dataset pruned to matched keywords/bullets.
- Feed `tailored.json` into `render` to produce a keyword-focused DOCX.
Style Corpus
- Put public-safe writing samples in `corpus/`; put personal/private samples under `_data/corpus/`.
- Build a style profile JSON:
  - `./bin/resume_assistant style build --corpus-dir corpus --profile brian_sherwin`
- Use with summarize/render to bias keyword selection:
  - `./bin/resume_assistant summarize --data out/brian_sherwin/data.json --style-profile out/brian_sherwin/style.json --profile brian_sherwin`
  - `./bin/resume_assistant render --data out/brian_sherwin/data.json --style-profile out/brian_sherwin/style.json --template config/template.example.yaml --structure-from ~/Downloads/your_resume.docx --profile brian_sherwin`
