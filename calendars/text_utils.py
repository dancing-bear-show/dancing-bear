"""Text parsing helpers for email/HTML schedule extraction.

Re-exports shared utilities from core.text_utils.
"""
from core.text_utils import extract_email_address, html_to_text, to_24h

__all__ = ["html_to_text", "to_24h", "extract_email_address"]
