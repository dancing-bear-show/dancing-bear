"""Outlook authentication commands - interactive device code flow."""
from __future__ import annotations

import json
from pathlib import Path

from ..config_resolver import expand_path, default_outlook_token_path
from core.auth import resolve_outlook_credentials
from core.constants import DEFAULT_REQUEST_TIMEOUT, GRAPH_API_URL, GRAPH_DEFAULT_SCOPE


def run_outlook_auth_device_code(args) -> int:
    """Start device code flow for Outlook authentication."""
    client_id, tenant, _ = resolve_outlook_credentials(
        getattr(args, "profile", None),
        getattr(args, "client_id", None),
        getattr(args, "tenant", None),
        None,
    )
    if not client_id:
        print("Missing --client-id. Set MAIL_ASSISTANT_OUTLOOK_CLIENT_ID, or store outlook_client_id in credentials.ini.")
        return 2

    try:
        import msal
    except Exception as e:
        print(f"Missing msal dependency: {e}. Run: pip install msal")
        return 1

    authority = f"https://login.microsoftonline.com/{tenant}"
    app = msal.PublicClientApplication(client_id, authority=authority)
    flow = app.initiate_device_flow(scopes=[GRAPH_DEFAULT_SCOPE])
    if "user_code" not in flow:
        print("Failed to start device flow.")
        return 1

    outp = Path(args.out)
    outp.parent.mkdir(parents=True, exist_ok=True)
    flow_out = dict(flow)
    flow_out["_client_id"] = client_id
    flow_out["_tenant"] = tenant
    outp.write_text(json.dumps(flow_out), encoding="utf-8")

    msg = flow.get("message") or f"To sign in, visit {flow.get('verification_uri')} and enter code: {flow.get('user_code')}"
    print(msg)

    prof = getattr(args, 'profile', None)
    prof_flag = f" --profile {prof}" if prof else ""
    print(f"Next: ./bin/mail-assistant{prof_flag} outlook auth poll --flow {args.out} --token {default_outlook_token_path()}")

    if getattr(args, 'verbose', False):
        print(f"[device-code] Saved flow to {outp} (client_id={client_id}, tenant={tenant}).")
    print(f"Saved device flow to {outp}")
    return 0


def run_outlook_auth_poll(args) -> int:
    """Poll device code flow and save token."""
    try:
        import msal
    except Exception as e:
        print(f"Missing msal dependency: {e}. Run: pip install msal")
        return 1

    flow_path = Path(expand_path(args.flow))
    if not flow_path.exists():
        print(f"Device flow file not found: {flow_path}")
        return 2

    flow = json.loads(flow_path.read_text())
    client_id = flow.get("_client_id")
    tenant = flow.get("_tenant") or "consumers"
    if not client_id:
        print("Device flow missing _client_id. Re-run outlook auth device-code.")
        return 2

    cache = msal.SerializableTokenCache()
    app = msal.PublicClientApplication(client_id, authority=f"https://login.microsoftonline.com/{tenant}", token_cache=cache)

    if getattr(args, 'verbose', False):
        print(f"[device-code] Polling device flow from {flow_path}. This may take up to {int(flow.get('expires_in', 900))//60} minutes…")

    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        print(f"Device flow failed: {result}")
        return 3

    token_path = Path(expand_path(args.token))
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(cache.serialize(), encoding="utf-8")
    print(f"Saved Outlook token cache to {token_path}")
    return 0


def _try_silent_auth(app, scopes: list, cache, tp: Path) -> tuple[bool, int]:
    """Try silent token acquisition. Returns (success, exit_code)."""
    accounts = []
    try:
        accounts = app.get_accounts()
    except Exception:  # nosec B110 - cache lookup may fail, proceed with empty
        pass

    if accounts:
        res = app.acquire_token_silent(scopes, account=accounts[0])
        if res and "access_token" in res:
            tp.parent.mkdir(parents=True, exist_ok=True)
            tp.write_text(cache.serialize(), encoding="utf-8")
            print(f"Token cache valid. Saved to {tp}")
            return True, 0
    return False, 0


