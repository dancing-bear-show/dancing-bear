# Familiarize Mode (Strict + Tiers)

Strict default (capsule‑only):
- Read only `.llm/familiarize.yaml` to get oriented without opening large files.
- Generate if missing: `./bin/llm familiar --stdout` (or `--write .llm/familiarize.yaml`).

Optional (on‑demand):
- Add `.llm/DOMAIN_MAP.md` for programmatic CLI tree + key modules.
- Prefer compact, agentic CLI schemas over `--help`:
  - `./bin/assistant mail --agentic --agentic-format yaml --agentic-compact`
  - `./bin/llm agentic --stdout`

Extended (explicit only):
- Heavy files require intent: `README.md`, `AGENTS.md`, provider/README files.

Budgets (optional env):
- `FAMILIARIZE_TOKEN_BUDGET` (e.g., 500) and `BUDGET_BYTES_PER_TOKEN` (default 4.0)
- Exclude noisy paths with `LLM_EXCLUDE` (e.g., `backups,_disasm,out,_out`)
