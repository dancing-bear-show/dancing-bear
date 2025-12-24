Resume Assistant — Patterns

Repo Path
- `cd resume`

Profile Overlay + Nested Outputs
- Use `--profile <prefix>` to apply overlays from `config/profiles/<prefix>/`.
- Outputs go to `_out/<prefix>/` (e.g., `data.json`, `resume.docx`, `structure.json`).

One-Page Render (compact)
- `python -m resume render --data _out/<prefix>/data.json --template config/template.onepage.yaml --profile <prefix> --structure-from _out/<prefix>/structure.json --out _out/<prefix>/resume.onepage.docx`

Alignment + Tailored Render (RBC example)
- Align: `python -m resume align --data _out/brian_sherwin/data.json --job config/job.rbc_sre.yaml --out _out/brian_sherwin/alignment.rbc.json --tailored _out/brian_sherwin/tailored.rbc.json --profile brian_sherwin`
- Render with filters: `python -m resume render --data _out/brian_sherwin/data.json --template config/template.onepage.yaml --profile brian_sherwin --structure-from _out/brian_sherwin/structure.json --filter-skills-alignment _out/brian_sherwin/alignment.rbc.json --filter-exp-alignment _out/brian_sherwin/alignment.rbc.json --min-priority 0.9 --out _out/brian_sherwin/resume.rbc.onepage.docx`

Experience Export
- `python -m resume experience export --data _out/<prefix>/data.json --out config/experience.<prefix>.yaml --max-bullets 8 --profile <prefix>`

Style Profile
- Build: `python -m resume style build --corpus-dir corpus --profile <prefix>` → writes `_out/<prefix>/style.json`
- Use: add `--style-profile _out/<prefix>/style.json` to render/summarize.

Tidy
- Archive/delete: `python -m resume files tidy --dir _out --prefix <prefix> --suffixes .json,.docx --keep 3`
- Purge temp: `python -m resume files tidy --dir _out --purge-temp`
