"""Shared helper functions for calendar assistant."""
from __future__ import annotations

from argparse import Namespace

from core.auth import build_gmail_service_from_args as _build_gmail_service_from_args

from .gmail_service import GmailService


def build_gmail_service_from_args(args: Namespace) -> GmailService:
    """Instantiate an authenticated GmailService from argparse-like args."""
    return _build_gmail_service_from_args(args, service_cls=GmailService)
