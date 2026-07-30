"""Tests for filters pipeline — plan, sync, impact, and export processors."""

from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace

from mail.context import MailContext
from mail.filters.consumers import (
    FiltersPlanConsumer,
    FiltersPlanPayload,
    FiltersSyncPayload,
    FiltersImpactPayload,
    FiltersExportConsumer,
)
from mail.filters.processors import (
    FiltersPlanProcessor,
    FiltersSyncProcessor,
    FiltersImpactProcessor,
    FiltersExportProcessor,
)
from mail.filters.producers import (
    FiltersPlanProducer,
    FiltersSyncProducer,
    FiltersImpactProducer,
    FiltersExportProducer,
)

from tests.mail_tests.fixtures import FakeGmailClient, make_args


def _make_pipeline_client():
    """Create a FakeGmailClient configured for filters pipeline tests."""
    return FakeGmailClient(
        labels=[
            {"id": "LBL_VIP", "name": "VIP"},
            {"id": "LBL_OTHER", "name": "Other"},
        ],
        filters=[
            {
                "id": "EXTRA",
                "criteria": {"from": "someone@example.com"},
                "action": {"addLabelIds": ["LBL_OTHER"]},
            }
        ],
        message_ids_by_query={
            "foo@example.com": ["m1"] * 5,
            'subject:"bar report"': ["m2"] * 3,
        },
        verified_forward_addresses={"verified@example.com"},
    )


class FiltersPlanConsumerTests(unittest.TestCase):
    def test_consume_loads_config_and_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg_path = Path(tmpdir) / "filters.yaml"
            cfg_path.write_text(
                "filters:\n"
                "  - match:\n"
                "      from: foo@example.com\n"
                "    action:\n"
                "      add:\n"
                "        - VIP\n"
            )
            args = make_args(config=str(cfg_path))
            ctx = MailContext.from_args(args)
            ctx.gmail_client = _make_pipeline_client()

            consumer = FiltersPlanConsumer(ctx)
            payload = consumer.consume()

            self.assertEqual(len(payload.desired_filters), 1)
            self.assertEqual(payload.name_to_id.get("VIP"), "LBL_VIP")
            self.assertEqual(payload.id_to_name.get("LBL_OTHER"), "Other")
            self.assertEqual(len(payload.existing_filters), 1)
            self.assertFalse(payload.delete_missing)


class FiltersPlanProcessorSadPathTests(unittest.TestCase):
    """Sad-path coverage for FiltersPlanProcessor SafeProcessor wrapping."""

    def test_process_raises_wraps_error_in_envelope(self):
        """An exception in _process_safe surfaces as a ResultEnvelope error, not a raise."""
        # Trigger an error by passing a payload whose desired_filters contains a
        # non-dict entry that causes _canon_desired to fail.
        payload = FiltersPlanPayload(
            desired_filters=[None],  # non-dict spec will raise AttributeError inside _process_safe
            existing_filters=[],
            id_to_name={},
            name_to_id={},
            delete_missing=False,
        )
        processor = FiltersPlanProcessor()
        envelope = processor.process(payload)

        self.assertFalse(envelope.ok())
        self.assertEqual(envelope.status, "error")
        self.assertIsNotNone(envelope.diagnostics)
        self.assertIsInstance(envelope.diagnostics.get("message"), str)
        self.assertIsNone(envelope.payload)

    def test_producer_handles_error_envelope_gracefully(self):
        """FiltersPlanProducer.produce() on an error envelope emits fallback message."""
        from core.pipeline import ResultEnvelope
        from core.cli_output import OutputWriter, OutputConfig

        buf = io.StringIO()
        writer = OutputWriter(OutputConfig(file=buf))
        producer = FiltersPlanProducer(writer=writer)
        error_envelope = ResultEnvelope(status="error", diagnostics={"message": "boom"})
        producer.produce(error_envelope)

        output = buf.getvalue()
        self.assertIn("failed", output.lower())


