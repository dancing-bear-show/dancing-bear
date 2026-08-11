# Phone / iOS Home Screen Layout Review Guide

## When loaded

Load this guide when working on iOS home screen layout tasks: building or
editing `out/ios.iconlayout.json`, running `./bin/phone` commands,
or pushing layouts via `./bin/ios-push-layout`.

## Concerns

### wrong-cfgutil-json-format
- **severity**: critical
- **check**: Verify the layout JSON uses the cfgutil `set-icon-layout` format,
  not a flat list and not the mobileconfig plist format.
- **triggers**: Any code or agent task that produces or edits `out/ios.iconlayout.json`;
  any JSON with folder entries that are not `["FolderName", [page1apps], [page2apps]]`.
- **example**: `["Social", "com.facebook.Facebook", "com.instagram.Instagram"]` is wrong —
  it passes the apps as flat siblings of the folder name. Correct form:
  `["Social", ["com.facebook.Facebook", "com.instagram.Instagram"]]`. A two-page folder
  would be `["Social", ["app1", "app2"], ["app3", "app4"]]`. Never use the mobileconfig
  plist format (XML `<dict>` with `iconLists` key) — that is a different tool and requires
  device taps to install.

### use-set-icon-layout-not-install-profile
- **severity**: critical
- **check**: Verify layout pushes use `cfgutil set-icon-layout --force` (via
  `./bin/ios-push-layout`) and never `cfgutil install-profile`.
- **triggers**: Any push step; any script or agent description mentioning
  `install-profile`, `.mobileconfig`, or P12/DER conversion for layout delivery.
- **example**: `cfgutil install-profile layout.mobileconfig` fails with Code 625
  (requires a physical tap on the device to accept the profile) and requires
  converting the P12 to DER format, which fails silently if the certificate is
  not in the expected format. Always use `./bin/ios-push-layout --layout out/ios.iconlayout.json`
  which calls `cfgutil set-icon-layout --force` internally.

### unplaced-device-apps
- **severity**: critical
- **check**: Verify every app present on the device appears in the layout JSON.
  Any app not placed in the layout gets scattered as a loose app on the last
  page by iOS — the final result will not match the intended layout.
- **triggers**: Producing or reviewing `out/ios.iconlayout.json`; any stage that
  builds a layout from a keep-list or folder assignments.
- **example**: Agent builds page-1 and folder pages but omits three apps that
  were newly installed since the last export. After push those apps end up loose
  on page 3. Fix: always include an `Other` or `Misc` overflow folder for any
  bundle IDs present in `out/ios.iconmap.current.json` that are not explicitly
  placed elsewhere.

### dock-app-in-folder
- **severity**: critical
- **check**: Verify dock apps do not appear inside any folder in the layout JSON.
  iOS silently removes them from the dock when they also appear in a folder,
  leaving the dock slot empty after the push.
- **triggers**: Building or reviewing the layout JSON; any agent that categorizes
  apps into folders without first stripping dock bundle IDs from the candidate set.
- **example**: `com.apple.mobilephone` placed in a `"Utilities"` folder while also
  listed in the dock entry — after push the dock phone slot is empty. Fix: collect
  the dock bundle IDs first and exclude them from all folder assignments.

### stale-device-layout
- **severity**: major
- **check**: Verify a fresh `cfgutil get-icon-layout` export was pulled from the
  device before building a new layout, so the app inventory reflects what is
  actually installed.
- **triggers**: Any workflow or task that builds a new `out/ios.iconlayout.json`
  without a preceding export step; any plan derived from a stale cached file.
- **example**: Layout built from a two-week-old export is missing six recently
  installed apps — those apps end up scattered after the push. Fix: always run
  `IOS_USE_CONFIGURATOR_IDENTITY=1 cfgutil get-icon-layout > out/ios.iconmap.current.json`
  as the first step, then derive the layout from that file.

### layout-not-validated-before-push
- **severity**: critical
- **check**: Verify `./bin/phone validate-layout` is run (and passes
  with zero errors) before pushing the layout to the device.
- **triggers**: Any push step; any workflow that proceeds from build-layout to
  push without an intervening validate stage.
- **example**: Layout JSON has a duplicate bundle ID in two folders — cfgutil
  accepts it silently and the device ends up with the app in an unpredictable
  location. Running validate-layout beforehand catches the duplicate and halts
  before the push. Required invocation:
  `./bin/phone validate-layout --layout out/ios.iconlayout.json --device-layout out/ios.iconmap.current.json`

### p12-reimport-each-run
- **severity**: minor
- **check**: Verify that scripts or workflow descriptions do not instruct the
  agent to import the P12 into keychain on every run.
- **triggers**: Any push step or setup description that includes a `security import`
  command outside of a first-time setup context.
- **example**: A workflow stage runs `security import supervisor.p12 -k login.keychain`
  on every execution — this creates duplicate keychain entries and can cause
  cfgutil to prompt for the password. Fix: the P12 only needs to be imported once;
  `./bin/ios-push-layout` reads the keychain entry automatically on subsequent runs.
  If the identity is missing, `bin/ios-push-layout` will report a clear error.
