# Apple Configurator 2 — Supervision + Home Screen Layout (Exhaustive Guide)

This guide shows how to use Apple Configurator 2 (macOS) to supervise an iPhone/iPad and apply a Home Screen Layout profile (apps, folders, dock). It also covers locking the layout, updating/removing profiles, and common troubleshooting.

Important: Supervision requires erasing the device. Back up first.

## What You Can Do Under Supervision

- Apply a Home Screen Layout profile (apps/folders/dock by bundle identifier)
- Optionally prevent users from editing the layout (Restrictions payload)
- Reinstall the profile to reassert layout if it drifts

Limitations:
- Widgets (Home/Lock Screen) are not managed by the layout payload
- App Library is not managed
- You can’t manage layout on unsupervised devices

## Prerequisites

- Mac with macOS (latest recommended)
- Apple Configurator 2 from the Mac App Store
- Lightning/USB‑C cable to connect device
- Enough disk space for a full encrypted backup
- Device passcode and Apple ID credentials (you’ll need to turn off Find My to erase)

## Step 1 — Back Up Your Device (Encrypted)

1. Connect iPhone/iPad to your Mac via USB
2. Open Finder (or iTunes on older macOS)
3. Select the device → “Back up all of the data on your iPhone to this Mac”
4. Check “Encrypt local backup” and set a password you will remember
5. Click “Back Up Now” and wait for completion

Why encrypted? It preserves more settings and is safer for restore.

## Step 2 — Install Apple Configurator 2

1. Open the Mac App Store and search for “Apple Configurator” (by Apple)
2. Install and launch “Apple Configurator 2”

## Step 3 — Prepare (Supervise) the Device

Supervision requires erasing the device. Turn off Find My to avoid Activation Lock prompts.

1. On device: Settings → Your Name → Find My → Find My iPhone → turn off (enter Apple ID password)
2. Connect the device to your Mac via USB
3. Open Apple Configurator 2
4. Select the device in the sidebar (or from the main grid)
5. Click “Prepare” in the toolbar
6. In “Prepare” wizard:
   - Choose “Manual Configuration”
   - Check “Supervise devices”
   - Leave “Enroll in MDM” unchecked (unless you have an MDM)
   - Optionally check “Allow devices to pair with other computers”
7. Organization: choose an existing organization or create one (just a label)
8. When prompted, choose “Erase” (required to enable supervision)
9. Proceed. The device will erase and reboot. Walk through Setup Assistant on device (language, Wi‑Fi, Apple ID, etc.)

Verify supervision: On device, Settings → General → VPN & Device Management shows “This iPhone is supervised”.

## Step 4 — Create a Home Screen Layout Profile

You can build a .mobileconfig profile in Apple Configurator:

1. Apple Configurator 2 → File → New Profile…
2. In the left pane, select “Home Screen Layout”
3. Build your layout:
   - Add pages and folders as needed
   - Add apps by bundle identifier (e.g., `com.apple.MobileMail`, `com.slack.Slack`)
   - Add items to the Dock
4. Optional: Add a “Restrictions” payload and disable “Allow modifying app layout” to lock the layout
5. Fill in “General” with a display name (e.g., “Home Screen Layout”), identifier, and organization
6. File → Save… to export as a `.mobileconfig`

Notes:
- Only bundle IDs present on the device will render; others are ignored until installed
- Widgets and App Library are not part of this payload

### Alternative: Build a Profile Programmatically (Advanced)

