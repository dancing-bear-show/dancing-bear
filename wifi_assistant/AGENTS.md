# Wi-Fi Assistant Agent Notes

- Purpose: quick Wi-Fi/LAN diagnostics (gateway vs upstream vs DNS vs HTTPS).
- CLI: `./bin/wifi-assistant` (ping sweep, traceroute, DNS timing, HTTPS smoke).
- Two-stage: quick ICMP survey to detect filtering, then full probes; avoid blaming Wi-Fi when ICMP is blocked.
- Keep dependencies minimal (stdlib + requests). Avoid privileged operations.
- Flags should remain stable; prefer additive behavior (`--no-trace`, `--no-http` to skip probes).
- Tests: add lightweight unit tests with fake runners; do not rely on live network.
