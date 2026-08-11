# bin/ — Entry Points

Thin wrappers around Python package CLIs. Regenerate generated wrappers with `make bin-wrappers`.

## Generated Python wrappers (`bin/_wrappers.yaml`)

**Primary entry points** (12):

| Wrapper | Module |
|---------|--------|
| `mail` | `mail` |
| `phone` | `phone` |
| `calendar` | `calendars` |
| `schedule` | `schedule` |
| `whatsapp` | `whatsapp` |
| `wifi` | `wifi` |
| `maker` | `maker` |
| `assistant` | `core.assistant_cli` |
| `charts` | `charts` |
| `metals` | `metals` |
| `apple-music-assistant` | `apple_music` |
| `apple-music-user-token` | `apple_music.user_token_cli` |

**Metals utilities** (9): `outlook-metals-scan`, `extract-metals`, `extract-metals-costs`, `extract-metals-costs-outlook`, `build-metals-summaries`, `metals-premium`, `metals-premium-summary`, `metals-spot-series`, `metals-excel-merge`

**Legacy `-assistant` aliases** (5, retained for compatibility): `mail-assistant`, `phone-assistant`, `calendar-assistant`, `schedule-assistant`, `wifi-assistant`

Docs should lead with the short name (e.g. `./bin/mail`, not `./bin/mail-assistant`).

## Manual scripts (custom logic, not generated)

`llm`, `ios-install-profile`, `ios-p12-to-der`, `ios-setup-device`, `ios-pages-sync`, `ios-hotlabel`, `ios-use-device`, `ios-verify-layout`, `ios-identity-verify`, `ios-iconmap-refresh`, `ios-push-layout`, `phone-profile-refresh`, `mail-assistant-auth`, `setup_venv`, `uuidgen-pair`, `apply-calendar-locations`, `reminders-off-sweep`, `diagrams`

Also: `telemetry`, `worker`, `workflow`, `pr-assistant`, `worker-install-launchd`, `worker-wait`, `bootstrap`, `bootstrap-otel`.

## Usage

```bash
./bin/mail --help
./bin/mail --agentic --agentic-format yaml --agentic-compact
./bin/assistant mail labels sync
```

