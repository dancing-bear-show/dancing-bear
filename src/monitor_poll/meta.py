from __future__ import annotations

from core.meta_base import AppMeta

META = AppMeta(
    app_id="monitor-poll",
    purpose="Poll a condition (command, file, URL, GitHub PR/run) until it resolves or times out",
    display_name="Monitor Poll",
    bin_name="./bin/monitor-poll",
    example_cmd="./bin/monitor-poll file /tmp/ready --timeout 60",
)
