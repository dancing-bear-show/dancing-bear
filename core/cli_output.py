"""CLI output formatting utilities.

Provides consistent output formatting across all assistant CLIs.
Supports JSON, YAML, and table formats.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, asdict, is_dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Sequence, TextIO


class OutputFormat(str, Enum):
    """Output format options."""
    TEXT = "text"
    JSON = "json"
    YAML = "yaml"
    TABLE = "table"


@dataclass
class OutputConfig:
    """Configuration for output formatting."""
    format: OutputFormat = OutputFormat.TEXT
    verbose: bool = False
    quiet: bool = False
    no_color: bool = False
    file: Optional[TextIO] = None

    @property
    def stream(self) -> TextIO:
        """Get the output stream."""
        return self.file or sys.stdout


class OutputWriter:
    """Handles formatted output for CLI commands."""

    def __init__(self, config: Optional[OutputConfig] = None):
        self.config = config or OutputConfig()

    def print(self, *args, **kwargs) -> None:
        """Print to the configured output stream."""
        if self.config.quiet:
            return
        kwargs.setdefault("file", self.config.stream)
        print(*args, **kwargs)

    def print_error(self, message: str) -> None:
        """Print an error message to stderr."""
        print(f"Error: {message}", file=sys.stderr)

    def print_warning(self, message: str) -> None:
        """Print a warning message to stderr."""
        print(f"Warning: {message}", file=sys.stderr)

    def print_verbose(self, message: str) -> None:
        """Print a verbose message (only if verbose mode is enabled)."""
        if self.config.verbose:
            self.print(message)

    def print_data(self, data: Any, headers: Optional[List[str]] = None) -> None:
        """Print data in the configured format.

        Args:
            data: Data to print (dict, list, dataclass, or any serializable object).
            headers: Optional column headers for table format.
        """
        fmt = self.config.format

        if fmt == OutputFormat.JSON:
            self._print_json(data)
        elif fmt == OutputFormat.YAML:
            self._print_yaml(data)
        elif fmt == OutputFormat.TABLE:
            self._print_table(data, headers)
        else:
            self._print_text(data)

    def print_list(
        self,
        items: Sequence[Any],
        *,
        bullet: str = "-",
        indent: int = 0,
    ) -> None:
        """Print a list of items.

        Args:
            items: Items to print.
            bullet: Bullet character to use.
            indent: Number of spaces to indent.
        """
        if self.config.format == OutputFormat.JSON:
            self._print_json(list(items))
            return
        if self.config.format == OutputFormat.YAML:
            self._print_yaml(list(items))
            return

        prefix = " " * indent
        for item in items:
            self.print(f"{prefix}{bullet} {item}")

    def print_dict(
        self,
        data: Dict[str, Any],
        *,
        separator: str = ": ",
        indent: int = 0,
    ) -> None:
        """Print a dictionary as key-value pairs.

        Args:
            data: Dictionary to print.
            separator: Separator between key and value.
            indent: Number of spaces to indent.
        """
        if self.config.format == OutputFormat.JSON:
            self._print_json(data)
            return
        if self.config.format == OutputFormat.YAML:
            self._print_yaml(data)
            return

        prefix = " " * indent
        for key, value in data.items():
            self.print(f"{prefix}{key}{separator}{value}")

    def print_success(self, message: str) -> None:
        """Print a success message."""
        self.print(message)

    def print_dry_run(self, message: str) -> None:
        """Print a dry-run message."""
        self.print(f"[dry-run] {message}")

    def _print_json(self, data: Any) -> None:
        """Print data as JSON."""
        normalized = self._normalize_for_json(data)
        self.print(json.dumps(normalized, indent=2, default=str))

    def _print_yaml(self, data: Any) -> None:
        """Print data as YAML."""
        try:
            import yaml
            normalized = self._normalize_for_json(data)
            self.print(yaml.safe_dump(normalized, default_flow_style=False, sort_keys=False))
        except ImportError:
            # Fallback to JSON if yaml not available
            self._print_json(data)

    def _row_to_strings(self, row: Any, headers: Optional[List[str]] = None) -> List[str]:
        """Convert a row to list of strings based on its type.

        Args:
            row: Row data (dict, list, tuple, or other).
            headers: Optional headers for dict extraction.

        Returns:
            List of string values.
        """
        if isinstance(row, dict):
            return [str(row.get(h, "")) for h in headers] if headers else [str(v) for v in row.values()]
        if isinstance(row, (list, tuple)):
            return [str(v) for v in row]
        return [str(row)]

    def _calculate_column_widths(self, headers: List[str], str_rows: List[List[str]]) -> List[int]:
        """Calculate column widths based on headers and data.

        Args:
            headers: Column headers.
            str_rows: Rows as lists of strings.

        Returns:
            List of column widths.
        """
        widths = [len(h) for h in headers]
        for str_row in str_rows:
            for i, val in enumerate(str_row):
                if i < len(widths):
                    widths[i] = max(widths[i], len(val))
        return widths

    def _print_table_with_headers(self, headers: List[str], str_rows: List[List[str]]) -> None:
        """Print table with headers and separator.

        Args:
            headers: Column headers.
            str_rows: Rows as lists of strings.
        """
        widths = self._calculate_column_widths(headers, str_rows)

        # Print header
        header_line = " | ".join(h.ljust(widths[i]) for i, h in enumerate(headers))
        self.print(header_line)
        self.print("-" * len(header_line))

        # Print rows
        for str_row in str_rows:
            padded = [str_row[i].ljust(widths[i]) if i < len(widths) else str_row[i]
                      for i in range(len(str_row))]
            self.print(" | ".join(padded))

    def _print_table(self, data: Any, headers: Optional[List[str]] = None) -> None:
        """Print data as a table."""
        rows = self._to_rows(data)
        if not rows:
            return

        # Determine headers from first row if not provided
        if headers is None and rows and isinstance(rows[0], dict):
            headers = list(rows[0].keys())

        if headers:
            # Convert rows to strings and print with headers
            str_rows = [self._row_to_strings(row, headers) for row in rows]
            self._print_table_with_headers(headers, str_rows)
        else:
            # No headers, just print rows
            for row in rows:
                if isinstance(row, (list, tuple)):
                    self.print(" | ".join(str(v) for v in row))
                else:
                    self.print(str(row))

    def _print_text(self, data: Any) -> None:
        """Print data as plain text."""
        if isinstance(data, str):
            self.print(data)
        elif isinstance(data, dict):
            self.print_dict(data)
        elif isinstance(data, (list, tuple)):
            for item in data:
                self.print(item)
        elif is_dataclass(data):
            self.print_dict(asdict(data))
        else:
            self.print(str(data))

    def _normalize_for_json(self, data: Any) -> Any:
        """Normalize data for JSON serialization."""
        if is_dataclass(data) and not isinstance(data, type):
            return asdict(data)
        if isinstance(data, dict):
            return {k: self._normalize_for_json(v) for k, v in data.items()}
        if isinstance(data, (list, tuple)):
            return [self._normalize_for_json(v) for v in data]
        if isinstance(data, Enum):
            return data.value
        return data

    def _to_rows(self, data: Any) -> List[Any]:
        """Convert data to a list of rows."""
        if isinstance(data, (list, tuple)):
            return list(data)
        if isinstance(data, dict):
            return [data]
        if is_dataclass(data):
            return [asdict(data)]
        return [data]


# Convenience functions for simple usage
_default_writer = OutputWriter()


def output(data: Any, format: OutputFormat = OutputFormat.TEXT) -> None:
    """Print data in the specified format."""
    writer = OutputWriter(OutputConfig(format=format))
    writer.print_data(data)


def output_json(data: Any) -> None:
    """Print data as JSON."""
    output(data, OutputFormat.JSON)


def output_yaml(data: Any) -> None:
    """Print data as YAML."""
    output(data, OutputFormat.YAML)


def output_table(data: Any, headers: Optional[List[str]] = None) -> None:
    """Print data as a table."""
    writer = OutputWriter(OutputConfig(format=OutputFormat.TABLE))
    writer.print_data(data, headers)
