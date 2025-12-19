Resume Assistant — Migration State

Completed
- Default profile set to `brian_sherwin` when `--profile` not provided.
- Outputs nested under `_out/<profile>/` (e.g., `data.json`, `resume.docx`, `structure.json`).
- Overlays moved to `config/profiles/<profile>/` with back-compat to legacy `config/<key>.<profile>.yaml`.
- Legacy config and outputs moved to `to_review_to_be_deleted/` for cleanup.
- Added job spec `config/job.rbc_sre.yaml` and alignment-driven render pattern.
- One-page template supports sentence cap for summary and honors `--min-priority` for trimming.

To Consider
- Add a full “modern” RBC template variant if needed.
- Optional: add CLI shortcuts (e.g., `render rbc-onepage`) that wire align+render.

