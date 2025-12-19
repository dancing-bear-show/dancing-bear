# Quick Commands

Unified entrypoints:
- `./bin/assistant <mail|calendar|schedule|resume|phone|whatsapp|maker> --help`
- `./bin/mail-assistant --help`
- Compact agentic capsule: `./bin/mail-assistant --agentic`

Onboarding and auth:
- Copy example Gmail creds: `./bin/mail-assistant env setup --no-venv --skip-install --copy-gmail-example`
- Validate Gmail token (non-interactive): `./bin/mail-assistant --profile gmail_personal auth --validate`
- Outlook device-code ensure/validate:
  - `./bin/mail-assistant --profile outlook_personal outlook auth ensure`
  - `./bin/mail-assistant --profile outlook_personal outlook auth validate`

Unified (derive from canonical):
- Derive filters: `./bin/mail-assistant config derive filters --in config/filters_unified.yaml --out-gmail out/filters.gmail.from_unified.yaml --out-outlook out/filters.outlook.from_unified.yaml`
- Optionally derive labels: `./bin/mail-assistant config derive labels --out-gmail out/labels.gmail.from_unified.yaml --out-outlook out/labels.outlook.from_unified.yaml`

Gmail filters (plan → apply → verify):
- Plan: `./bin/mail-assistant filters plan --config out/filters.gmail.from_unified.yaml --delete-missing`
- Apply: `./bin/mail-assistant filters sync --config out/filters.gmail.from_unified.yaml --delete-missing`
- Verify: `./bin/mail-assistant filters export --out out/filters.gmail.export.after.yaml`

Outlook rules (plan → apply → verify):
- Plan: `./bin/mail-assistant outlook rules plan --config out/filters.outlook.from_unified.yaml --move-to-folders`
- Apply: `./bin/mail-assistant outlook rules sync --config out/filters.outlook.from_unified.yaml --move-to-folders --delete-missing`
- Verify: `./bin/mail-assistant outlook rules list`

Labels (Gmail):
- Plan: `./bin/mail-assistant labels plan --config config/labels_current.yaml --delete-missing`
- Apply: `./bin/mail-assistant labels sync --config config/labels_current.yaml --delete-missing`
- Verify: `./bin/mail-assistant labels export --out out/labels.export.after.yaml`

Signatures (Gmail):
- Export: `./bin/mail-assistant signatures export --out out/signatures.export.yaml`
- Normalize preview: `./bin/mail-assistant signatures normalize --config config/signatures.yaml --out-html out/signature.preview.html`
- Sync: `./bin/mail-assistant signatures sync --config config/signatures.yaml`

Forwarding (Gmail):
- List/add/status: `./bin/mail-assistant forwarding list|add|status`
- Enforce verified forwarders on sync: `./bin/mail-assistant filters sync --config out/filters.gmail.from_unified.yaml --require-forward-verified --dry-run`

Auto (categorize + archive) (Gmail):
- Propose: `./bin/mail-assistant auto propose --out out/auto.proposal.json --days 7 --only-inbox --dry-run`
- Summary: `./bin/mail-assistant auto summary --proposal out/auto.proposal.json`
- Apply (dry-run first): `./bin/mail-assistant auto apply --proposal out/auto.proposal.json --cutoff-days 7 --dry-run`

LLM maintenance:
- Inventory: `./bin/llm inventory --preserve`
- Stale with status: `./bin/llm stale --with-status --limit 10`
- Dependency hotspots: `./bin/llm deps --by combined --order desc --limit 10`
- SLA check (fail on stale): `./bin/llm check --fail-on-stale`

Tests:
- `make test` or `python3 -m unittest -v`

Phone (iOS) — Home Screen Scaffolding:
- Export layout from Finder backup: `./bin/phone export --out out/ios.IconState.yaml`
- Scaffold plan (pins + folders): `./bin/phone plan --layout out/ios.IconState.yaml --out out/ios.plan.yaml`
- Manual checklist from plan: `./bin/phone checklist --plan out/ios.plan.yaml --layout out/ios.IconState.yaml --out out/ios.checklist.txt`
- Build configuration profile (.mobileconfig):
  - `./bin/phone profile build --plan out/ios.plan.yaml --layout out/ios.IconState.yaml --out out/ios.hslayout.mobileconfig \
     --identifier com.example.profile --hs-identifier com.example.hslayout --display-name "Home Screen Layout" --organization "Personal"`
  - Note: Home Screen Layout payloads apply on supervised devices (MDM/Configurator). For personal devices, use the checklist.
