"""CSV schedule parser."""
from __future__ import annotations

import csv
from typing import List

from .base import ScheduleParser
from .model import ScheduleItem


class CSVParser(ScheduleParser):
    """Parser for CSV schedule files."""

    def parse(self, path: str) -> List[ScheduleItem]:
        """Parse schedule items from CSV file.

        Args:
            path: Path to CSV file

        Returns:
            List of ScheduleItem objects
        """
        items: List[ScheduleItem] = []
        with open(path, newline='', encoding='utf-8') as fh:
            rd = csv.DictReader(fh)
            for raw in rd:
                # Normalize keys: strip spaces and lower-case header names
                row = {str(k).strip().lower(): (raw.get(k) if raw.get(k) is not None else '') for k in raw.keys()}
                item = self._row_to_schedule_item(row)
                if item:
                    items.append(item)
        return items


# Backward compatibility function
def parse_csv(path: str) -> List[ScheduleItem]:
    """Parse schedule items from CSV file.

    Args:
        path: Path to CSV file

    Returns:
        List of ScheduleItem objects
    """
    return CSVParser().parse(path)
