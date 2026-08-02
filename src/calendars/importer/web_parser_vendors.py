"""Venue-specific website schedule parsers — dispatch facade."""
from __future__ import annotations

from .base import ScheduleParser
from .model import ScheduleItem
from .web_parser_vendors_rh import (
    RichmondHillSkatingParser,
    RichmondHillSwimmingParser,
)
from .web_parser_vendors_aurora import AuroraAquaticsParser


class WebParser(ScheduleParser):
    """Parser for website-based schedules.

    Supports:
    - Richmond Hill skating schedules
    - Richmond Hill swimming schedules
    - Aurora Aquatics schedules
    """

    def parse(self, url: str) -> list[ScheduleItem]:
        """Parse schedule items from supported website.

        Args:
            url: URL to parse

        Returns:
            List of ScheduleItem objects

        Raises:
            NotImplementedError: If website is not supported
        """
        u = str(url or '')

        # Richmond Hill Skating
        if 'richmondhill.ca' in u and 'Skating.aspx' in u:
            return RichmondHillSkatingParser().parse(u)

        # Richmond Hill Swimming
        if 'richmondhill.ca' in u and 'Swimming.aspx' in u:
            return RichmondHillSwimmingParser().parse(u)

        # Aurora Aquatics
        if 'aurora.ca' in u and 'aquatics-and-swim-programs' in u:
            return AuroraAquaticsParser().parse(u)

        raise NotImplementedError("Website parsing not implemented for this source. Provide CSV/XLSX or known site.")


def parse_website(url: str) -> list[ScheduleItem]:
    """Parse schedule from supported websites (backward compatibility)."""
    return WebParser().parse(url)
