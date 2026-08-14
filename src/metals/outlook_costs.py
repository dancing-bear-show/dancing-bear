"""
Extract per-order costs from Outlook Royal Canadian Mint (RCM) emails and merge into costs.csv.

Re-export shim: implementation split into outlook_costs_extract and outlook_costs_build.
"""
from __future__ import annotations

from core.text_utils import html_to_text  # noqa: F401 - tests patch metals.outlook_costs.html_to_text

from .outlook_costs_extract import (  # noqa: F401
    OutlookCostExtractor,
    OutputRowsContext,
    ConfirmationRowContext,
    GoldRowContext,
    SUBJECT_RANK,
    _RCM_QUERIES,
    _fetch_rcm_message_ids,
    _filter_and_group_by_order,
    _try_upgrade_to_confirmation,
    _trim_disclaimer_lines,
)
from .outlook_costs_build import (  # noqa: F401
    _summarize_ounces,
    _compute_confirmation_line_costs,
    _compute_proximity_line_costs,
    _build_gold_row,
    run,
    main,
)

if __name__ == '__main__':  # pragma: no cover
    raise SystemExit(main())
