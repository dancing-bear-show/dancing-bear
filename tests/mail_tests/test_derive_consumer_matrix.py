"""Parametrized matrix test: derive → consumer contract for Outlook filter rules.

Covers the six-axis input space (64 cells) that was the site of 13 defects across
10 review rounds for the keepInInbox feature.  Each defect was an individually-correct
module with a broken seam; most would have been caught by a single cell of this matrix.

Axes:
  add            -- action.add: [Tech/Grafana] present or absent
  remove_inbox   -- action.remove: [INBOX] present or absent
  marker         -- action.keepInInbox: true present or absent
  authored       -- action.moveToFolder: Explicit/Dest present or absent (explicit path)
  archive_flag   -- DeriveFiltersRequest.outlook_archive_on_remove_inbox
  move_flag      -- DeriveFiltersRequest.outlook_move_to_folders

For each cell the test:
  1. Runs the REAL DeriveFiltersProcessor.
  2. Feeds derived specs into all three REAL consumers: _build_rule_action (sync),
     _build_plan_action (plan), _resolve_destination_folder (sweep).
  3. Asserts the cross-consumer invariants documented below.

Mock strategy
-------------
Sync (_build_rule_action) resolves folders via client.ensure_folder_path().
Plan (_build_plan_action) resolves via folder_map dict lookup.
Sweep (_resolve_destination_folder) resolves via folder_paths dict on dry_run=True.

To make "plan and sync agree on destination" testable without string games, the
mock is wired so that ensure_folder_path returns the same id that folder_map holds
for the same path.  The folder_map is pre-populated for the derived folder
(Tech/Grafana), the authored folder (Explicit/Dest), and Archive; ensure_folder_path
returns the matching value via a side_effect lambda.  When both sides resolve the
same path to the same id the equality assertion is meaningful — a divergence means
the two consumers disagree on what rule sync will actually create.
"""
from __future__ import annotations

import itertools
from pathlib import Path
from typing import Any
from unittest import TestCase
from unittest.mock import MagicMock, patch

from tests.fixtures import TempDirMixin
from mail.config_cli.pipeline_derive import (
    DeriveFiltersProcessor,
    DeriveFiltersRequest,
)
from mail.outlook.processors_rules_helpers import (
    RuleContext,
    _build_plan_action,
    _build_rule_action,
    _resolve_destination_folder,
)

# Folder ids used in mock wiring.  The same string appears in folder_map and as the
# return value of ensure_folder_path for the same path, making plan/sync comparable.
_FOLDER_ID_GRAFANA = "fid-tech-grafana"
_FOLDER_ID_EXPLICIT = "fid-explicit-dest"
_FOLDER_ID_ARCHIVE = "fid-archive"

# Folder paths present in the test config
_PATH_GRAFANA = "Tech/Grafana"
_PATH_EXPLICIT = "Explicit/Dest"
_PATH_ARCHIVE = "Archive"

# label-id for the categorise-only path (no folder move)
_LABEL_ID_GRAFANA = "label-tech-grafana"

# Pre-built folder_map shared by all contexts.  ensure_folder_path returns the
# matching value so plan and sync return the same id for the same path.
_FOLDER_MAP: dict[str, str] = {
    _PATH_GRAFANA: _FOLDER_ID_GRAFANA,
    _PATH_EXPLICIT: _FOLDER_ID_EXPLICIT,
    _PATH_ARCHIVE: _FOLDER_ID_ARCHIVE,
}

_NAME_TO_ID: dict[str, str] = {
    _PATH_GRAFANA: _LABEL_ID_GRAFANA,
}

_AXES = ("add", "remove_inbox", "marker", "authored", "archive_flag", "move_flag")


def _make_client() -> MagicMock:
    """Return a mock client whose ensure_folder_path uses the shared folder_map."""
    client = MagicMock()
    client.ensure_folder_path.side_effect = lambda path: _FOLDER_MAP.get(path, path)
    return client


def _make_ctx(move_flag: int, client: MagicMock) -> RuleContext:
    return RuleContext(
        client=client,
        name_to_id=_NAME_TO_ID,
        folder_map=_FOLDER_MAP,
        move_to_folders=bool(move_flag),
    )


