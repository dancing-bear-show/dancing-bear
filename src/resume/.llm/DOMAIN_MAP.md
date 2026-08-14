Resume Assistant — Domain Map

CLI
- Entrypoint: `resume/cli/main.py`
- Subcommands: extract, summarize, render, structure, align, candidate-init, style, files, experience

Overlays & Profiles
- `config/profiles/<profile>/profile.yaml` — identity/contact/summary
- `config/profiles/<profile>/skills_groups.yaml` — grouped skills
- `config/profiles/<profile>/experience.yaml` — canonical roles
- Optional: `interests.yaml`, `presentations.yaml`, `languages.yaml`, `coursework.yaml`, `structure.yaml`

Outputs (by profile)
- `out/<profile>/data.json` — unified dataset
- `out/<profile>/resume.docx` — rendered resume
- `out/<profile>/structure.json` — inferred/app-specific section order
- `out/<profile>/alignment.*.json` — align reports
- `out/<profile>/style.json` — style profile from corpus

Core Modules
- Rendering: `resume/docx_writer.py`
- Parsing: `resume/parsing_experience_{docx,pdf,text}.py`, `resume/parsing_linkedin.py`
- Alignment: `resume/aligner.py`, `resume/job.py`
- Filters: `resume/skills_filter.py`, `resume/experience_filter.py`
- Priority: `resume/priority.py`
- Structure inference: `resume/structure.py`
- Utilities: `resume/io_utils.py`, `resume/cleanup.py`, `resume/style.py`