class FiltersPlanProcessorTests(unittest.TestCase):
    def test_processor_and_producer_match_legacy_output(self):
        payload = FiltersPlanPayload(
            desired_filters=[
                {"match": {"from": "foo@example.com"}, "action": {"add": ["VIP"]}},
                {"match": {"from": "bar@example.com"}, "action": {"add": ["Other"]}},
            ],
            existing_filters=[
                {
                    "id": "KEEP",
                    "criteria": {"from": "foo@example.com"},
                    "action": {"addLabelIds": ["LBL_VIP"]},
                },
                {
                    "id": "DROP",
                    "criteria": {"from": "dropme@example.com"},
                    "action": {"addLabelIds": ["LBL_OTHER"]},
                },
            ],
            id_to_name={"LBL_VIP": "VIP", "LBL_OTHER": "Other"},
            name_to_id={"VIP": "LBL_VIP", "Other": "LBL_OTHER"},
            delete_missing=True,
        )
        processor = FiltersPlanProcessor()
        envelope = processor.process(payload)

        self.assertTrue(envelope.ok())
        result = envelope.payload
        self.assertIsNotNone(result)
        self.assertEqual(len(result.to_create), 1)
        self.assertEqual(len(result.to_delete), 1)

        buf = io.StringIO()
        producer = FiltersPlanProducer(preview_limit=5)
        with redirect_stdout(buf):
            producer.produce(envelope)
        output = buf.getvalue()

        self.assertIn("Plan: create=1 delete=1", output)
        self.assertIn("from:bar@example.com", output)
        self.assertIn("Would delete (not present in YAML):", output)
        self.assertIn("add=['Other']", output)


class FiltersSyncProcessorTests(unittest.TestCase):
    def test_sync_processor_detects_diffs_and_producer_executes(self):
        payload = FiltersSyncPayload(
            desired_filters=[
                {
                    "match": {"from": "bar@example.com"},
                    "action": {"add": ["VIP"], "categorizeAs": "promotions"},
                },
            ],
            existing_filters=[
                {
                    "id": "DROP",
                    "criteria": {"from": "drop@example.com"},
                    "action": {"addLabelIds": ["LBL_OTHER"]},
                }
            ],
            id_to_name={"LBL_VIP": "VIP", "LBL_OTHER": "Other"},
            name_to_id={"VIP": "LBL_VIP", "Other": "LBL_OTHER"},
            delete_missing=True,
            require_forward_verified=False,
            verified_forward_addresses=set(),
        )
        processor = FiltersSyncProcessor()
        envelope = processor.process(payload)
        self.assertTrue(envelope.ok())
        result = envelope.payload
        self.assertIsNotNone(result)
        self.assertEqual(len(result.to_create), 1)
        self.assertEqual(len(result.to_delete), 1)

        fake_client = FakeGmailClient(
            labels=[{"id": "LBL_VIP", "name": "VIP"}, {"id": "LBL_OTHER", "name": "Other"}],
            filters=[
                {
                    "id": "DROP",
                    "criteria": {"from": "drop@example.com"},
                    "action": {"addLabelIds": ["LBL_OTHER"]},
                }
            ],
        )
        producer = FiltersSyncProducer(fake_client, dry_run=False)
        producer.produce(envelope)

        created = [f for f in fake_client.created_filters]
        self.assertTrue(
            any(
                "CATEGORY_PROMOTIONS" in (f.get("action", {}).get("addLabelIds") or [])
                for f in created
            )
        )

    def test_sync_processor_errors_on_unverified_forward(self):
        payload = FiltersSyncPayload(
            desired_filters=[
                {"match": {"from": "foo@example.com"}, "action": {"forward": "bad@example.com"}}
            ],
            existing_filters=[],
            id_to_name={},
            name_to_id={},
            delete_missing=False,
            require_forward_verified=True,
            verified_forward_addresses={"verified@example.com"},
        )
        processor = FiltersSyncProcessor()
        envelope = processor.process(payload)
        self.assertFalse(envelope.ok())
        self.assertEqual(envelope.diagnostics.get("code"), 2)


class FiltersImpactProcessorTests(unittest.TestCase):
    def test_impact_processor_counts_and_producer_outputs(self):
        client = _make_pipeline_client()
        payload = FiltersImpactPayload(
            filters=[
                {"match": {"from": "foo@example.com"}},
                {"match": {"subject": "Bar Report"}},
            ],
            days=7,
            only_inbox=True,
            pages=2,
            client=client,
        )
        processor = FiltersImpactProcessor()
        envelope = processor.process(payload)
        self.assertTrue(envelope.ok())
        buf = io.StringIO()
        producer = FiltersImpactProducer()
        with redirect_stdout(buf):
            producer.produce(envelope)
        out = buf.getvalue()
        self.assertIn("     5", out)
        self.assertIn("     3", out)
        self.assertIn("Total impacted: 8", out)


