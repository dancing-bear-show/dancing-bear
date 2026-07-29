"""Regression test: OTLPEventsRecord.from_dict must not crash on empty scopeLogs.

telemetry/otel/models.py:OTLPEventsRecord.from_dict previously used
``resource_log.get("scopeLogs", [{}])[0]`` — a default-only guard that only
applies when the key is absent. An explicit ``scopeLogs: []`` bypassed the
default and raised IndexError, unlike the sibling OTLPMetricsRecord and
OTLPSpansRecord, which already use ``... or [{}]``.
"""

import unittest

from telemetry.otel.models import OTLPEventsRecord


class TestOTLPEventsRecordEmptyScopeLogs(unittest.TestCase):
    def test_otlp_wrapper_empty_scope_logs_returns_empty_record(self):
        record = OTLPEventsRecord.from_dict(
            {"resourceLogs": [{"resource": {}, "scopeLogs": []}]}
        )
        self.assertEqual(record.log_records, [])

    def test_simplified_format_empty_scope_logs_returns_empty_record(self):
        record = OTLPEventsRecord.from_dict({"resource": {}, "scopeLogs": []})
        self.assertEqual(record.log_records, [])

    def test_otlp_wrapper_absent_scope_logs_still_returns_empty_record(self):
        record = OTLPEventsRecord.from_dict({"resourceLogs": [{"resource": {}}]})
        self.assertEqual(record.log_records, [])

    def test_simplified_format_absent_scope_logs_still_returns_empty_record(self):
        record = OTLPEventsRecord.from_dict({"resource": {}})
        self.assertEqual(record.log_records, [])


if __name__ == "__main__":
    unittest.main()
