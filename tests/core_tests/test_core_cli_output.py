"""Tests for core/cli_output.py uncovered branches."""

from __future__ import annotations

import json
import unittest
from dataclasses import dataclass
from enum import Enum
from io import StringIO
from unittest import mock

from core.cli_output import (
    OutputFormat,
    OutputConfig,
    OutputWriter,
    output,
    output_json,
    output_yaml,
    output_table,
)


@dataclass
class SampleData:
    name: str
    value: int


class SampleEnum(Enum):
    FIRST = "first"
    SECOND = "second"


class TestOutputConfig(unittest.TestCase):
    def test_default_stream_is_stdout(self):
        import sys
        config = OutputConfig()
        self.assertIs(config.stream, sys.stdout)

    def test_custom_file_stream(self):
        buf = StringIO()
        config = OutputConfig(file=buf)
        self.assertIs(config.stream, buf)


class TestOutputWriterPrint(unittest.TestCase):
    def test_print_to_stream(self):
        buf = StringIO()
        config = OutputConfig(file=buf)
        writer = OutputWriter(config)
        writer.print("hello world")
        self.assertIn("hello world", buf.getvalue())

    def test_quiet_mode_suppresses_print(self):
        buf = StringIO()
        config = OutputConfig(file=buf, quiet=True)
        writer = OutputWriter(config)
        writer.print("should not appear")
        self.assertEqual(buf.getvalue(), "")

    def test_print_error_to_stderr(self):
        buf = StringIO()
        writer = OutputWriter()
        with mock.patch("sys.stderr", buf):
            writer.print_error("something went wrong")
        self.assertIn("Error: something went wrong", buf.getvalue())

    def test_print_warning_to_stderr(self):
        buf = StringIO()
        writer = OutputWriter()
        with mock.patch("sys.stderr", buf):
            writer.print_warning("be careful")
        self.assertIn("Warning: be careful", buf.getvalue())

    def test_print_verbose_when_verbose(self):
        buf = StringIO()
        config = OutputConfig(file=buf, verbose=True)
        writer = OutputWriter(config)
        writer.print_verbose("verbose message")
        self.assertIn("verbose message", buf.getvalue())

    def test_print_verbose_suppressed_when_not_verbose(self):
        buf = StringIO()
        config = OutputConfig(file=buf, verbose=False)
        writer = OutputWriter(config)
        writer.print_verbose("should not appear")
        self.assertEqual(buf.getvalue(), "")

    def test_print_success(self):
        buf = StringIO()
        config = OutputConfig(file=buf)
        writer = OutputWriter(config)
        writer.print_success("all good")
        self.assertIn("all good", buf.getvalue())

    def test_print_dry_run(self):
        buf = StringIO()
        config = OutputConfig(file=buf)
        writer = OutputWriter(config)
        writer.print_dry_run("would do something")
        self.assertIn("[dry-run] would do something", buf.getvalue())


