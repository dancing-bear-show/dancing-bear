Resume Assistant — Patterns

Repo Path
- `cd resume`

Profile Overlay + Nested Outputs
- Use `--profile <prefix>` to apply overlays from `config/profiles/<prefix>/`.
- Outputs go to `out/<prefix>/` (e.g., `data.json`, `resume.docx`, `structure.json`).

One-Page Render (compact)
- `python -m resume render --data out/<prefix>/data.json --template config/template.onepage.yaml --profile <prefix> --structure-from out/<prefix>/structure.json --out out/<prefix>/resume.onepage.docx`

Alignment + Tailored Render (example)
- Align: `python -m resume align --data out/brian_sherwin/data.json --job config/job.rbc.yaml --out out/brian_sherwin/alignment.rbc.json --tailored out/brian_sherwin/tailored.rbc.json --profile brian_sherwin`
- Render with filters: `python -m resume render --data out/brian_sherwin/data.json --template config/template.onepage.yaml --profile brian_sherwin --structure-from out/brian_sherwin/structure.json --filter-skills-alignment out/brian_sherwin/alignment.rbc.json --filter-exp-alignment out/brian_sherwin/alignment.rbc.json --min-priority 0.9 --out out/brian_sherwin/resume.rbc.onepage.docx`

Experience Export
- `python -m resume experience export --data out/<prefix>/data.json --out config/experience.<prefix>.yaml --max-bullets 8 --profile <prefix>`

Style Profile
- Build: `python -m resume style build --corpus-dir corpus --profile <prefix>` → writes `out/<prefix>/style.json`
- Use: add `--style-profile out/<prefix>/style.json` to render/summarize.

Tidy
- Archive/delete: `python -m resume files tidy --dir _out --prefix <prefix> --suffixes .json,.docx --keep 3`
- Purge temp: `python -m resume files tidy --dir _out --purge-temp`
