# Phone

- Local-only CLI for iOS/iPadOS layout exports, plan scaffolds, manifests, and identity verification.
- Entry point: `./bin/phone` (includes `export`, `plan`, `checklist`, `manifest`, `identity`, etc.).
- LLM helpers:
  - `./bin/llm --app phone agentic --stdout`
  - `./bin/llm --app phone domain-map --stdout`
  - `./bin/llm --app phone derive-all --out-dir .llm --include-generated`

## Repeatable Home Screen Org Flow (single-page, category folders)

1) **Export/inspect layout**
   - Live (cfgutil): `./bin/ios-verify-layout --device-label <label>` or `--udid <UDID>`
   - From backup: `./bin/phone export --out out/ios.IconState.yaml`

2) **Build profile** (spec-aligned, single page)
   - Example (latest profile used): `out/homescreen.spec.mobileconfig`
   - Procedural build: `./bin/phone profile build --plan <plan.yaml> --layout <export.yaml> --all-apps-folder-name "All Apps" --all-apps-folder-page 2 --out out/ios.mobileconfig`
   - Current canned layout: dock = Mail/Safari; root apps on page 1: Settings, Calculator, Camera, Clock, Find My, Calendar, Messages, Photos, Edge, YouTube, YouTube Kids; folders on page 1: Home Freeform, Socials, News, Financials, Retail, Media, Utilities.

3) **Install apps**
   - Configurator UI: select device → Add → Apps → choose missing apps (Edge/YouTube/etc.).
   - CLI requires IPAs: `/Applications/Apple\\ Configurator.app/Contents/MacOS/cfgutil --ecid <ECID> install-app /path/to/app.ipa`.
   - Without IPAs, use the UI “Add → Apps” route.

4) **Install layout profile** (manual approval still required)
   - `./bin/ios-install-profile --profile out/homescreen.spec.mobileconfig --udid <UDID> --no-prompt`
   - Tap Install on the device if prompted.

5) **Verify layout**
   - `./bin/ios-verify-layout --device-label <label>` (or `--udid <UDID>`) to confirm dock/page 1.

### Naming and archival (bcsphone)
- Canonical profile filename: `out/bcsphone_snap2.layout.mobileconfig` (keeps Outlook in dock and curated Page 1).
- Regeneration keeps the filename stable and auto-archives the prior copy to `out/archive/bcsphone_snap2.layout.<YYYYMMDDHHMMSS>.mobileconfig` to avoid name sprawl. Use `./bin/phone-profile-refresh --name bcsphone_snap2` (defaults: plan `out/ios.plan.yaml`, layout `out/ios.IconState.yaml`, all-apps folder “Apple Extras”).
- The current layout summary + apply/verify steps live in `out/bcsphone_layout.md` for quick reference.

## Current canonical layouts

- `out/homescreen.spec.mobileconfig` — single-page layout (dock Safari/Netflix/YouTube Kids/Photos; roots include Mail/Edge/YouTube/Zoom/Azure Authenticator; Games on page 1; other folders on page 2). Used for primary iPad.
- `out/ipadBiggest.layout.mobileconfig` — generated from the latest `ipadBiggest` snapshot (dock Safari/YouTube Kids/Photos/Netflix; Page 1 roots: Settings/Calculator/Camera/Clock/Find My/Calendar/Messages/Mail/Edge/YouTube/Zoom/Azure Authenticator; Page 1 folder: Games; Page 2 folders: Home Freeform, Socials, News, Financials, Retail, Media, Google, Microsoft, AI, Security, Travel, Utilities; loose on page 2: Ring, SwiftKey).
- `out/bcsphone.layout.mobileconfig` — latest managed iPhone layout (dock Phone/Edge/WhatsApp/Slack `com.tinyspeck.chatlyio`; Page 1 roots: Settings/Mail/Maps/Calculator/Contacts/Calendar/Messages/Camera/Clock/Safari/Azure Authenticator/LinkedIn/Photos/Zoom/Hearthstone/Duolingo; Page 2: Social (Slack), Media, Games, News, Apple Apps; Page 3: Finance/Travel/Home; Page 4: Google/Microsoft (Copilot/Lens/Teams/Office mobile)/Adobe (incl. Account Access); Page 5: AI/Security/Retail).

## Device labels (credentials.ini)

- `ipadBiggest` → UDID `00008132-001645323C05001C` (new iPad 16,5). Used by `--device-label ipadBiggest` for verify/install commands.
- `bcsphone` → UDID `00008150-000578D421D8401C` (iPhone; managed layout above). Used by `--device-label bcsphone`.

## CLI helpers recap

- Apply profile: `./bin/ios-install-profile --profile <file> --device-label <label> --no-prompt` (tap Install on-device).
- Verify layout: `./bin/ios-verify-layout --device-label <label>`.
- Build profile procedurally: `./bin/phone profile build --plan <plan.yaml> --layout <export.yaml> [--all-apps-folder-*] --out <file>`.

Notes:
- cfgutil requires on-device approval (Code 625) for profile installs; treat that prompt as expected and rerun after tapping Install on the device.
- App installs still require Configurator UI “Add → Apps” or local IPAs.

Notes:
- cfgutil cannot pull App Store apps; you must add them via Configurator UI or local IPAs.
- Profiles place apps only if installed; missing apps are skipped until added.
- Helpers: `bin/ios-install-profile` (profile push) and `bin/ios-verify-layout` (layout snapshot).
