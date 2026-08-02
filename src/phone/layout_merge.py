"""iOS layout merge-folders logic.

Redistributes apps from dump folders (e.g. "Other") into the best-fit
existing folder, and files loose apps (pages >= 2) into existing folders.
Preserves dock and page-1 pins. Enforces conservation invariant.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .classify import classify_app


# Mapping from classify_app() categories to the user's actual folder names.
# classify_app returns: Work, Media, Social, Finance, Travel, Health, Shopping, Utilities
# User's actual folders: Work, Finance, Travel, Fitness, Shopping, Media, Social,
#   Games, SmartHome, News, AI, Security, Apple, Argentina, Loyalty, Gear,
#   Libraries, Google, Kids, Misc
_CATEGORY_TO_FOLDER: dict[str, str] = {
    "Work": "Work",
    "Media": "Media",
    "Social": "Social",
    "Finance": "Finance",
    "Travel": "Travel",
    "Health": "Fitness",
    "Shopping": "Shopping",
    "Utilities": "Misc",
}

# Additional bundle-id-level overrides for specific apps the classifier might
# mis-categorize. Add entries here when needed.
_BUNDLE_OVERRIDES: dict[str, str] = {
    # Apple stock apps → Apple folder
    "com.apple.mobilephone": "Apple",
    "com.apple.VoiceMemos": "Apple",
    "com.apple.compass": "Apple",
    "com.apple.measure": "Apple",
    "com.apple.calculator": "Apple",
    "com.apple.shortcuts": "Apple",
    "com.apple.findmy": "Apple",
    "com.apple.tips": "Apple",
    "com.apple.Translate": "Apple",
    "com.apple.Magnifier": "Apple",
    "com.apple.Preview": "Apple",
    "com.apple.DocumentsApp": "Apple",
    "com.apple.Passbook": "Apple",
    "com.apple.journal": "Apple",
    "com.apple.Bridge": "Apple",
    "com.apple.supportapp": "Apple",
    "com.apple.AppStore": "Apple",
    "com.apple.MobileStore": "Apple",
    "com.apple.iBooks": "Media",
    "com.apple.facetime": "Social",
    "com.apple.MobileSMS": "Social",
    "com.apple.mobilecal": "Work",
    "com.apple.reminders": "Work",
    "com.apple.news": "News",
    "com.apple.podcasts": "Media",
    "com.apple.tv": "Media",
    "com.apple.Music": "Media",
    "com.apple.Fitness": "Fitness",
    # Google workspace → Work
    "com.google.Docs": "Work",
    "com.google.Sheets": "Work",
    "com.google.Slides": "Work",
    "com.google.Drive": "Work",
    "com.google.Gmail": "Work",
    "com.google.calendar": "Work",
    # Other Google → Google folder
    "com.google.GoogleMobile": "Google",
    "com.google.one": "Google",
    "com.google.ProjectFi": "Google",
    "com.google.chrome.ios": "Google",
    "com.google.photos": "Media",
    "com.google.ios.youtube": "Media",
    "com.google.ios.youtubekids": "Media",
    "com.google.ios.youtubemusic": "Media",
    "com.google.Chromecast": "SmartHome",
    "com.google.Tachyon": "Social",
    "com.google.Dynamite": "Work",
    "com.google.Classroom": "Work",
    # Microsoft → Work
    "com.microsoft.Office.Excel": "Work",
    "com.microsoft.Office.Powerpoint": "Work",
    "com.microsoft.Office.Word": "Work",
    "com.microsoft.azure": "Work",
    "com.microsoft.onenote": "Work",
    "com.microsoft.skydrive": "Work",
    "com.microsoft.officemobile": "Work",
    "com.microsoft.officelens": "Work",
    "com.microsoft.skype.teams": "Work",
    "com.microsoft.scmx": "Work",
    "com.microsoft.smartglass": "Work",
    "com.microsoft.bing": "Work",
    "com.microsoft.copilot": "AI",
    # AI apps → AI
    "ai.perplexity.app": "AI",
    "com.openai.chat": "AI",
    "com.anthropic.claude": "AI",
    "com.google.gemini": "AI",
    "com.swiftkey.SwiftKeyApp": "AI",
    # Travel extras
    "com.ubercab.UberClient": "Travel",
    "com.waze.iphone": "Travel",
    "com.hilton.hhonors": "Travel",
    "com.marriott.iphoneprod": "Travel",
    "com.hoteltonight.prod": "Travel",
    "com.united.UnitedCustomerFacingIPhone": "Travel",
    "com.aa.AmericanAirlines": "Travel",
    "com.travelingmailbox.mail": "Travel",
    "com.zillow.ZillowMap": "Travel",
    "com.yelp.yelpiphone": "Travel",
    # Finance extras
    "com.chase": "Finance",
    "com.fidelity.watchlist": "Finance",
    "com.schwab.schwabmobile": "Finance",
    "com.rogers.rogersbank": "Finance",
    "com.bmo.mbanking": "Finance",
    "com.CIBC.mobilebanking": "Finance",
    "ca.pcfinancial.bank": "Finance",
    "ca.co.americanexpress.amexservice": "Finance",
    "net.kortina.labs.Venmo": "Finance",
    "com.coinbase.pro": "Finance",
    "com.transferwise.Transferwise": "Finance",
    "ca.mint.rcm-mint-mobile": "Finance",
    "ar.com.santander.rio.mbanking": "Finance",
    # Shopping extras
    "com.amazon.Amazon": "Shopping",
    "com.amazon.aiv.AIVApp": "Media",
    "com.amazon.mp3.AmazonCloudPlayer": "Media",
    "com.amazon.CloudDrivePhotos": "Media",
    "com.amazon.echo": "SmartHome",
    "com.amazon.firetv.remote": "SmartHome",
    "com.amazon.Lassen": "Shopping",
    "com.alibaba.iAliexpress": "Shopping",
    "com.bestbuy.BestBuy": "Shopping",
    "com.costco.costco": "Shopping",
    "ca.thehomedepot.homedepotCanada": "Shopping",
    "ca.walmart.ecommerceapp": "Shopping",
    "com.ebay.iphone": "Shopping",
    "com.etsy.etsyforios": "Shopping",
    # Media extras
    "com.netflix.Netflix": "Media",
    "com.disney.disneyplus": "Media",
    "com.reddit.Reddit": "Social",
    "com.facebook.Messenger": "Social",
    "com.burbn.instagram": "Social",
    "com.zhiliaoapp.musically": "Social",
    "com.hammerandchisel.discord": "Social",
    "tv.twitch": "Media",
    "tv.fubo.mobile": "Media",
    "com.bose.bosemusic": "Media",
    # Fitness
    "com.alltrails.AllTrails": "Fitness",
    # Work: Adobe
    "com.adobe.Adobe-Reader": "Work",
    "com.adobe.echosign.ios": "Work",
    "com.adobe.ims.accountAccess": "Work",
    "com.adobe.scan.ios": "Work",
    "com.docusign.DocuSignIt": "Work",
    "com.github.stormbreaker.prod": "Work",
    # Social extras
    "com.linkedin.LinkedIn": "Social",
    "com.linkedin.Learning": "Work",
    "org.whispersystems.signal": "Social",
    "net.whatsapp.WhatsAppSMB": "Social",
    # News extras
    "org.wikimedia.wikipedia": "News",
    # Misc (no better home)
    "com.rogers.ignitetv": "Media",
    "ca.caa.coremobileapp": "Travel",
    "com.fivemobile.cineplex": "Shopping",
}


@dataclass
class MergePlan:
    """Output of merge_folders — ready for profile build."""

    dock: list[str] = field(default_factory=list)
    pins: list[str] = field(default_factory=list)  # page-1 loose apps
    folders: dict[str, list[str]] = field(default_factory=dict)
    pages: dict[int, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "dock": self.dock,
            "pins": self.pins,
            "folders": {k: list(v) for k, v in self.folders.items()},
            "pages": {
                str(k): {"apps": v["apps"], "folders": v["folders"]}
                for k, v in self.pages.items()
            },
        }


def classify_to_folder(
    bundle_id: str,
    existing_folders: set[str],
    fallback: str = "Misc",
) -> str:
    """Map a bundle ID to one of the user's actual existing folder names.

    Priority:
    1. _BUNDLE_OVERRIDES exact match (if target folder exists)
    2. classify_app() category → _CATEGORY_TO_FOLDER (if target folder exists)
    3. fallback ("Misc") if in existing_folders
    4. first folder in existing_folders (alphabetical)
    """
    # 1. Check bundle-level override
    if bundle_id in _BUNDLE_OVERRIDES:
        target = _BUNDLE_OVERRIDES[bundle_id]
        if target in existing_folders:
            return target
        # Override points to a folder not in layout; fall through to classifier

    # 2. Classifier → category → folder name
    category = classify_app(bundle_id)
    folder_name = _CATEGORY_TO_FOLDER.get(category, fallback)
    if folder_name in existing_folders:
        return folder_name

    # 3. Fallback to "Misc" if available
    if fallback in existing_folders:
        return fallback

    # 4. First available folder (deterministic)
    if existing_folders:
        return sorted(existing_folders)[0]

    return fallback


def _collect_layout_ids(layout: dict[str, Any]) -> list[str]:
    """Collect all bundle IDs from a raw layout dict (dock + pages)."""
    ids: list[str] = list(layout.get("dock") or [])
    for page in layout.get("pages") or []:
        ids.extend(bid for bid in (page.get("apps") or []) if bid)
        for folder in page.get("folders") or []:
            ids.extend(bid for bid in (folder.get("apps") or []) if bid)
    return ids


def _collect_plan_ids(plan: dict[str, Any]) -> list[str]:
    """Collect all bundle IDs from a plan dict (dock + pins + folder members)."""
    ids: list[str] = list(plan.get("dock") or [])
    ids.extend(plan.get("pins") or [])
    for apps in (plan.get("folders") or {}).values():
        ids.extend(bid for bid in apps if bid)
    return ids


def verify_conservation(
    layout: dict[str, Any],
    plan: dict[str, Any],
) -> None:
    """Raise ValueError if app multisets differ between layout and plan.

    Counts all bundle IDs in: layout dock + layout pages (loose apps + folder members).
    Counts all bundle IDs in: plan dock (if present) + plan pins + plan folder members.
    Raises ValueError with details if they differ.
    """
    layout_counter = Counter(_collect_layout_ids(layout))
    plan_counter = Counter(_collect_plan_ids(plan))

    if layout_counter == plan_counter:
        return

    missing_from_plan = layout_counter - plan_counter
    extra_in_plan = plan_counter - layout_counter
    parts: list[str] = []
    if missing_from_plan:
        parts.append(f"missing from plan: {dict(missing_from_plan)}")
    if extra_in_plan:
        parts.append(f"extra in plan: {dict(extra_in_plan)}")
    raise ValueError("; ".join(parts))


def _collect_existing_folders(
    pages_raw: list[dict[str, Any]], dump_set: set[str]
) -> tuple[dict[str, list[str]], dict[str, int]]:
    """Build folder contents and page assignments from raw pages (excluding dump folders).

    Returns:
        folders_by_name: name → [bundle_ids]
        folder_page: name → page number (1-based)
    """
    folders_by_name: dict[str, list[str]] = {}
    folder_page: dict[str, int] = {}
    for page_idx, page in enumerate(pages_raw):
        page_num = page_idx + 1
        for folder in page.get("folders") or []:
            name = folder.get("name") or ""
            if not name or name in dump_set:
                continue
            if name not in folders_by_name:
                folders_by_name[name] = []
                folder_page[name] = page_num
            folders_by_name[name].extend(
                bid for bid in (folder.get("apps") or []) if bid
            )
    return folders_by_name, folder_page


def _collect_apps_to_file(
    pages_raw: list[dict[str, Any]], dump_set: set[str], dock_set: set[str]
) -> list[str]:
    """Collect bundle IDs that need to be filed into a folder.

    Includes loose apps from pages >= 2 and apps from dump folders on ANY page
    (including page 1). Loose apps on page 1 become pins, not foldered, so only
    dump-folder members on page 1 are captured here.
    """
    to_file: list[str] = []
    for page_idx, page in enumerate(pages_raw):
        if page_idx > 0:
            # Pages >= 2: loose apps get filed into folders
            to_file.extend(
                bid for bid in (page.get("apps") or [])
                if bid and bid not in dock_set
            )
        # All pages (including page 1): dump-folder members get redistributed
        for folder in page.get("folders") or []:
            if (folder.get("name") or "") in dump_set:
                to_file.extend(
                    bid for bid in (folder.get("apps") or [])
                    if bid and bid not in dock_set
                )
    return to_file


def _file_apps_into_folders(
    to_file: list[str],
    keep_set: set[str],
    folders_by_name: dict[str, list[str]],
    folder_page: dict[str, int],
    existing_folders: set[str],
    default_page: int,
) -> None:
    """Distribute apps from to_file into folders_by_name in place."""
    for bid in to_file:
        if bid in keep_set:
            continue
        target = classify_to_folder(bid, existing_folders, fallback="Misc")
        if target not in folders_by_name:
            folders_by_name[target] = []
            folder_page[target] = default_page
        folders_by_name[target].append(bid)


def _build_pins(
    pages_raw: list[dict[str, Any]], dock_set: set[str], keep_set: set[str]
) -> list[str]:
    """Build page-1 pins from first page loose apps plus keep_set extras."""
    pins: list[str] = []
    if pages_raw:
        pins.extend(
            bid for bid in (pages_raw[0].get("apps") or [])
            if bid and bid not in dock_set
        )
    for bid in sorted(keep_set):  # sorted: deterministic pin order across runs
        if bid not in pins and bid not in dock_set:
            pins.append(bid)
    return pins


def _build_pages_dict(
    pins: list[str], folder_page: dict[str, int]
) -> dict[int, dict[str, Any]]:
    """Build pages dict from pins (page 1) and folder page assignments.

    Page 1 always contains the pin apps plus any non-dump folders originally
    on page 1. Pages >= 2 contain only their folder assignments.
    """
    page_to_folders: dict[int, list[str]] = {}
    for name, page_num in folder_page.items():
        page_to_folders.setdefault(page_num, []).append(name)

    pages: dict[int, dict[str, Any]] = {
        1: {"apps": list(pins), "folders": page_to_folders.get(1, [])}
    }
    for page_num, folder_names in sorted(page_to_folders.items()):
        if page_num != 1:
            pages[page_num] = {"apps": [], "folders": folder_names}
    return pages


def merge_folders(
    layout: dict[str, Any],
    keep: list[str] | None = None,
    dump_folders: list[str] | None = None,
) -> MergePlan:
    """Merge folder layout, redistributing dump folders into best-fit existing folders.

    Args:
        layout: Raw YAML export dict (dock, pages list)
        keep: Bundle IDs to keep as page-1 pins (not foldered)
        dump_folders: Folder names to treat as dump/redistribute (default ["Other"])

    Returns:
        MergePlan with dock, pins, folders, pages

    Behavior:
        - Dock: preserved exactly
        - Page 1 apps: all kept as pins (not foldered)
        - Keep set: always pins on page 1
        - Loose apps on pages >= 2: filed into best-fit existing folder
        - Dump folder apps: redistributed into best-fit existing folder
        - All other existing folders: preserved exactly
        - Page assignments: each folder stays on its original page
        - Dump folder slot: removed (no empty replacement)
    """
    dump_set = set(dump_folders or ["Other"])
    keep_set: set[str] = set(keep or [])
    dock: list[str] = list(layout.get("dock") or [])
    dock_set: set[str] = set(dock)
    pages_raw: list[dict[str, Any]] = list(layout.get("pages") or [])

    folders_by_name, folder_page = _collect_existing_folders(pages_raw, dump_set)
    existing_folders: set[str] = set(folders_by_name.keys())

    if not existing_folders:
        raise ValueError(
            "No existing (non-dump) folders in layout; cannot redistribute apps"
        )

    to_file = _collect_apps_to_file(pages_raw, dump_set, dock_set)
    _file_apps_into_folders(
        to_file, keep_set, folders_by_name, folder_page, existing_folders,
        default_page=max(len(pages_raw), 2),
    )

    pins = _build_pins(pages_raw, dock_set, keep_set)
    pages = _build_pages_dict(pins, folder_page)

    return MergePlan(dock=dock, pins=pins, folders=folders_by_name, pages=pages)
