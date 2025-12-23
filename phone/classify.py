"""App classification by bundle ID.

Provides heuristic folder/category assignment for iOS apps based on bundle ID patterns.
"""

from __future__ import annotations

from typing import Dict, List

# Standard folder categories
FOLDERS = [
    "Work",
    "Media",
    "Social",
    "Finance",
    "Travel",
    "Health",
    "Shopping",
    "Utilities",
]

# Explicit Apple app mappings
_APPLE_APPS: Dict[str, str] = {
    "com.apple.mobileslideshow": "Media",  # Photos
    "com.apple.tv": "Media",
    "com.apple.podcasts": "Media",
    "com.apple.music": "Media",
    "com.apple.Music": "Media",
    "com.apple.news": "Media",
    "com.apple.Books": "Media",
    "com.apple.mobilemail": "Work",
    "com.apple.mobilecal": "Work",
    "com.apple.reminders": "Work",
    "com.apple.notes": "Work",
    "com.apple.mobilesafari": "Utilities",
    "com.apple.Preferences": "Utilities",
    "com.apple.calculator": "Utilities",
    "com.apple.weather": "Utilities",
    "com.apple.Maps": "Travel",
    "com.apple.maps": "Travel",
    "com.apple.Health": "Health",
    "com.apple.stocks": "Finance",
    "com.apple.facetime": "Social",
    "com.apple.MobileSMS": "Social",
    "com.apple.AppStore": "Shopping",
    "com.apple.MobileStore": "Shopping",
}

# Keyword patterns for classification
_PATTERNS: Dict[str, List[str]] = {
    "Work": [
        "slack", "trello", "asana", "jira", "notion", "zoom", "meet", "calendar",
        "docs", "sheets", "slides", "drive", "gmail", "outlook", "microsoft", "teams",
        "onedrive", "dropbox", "docusign", "adobe", "pdf", "todoist", "evernote", "box.",
        "linear", "figma", "sketch", "xcode", "vscode", "github", "gitlab", "bitbucket",
    ],
    "Media": [
        "spotify", "netflix", "youtube", "music", "podcast", "tv", "photo", "slideshow",
        "primevideo", "prime-video", "hulu", "disney", "hbomax", "maxapp", "plex",
        "audible", "kindle", "camera", "video", "stream", "twitch", "vimeo",
    ],
    "Social": [
        "facebook", "instagram", "twitter", "reddit", "snap", "tiktok", "threads",
        "messenger", "whatsapp", "telegram", "signal", "discord", "linkedin",
        "mastodon", "bluesky", "wechat", "line",
    ],
    "Shopping": [
        "amazon", "shopify", "ebay", "etsy", "target", "walmart", "bestbuy", "costco",
        "doordash", "ubereats", "uber-eats", "grubhub", "instacart", "shop.app",
        "aliexpress", "wish", "mercari", "poshmark", "offerup",
    ],
    "Travel": [
        "uber", "lyft", "airbnb", "marriott", "hilton", "hyatt", "delta", "united",
        "southwest", "aa", "american", "hotel", "booking", "kayak", "expedia",
        "map", "tripadvisor", "yelp", "citymapper", "waze", "flightradar",
    ],
    "Finance": [
        "bank", "pay", "venmo", "paypal", "amex", "chase", "mint", "robinhood",
        "schwab", "fidelity", "credit", "wallet", "cashapp", "stripe", "coinbase",
        "tax", "turbotax", "quicken", "ynab", "splitwise", "wise", "revolut",
    ],
    "Health": [
        "health", "fit", "fitness", "peloton", "strava", "calm", "sleep", "headspace",
        "workout", "med", "pill", "myfitnesspal", "noom", "weight", "yoga",
        "alltrails", "nike", "garmin", "whoop", "oura",
    ],
}


def classify_app(bundle_id: str) -> str:
    """Classify an app by bundle ID into a folder category.

    Returns one of: Work, Media, Social, Finance, Travel, Health, Shopping, Utilities
    """
    # Check explicit Apple mappings first
    if bundle_id in _APPLE_APPS:
        return _APPLE_APPS[bundle_id]

    # Case-insensitive pattern matching
    s = bundle_id.lower()
    for folder, keywords in _PATTERNS.items():
        if any(kw in s for kw in keywords):
            return folder

    # Default
    return "Utilities"