class TestOutputWriterDataFormats(unittest.TestCase):
    def test_print_data_json(self):
        buf = StringIO()
        config = OutputConfig(format=OutputFormat.JSON, file=buf)
        writer = OutputWriter(config)
        writer.print_data({"key": "value"})
        data = json.loads(buf.getvalue())
        self.assertEqual(data["key"], "value")

    def test_print_data_json_list(self):
        buf = StringIO()
        config = OutputConfig(format=OutputFormat.JSON, file=buf)
        writer = OutputWriter(config)
        writer.print_data([1, 2, 3])
        data = json.loads(buf.getvalue())
        self.assertEqual(data, [1, 2, 3])

    def test_print_data_text_string(self):
        buf = StringIO()
        config = OutputConfig(format=OutputFormat.TEXT, file=buf)
        writer = OutputWriter(config)
        writer.print_data("plain text")
        self.assertIn("plain text", buf.getvalue())

    def test_print_data_text_list(self):
        buf = StringIO()
        config = OutputConfig(format=OutputFormat.TEXT, file=buf)
        writer = OutputWriter(config)
        writer.print_data(["item1", "item2"])
        self.assertIn("item1", buf.getvalue())
        self.assertIn("item2", buf.getvalue())

    def test_print_data_text_dict(self):
        buf = StringIO()
        config = OutputConfig(format=OutputFormat.TEXT, file=buf)
        writer = OutputWriter(config)
        writer.print_data({"a": 1, "b": 2})
        self.assertIn("a", buf.getvalue())
        self.assertIn("b", buf.getvalue())

    def test_print_data_text_dataclass(self):
        buf = StringIO()
        config = OutputConfig(format=OutputFormat.TEXT, file=buf)
        writer = OutputWriter(config)
        writer.print_data(SampleData(name="test", value=42))
        self.assertIn("name", buf.getvalue())
        self.assertIn("value", buf.getvalue())

    def test_print_data_text_other(self):
        buf = StringIO()
        config = OutputConfig(format=OutputFormat.TEXT, file=buf)
        writer = OutputWriter(config)
        writer.print_data(12345)
        self.assertIn("12345", buf.getvalue())

    def test_print_data_yaml_fallback_json(self):
        buf = StringIO()
        config = OutputConfig(format=OutputFormat.YAML, file=buf)
        writer = OutputWriter(config)
        with mock.patch.dict("sys.modules", {"yaml": None}):
            writer.print_data({"key": "value"})
        # If yaml not available, should fallback to JSON
        output = buf.getvalue()
        self.assertTrue(output.strip())  # some output produced

    def test_print_data_table_with_headers(self):
        buf = StringIO()
        config = OutputConfig(format=OutputFormat.TABLE, file=buf)
        writer = OutputWriter(config)
        data = [{"name": "Alice", "age": "30"}, {"name": "Bob", "age": "25"}]
        writer.print_data(data, headers=["name", "age"])
        output = buf.getvalue()
        self.assertIn("name", output)
        self.assertIn("Alice", output)
        self.assertIn("Bob", output)

    def test_print_data_table_infers_headers(self):
        buf = StringIO()
        config = OutputConfig(format=OutputFormat.TABLE, file=buf)
        writer = OutputWriter(config)
        data = [{"name": "Alice", "score": "100"}]
        writer.print_data(data)
        output = buf.getvalue()
        self.assertIn("name", output)
        self.assertIn("Alice", output)

    def test_print_data_table_no_headers_list_of_lists(self):
        buf = StringIO()
        config = OutputConfig(format=OutputFormat.TABLE, file=buf)
        writer = OutputWriter(config)
        data = [["a", "b"], ["c", "d"]]
        writer.print_data(data)
        output = buf.getvalue()
        self.assertIn("a | b", output)

    def test_print_data_table_no_headers_simple_values(self):
        buf = StringIO()
        config = OutputConfig(format=OutputFormat.TABLE, file=buf)
        writer = OutputWriter(config)
        writer.print_data(["single", "items"])
        output = buf.getvalue()
        self.assertIn("single", output)

    def test_print_data_table_empty(self):
        buf = StringIO()
        config = OutputConfig(format=OutputFormat.TABLE, file=buf)
        writer = OutputWriter(config)
        writer.print_data([])
        # Empty table produces no output
        self.assertEqual(buf.getvalue(), "")


class TestOutputWriterList(unittest.TestCase):
    def test_print_list_default_bullet(self):
        buf = StringIO()
        config = OutputConfig(file=buf)
        writer = OutputWriter(config)
        writer.print_list(["apple", "banana"])
        self.assertIn("- apple", buf.getvalue())
        self.assertIn("- banana", buf.getvalue())

    def test_print_list_custom_bullet(self):
        buf = StringIO()
        config = OutputConfig(file=buf)
        writer = OutputWriter(config)
        writer.print_list(["item"], bullet="*")
        self.assertIn("* item", buf.getvalue())

    def test_print_list_with_indent(self):
        buf = StringIO()
        config = OutputConfig(file=buf)
        writer = OutputWriter(config)
        writer.print_list(["item"], indent=4)
        self.assertIn("    - item", buf.getvalue())

    def test_print_list_json_format(self):
        buf = StringIO()
        config = OutputConfig(format=OutputFormat.JSON, file=buf)
        writer = OutputWriter(config)
        writer.print_list(["a", "b"])
        data = json.loads(buf.getvalue())
        self.assertEqual(data, ["a", "b"])

    def test_print_list_yaml_format(self):
        buf = StringIO()
        config = OutputConfig(format=OutputFormat.YAML, file=buf)
        writer = OutputWriter(config)
        writer.print_list(["a", "b"])
        # Should call _print_yaml
        output = buf.getvalue()
        self.assertTrue(output.strip())


class TestOutputWriterDict(unittest.TestCase):
    def test_print_dict_text(self):
        buf = StringIO()
        config = OutputConfig(file=buf)
        writer = OutputWriter(config)
        writer.print_dict({"key": "value", "num": 42})
        output = buf.getvalue()
        self.assertIn("key: value", output)
        self.assertIn("num: 42", output)

    def test_print_dict_custom_separator(self):
        buf = StringIO()
        config = OutputConfig(file=buf)
        writer = OutputWriter(config)
        writer.print_dict({"k": "v"}, separator=" = ")
        self.assertIn("k = v", buf.getvalue())

    def test_print_dict_with_indent(self):
        buf = StringIO()
        config = OutputConfig(file=buf)
        writer = OutputWriter(config)
        writer.print_dict({"k": "v"}, indent=2)
        self.assertIn("  k: v", buf.getvalue())

    def test_print_dict_json_format(self):
        buf = StringIO()
        config = OutputConfig(format=OutputFormat.JSON, file=buf)
        writer = OutputWriter(config)
        writer.print_dict({"x": 1})
        data = json.loads(buf.getvalue())
        self.assertEqual(data["x"], 1)

    def test_print_dict_yaml_format(self):
        buf = StringIO()
        config = OutputConfig(format=OutputFormat.YAML, file=buf)
        writer = OutputWriter(config)
        writer.print_dict({"x": 1})
        output = buf.getvalue()
        self.assertTrue(output.strip())


