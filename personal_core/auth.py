"""Compatibility shim for auth helpers (migrated to core)."""

from core.auth import (  # noqa: F401
    build_gmail_service,
    build_gmail_service_from_args,
    build_outlook_service,
    build_outlook_service_from_args,
    resolve_outlook_credentials,
)

__all__ = [
    "resolve_outlook_credentials",
    "build_outlook_service",
    "build_outlook_service_from_args",
    "build_gmail_service",
    "build_gmail_service_from_args",
]
