Scope
- Applies to shell scripts under `bin/`.

Guidelines
- Scripts are Bash-compatible; prefer portable constructs but Bash arrays/[[ ]] are acceptable.
- Do not echo secrets; read credentials via profiles or env.
- Keep logic minimal; defer to Python package CLIs for behavior.