class TestNormalizeForJson(unittest.TestCase):
    def test_dataclass_normalized(self):
        buf = StringIO()
        config = OutputConfig(format=OutputFormat.JSON, file=buf)
        writer = OutputWriter(config)
        writer.print_data(SampleData(name="test", value=99))
        data = json.loads(buf.getvalue())
        self.assertEqual(data["name"], "test")
        self.assertEqual(data["value"], 99)

    def test_enum_normalized(self):
        buf = StringIO()
        config = OutputConfig(format=OutputFormat.JSON, file=buf)
        writer = OutputWriter(config)
        writer.print_data({"fmt": SampleEnum.FIRST})
        data = json.loads(buf.getvalue())
        self.assertEqual(data["fmt"], "first")

    def test_nested_list_normalized(self):
        buf = StringIO()
        config = OutputConfig(format=OutputFormat.JSON, file=buf)
        writer = OutputWriter(config)
        writer.print_data({"items": [SampleData("a", 1)]})
        data = json.loads(buf.getvalue())
        self.assertEqual(data["items"][0]["name"], "a")


class TestConvenienceFunctions(unittest.TestCase):
    def test_output_json(self):
        buf = StringIO()
        with mock.patch("sys.stdout", buf):
            output_json({"key": "val"})
        data = json.loads(buf.getvalue())
        self.assertEqual(data["key"], "val")

    def test_output_yaml(self):
        buf = StringIO()
        with mock.patch("sys.stdout", buf):
            output_yaml({"key": "val"})
        # Should produce some output
        self.assertTrue(buf.getvalue().strip())

    def test_output_table(self):
        buf = StringIO()
        with mock.patch("sys.stdout", buf):
            output_table([{"col": "row1"}, {"col": "row2"}])
        self.assertIn("col", buf.getvalue())
        self.assertIn("row1", buf.getvalue())

    def test_output_table_with_explicit_headers(self):
        buf = StringIO()
        with mock.patch("sys.stdout", buf):
            output_table([{"col": "val"}], headers=["col"])
        self.assertIn("col", buf.getvalue())

    def test_output_text(self):
        buf = StringIO()
        with mock.patch("sys.stdout", buf):
            output("plain text")
        self.assertIn("plain text", buf.getvalue())


class TestRowToStrings(unittest.TestCase):
    def setUp(self):
        self.writer = OutputWriter()

    def test_dict_with_headers(self):
        row = {"name": "Alice", "age": 30}
        result = self.writer._row_to_strings(row, ["name", "age"])
        self.assertEqual(result, ["Alice", "30"])

    def test_dict_without_headers(self):
        row = {"name": "Bob", "age": 25}
        result = self.writer._row_to_strings(row)
        self.assertIn("Bob", result)

    def test_list_row(self):
        row = ["col1", "col2"]
        result = self.writer._row_to_strings(row)
        self.assertEqual(result, ["col1", "col2"])

    def test_tuple_row(self):
        row = ("a", "b")
        result = self.writer._row_to_strings(row)
        self.assertEqual(result, ["a", "b"])

    def test_scalar_row(self):
        result = self.writer._row_to_strings("single")
        self.assertEqual(result, ["single"])


class TestToRows(unittest.TestCase):
    def setUp(self):
        self.writer = OutputWriter()

    def test_list_returned_as_is(self):
        result = self.writer._to_rows([1, 2, 3])
        self.assertEqual(result, [1, 2, 3])

    def test_tuple_converted_to_list(self):
        result = self.writer._to_rows((1, 2))
        self.assertEqual(result, [1, 2])

    def test_dict_wrapped_in_list(self):
        result = self.writer._to_rows({"a": 1})
        self.assertEqual(result, [{"a": 1}])

    def test_dataclass_wrapped(self):
        result = self.writer._to_rows(SampleData("test", 5))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["name"], "test")

    def test_other_wrapped_in_list(self):
        result = self.writer._to_rows("string")
        self.assertEqual(result, ["string"])


if __name__ == "__main__":
    unittest.main()
