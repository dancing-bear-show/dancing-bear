"""App metadata for the slides CLI."""

from __future__ import annotations

from core.meta_base import AppMeta

META = AppMeta(
    app_id="slides",
    purpose="Generate PowerPoint slides from YAML deck definitions",
    display_name="Slides",
    example_cmd="./bin/slides generate deck.yaml --template template.pptx -o output.pptx",
)