def _build_unified_filter(
    add: int, remove_inbox: int, marker: int, authored: int
) -> dict[str, Any]:
    """Build a unified filter dict for the given axis values."""
    action: dict[str, Any] = {}
    if add:
        action["add"] = [_PATH_GRAFANA]
    if remove_inbox:
        action["remove"] = ["INBOX"]
    if marker:
        action["keepInInbox"] = True
    if authored:
        action["moveToFolder"] = _PATH_EXPLICIT
    return {
        "match": {"from": "grafana.com"},
        "action": action,
    }


def _run_derive(
    tmpdir: str,
    unified_filter: dict[str, Any],
    archive_flag: int,
    move_flag: int,
) -> list[dict]:
    """Run DeriveFiltersProcessor and return the derived Outlook filter list."""
    import yaml  # noqa: PLC0415 - lazy; yaml is an optional dep

    in_path = Path(tmpdir) / "filters.yaml"
    in_path.write_text(yaml.safe_dump({"filters": [unified_filter]}))
    out_gmail = Path(tmpdir) / "g.yaml"
    out_outlook = Path(tmpdir) / "o.yaml"

    result = DeriveFiltersProcessor().process(
        DeriveFiltersRequest(
            in_path=str(in_path),
            out_gmail=str(out_gmail),
            out_outlook=str(out_outlook),
            outlook_archive_on_remove_inbox=bool(archive_flag),
            outlook_move_to_folders=bool(move_flag),
        )
    )
    if not result.ok():
        raise AssertionError(f"derive failed: {result}")
    raw = yaml.safe_load(out_outlook.read_text())
    return raw.get("filters") or []


