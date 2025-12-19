Resume Assistant — Domain Map

CLI
- Entrypoint: `resume_assistant/cli/main.py`
- Subcommands: extract, summarize, render, structure, align, candidate-init, style, files, experience

Overlays & Profiles
- `config/profiles/<profile>/profile.yaml` — identity/contact/summary
- `config/profiles/<profile>/skills_groups.yaml` — grouped skills
- `config/profiles/<profile>/experience.yaml` — canonical roles
- Optional: `interests.yaml`, `presentations.yaml`, `languages.yaml`, `coursework.yaml`, `structure.yaml`

Outputs (by profile)
- `_out/<profile>/data.json` — unified dataset
- `_out/<profile>/resume.docx` — rendered resume
- `_out/<profile>/structure.json` — inferred/app-specific section order
- `_out/<profile>/alignment.*.json` — align reports
- `_out/<profile>/style.json` — style profile from corpus

Core Modules
- Rendering: `resume_assistant/docx_writer.py`
- Parsing: `resume_assistant/parsing.py`
- Alignment: `resume_assistant/aligner.py`, `resume_assistant/job.py`
- Filters: `resume_assistant/skills_filter.py`, `resume_assistant/experience_filter.py`
- Priority: `resume_assistant/priority.py`
- Structure inference: `resume_assistant/structure.py`
- Utilities: `resume_assistant/io_utils.py`, `resume_assistant/cleanup.py`, `resume_assistant/style.py`

