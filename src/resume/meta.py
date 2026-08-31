from __future__ import annotations

from core.meta_base import AppMeta

META = AppMeta(
    app_id="resume",
    purpose="Extract, summarize, and render resumes",
    display_name="Resume",
    bin_name="./bin/assistant resume",
    example_cmd="./bin/assistant resume render --help",
)
