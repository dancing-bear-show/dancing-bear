"""Tests for CLI output formatting, error types, and error handling."""
from __future__ import annotations

import io
import unittest
from dataclasses import dataclass
from unittest.mock import patch

from core.cli_errors import (
    CLIError,
    ConfigError,
    AuthError,
    NetworkError,
    NotFoundError,
    UsageError,
    ExitCode,
    handle_error,
)
from core.cli_output import (
    OutputConfig,
    OutputFormat,
    OutputWriter,
)


class TestExitCodes(unittest.TestCase):
    """Test exit code definitions."""

    def test_exit_codes_are_integers(self):
        self.assertEqual(ExitCode.SUCCESS, 0)
        self.assertEqual(ExitCode.ERROR, 1)
        self.assertEqual(ExitCode.USAGE, 2)
        self.assertEqual(ExitCode.INTERRUPTED, 130)

    def test_error_types_have_correct_codes(self):
        self.assertEqual(ConfigError("test").code, ExitCode.CONFIG_ERROR)
        self.assertEqual(AuthError("test").code, ExitCode.AUTH_ERROR)
        self.assertEqual(NetworkError("test").code, ExitCode.NETWORK_ERROR)
        self.assertEqual(NotFoundError("test").code, ExitCode.NOT_FOUND)
        self.assertEqual(UsageError("test").code, ExitCode.USAGE)


class TestCLIError(unittest.TestCase):
    """Test CLIError class."""

    def test_error_message(self):
        err = CLIError("Something went wrong")
        self.assertEqual(str(err), "Something went wrong")

    def test_error_with_hint(self):
        err = CLIError("Failed", hint="Try again")
        self.assertEqual(err.message, "Failed")
        self.assertEqual(err.hint, "Try again")

    def test_error_default_code(self):
        err = CLIError("Error")
        self.assertEqual(err.code, ExitCode.ERROR)


class TestHandleError(unittest.TestCase):
    """Test error handling."""

    def test_handle_cli_error(self):
        err = CLIError("Test error", ExitCode.CONFIG_ERROR)
        with patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
            code = handle_error(err)
            self.assertEqual(code, ExitCode.CONFIG_ERROR)
            self.assertIn("Test error", mock_stderr.getvalue())

    def test_handle_cli_error_with_hint(self):
        err = CLIError("Test error", hint="Check config")
        with patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
            handle_error(err)
            output = mock_stderr.getvalue()
            self.assertIn("Test error", output)
            self.assertIn("Check config", output)

    def test_handle_keyboard_interrupt(self):
        with patch("sys.stderr", new_callable=io.StringIO):
            code = handle_error(KeyboardInterrupt())
            self.assertEqual(code, ExitCode.INTERRUPTED)

    def test_handle_unexpected_error(self):
        with patch("sys.stderr", new_callable=io.StringIO) as mock_stderr:
            code = handle_error(ValueError("Unexpected"))
            self.assertEqual(code, ExitCode.ERROR)
            self.assertIn("Unexpected", mock_stderr.getvalue())


