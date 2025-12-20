from __future__ import annotations

from typing import List


def _section(title: str, body: str) -> str:
    return f"{title}:\n{body}"


def build_agentic_capsule() -> str:
    lines: List[str] = []
    lines.append("agentic: wifi")
    lines.append("purpose: Wi-Fi and LAN diagnostics (gateway vs upstream vs DNS)")
    lines.append("commands:")
    lines.append("  - quick diag: ./bin/wifi --ping-count 12")
    lines.append("  - trim trace/http: ./bin/wifi --no-trace --no-http")
    lines.append("  - JSON output: ./bin/wifi --json --out out/wifi.diag.json")
    lines.append(
        _section(
            "Probes",
            "\n".join(
                [
                    "- gateway detection via route/ip",
                    "- Wi-Fi info: airport|nmcli|iwconfig",
                    "- ping sweep: gateway + 1.1.1.1 + 8.8.8.8 + google.com",
                    "- DNS timing: configurable host (default google.com)",
                    "- Tracepath/traceroute and HTTPS smoke",
                ]
            ),
        )
    )
    return "\n".join(lines)


def build_domain_map() -> str:
    return "Top-Level\n- bin/wifi — CLI wrapper\n- wifi_assistant/cli.py — argparse entry\n- wifi_assistant/pipeline.py — pipeline components\n- wifi_assistant/diagnostics.py — probes (wifi info, ping, dns, trace, http)\n- wifi_assistant/agentic.py — capsule + domain map\n- wifi_assistant/llm_cli.py — LLM wiring"


def emit_agentic_context() -> int:
    print(build_agentic_capsule())
    return 0
