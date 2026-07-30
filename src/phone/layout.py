"""Phone layout module — re-export shim.

All implementation has moved to:
  - layout_normalize.py  (NormalizedLayout, normalize_iconstate, to_yaml_export, etc.)
  - layout_plan.py       (scaffold_plan, checklist_from_plan, analyze_layout, etc.)
"""

from __future__ import annotations

from .layout_normalize import (  # noqa: F401
    Item,
    NormalizedLayout,
    _add_app_location,
    _extract_bundle_id,
    _extract_bundle_ids,
    _flatten_folder_iconlists,
    _get_app_id,
    _get_folder_apps,
    _get_folder_name,
    _is_app_item,
    _is_folder,
    _is_folder_item,
    _iter_all_app_ids,
    _normalize_page_item,
    compute_folder_page_map,
    compute_location_map,
    compute_root_app_page_map,
    list_all_apps,
    normalize_iconstate,
    to_yaml_export,
)
from .layout_plan import (  # noqa: F401
    _add_folder_observations,
    _add_page_observations,
    _add_plan_observations,
    _analyze_pages,
    _app_page_instructions,
    _collect_all_app_ids,
    _collect_pinned_apps,
    _compute_app_score,
    _count_app_occurrences,
    _folder_page_instructions,
    _generate_folder_instructions,
    _generate_observations,
    _generate_page_instructions,
    _parse_location,
    _safe_int,
    _score_location,
    _score_membership,
    analyze_layout,
    auto_folderize,
    checklist_from_plan,
    distribute_folders_across_pages,
    rank_unused_candidates,
    scaffold_plan,
)
