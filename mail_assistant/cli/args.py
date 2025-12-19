from __future__ import annotations

"""Shared CLI argument builders for Mail Assistant.

Small helpers to attach common Gmail/Outlook auth/cache flags to
argparse parsers. Kept dependency‑light and import‑safe.
"""

def add_gmail_common_args(parser):
    parser.add_argument("--credentials", type=str)
    parser.add_argument("--token", type=str)
    parser.add_argument("--cache", type=str, help="Cache directory (optional)")
    return parser


def add_outlook_common_args(parser):
    parser.add_argument("--client-id", help="Azure app (client) ID; defaults from profile or env")
    parser.add_argument("--tenant", default="consumers", help="AAD tenant (default: consumers)")
    parser.add_argument("--token", help="Path to token cache JSON (optional)")
    return parser