You can generate a .mobileconfig with the `com.apple.homescreenlayout` payload. Keep `PayloadIdentifier` stable between versions to update in place. Example (simplified):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
  <dict>
    <key>PayloadContent</key>
    <array>
      <dict>
        <key>PayloadType</key><string>com.apple.homescreenlayout</string>
        <key>PayloadVersion</key><integer>1</integer>
        <key>PayloadIdentifier</key><string>com.example.hslayout</string>
        <key>PayloadUUID</key><string>REPLACE-WITH-UUID</string>
        <key>PayloadDisplayName</key><string>Home Screen Layout</string>
        <key>Dock</key>
        <array>
          <dict><key>Type</key><string>BundleIdentifier</string><key>BundleIdentifier</key><string>com.apple.MobileSafari</string></dict>
          <dict><key>Type</key><string>BundleIdentifier</string><key>BundleIdentifier</key><string>com.apple.MobileSMS</string></dict>
        </array>
        <key>Pages</key>
        <array>
          <array>
            <dict><key>Type</key><string>BundleIdentifier</string><key>BundleIdentifier</key><string>com.apple.mobilemail</string></dict>
            <dict>
              <key>Type</key><string>Folder</string>
              <key>DisplayName</key><string>Work</string>
              <key>Pages</key>
              <array>
                <array>
                  <dict><key>Type</key><string>BundleIdentifier</string><key>BundleIdentifier</key><string>com.slack.Slack</string></dict>
                  <dict><key>Type</key><string>BundleIdentifier</string><key>BundleIdentifier</key><string>com.microsoft.teams</string></dict>
                </array>
              </array>
            </dict>
          </array>
        </array>
      </dict>
    </array>
    <key>PayloadType</key><string>Configuration</string>
    <key>PayloadVersion</key><integer>1</integer>
    <key>PayloadIdentifier</key><string>com.example.profile</string>
    <key>PayloadUUID</key><string>REPLACE-WITH-ANOTHER-UUID</string>
    <key>PayloadDisplayName</key><string>My Layout</string>
    <key>PayloadOrganization</key><string>Your Org</string>
  </dict>
  </plist>
```

## Step 5 — Install the Profile

With Apple Configurator GUI:
1. Connect the supervised device
2. In Apple Configurator, select the device
3. Click “Add” → “Profiles…” and choose your `.mobileconfig`
4. Wait for the operation to complete

With `cfgutil` (installed with Apple Configurator):

```bash
# List connected devices
cfgutil list

# Install a profile to the selected device
cfgutil install-profile path=/path/to/HomeScreenLayout.mobileconfig

# Expected: cfgutil often returns Code 625 until you tap “Install” on the device.
# Treat that as a required approval step, then rerun if needed.

# Remove a profile by identifier (or UUID shown by cfgutil get-profiles)
cfgutil remove-profile identifier=com.example.hslayout
```

Tip: Keep `PayloadIdentifier` consistent to update in place without duplicates.

## Step 6 — Lock or Allow Edits (Optional)

To lock the layout so it can’t be modified on device:
1. Edit the same profile in Apple Configurator
2. Add “Restrictions” payload
3. Under “Apps + Desktop”, uncheck “Allow modifying app layout” (supervised only)
4. Save and reinstall the updated profile

To allow edits again, re-enable the restriction and re‑install.

## Updating or Removing the Layout

- Update: edit the profile (same PayloadIdentifier) and reinstall; layout updates in place
- Remove: delete the profile from Settings → General → VPN & Device Management on the device (if allowed), or use Apple Configurator/`cfgutil remove-profile`

## Using With Phone Assistant

- Plan‑only flow (no supervision): use Phone Assistant to export, plan, and generate a manual checklist
- Supervised flow (automation): mirror your plan into a Home Screen Layout profile and install via Apple Configurator
- Widgets remain manual in both flows (not supported by MDM payloads)

## Troubleshooting

- Prepare fails with Activation Lock
  - Turn off Find My on the device (Settings → Your Name → Find My) and retry; you’ll need the Apple ID password
- “This device is not supervised” after Prepare
  - Ensure you selected “Supervise devices” and allowed erase during Prepare
- Profile failed to install (invalid)
  - Check the payload structure and iOS version compatibility; confirm bundle identifiers exist on the device
- Apps missing from layout
  - Only installed apps render; install the apps first or let them appear as they’re installed
- Layout doesn’t match exactly
  - Some system pages and native icons may be pinned by iOS; recheck the payload and reinstall
- Widgets or App Library aren’t changing
  - Expected; they’re out of scope for the layout payload

## Safety + Recovery

- Always keep a fresh encrypted backup before supervising or applying new profiles
- You can restore your backup if needed to return to pre‑supervision state (supervision flag persists through restore; removing supervision requires erase)

## References (Apple)

- Apple Configurator 2 (Mac App Store)
- MDM Payload Reference → Home Screen Layout (PayloadType: `com.apple.homescreenlayout`)
- `cfgutil` command reference (installed with Apple Configurator)
