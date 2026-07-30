Scope
- Applies to files under `phone/`.

LLM Helpers
- `./bin/llm --app phone agentic --stdout`
- `./bin/llm --app phone domain-map --stdout`
- `./bin/llm --app phone derive-all --out-dir .llm --include-generated`

Notes
- Canonical iPhone layout: rebuild via `./bin/phone-profile-refresh` (plan/layout defaults in `out/ios.plan.yaml` + `out/ios.IconState.yaml`, generated via `./bin/phone export-device`), profile at `out/bcsphone_snap2.layout.mobileconfig`, summary in `out/bcsphone_layout.md`.
