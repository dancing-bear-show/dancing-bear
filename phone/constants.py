"""Phone module constants.

Shared constants for iOS layout, classification, and device helpers.
"""

from __future__ import annotations

# Standard folder categories for app organization
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

# Stock Apple apps that are often unused
STOCK_MAYBE_UNUSED = frozenset({
    "com.apple.tips",
    "com.apple.stocks",
    "com.apple.measure",
    "com.apple.compass",
    "com.apple.podcasts",
    "com.apple.books",
})

# Common Apple apps users typically want to keep accessible
COMMON_KEEP = frozenset({
    "com.apple.camera",
    "com.apple.Preferences",
    "com.apple.facetime",
    "com.apple.mobilephone",
    "com.apple.mobilesafari",
    "com.apple.MobileSMS",
    "com.apple.mobilemail",
    "com.apple.Maps",
})

# Credential key names for supervision identity
P12_PATH_KEYS = ("supervision_identity_p12", "ios_home_layout_identity_p12", "supervision_p12")
P12_PASS_KEYS = ("supervision_identity_pass", "ios_home_layout_identity_pass", "supervision_p12_pass")
