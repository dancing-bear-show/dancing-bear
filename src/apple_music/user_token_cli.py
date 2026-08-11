"""CLI to print a data URL for fetching the Apple Music user token."""

from __future__ import annotations

import argparse
import http.server
import os
import sys
import time
import webbrowser

from apple_music.cli_helpers import save_credential_value
from apple_music.config import DEFAULT_PROFILE, load_profile
from apple_music.token_helpers import build_data_url, build_html


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a data URL to obtain Music User Token via browser.")
    parser.add_argument("--profile", default=DEFAULT_PROFILE, help="credentials.ini section (default: musickit.personal)")
    parser.add_argument("--config", help="Path to credentials.ini (optional)")
    parser.add_argument("--developer-token", help="Developer token (overrides credentials.ini / env)")
    parser.add_argument("--serve", action="store_true", help="Serve a local HTML page on localhost instead of a data URL")
    parser.add_argument("--port", type=int, default=0, help="Port for --serve (default: auto)")
    parser.add_argument("--timeout", type=int, default=300, help="Seconds to wait for authorization with --serve")
    parser.add_argument("--save", action="store_true", help="Write the captured token to credentials.ini (--serve only)")
    parser.add_argument("--open", action="store_true", help="Open the data URL in your default browser")
    parser.add_argument("--no-open", action="store_true", help="Do not open browser (print URL only)")
    return parser


def _serve_once(html: str, port: int = 0) -> tuple[http.server.HTTPServer, str]:
    """Serve the auth page on localhost, capturing the token the page POSTs back.

    The captured token is stored on the server as ``captured_token``. Serving stays
    up across multiple requests (favicon probes, reloads) until the POST arrives.
    """
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # pragma: no cover - exercised interactively
            if self.path.startswith("/favicon.ico"):
                self.send_response(204)
                self.end_headers()
                return
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            # The page is regenerated per run; a cached copy would mask fixes.
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:  # pragma: no cover - exercised interactively
            length = int(self.headers.get("Content-Length") or 0)
            token = self.rfile.read(length).decode("utf-8").strip() if length else ""
            if token:
                self.server.captured_token = token  # type: ignore[attr-defined]
            self.send_response(200 if token else 400)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, fmt: str, *args) -> None:  # pragma: no cover - quiet logs
            return

    server = http.server.HTTPServer(("127.0.0.1", port), Handler, False)
    server.captured_token = None  # type: ignore[attr-defined]
    server.timeout = 1
    server.server_bind()
    server.server_activate()
    host, bound_port = server.server_address
    url = f"http://{host}:{bound_port}/"
    return server, url


def _wait_for_token(server: http.server.HTTPServer, timeout_seconds: int) -> str | None:
    """Pump requests until the page posts a token back or the timeout elapses."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        server.handle_request()  # returns after server.timeout even with no request
        token = getattr(server, "captured_token", None)
        if token:
            return token
    return None


def _persist_token(args, token: str) -> int:
    """Save the captured token to credentials.ini, or print it when saving is off."""
    if not args.save:
        print(token)
        return 0
    config_path, _ = load_profile(args.profile, args.config)
    if config_path is None:
        print(f"Cannot save: no credentials.ini defines profile [{args.profile}].", file=sys.stderr)
        print(token)
        return 1
    save_credential_value(config_path, args.profile, "user_token", token)
    print(f"Music User Token saved to {config_path} under [{args.profile}].")
    return 0


def _run_serve_flow(args, developer_token: str) -> int:
    """Serve the auth page, wait for the browser handoff, then persist the token."""
    server, url = _serve_once(build_html(developer_token), args.port)
    if not args.no_open:
        webbrowser.open(url)
    print("Sign in via the browser page below; the token is captured automatically.\n")
    print(url)
    print(f"\nWaiting up to {args.timeout}s for authorization…")
    try:
        token = _wait_for_token(server, args.timeout)
    except KeyboardInterrupt:  # pragma: no cover - manual stop
        print("\nCancelled.", file=sys.stderr)
        return 1
    finally:
        server.server_close()

    if not token:
        print("Timed out waiting for the Music User Token.", file=sys.stderr)
        return 1
    return _persist_token(args, token)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _, profile_cfg = load_profile(args.profile, args.config)
    developer_token = (
        args.developer_token
        or os.environ.get("APPLE_MUSIC_DEVELOPER_TOKEN")
        or profile_cfg.get("developer_token")
    )
    if not developer_token:
        print("Missing developer token. Provide --developer-token, APPLE_MUSIC_DEVELOPER_TOKEN, or set developer_token in credentials.ini.", file=sys.stderr)
        return 2

    if args.serve:
        return _run_serve_flow(args, developer_token)

    url = build_data_url(developer_token)
    if args.open and not args.no_open:
        webbrowser.open(url)
        print("Opened browser for Music User Token capture. If it did not open, paste this URL manually:\n")
    print(url)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
