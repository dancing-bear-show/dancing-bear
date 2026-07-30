"""Website schedule parsers — re-export shim."""
from .web_parser_base import (  # noqa: F401
    WEEKDAYS,
    LEISURE_SWIM,
    ScheduleItemParams,
    _make_schedule_item_from_params,
    _fetch_html,
)
from .web_parser_vendors import (  # noqa: F401
    RichmondHillSkatingParser,
    RichmondHillSwimmingParser,
    AuroraAquaticsParser,
    WebParser,
    parse_website,
)