class OutlookDeriveConsumerMatrixTests(TempDirMixin, TestCase):
    """Parametrized 6-axis matrix test for the derive → consumer seam.

    Most of the 13 defects found during the keepInInbox series were single cells
    in this matrix: an individually-correct module whose contract with the next
    stage was wrong for exactly one combination of inputs.  This class runs all
    64 cells and asserts the cross-consumer invariants, so a regression in any
    seam names the broken cell rather than failing an unrelated integration test
    or going undetected until mail is moved out of the inbox.

    The tmpdir from TempDirMixin is reused across cells (the YAML files are
    overwritten on each iteration) rather than creating a new TemporaryDirectory
    per subTest, cutting I/O cost from 64 mkdtemp/rmtree round-trips to one.
    """

    def _run_all_consumers(
        self,
        derived: list[dict],
        move_flag: int,
    ) -> list[dict]:
        """Run all three consumers on each derived spec and return per-spec results.

        Returns a list of dicts, one per derived spec, each containing:
          sync_action  -- dict returned by _build_rule_action
          plan_action  -- dict returned by _build_plan_action
          sweep_dest   -- str | None returned by _resolve_destination_folder (dry_run=True)
          action_spec  -- the raw action dict from the derived spec
        """
        client = _make_client()
        ctx = _make_ctx(move_flag, client)
        results = []
        for spec in derived:
            action_spec = spec.get("action") or {}
            sync_action = _build_rule_action(action_spec, ctx)
            plan_action = _build_plan_action(action_spec, ctx)
            sweep_dest = _resolve_destination_folder(
                action_spec,
                move_to_folders=bool(move_flag),
                folder_paths=_FOLDER_MAP,
                client=client,
                dry_run=True,
            )
            results.append(
                {
                    "sync_action": sync_action,
                    "plan_action": plan_action,
                    "sweep_dest": sweep_dest,
                    "action_spec": action_spec,
                }
            )
        return results

    def _assert_no_actionless_specs(self, derived: list[dict], label: str) -> None:
        """Invariant 4: every derived spec must carry at least one actionable key.

        An empty action creates create_filter(criteria, {}), and create_filter sets
        stopProcessingRules: True unconditionally (core/outlook/_mail_labels.py:202) —
        a rule that matches mail, does nothing, and halts every later inbox rule.
        """
        _ACTIONABLE = ("add", "forward", "moveToFolder")
        for spec in derived:
            action = spec.get("action") or {}
            self.assertTrue(
                any(action.get(k) for k in _ACTIONABLE),
                f"{label}: derived spec reached consumers with no actionable key: {spec}",
            )

    def _assert_no_marker_leak(
        self, sync_action: dict, plan_action: dict, label: str
    ) -> None:
        """Invariant 5: no internal marker key in consumer output.

        keepInInbox and noMoveToFolder are internal pipeline fields that must never
        reach the Graph API.
        """
        for key in ("keepInInbox", "noMoveToFolder"):
            self.assertNotIn(
                key, sync_action,
                f"{label}: '{key}' leaked into sync action: {sync_action!r}",
            )
            self.assertNotIn(
                key, plan_action,
                f"{label}: '{key}' leaked into plan action: {plan_action!r}",
            )

    def _assert_consumer_agreement(
        self,
        sync_action: dict,
        plan_action: dict,
        sweep_dest: str | None,
        label: str,
    ) -> None:
        """Invariant 3: plan, sync, and sweep agree on whether a move happens and on destination.

        This is the primary guard for defect 9 (sweep --dry-run reporting zero moves while
        the live run moved mail).  The mock wires ensure_folder_path to return the same id
        as folder_map, so the comparison is meaningful.
        """
        sync_moves = "moveToFolderId" in sync_action
        plan_moves = "moveToFolderId" in plan_action
        sweep_moves = sweep_dest is not None

        self.assertEqual(
            sync_moves, plan_moves,
            f"{label}: sync says move={sync_moves} but plan says move={plan_moves}; "
            f"sync={sync_action!r} plan={plan_action!r}",
        )
        self.assertEqual(
            sync_moves, sweep_moves,
            f"{label}: sync says move={sync_moves} but sweep says move={sweep_moves}; "
            f"sync={sync_action!r} sweep_dest={sweep_dest!r}",
        )
        if sync_moves:
            sync_dest = sync_action["moveToFolderId"]
            plan_dest = plan_action["moveToFolderId"]
            self.assertEqual(
                sync_dest, plan_dest,
                f"{label}: sync folder={sync_dest!r} differs from plan folder={plan_dest!r}",
            )
            self.assertEqual(
                sync_dest, sweep_dest,
                f"{label}: sync folder={sync_dest!r} differs from sweep folder={sweep_dest!r}",
            )

    def _assert_marker_and_authored(
        self, cell: dict[str, int], sync_action: dict, plan_action: dict,
        sweep_dest: str | None, label: str,
    ) -> None:
        """Invariants 1 and 2: marker suppression and authored destination override.

        Invariant 1: marker=1, authored=0 ⇒ no folder move from any consumer.
        Invariant 2: authored=1 ⇒ consumers target Explicit/Dest (or Archive when the
        archive branch legitimately overwrites it: archive_flag=1, remove_inbox=1, marker=0).
        """
        marker = cell["marker"]
        authored = cell["authored"]
        sync_moves = "moveToFolderId" in sync_action
        plan_moves = "moveToFolderId" in plan_action
        sweep_moves = sweep_dest is not None

        if marker and not authored:
            self.assertFalse(
                sync_moves,
                f"{label}: marker=1 authored=0 but sync produced a folder move: {sync_action!r}",
            )
            self.assertFalse(
                plan_moves,
                f"{label}: marker=1 authored=0 but plan produced a folder move: {plan_action!r}",
            )
            self.assertFalse(
                sweep_moves,
                f"{label}: marker=1 authored=0 but sweep returned a destination: {sweep_dest!r}",
            )

        # _apply_archive_on_remove_inbox rewrites the destination to Archive even when
        # an explicit moveToFolder was authored, because that branch unconditionally sets
        # a["moveToFolder"] = "Archive".  This is the documented contract for the flag.
        archive_overrides = bool(
            cell.get("archive_flag") and cell.get("remove_inbox") and not cell.get("marker")
        )
        if authored and sync_moves:
            expected = _FOLDER_ID_ARCHIVE if archive_overrides else _FOLDER_ID_EXPLICIT
            self.assertEqual(
                expected, sync_action["moveToFolderId"],
                f"{label}: authored=1, expected dest {expected!r} but "
                f"sync has {sync_action['moveToFolderId']!r}",
            )

    def _assert_invariants(
        self,
        cell: dict[str, int],
        derived: list[dict],
        consumer_results: list[dict],
        label: str,
    ) -> None:
        """Assert all five invariants for one matrix cell.

        Delegates to focused helpers to keep cognitive complexity tractable.  See
        each helper's docstring for the invariant it enforces.
        """
        self._assert_no_actionless_specs(derived, label)
        for r in consumer_results:
            sync_action = r["sync_action"]
            plan_action = r["plan_action"]
            sweep_dest = r["sweep_dest"]
            self._assert_no_marker_leak(sync_action, plan_action, label)
            self._assert_consumer_agreement(sync_action, plan_action, sweep_dest, label)
            self._assert_marker_and_authored(cell, sync_action, plan_action, sweep_dest, label)

    def test_all_64_cells(self) -> None:
        """Run all 64 cells of the derive → consumer matrix and assert invariants.

        Six binary axes: add, remove_inbox, marker, authored, archive_flag, move_flag.
        Each cell builds a unified YAML config, runs the full derive pipeline, then
        passes every derived spec through all three Outlook consumers (sync, plan,
        sweep).  An empty derived list (some marker combinations yield no specs) is a
        valid, asserted outcome.

        A subTest failure message names the exact cell, e.g.:
          add=1 remove_inbox=0 marker=1 authored=0 archive_flag=0 move_flag=1
        so a regression is immediately locatable without reading a full traceback.
        """
        for values in itertools.product((0, 1), repeat=6):
            cell = dict(zip(_AXES, values))
            add, remove_inbox, marker, authored, archive_flag, move_flag = values
            with self.subTest(**cell):
                label = " ".join(f"{k}={v}" for k, v in cell.items())
                unified = _build_unified_filter(add, remove_inbox, marker, authored)
                derived = _run_derive(self.tmpdir, unified, archive_flag, move_flag)
                consumer_results = self._run_all_consumers(derived, move_flag)
                self._assert_invariants(cell, derived, consumer_results, label)


