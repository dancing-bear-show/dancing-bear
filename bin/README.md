# bin/ — Entry Points

Thin wrappers around Python package CLIs. Regenerate generated wrappers with `make bin-wrappers`.

## Generated Python wrappers (`bin/_wrappers.yaml`)

**Primary entry points** (20):

| Wrapper | Module |
|---------|--------|
| `mail` | `mail` |
| `phone` | `phone` |
| `calendar` | `calendars` |
| `schedule` | `schedule` |
| `whatsapp` | `whatsapp` |
| `wifi` | `wifi` |
| `desk` | `desk` |
| `slides` | `slides` |
| `sheets` | `sheets` |
| `maker` | `maker` |
| `assistant` | `core.assistant_cli` |
| `charts` | `charts` |
| `apple-music-assistant` | `apple_music` |
| `apple-music-user-token` | `apple_music.user_token_cli` |
| `diagrams` | `diagrams` |
| `telemetry` | `telemetry.cli` |
| `worker` | `worker.cli` |
| `workflow` | `workflow.cli` |
| `qlty-assistant` | `qlty` |
| `github` | `github_assistant` |


**Legacy `-assistant` aliases** (5, retained for compatibility): `mail-assistant`, `phone-assistant`, `calendar-assistant`, `schedule-assistant`, `wifi-assistant`

Docs should lead with the short name (e.g. `./bin/mail`, not `./bin/mail-assistant`).

## Manual scripts (custom logic, not generated)

`llm`, `path-guard`, `ios-install-profile`, `ios-p12-to-der`, `ios-setup-device`, `ios-pages-sync`, `ios-hotlabel`, `ios-use-device`, `ios-verify-layout`, `ios-identity-verify`, `ios-iconmap-refresh`, `ios-push-layout`, `phone-profile-refresh`, `mail-assistant-auth`, `setup_venv`, `uuidgen-pair`, `apply-calendar-locations`, `reminders-off-sweep`

Also standalone, and absent from the `manual:` list: `pr-assistant`, `worker-install-launchd`, `worker-wait`, `bootstrap`, `bootstrap-otel`.

## Usage

```bash
./bin/mail --help
./bin/mail --agentic --agentic-format yaml --agentic-compact
./bin/assistant mail labels sync
```

