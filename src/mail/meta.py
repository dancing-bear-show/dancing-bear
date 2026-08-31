from __future__ import annotations

from core.meta_base import AppMeta

META = AppMeta(
    app_id="mail",
    purpose="Gmail/Outlook CLI (labels, filters, signatures)",
    display_name="Mail",
    bin_name="./bin/mail-assistant",
    example_cmd="./bin/mail-assistant messages search --query 'subject:invoice' --json",
)
