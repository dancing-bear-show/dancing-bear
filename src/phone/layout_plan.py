"""iOS layout planning helpers — re-export shim.

All implementations live in:
  - layout_plan_scaffold.py  (scaffolding and instruction generation)
  - layout_plan_analyze.py   (analysis and scoring)
"""

from .layout_plan_analyze import (  # noqa: F401
    _add_folder_observations,
    _add_page_observations,
    _add_plan_observations,
    _analyze_pages,
    _compute_app_score,
    _count_app_occurrences,
    _generate_observations,
    _parse_location,
    _score_location,
    _score_membership,
    analyze_layout,
    auto_folderize,
    distribute_folders_across_pages,
    rank_unused_candidates,
)
from .layout_plan_scaffold import (  # noqa: F401
    _app_page_instructions,
    _collect_all_app_ids,
    _collect_pinned_apps,
    _folder_page_instructions,
    _generate_folder_instructions,
    _generate_page_instructions,
    _safe_int,
    checklist_from_plan,
    scaffold_plan,
)