- Install profile (no-touch apply):
  - `./bin/ios-install-profile --profile out/ipad.hslayout.mobileconfig` (or `--udid <UDID>` to target explicitly)
- Build and install in one step:
  - `./bin/ios-pages-sync --plan out/ipad.plan.yaml --layout out/ipad.IconState.yaml --out out/ipad.hslayout.mobileconfig --udid <UDID>`
  - Multiple devices by labels or UDIDs:
    - `./bin/ios-pages-sync --device-labels home_ipad,work_ipad`
    - `./bin/ios-pages-sync --udids 0000...A,0000...B`

Supervision identity helpers (silent install):
- Convert a .p12 to DER cert/key for cfgutil:
  - `./bin/ios-p12-to-der --p12 "/Users/you/Documents/sherwin family.p12" --pass 'PASSWORD' --out-dir out/cfgutil_identity --print-cfgutil`
- Install using the identity directly:
  - `./bin/ios-install-profile --udid <UDID> --profile out/ipad.hslayout.mobileconfig --p12 "/Users/you/Documents/sherwin family.p12" --p12-pass 'PASSWORD'`
- Read from credentials.ini (preferred, descriptive names):
  - Put this in `~/.config/sre-utils/credentials.ini` (or `$SRE_CREDENTIALS`):
    [ios_layout_manager]
    supervision_identity_p12 = /Users/you/Documents/SHERWIN.p12
    supervision_identity_pass = YOURPASSWORD
    # Optional alternate section also checked:
    # [ios_supervisor]
    # supervision_identity_p12 = /Users/you/Documents/SHERWIN.p12
    # supervision_identity_pass = YOURPASSWORD
  - Then run without passing secrets (defaults to [ios_layout_manager]):
    `./bin/ios-install-profile --udid <UDID> --profile out/ipad.hslayout.mobileconfig`
    `./bin/ios-pages-sync --udid <UDID>`
  - Override section/file when needed:
    `./bin/ios-install-profile --udid <UDID> --creds-profile ios_supervisor --config /path/credentials.ini --profile out/ipad.hslayout.mobileconfig`

Device labels and settings.init:
- Add/label a device and write settings.init:
  - `./bin/ios-setup-device --label home_ipad --udid <UDID>`
- Switch active device (updates settings.init):
  - `./bin/ios-use-device --label home_ipad`
  - Backward-compatible keys supported: `supervision_p12`, `supervision_p12_pass`.

Pages organization (optional in plan):
- Add a `pages` mapping to your plan to get page-move steps in the checklist.
```
pages:
  1:
    apps: [com.apple.mobilemail]
    folders: [Work, Media]
  2:
    apps: [com.apple.measure]
    folders: [Travel]
```

Phone (iOS) — Unused Apps (heuristic):
- Suggest unused candidates (text): `./bin/phone unused --layout out/ios.IconState.yaml --limit 50`
- CSV output with recent/keep lists:
  - `./bin/phone unused --layout out/ios.IconState.yaml --recent recent.txt --keep keep.txt --format csv`
- Generate removal checklist (no device writes):
  - Offload: `./bin/phone prune --layout out/ios.IconState.yaml --mode offload --limit 50`
  - Delete: `./bin/phone prune --layout out/ios.IconState.yaml --mode delete --limit 50`

Phone (iOS) — Layout Analysis:
- Text summary: `./bin/phone analyze --layout out/ios.IconState.yaml`
- With plan alignment: `./bin/phone analyze --layout out/ios.IconState.yaml --plan out/ios.plan.yaml`
- JSON output: `./bin/phone analyze --layout out/ios.IconState.yaml --format json`

Phone (iOS) — Auto‑organize into folders:
- Auto‑assign all apps into folders and place folders from Page 2:
  - `./bin/phone auto-folders --layout out/ipad.IconState.yaml --plan out/ipad.plan.yaml --place-folders-from-page 2`
- Then build+install the multi‑page profile:
  - `./bin/ios-pages-sync --plan out/ipad.plan.yaml --layout out/ipad.IconState.yaml --out out/ipad.hslayout.mobileconfig --udid <UDID>`
