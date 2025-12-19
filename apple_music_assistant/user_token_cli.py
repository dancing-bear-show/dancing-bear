"""CLI to print a data URL for fetching the Apple Music user token."""

from __future__ import annotations

import argparse
import http.server
import os
import socket
import sys
import webbrowser

from apple_music_assistant.config import DEFAULT_PROFILE, load_profile
from apple_music_assistant.token_helpers import build_data_url, build_html


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate a data URL to obtain Music User Token via browser.")
    parser.add_argument("--profile", default=DEFAULT_PROFILE, help="credentials.ini section (default: musickit.personal)")
    parser.add_argument("--config", help="Path to credentials.ini (optional)")
    parser.add_argument("--developer-token", help="Developer token (overrides credentials.ini / env)")
    parser.add_argument("--serve", action="store_true", help="Serve a local HTML page on localhost instead of a data URL")
    parser.add_argument("--port", type=int, default=0, help="Port for --serve (default: auto)")
    parser.add_argument("--open", action="store_true", help="Open the data URL in your default browser")
    parser.add_argument("--no-open", action="store_true", help="Do not open browser (print URL only)")
    return parser


def _serve_once(html: str, port: int = 0) -> tuple[http.server.HTTPServer, str]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # pragma: no cover - trivial
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args) -> None:  # pragma: no cover - quiet logs
            return

    server = http.server.HTTPServer(("127.0.0.1", port), Handler, False)
    server.timeout = 15
    server.server_bind()
    server.server_activate()
    host, bound_port = server.server_address
    url = f"http://{host}:{bound_port}/"
    return server, url


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
        html = build_html(developer_token)
        server, url = _serve_once(html, args.port)
        if not args.no_open:
            webbrowser.open(url)
        print("Local server running for one request. Open this URL in your browser to copy the Music User Token:\n")
        print(url)
        # Handle a single request (page load), then exit.
        try:
            server.handle_request()
        except KeyboardInterrupt:  # pragma: no cover - manual stop
            pass
        return 0

    url = build_data_url(developer_token)
    if args.open and not args.no_open:
        webbrowser.open(url)
        print("Opened browser for Music User Token capture. If it did not open, paste this URL manually:\n")
    print(url)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