# ---------------------------------------------------------------------------
# Proof-of-teeth: verify the matrix catches two real regressions.
#
# `OutlookMatrixTeethProofTests` below is an ordinary TestCase: discovery loads
# it, it runs in `make test` and in CI, and it PASSES. Each of its tests
# monkeypatches one fix back to its pre-fix state, runs the 64-cell matrix with
# failures captured rather than raised, and asserts at least one cell failed —
# so a green run means the matrix still has teeth for that regression. Nothing
# in src/ is touched, so `git diff src/` stays empty.
#
# It subclasses the matrix case to reuse the fixtures, which means the 64-cell
# test runs a second time here against the real code. That is a few hundred
# milliseconds and a genuine second execution, not a skipped one.
#
# Monkeypatching proves the matrix catches a *reimplementation* of each bug. The
# stronger check — reverting the real guard in src/ and confirming the matrix
# fails naming the affected cells — was done by hand before this file landed;
# it cannot live in the suite without a test that edits source.
# ---------------------------------------------------------------------------

def _broken_apply_archive_without_keepinbox_guard(
    out_specs: list, filters: list
) -> None:
    """Reproduce the pre-fix _apply_archive_on_remove_inbox that lacked the
    keepInInbox guard.  Without the guard, a rule with remove: [INBOX] and
    keepInInbox: true was still archived, violating the 'marker suppresses
    derived destinations' contract.
    """
    from mail.config_cli.pipeline_derive import _pair_specs_with_sources

    for spec, orig in _pair_specs_with_sources(out_specs, filters):
        orig_action = (orig or {}).get("action") or {}
        remove_list = orig_action.get("remove") or []
        if isinstance(remove_list, list) and any(
            str(x).upper() == "INBOX" for x in remove_list
        ):
            a = spec.get("action") or {}
            a["moveToFolder"] = "Archive"
            a.pop("add", None)
            spec["action"] = a


