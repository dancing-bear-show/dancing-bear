"""Tests for the qwen_patch memory precheck: how headroom is measured, and
the smaller requirement when Ollama already has the model loaded.

Measurement tests patch the per-command seams (_memory_pressure_output,
_vm_stat_output, _total_memory_bytes); no real memory_pressure or vm_stat
runs. Warm-model tests go through QwenHandlerCase, whose urlopen router
serves /api/ps from self.ps_response, so the real _ollama_ps transport runs.
"""

from __future__ import annotations

import os
import subprocess  # nosec B404 - only CompletedProcess/TimeoutExpired values, nothing is executed
import unittest
import urllib.error
import unittest.mock as mock

from worker import qwen
from tests.worker_tests.qwen_fixtures import GIB, MODEL, QwenHandlerCase

# vm_stat as measured on a healthy 32 GB Apple silicon Mac (2026-09-23).
_PAGE = 16384
_FREE, _ACTIVE, _INACTIVE, _SPECULATIVE = 373844, 234049, 350556, 3876
_WIRED, _PURGEABLE, _FILE_BACKED = 280504, 11837, 329220
VM_STAT_TODAY = (
    f"Mach Virtual Memory Statistics: (page size of {_PAGE} bytes)\n"
    f"Pages free:                             {_FREE}.\n"
    f"Pages active:                           {_ACTIVE}.\n"
    f"Pages inactive:                         {_INACTIVE}.\n"
    f"Pages speculative:                        {_SPECULATIVE}.\n"
    "Pages throttled:                               0.\n"
    f"Pages wired down:                       {_WIRED}.\n"
    f"Pages purgeable:                         {_PURGEABLE}.\n"
    "Pages purged:                              12345.\n"
    f"File-backed pages:                      {_FILE_BACKED}.\n"
)
TOTAL_32_GIB = 32 * GIB
MEMORY_PRESSURE_TODAY = (
    f"The system has {TOTAL_32_GIB} (2097152 pages with a page size of {_PAGE}).\n"
    "System-wide memory free percentage: 47%\n"
)
FULL_REQUIREMENT = (qwen.THRESHOLDS.model_resident_gb + qwen.THRESHOLDS.memory_margin_gb) * GIB
VM_STAT_WITH_PURGEABLE = (_FREE + _INACTIVE + _SPECULATIVE + _PURGEABLE) * _PAGE