def _run_device_flow(app, scopes: list, cache, tp: Path) -> int:
    """Run interactive device flow. Returns exit code."""
    flow = app.initiate_device_flow(scopes=scopes)
    if "user_code" not in flow:
        print("Failed to start device flow.")
        return 1

    msg = flow.get("message") or f"To sign in, visit {flow.get('verification_uri')} and enter code: {flow.get('user_code')}"
    print(msg)

    result = app.acquire_token_by_device_flow(flow)
    if "access_token" not in result:
        print(f"Device flow failed: {result}")
        return 3

    tp.parent.mkdir(parents=True, exist_ok=True)
    tp.write_text(cache.serialize(), encoding="utf-8")
    print(f"Saved Outlook token cache to {tp}")
    return 0


def run_outlook_auth_ensure(args) -> int:
    """Ensure a persistent Outlook MSAL token cache exists and is valid."""
    try:
        import msal
    except Exception as e:
        print(f"Missing msal dependency: {e}. Run: pip install msal")
        return 1

    client_id, tenant, token_path = resolve_outlook_credentials(
        getattr(args, "profile", None),
        getattr(args, "client_id", None),
        getattr(args, "tenant", None),
        getattr(args, "token", None),
    )
    token_path = expand_path(token_path or default_outlook_token_path())
    if not client_id:
        print("Missing --client-id. Set MAIL_ASSISTANT_OUTLOOK_CLIENT_ID or configure a profile in ~/.config/credentials.ini")
        return 2

    cache = msal.SerializableTokenCache()
    tp = Path(token_path)
    if tp.exists():
        try:
            cache.deserialize(tp.read_text(encoding="utf-8"))
        except (ValueError, OSError, IOError) as e:  # nosec B110 - corrupt/invalid cache, start fresh
            import sys
            print(f"Warning: Could not load token cache ({type(e).__name__}), starting fresh", file=sys.stderr)

    app = msal.PublicClientApplication(client_id, authority=f"https://login.microsoftonline.com/{tenant}", token_cache=cache)
    scopes = [GRAPH_DEFAULT_SCOPE]

    # Try silent auth first, fall back to device flow
    success, code = _try_silent_auth(app, scopes, cache, tp)
    if success:
        return code
    return _run_device_flow(app, scopes, cache, tp)


def run_outlook_auth_validate(args) -> int:
    """Validate Outlook token cache by performing a silent refresh and a /me ping."""
    try:
        import msal
        import requests
    except Exception as e:
        print(f"Outlook validation unavailable (missing deps): {e}")
        return 1

    client_id, tenant, token_path = resolve_outlook_credentials(
        getattr(args, "profile", None),
        getattr(args, "client_id", None),
        getattr(args, "tenant", None),
        getattr(args, "token", None),
    )
    token_path = expand_path(token_path or default_outlook_token_path())
    if not client_id:
        print("Missing --client-id. Set MAIL_ASSISTANT_OUTLOOK_CLIENT_ID or configure a profile in ~/.config/credentials.ini")
        return 2

    tp = Path(token_path)
    if not tp.exists():
        print(f"Token cache not found: {tp}")
        return 2

    cache = msal.SerializableTokenCache()
    try:
        cache.deserialize(tp.read_text(encoding="utf-8"))
    except Exception:
        print(f"Unable to read token cache: {tp}")
        return 3

    app = msal.PublicClientApplication(client_id, authority=f"https://login.microsoftonline.com/{tenant}", token_cache=cache)

    accounts = []
    try:
        accounts = app.get_accounts()
    except Exception:
        accounts = []  # Cache lookup failed; proceed with empty accounts

    if not accounts:
        print("No account in token cache.")
        return 3

    res = app.acquire_token_silent([GRAPH_DEFAULT_SCOPE], account=accounts[0])
    if not (res and res.get("access_token")):
        print("Silent token acquisition failed.")
        return 4

    # Ping /me to confirm validity
    r = requests.get(f"{GRAPH_API_URL}/me", headers={"Authorization": f"Bearer {res['access_token']}"}, timeout=DEFAULT_REQUEST_TIMEOUT)
    if r.status_code == 200:
        print("Outlook token valid.")
        return 0

    print(f"Graph /me failed: {r.status_code} {r.text[:200]}")
    return 5