class TestOutputWriter(unittest.TestCase):
    """Test output formatting."""

    def test_print_basic(self):
        output = io.StringIO()
        config = OutputConfig(file=output)
        writer = OutputWriter(config)
        writer.print("Hello")
        self.assertEqual(output.getvalue(), "Hello\n")

    def test_print_quiet_mode(self):
        output = io.StringIO()
        config = OutputConfig(file=output, quiet=True)
        writer = OutputWriter(config)
        writer.print("Hello")
        self.assertEqual(output.getvalue(), "")

    def test_print_verbose(self):
        output = io.StringIO()
        config = OutputConfig(file=output, verbose=True)
        writer = OutputWriter(config)
        writer.print_verbose("Debug info")
        self.assertEqual(output.getvalue(), "Debug info\n")

    def test_print_verbose_when_disabled(self):
        output = io.StringIO()
        config = OutputConfig(file=output, verbose=False)
        writer = OutputWriter(config)
        writer.print_verbose("Debug info")
        self.assertEqual(output.getvalue(), "")

    def test_print_dry_run(self):
        output = io.StringIO()
        config = OutputConfig(file=output)
        writer = OutputWriter(config)
        writer.print_dry_run("Would delete file")
        self.assertIn("[dry-run]", output.getvalue())

    def test_print_json(self):
        output = io.StringIO()
        config = OutputConfig(file=output, format=OutputFormat.JSON)
        writer = OutputWriter(config)
        writer.print_data({"key": "value"})
        self.assertIn('"key"', output.getvalue())
        self.assertIn('"value"', output.getvalue())

    def test_print_list(self):
        output = io.StringIO()
        config = OutputConfig(file=output)
        writer = OutputWriter(config)
        writer.print_list(["a", "b", "c"])
        out = output.getvalue()
        self.assertIn("- a", out)
        self.assertIn("- b", out)
        self.assertIn("- c", out)

    def test_print_dict(self):
        output = io.StringIO()
        config = OutputConfig(file=output)
        writer = OutputWriter(config)
        writer.print_dict({"name": "test", "value": 42})
        out = output.getvalue()
        self.assertIn("name: test", out)
        self.assertIn("value: 42", out)

    def test_print_table(self):
        output = io.StringIO()
        config = OutputConfig(file=output, format=OutputFormat.TABLE)
        writer = OutputWriter(config)
        data = [
            {"name": "Alice", "age": 30},
            {"name": "Bob", "age": 25},
        ]
        writer.print_data(data)
        out = output.getvalue()
        self.assertIn("name", out)
        self.assertIn("Alice", out)
        self.assertIn("Bob", out)