class QwenMemoryMeasurementTests(unittest.TestCase):
    """_available_memory_bytes: memory_pressure first, vm_stat fallback, then None."""

    def measure(
        self, pressure: str | None, vm_stat: str | None, total: int | None = TOTAL_32_GIB
    ) -> int | None:
        with (
            mock.patch("worker.qwen._memory_pressure_output", return_value=pressure),
            mock.patch("worker.qwen._vm_stat_output", return_value=vm_stat),
            mock.patch("worker.qwen._total_memory_bytes", return_value=total),
        ):
            return qwen._available_memory_bytes()

    def test_todays_reading_passes_where_vm_stat_alone_deferred(self) -> None:
        old_vm_stat_reading = (_FREE + _INACTIVE + _SPECULATIVE) * _PAGE
        self.assertLess(old_vm_stat_reading, FULL_REQUIREMENT, "the old formula is why the guard deferred")

        available = self.measure(MEMORY_PRESSURE_TODAY, VM_STAT_TODAY)

        self.assertEqual(available, TOTAL_32_GIB * 47 // 100)
        with (
            mock.patch("worker.qwen._available_memory_bytes", return_value=available),
            mock.patch("worker.qwen._model_loaded") as loaded,
        ):
            self.assertIsNone(qwen._check_memory_guard(qwen.DEFAULT_OLLAMA_HOST, MODEL))
        loaded.assert_not_called()

    def test_memory_pressure_missing_falls_back_to_vm_stat_with_purgeable(self) -> None:
        self.assertEqual(self.measure(None, VM_STAT_TODAY), VM_STAT_WITH_PURGEABLE)

    def test_unparseable_memory_pressure_falls_back_to_vm_stat(self) -> None:
        for garbage in ("", "memory_pressure: unexpected output\n", "System-wide memory free percentage: 250%\n"):
            with self.subTest(garbage=garbage):
                self.assertEqual(self.measure(garbage, VM_STAT_TODAY), VM_STAT_WITH_PURGEABLE)

    def test_unknown_total_memory_falls_back_to_vm_stat(self) -> None:
        self.assertEqual(self.measure(MEMORY_PRESSURE_TODAY, VM_STAT_TODAY, total=None), VM_STAT_WITH_PURGEABLE)

    def test_zero_percent_free_is_a_reading_not_a_fallback(self) -> None:
        zero = "System-wide memory free percentage: 0%\n"
        self.assertEqual(self.measure(zero, VM_STAT_TODAY), 0)

    def test_both_sources_missing_returns_none(self) -> None:
        self.assertIsNone(self.measure(None, None))
        self.assertIsNone(self.measure("garbage", "garbage"))

    def test_parse_vm_stat_counts_purgeable_pages(self) -> None:
        self.assertEqual(qwen._parse_vm_stat(VM_STAT_TODAY), VM_STAT_WITH_PURGEABLE)

    def test_run_probe_returns_none_when_the_command_is_missing_or_fails(self) -> None:
        done = subprocess.CompletedProcess
        cases: tuple[tuple[str, BaseException | None, object, str | None], ...] = (
            ("missing", FileNotFoundError("memory_pressure"), None, None),
            ("timeout", subprocess.TimeoutExpired(["memory_pressure"], 5), None, None),
            ("nonzero", None, done([], 1, stdout="x", stderr=""), None),
            ("ok", None, done([], 0, stdout="out", stderr=""), "out"),
        )
        for name, error, completed, expected in cases:
            with self.subTest(name), mock.patch("subprocess.run", side_effect=error, return_value=completed) as run:
                self.assertEqual(qwen._run_probe(["memory_pressure", "-Q"]), expected)
                self.assertEqual(run.call_args.args[0], ["memory_pressure", "-Q"])
                self.assertNotIn("shell", run.call_args.kwargs)

    def test_seams_run_fixed_argv(self) -> None:
        with mock.patch("worker.qwen._run_probe", return_value="x") as probe:
            qwen._memory_pressure_output()
            qwen._vm_stat_output()
        self.assertEqual([c.args[0] for c in probe.call_args_list], [["memory_pressure", "-Q"], ["vm_stat"]])

    def test_total_memory_is_page_size_times_physical_pages(self) -> None:
        sizes = {"SC_PAGE_SIZE": _PAGE, "SC_PHYS_PAGES": 2097152}
        with mock.patch("os.sysconf", side_effect=sizes.__getitem__):
            self.assertEqual(qwen._total_memory_bytes(), TOTAL_32_GIB)
        with mock.patch("os.sysconf", side_effect=ValueError("unsupported")):
            self.assertIsNone(qwen._total_memory_bytes())


class QwenWarmModelTests(QwenHandlerCase):
    """A model Ollama already holds needs only memory_margin_gb, not the full load."""

    FIVE_GIB = 5 * GIB

    def ps_requests(self) -> list[str]:
        return [r[0] for r in self.requests if r[0].endswith("/api/ps")]

    def run_with_memory(self, available: int | None, payload: dict[str, object] | None = None) -> tuple[bool, object]:
        with mock.patch("worker.qwen._available_memory_bytes", return_value=available):
            return self.run_handler(payload)

    def test_warm_model_with_five_gib_proceeds(self) -> None:
        self.ps_response = {"models": [{"name": MODEL, "model": MODEL}]}

        ok, _ = self.run_with_memory(self.FIVE_GIB)

        self.assertTrue(ok)
        self.assertEqual(len(self.generate_requests()), 1)
        self.assertEqual(self.ps_requests(), ["http://localhost:11434/api/ps"])

    def test_cold_model_with_the_same_five_gib_defers(self) -> None:
        ok, out = self.run_with_memory(self.FIVE_GIB)

        self.assertEqual((ok, out), (False, "deferred-low-memory"))
        self.assertEqual(self.generate_requests(), [])
        self.assertEqual(len(self.ps_requests()), 1)

    def test_unreadable_ps_keeps_the_full_requirement(self) -> None:
        cases: tuple[tuple[str, str, object], ...] = (
            ("unreachable", "ps_error", urllib.error.URLError("connection refused")),
            ("non-json body", "ps_raw", b"<html>proxy error</html>"),
            ("models not a list", "ps_response", {"models": MODEL}),
            ("no models key", "ps_response", {}),
            ("entry not a dict", "ps_response", {"models": [MODEL]}),
        )
        for name, attr, value in cases:
            with self.subTest(name):
                self.ps_error, self.ps_raw, self.ps_response = None, None, {"models": []}
                setattr(self, attr, value)
                ok, out = self.run_with_memory(self.FIVE_GIB, {"model": MODEL})
                self.assertEqual((ok, out), (False, "deferred-low-memory"))
        self.assertEqual(self.generate_requests(), [])

    def test_a_different_loaded_model_is_not_warm(self) -> None:
        self.ps_response = {"models": [{"name": "llama3:8b", "model": "llama3:8b"}]}

        ok, out = self.run_with_memory(self.FIVE_GIB)

        self.assertEqual((ok, out), (False, "deferred-low-memory"))
        self.assertEqual(self.generate_requests(), [])

    def test_payload_model_and_configured_host_are_the_ones_checked(self) -> None:
        os.environ["QWEN_OLLAMA_HOST"] = "http://127.0.0.1:9999"
        self.ps_response = {"models": [{"name": "llama3:8b", "model": "llama3:8b"}]}

        ok, report = self.run_with_memory(self.FIVE_GIB, {"model": "llama3:8b", "explain": True})
        self.assertTrue(ok)
        self.assertEqual(self.as_dict(self.as_dict(report)["memory_detail"])["requirement"], "margin_only")

        ok, _ = self.run_with_memory(self.FIVE_GIB, {"model": "llama3:8b"})

        self.assertTrue(ok)
        self.assertEqual(self.ps_requests(), ["http://127.0.0.1:9999/api/ps"] * 2)

    def test_warm_model_below_the_margin_still_defers(self) -> None:
        self.ps_response = {"models": [{"name": MODEL, "model": MODEL}]}

        ok, out = self.run_with_memory(3 * GIB)

        self.assertEqual((ok, out), (False, "deferred-low-memory"))
        self.assertEqual(self.ps_requests(), [], "below the margin, whether the model is loaded cannot matter")

    def test_ample_memory_does_not_query_ps(self) -> None:
        ok, _ = self.run_with_memory(64 * GIB)

        self.assertTrue(ok)
        self.assertEqual(self.ps_requests(), [])

    def test_explain_and_real_run_reach_the_same_decision(self) -> None:
        warm: dict[str, object] = {"models": [{"name": MODEL, "model": MODEL}]}
        full_gb = qwen.THRESHOLDS.model_resident_gb + qwen.THRESHOLDS.memory_margin_gb
        cases: tuple[tuple[str, int | None, dict[str, object], str, dict[str, object]], ...] = (
            ("warm", self.FIVE_GIB, warm, "pass", {"requirement": "margin_only", "required_gb": 4, "available_gb": 5.0}),
            (
                "cold",
                self.FIVE_GIB,
                {"models": []},
                "deferred-low-memory",
                {"requirement": "model_resident+margin", "required_gb": full_gb, "available_gb": 5.0},
            ),
            (
                "ample",
                64 * GIB,
                {"models": []},
                "pass",
                {"requirement": "model_resident+margin", "required_gb": full_gb, "available_gb": 64.0},
            ),
            ("unreadable", None, {"models": []}, "pass", {"requirement": "unguarded", "required_gb": None, "available_gb": None}),
        )
        for name, available, ps, verdict, detail in cases:
            with self.subTest(name):
                self.ps_response = ps
                ok, report = self.run_with_memory(available, {"explain": True})
                self.assertTrue(ok)
                report = self.as_dict(report)
                self.assertEqual(self.as_dict(report["guard_results"])["memory"], verdict)
                self.assertEqual(report["memory_detail"], detail)

                ok, out = self.run_with_memory(available)
                self.assertEqual(ok, verdict == "pass")
                if not ok:
                    self.assertEqual(out, verdict)
                self.deferral_file().unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