def _broken_apply_archive_never_sets_no_move(out_specs: list) -> None:
    """Reproduce pre-fix _apply_move_to_folders that lacked the keepInInbox check.
    Without it, rules marked keepInInbox get a moveToFolder derived from add[0],
    violating the marker's promise to leave mail in the inbox.
    """
    for spec in out_specs:
        a = spec.get("action") or {}
        adds = a.get("add") or []
        if adds and not a.get("moveToFolder"):  # missing: and not a.get("keepInInbox")
            a["moveToFolder"] = str(adds[0])
            spec["action"] = a


class OutlookMatrixTeethProofTests(OutlookDeriveConsumerMatrixTests):
    """Proof that the matrix catches two real regressions when they are
    monkeypatched back in.

    Each test patches a function to its pre-fix broken state, runs the 64-cell
    matrix logic (capturing failures instead of raising them), and asserts that
    at least one cell DID fail.  If the assertion holds, the matrix has teeth
    for that regression.

    These tests PASS under normal conditions (the matrix correctly detects the
    regression when the broken code is patched in).  They inherit test_all_64_cells
    from the parent class and that test also runs here, passing with the real code.
    """

    def _run_matrix_with_patched_derive(self, patch_target: str, replacement: object) -> bool:
        """Run the full 64-cell matrix with a patched pipeline_derive function.

        Returns True if the matrix would FAIL (i.e., a regression was caught),
        False if it passes (i.e., the patch did not break anything, which would
        mean the test lacks teeth for this regression).
        """
        failures: list[str] = []

        with patch(patch_target, replacement):
            for values in itertools.product((0, 1), repeat=6):
                cell = dict(zip(_AXES, values))
                add, remove_inbox, marker, authored, archive_flag, move_flag = values
                label = " ".join(f"{k}={v}" for k, v in cell.items())
                unified = _build_unified_filter(add, remove_inbox, marker, authored)
                derived = _run_derive(self.tmpdir, unified, archive_flag, move_flag)
                consumer_results = self._run_all_consumers(derived, move_flag)
                try:
                    self._assert_no_actionless_specs(derived, label)
                    for r in consumer_results:
                        self._assert_no_marker_leak(r["sync_action"], r["plan_action"], label)
                        self._assert_consumer_agreement(
                            r["sync_action"], r["plan_action"], r["sweep_dest"], label
                        )
                        self._assert_marker_and_authored(
                            cell, r["sync_action"], r["plan_action"], r["sweep_dest"], label
                        )
                except AssertionError as exc:
                    failures.append(f"{label}: {exc}")

        return len(failures) > 0

    def test_matrix_catches_missing_keepinbox_guard_in_archive_branch(self) -> None:
        """The matrix must fail when _apply_archive_on_remove_inbox lacks the
        keepInInbox guard.

        Without the guard: a rule with remove: [INBOX] and keepInInbox: true is
        archived, moving mail the marker said to keep in the inbox.  This is
        invariant 1: marker=1 and authored=0 must never produce a folder move.
        """
        caught = self._run_matrix_with_patched_derive(
            "mail.config_cli.pipeline_derive._apply_archive_on_remove_inbox",
            _broken_apply_archive_without_keepinbox_guard,
        )
        self.assertTrue(
            caught,
            "Matrix should have caught the missing keepInInbox guard in the archive branch "
            "but all 64 cells passed — the test lacks teeth for this regression.",
        )

    def test_matrix_catches_move_to_folders_without_keepinbox_check(self) -> None:
        """The matrix must fail when _apply_move_to_folders lacks the keepInInbox guard.

        Without the guard: rules marked keepInInbox get a moveToFolder derived from
        add[0], violating invariant 1 (marker=1, authored=0 must never produce a move).
        This was the original defect that drove the entire 13-fix series.
        """
        caught = self._run_matrix_with_patched_derive(
            "mail.config_cli.pipeline_derive._apply_move_to_folders",
            _broken_apply_archive_never_sets_no_move,
        )
        self.assertTrue(
            caught,
            "Matrix should have caught the missing keepInInbox check in "
            "_apply_move_to_folders but all 64 cells passed — the test lacks teeth.",
        )