class TestOutputWriterHelperFunctions(unittest.TestCase):
    """Test OutputWriter helper functions extracted during refactoring."""

    def setUp(self):
        """Set up test fixtures."""
        self.output = io.StringIO()
        self.config = OutputConfig(file=self.output)
        self.writer = OutputWriter(self.config)

    def test_row_to_strings_with_dict_and_headers(self):
        """Test _row_to_strings converts dict with headers correctly."""
        row = {"name": "Alice", "age": 30, "city": "NYC"}
        headers = ["name", "age"]
        result = self.writer._row_to_strings(row, headers)
        self.assertEqual(result, ["Alice", "30"])

    def test_row_to_strings_with_dict_no_headers(self):
        """Test _row_to_strings converts dict without headers."""
        row = {"name": "Bob", "age": 25}
        result = self.writer._row_to_strings(row)
        self.assertEqual(len(result), 2)
        self.assertIn("Bob", result)
        self.assertIn("25", result)

    def test_row_to_strings_with_list(self):
        """Test _row_to_strings converts list."""
        row = ["Alice", 30, "NYC"]
        result = self.writer._row_to_strings(row)
        self.assertEqual(result, ["Alice", "30", "NYC"])

    def test_row_to_strings_with_tuple(self):
        """Test _row_to_strings converts tuple."""
        row = ("Bob", 25)
        result = self.writer._row_to_strings(row)
        self.assertEqual(result, ["Bob", "25"])

    def test_row_to_strings_with_other_type(self):
        """Test _row_to_strings converts other types to single-item list."""
        result = self.writer._row_to_strings(42)
        self.assertEqual(result, ["42"])

    def test_row_to_strings_handles_missing_keys(self):
        """Test _row_to_strings handles missing dict keys."""
        row = {"name": "Alice"}
        headers = ["name", "age", "city"]
        result = self.writer._row_to_strings(row, headers)
        self.assertEqual(result, ["Alice", "", ""])

    def test_calculate_column_widths_basic(self):
        """Test _calculate_column_widths calculates correct widths."""
        headers = ["Name", "Age"]
        str_rows = [["Alice", "30"], ["Bob", "25"]]
        widths = self.writer._calculate_column_widths(headers, str_rows)
        self.assertEqual(widths, [5, 3])  # max("Name"=4, "Alice"=5), max("Age"=3, "30"=2, "25"=2)

    def test_calculate_column_widths_with_long_data(self):
        """Test _calculate_column_widths handles data wider than headers."""
        headers = ["ID", "Name"]
        str_rows = [["123456", "Alexander"], ["7", "Bo"]]
        widths = self.writer._calculate_column_widths(headers, str_rows)
        self.assertEqual(widths, [6, 9])  # max(2,6), max(4,9)

    def test_calculate_column_widths_empty_rows(self):
        """Test _calculate_column_widths with empty rows."""
        headers = ["Name", "Age"]
        str_rows = []
        widths = self.writer._calculate_column_widths(headers, str_rows)
        self.assertEqual(widths, [4, 3])  # Just header lengths

    def test_calculate_column_widths_with_extra_columns(self):
        """Test _calculate_column_widths ignores columns beyond headers."""
        headers = ["Name", "Age"]
        str_rows = [["Alice", "30", "Extra", "Data"]]
        widths = self.writer._calculate_column_widths(headers, str_rows)
        self.assertEqual(widths, [5, 3])  # Only first 2 columns considered

    def test_print_table_with_headers_basic(self):
        """Test _print_table_with_headers prints formatted table."""
        headers = ["Name", "Age"]
        str_rows = [["Alice", "30"], ["Bob", "25"]]
        self.writer._print_table_with_headers(headers, str_rows)

        output = self.output.getvalue()
        self.assertIn("Name", output)
        self.assertIn("Age", output)
        self.assertIn("Alice", output)
        self.assertIn("Bob", output)
        self.assertIn("|", output)  # Column separator
        self.assertIn("-", output)  # Header separator

    def test_print_table_with_headers_alignment(self):
        """Test _print_table_with_headers aligns columns properly."""
        headers = ["ID", "Name"]
        str_rows = [["1", "Alice"], ["123", "Bo"]]
        self.writer._print_table_with_headers(headers, str_rows)

        output = self.output.getvalue()
        lines = output.strip().split("\n")
        # Check that we have header, separator, and data rows
        self.assertEqual(len(lines), 4)  # header + separator + 2 data rows
        # Check that separator line uses dashes
        self.assertTrue(all(c in "-" for c in lines[1]))
        # Check that data lines contain the expected values
        data_lines = [line for line in lines if "Alice" in line or "Bo" in line]
        self.assertEqual(len(data_lines), 2)

    def test_print_table_with_headers_empty_values(self):
        """Test _print_table_with_headers handles empty values."""
        headers = ["Name", "Age"]
        str_rows = [["Alice", ""], ["", "25"]]
        self.writer._print_table_with_headers(headers, str_rows)

        output = self.output.getvalue()
        self.assertIn("Alice", output)
        self.assertIn("25", output)


class TestDataclassOutput(unittest.TestCase):
    """Test output with dataclasses."""

    def test_print_dataclass_as_json(self):
        @dataclass
        class Person:
            name: str
            age: int

        output = io.StringIO()
        config = OutputConfig(file=output, format=OutputFormat.JSON)
        writer = OutputWriter(config)
        writer.print_data(Person("Alice", 30))
        out = output.getvalue()
        self.assertIn('"name"', out)
        self.assertIn('"Alice"', out)
        self.assertIn('"age"', out)
        self.assertIn("30", out)

    def test_print_dataclass_as_text(self):
        @dataclass
        class Person:
            name: str
            age: int

        output = io.StringIO()
        config = OutputConfig(file=output, format=OutputFormat.TEXT)
        writer = OutputWriter(config)
        writer.print_data(Person("Bob", 25))
        out = output.getvalue()
        self.assertIn("name", out)
        self.assertIn("Bob", out)


if __name__ == "__main__":
    unittest.main()
