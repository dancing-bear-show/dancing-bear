"""Classification symbols, colors, and waste-tag abbreviations."""

_CLASS_SYMBOLS = {
    "productive": "●",
    "neutral": "○",
    "avoidable": "✗",
    "review": "⚠",
}

_CLASS_COLORS = {
    "productive": "green",
    "neutral": "dim",
    "avoidable": "red",
    "review": "yellow",
}

_WASTE_TAGS = {
    "bash-as-grep": "GREP",
    "bash-as-read": "READ",
    "bash-as-glob": "GLOB",
    "bash-as-write": "WRITE",
    "redundant-read": "DUP",
    "rapid-re-edit": "REIT",
    "abandoned-search": "SRCH",
    "fruitless-agent": "AGNT",
    "failed-tool": "FAIL",
}
