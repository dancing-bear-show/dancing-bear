"""Config-cache and accounts-list producers print through their injected writer.

A test that captures global stdout with the default writer passes whether a
producer calls ``self._writer.print`` or bare ``print``. These inject a writer
bound to a buffer and assert stdout stays empty, so a regression to bare
``print`` fails here.
"""
from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from unittest.mock import patch

from core.cli_output import OutputConfig, OutputWriter
from core.pipeline import ResultEnvelope
from mail.accounts.pipeline_list import AccountInfo, AccountsListProducer, AccountsListResult
from mail.accounts.pipeline_list_export import (
    AccountsExportFiltersProducer,
    AccountsExportFiltersResult,
    AccountsExportLabelsProducer,
    AccountsExportLabelsResult,
    ExportedFiltersInfo,
    ExportedLabelsInfo,
)
from mail.accounts.pipeline_list_plan import (
    AccountsPlanFiltersProducer,
    AccountsPlanFiltersResult,
    AccountsPlanLabelsProducer,
    AccountsPlanLabelsResult,
    FiltersPlanInfo,
    LabelsPlanInfo,
)
from mail.accounts.pipeline_list_signatures import (
    AccountsExportSignaturesProducer,
    AccountsExportSignaturesResult,
    AccountsSyncSignaturesProducer,
    AccountsSyncSignaturesResult,
    ExportedSignaturesInfo,
    SyncedSignaturesInfo,
)
from mail.accounts.pipeline_list_sync import (
    AccountsSyncFiltersProducer,
    AccountsSyncFiltersResult,
    AccountsSyncLabelsProducer,
    AccountsSyncLabelsResult,
    SyncedFiltersInfo,
    SyncedLabelInfo,
)
from mail.config_cli.pipeline_cache import (
    AuthProducer,
    AuthResult,
    BackupProducer,
    BackupResult,
    CacheClearProducer,
    CacheClearResult,
    CachePruneProducer,
    CachePruneResult,
    CacheStatsProducer,
    CacheStatsResult,
    ConfigInspectProducer,
    ConfigInspectResult,
    ConfigSection,
)


@dataclass
class _Case:
    name: str
    make: Callable[[OutputWriter], Any]
    payload: Any
    expected: list[str]


_CASES = [
    # --- mail/config_cli/pipeline_cache.py ---
    _Case("auth", AuthProducer, AuthResult(success=True, message="auth ok"), ["auth ok"]),
    _Case(
        "backup", BackupProducer,
        BackupResult(out_path="b.yaml", labels_count=1, filters_count=2),
        ["Backup written to b.yaml"],
    ),
    _Case(
        "cache-stats", CacheStatsProducer,
        CacheStatsResult(path="c", files=3, size_bytes=10),
        ["Cache: c files=3 size=10 bytes"],
    ),
    _Case("cache-clear", CacheClearProducer, CacheClearResult(path="c", cleared=True), ["Cleared cache: c"]),
    _Case(
        "cache-clear-missing", CacheClearProducer,
        CacheClearResult(path="c", cleared=False), ["Cache does not exist."],
    ),
    _Case(
        "cache-prune", CachePruneProducer,
        CachePruneResult(path="c", removed=4, days=7),
        ["Pruned 4 files older than 7 days from c"],
    ),
    _Case(
        "config-inspect", ConfigInspectProducer,
        ConfigInspectResult(sections=[ConfigSection(name="mail.x", items=[("user", "me")])]),
        ["[mail.x]", "user = me", ""],
    ),
    # --- mail/accounts/pipeline_list*.py ---
    _Case(
        "accounts-list", lambda w: AccountsListProducer(writer=w),
        AccountsListResult(accounts=[AccountInfo(name="a", provider="gmail", credentials="c", token="t")]),  # nosec B106 - token file path fixture, not a secret
        ["a\tprovider=gmail\tcred=c\ttoken=t"],
    ),
    _Case(
        "export-labels", lambda w: AccountsExportLabelsProducer(writer=w),
        AccountsExportLabelsResult(exports=[ExportedLabelsInfo("a", "l.yaml", 1)]),
        ["Exported labels for a: l.yaml"],
    ),
    _Case(
        "export-filters", lambda w: AccountsExportFiltersProducer(writer=w),
        AccountsExportFiltersResult(exports=[ExportedFiltersInfo("a", "f.yaml", 1)]),
        ["Exported filters for a: f.yaml"],
    ),
    _Case(
        "plan-labels", lambda w: AccountsPlanLabelsProducer(writer=w),
        AccountsPlanLabelsResult(plans=[LabelsPlanInfo("a", "gmail", 1, 2)]),
        ["[plan-labels] a provider=gmail create=1 update=2"],
    ),
    _Case(
        "plan-filters", lambda w: AccountsPlanFiltersProducer(writer=w),
        AccountsPlanFiltersResult(plans=[FiltersPlanInfo("a", "gmail", -1), FiltersPlanInfo("b", "gmail", 3)]),
        ["[plan-filters] a provider=gmail not supported", "[plan-filters] b provider=gmail create=3"],
    ),
    _Case(
        "export-signatures", lambda w: AccountsExportSignaturesProducer(writer=w),
        AccountsExportSignaturesResult(exports=[ExportedSignaturesInfo("a", "gmail", "s.yaml", 1)]),
        ["Exported signatures for a: s.yaml"],
    ),
    _Case(
        "sync-signatures", lambda w: AccountsSyncSignaturesProducer(writer=w),
        AccountsSyncSignaturesResult(synced=[
            SyncedSignaturesInfo("a", "outlook", "delegated"),
            SyncedSignaturesInfo("b", "ios", "wrote_guidance"),
            SyncedSignaturesInfo("c", "gmail", "updated"),
        ]),
        [
            "[signatures sync] a provider=outlook (delegated)",
            f"[signatures sync] b provider=ios wrote guidance to {Path('data-home', 'signatures_assets')}",
            "[signatures sync] c provider=gmail status=updated",
        ],
    ),
    _Case(
        "sync-labels", lambda w: AccountsSyncLabelsProducer(dry_run=True, writer=w),
        AccountsSyncLabelsResult(synced=[SyncedLabelInfo("a", "gmail", 1, 2)]),
        ["[labels sync] a provider=gmail would created=1 updated=2"],
    ),
    _Case(
        "sync-filters", lambda w: AccountsSyncFiltersProducer(dry_run=True, writer=w),
        AccountsSyncFiltersResult(synced=[SyncedFiltersInfo("a", "outlook", -1, 0), SyncedFiltersInfo("b", "gmail", 2, 1)]),
        ["[filters sync] a provider=outlook (delegated)", "[filters sync] b provider=gmail would created=2 errors=1"],
    ),
]


class TestProducersUseInjectedWriter(unittest.TestCase):
    def test_every_migrated_producer_writes_to_injected_writer_only(self):
        for case in _CASES:
            with self.subTest(case.name):
                buf = io.StringIO()
                stdout = io.StringIO()
                producer = case.make(OutputWriter(OutputConfig(file=buf)))
                with patch(
                    "mail.accounts.pipeline_list_signatures.output_dir",
                    return_value=Path("data-home"),
                ), redirect_stdout(stdout):
                    producer.produce(ResultEnvelope(status="success", payload=case.payload))
                self.assertEqual(stdout.getvalue(), "")
                self.assertEqual(buf.getvalue().split("\n")[:-1], case.expected)


if __name__ == "__main__":
    unittest.main()
