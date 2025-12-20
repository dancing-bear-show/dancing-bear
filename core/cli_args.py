from __future__ import annotations

"""Shared CLI argument helpers for auth flags."""

from typing import Optional


def add_outlook_auth_args(
    parser,
    *,
    include_profile: bool = False,
    profile_help: Optional[str] = None,
    client_id_help: Optional[str] = "Azure app (client) ID; defaults from profile or env",
    tenant_help: Optional[str] = "AAD tenant (default: consumers)",
    tenant_default: Optional[str] = "consumers",
    token_help: Optional[str] = "Path to token cache JSON (optional)",
):
    if include_profile:
        if profile_help is None:
            parser.add_argument("--profile")
        else:
            parser.add_argument("--profile", help=profile_help)
    if client_id_help is None:
        parser.add_argument("--client-id")
    else:
        parser.add_argument("--client-id", help=client_id_help)
    if tenant_default is None:
        if tenant_help is None:
            parser.add_argument("--tenant")
        else:
            parser.add_argument("--tenant", help=tenant_help)
    else:
        if tenant_help is None:
            parser.add_argument("--tenant", default=tenant_default)
        else:
            parser.add_argument("--tenant", default=tenant_default, help=tenant_help)
    if token_help is None:
        parser.add_argument("--token")
    else:
        parser.add_argument("--token", help=token_help)
    return parser


def add_gmail_auth_args(
    parser,
    *,
    include_cache: bool = True,
    credentials_help: Optional[str] = None,
    token_help: Optional[str] = None,
    cache_help: Optional[str] = None,
):
    if credentials_help is None:
        parser.add_argument("--credentials", type=str)
    else:
        parser.add_argument("--credentials", type=str, help=credentials_help)
    if token_help is None:
        parser.add_argument("--token", type=str)
    else:
        parser.add_argument("--token", type=str, help=token_help)
    if include_cache:
        if cache_help is None:
            parser.add_argument("--cache", type=str)
        else:
            parser.add_argument("--cache", type=str, help=cache_help)
    return parser