class FiltersExportProcessorTests(unittest.TestCase):
    def test_export_pipeline_writes_yaml(self):
        args = SimpleNamespace(out=None)
        ctx = MailContext.from_args(args)
        ctx.gmail_client = _make_pipeline_client()
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "filters.yaml"
            ctx.args.out = str(out_path)
            consumer = FiltersExportConsumer(ctx)
            payload = consumer.consume()
            processor = FiltersExportProcessor()
            envelope = processor.process(payload)
            producer = FiltersExportProducer()
            buf = io.StringIO()
            with redirect_stdout(buf):
                producer.produce(envelope)
            self.assertTrue(out_path.exists())
            import yaml

            data = yaml.safe_load(out_path.read_text())
            self.assertIn("filters", data)
            self.assertEqual(len(data["filters"]), len(ctx.gmail_client.list_filters()))
            self.assertIn("criteria", data["filters"][0])
            self.assertIn("action", data["filters"][0])
            self.assertIn("Exported", buf.getvalue())


class FiltersImpactProcessorSadPathTests(unittest.TestCase):
    """Sad-path coverage for FiltersImpactProcessor SafeProcessor wrapping."""

    def test_client_exception_wraps_in_error_envelope(self):
        """When list_message_ids raises, SafeProcessor wraps it as error envelope."""
        from unittest.mock import MagicMock

        bad_client = MagicMock()
        bad_client.list_message_ids.side_effect = RuntimeError("network error")

        payload = FiltersImpactPayload(
            filters=[{"match": {"from": "x@example.com"}}],
            days=7,
            only_inbox=False,
            pages=1,
            client=bad_client,
        )
        processor = FiltersImpactProcessor()
        envelope = processor.process(payload)

        self.assertFalse(envelope.ok())
        self.assertEqual(envelope.status, "error")
        self.assertIn("network error", envelope.diagnostics.get("message", ""))
        bad_client.list_message_ids.assert_called_once()

    def test_producer_handles_impact_error_envelope(self):
        """FiltersImpactProducer.produce() on error envelope emits fallback message."""
        from core.pipeline import ResultEnvelope
        from core.cli_output import OutputWriter, OutputConfig

        buf = io.StringIO()
        writer = OutputWriter(OutputConfig(file=buf))
        producer = FiltersImpactProducer(writer=writer)
        error_envelope = ResultEnvelope(status="error", diagnostics={"message": "impact boom"})
        producer.produce(error_envelope)

        self.assertIn("failed", buf.getvalue().lower())


class FiltersExportProcessorSadPathTests(unittest.TestCase):
    """Sad-path coverage for FiltersExportProcessor SafeProcessor wrapping."""

    def test_process_raises_wraps_in_error_envelope(self):
        """An exception in _process_safe (e.g. bad filter element type) surfaces as error envelope."""
        from mail.filters.consumers import FiltersExportPayload

        # A non-dict entry in filters triggers AttributeError inside _process_safe via
        # filt.get("criteria") being called on a string — surfaced as ResultEnvelope(error).
        payload = FiltersExportPayload(
            filters=["not-a-dict"],  # type: ignore[list-item]
            id_to_name={},
            out_path=Path("/dev/null"),
        )
        processor = FiltersExportProcessor()
        envelope = processor.process(payload)

        self.assertFalse(envelope.ok())
        self.assertEqual(envelope.status, "error")
        self.assertIsNotNone(envelope.diagnostics)
        self.assertIsInstance(envelope.diagnostics.get("message"), str)
        self.assertIsNone(envelope.payload)

    def test_producer_handles_export_error_envelope(self):
        """FiltersExportProducer.produce() on error envelope emits fallback message."""
        from core.pipeline import ResultEnvelope

        buf = io.StringIO()
        producer = FiltersExportProducer()
        error_envelope = ResultEnvelope(status="error", diagnostics={"message": "export boom"})
        with redirect_stdout(buf):
            producer.produce(error_envelope)

        self.assertIn("failed", buf.getvalue().lower())


if __name__ == "__main__":
    unittest.main()
