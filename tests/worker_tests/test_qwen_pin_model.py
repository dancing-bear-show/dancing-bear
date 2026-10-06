"""Tests for the model digest pin record: qwen.record_model_pin and
qwen.check_model_pin, the library behind `qwen pin-model`.

The record path is the real recorded_digest_path(), resolved inside a temp
DANCING_BEAR_WORKER_STATE_DIR; GET /api/tags is stubbed (see PinRecordCase).
"""

from __future__ import annotations

import json
import os
import stat
import unittest
import unittest.mock as mock

from tests.worker_tests.qwen_fixtures import MODEL, RUNNING_DIGEST, PinRecordCase
from worker import qwen

OTHER_MODEL = "llama3:8b"
OTHER_DIGEST = "a" * 64
OLD_DIGEST = "b" * 64


class RecordModelPinWriteTests(PinRecordCase):
    def test_fresh_record_is_written_private_and_read_back(self) -> None:
        result = qwen.record_model_pin(MODEL)

        self.assertEqual(result.path, self.record_path)
        self.assertEqual(qwen.recorded_digest_path(), self.record_path)
        self.assertTrue(result.written)
        self.assertEqual(result.reason, "written")
        self.assertTrue(result.readback_ok)
        self.assertEqual(result.digest, RUNNING_DIGEST)
        self.assertEqual(self.read_record(), {MODEL: RUNNING_DIGEST})
        self.assertEqual(stat.S_IMODE(self.record_path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.record_path.parent.stat().st_mode), 0o700)

    def test_no_temp_file_is_left_beside_the_record(self) -> None:
        qwen.record_model_pin(MODEL)

        self.assertEqual(sorted(p.name for p in self.record_path.parent.iterdir()), ["model_digest.json"])

    def test_other_tags_are_kept_when_merging(self) -> None:
        self.write_record(json.dumps({OTHER_MODEL: OTHER_DIGEST, MODEL: OLD_DIGEST}))

        result = qwen.record_model_pin(MODEL)

        self.assertTrue(result.written)
        self.assertEqual(self.read_record(), {OTHER_MODEL: OTHER_DIGEST, MODEL: RUNNING_DIGEST})

    def test_already_current_record_is_not_rewritten(self) -> None:
        self.write_record(json.dumps({MODEL: RUNNING_DIGEST}))
        before = self.record_path.stat()

        with mock.patch.object(qwen, "_write_pin_record") as write:
            result = qwen.record_model_pin(MODEL)

        write.assert_not_called()
        self.assertFalse(result.written)
        self.assertEqual(result.reason, "already-current")
        self.assertEqual(self.record_path.stat().st_ino, before.st_ino)

    def test_already_current_compares_normalised_digests(self) -> None:
        self.write_record(json.dumps({MODEL: f"sha256:{RUNNING_DIGEST.upper()}"}))

        result = qwen.record_model_pin(MODEL)

        self.assertEqual(result.reason, "already-current")

    def test_uses_the_configured_ollama_host(self) -> None:
        with mock.patch.dict(os.environ, {qwen.OLLAMA_HOST_ENV: "http://gpu-box:11434"}):
            qwen.record_model_pin(MODEL)

        self.assertEqual(self.tags_hosts, ["http://gpu-box:11434"])

    def test_readback_mismatch_is_reported(self) -> None:
        """A write that does not land as intended must not report success."""

        def write_wrong(path: object, record: dict[str, object]) -> None:
            self.write_record(json.dumps({MODEL: OLD_DIGEST}))

        with mock.patch.object(qwen, "_write_pin_record", side_effect=write_wrong):
            result = qwen.record_model_pin(MODEL)

        self.assertTrue(result.written)
        self.assertFalse(result.readback_ok)


class RecordModelPinRefusalTests(PinRecordCase):
    def assert_refused_without_write(self, expected: str) -> None:
        with self.assertRaises(qwen.ModelPinError) as ctx:
            qwen.record_model_pin(MODEL)
        self.assertIn(expected, str(ctx.exception))

    def test_digest_unavailable_writes_nothing(self) -> None:
        cases: list[tuple[str, dict[str, object], BaseException | None]] = [
            ("ollama down", {}, ConnectionError("refused")),
            ("model not installed", {"models": [{"name": OTHER_MODEL, "digest": OTHER_DIGEST}]}, None),
            ("no digest field", {"models": [{"name": MODEL}]}, None),
        ]
        for label, response, error in cases:
            with self.subTest(label):
                self.tags_response, self.tags_error = response, error
                self.assert_refused_without_write("running digest unavailable")
                self.assertFalse(self.record_path.parent.exists())

    def test_symlinked_record_is_refused_and_target_untouched(self) -> None:
        target = self.state_dir / "elsewhere.json"
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps({OTHER_MODEL: OTHER_DIGEST}), encoding="utf-8")
        self.record_path.parent.mkdir(parents=True)
        os.symlink(target, self.record_path)

        self.assert_refused_without_write("unreadable digest record")

        self.assertTrue(self.record_path.is_symlink())
        self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {OTHER_MODEL: OTHER_DIGEST})

    def test_dangling_symlink_is_refused_and_not_created_through(self) -> None:
        target = self.state_dir / "planted.json"
        self.record_path.parent.mkdir(parents=True)
        os.symlink(target, self.record_path)

        self.assert_refused_without_write("unreadable digest record")

        self.assertFalse(target.exists())
        self.assertTrue(self.record_path.is_symlink())

    def test_non_regular_record_is_refused(self) -> None:
        self.record_path.mkdir(parents=True)

        self.assert_refused_without_write("unreadable digest record")

        self.assertTrue(self.record_path.is_dir())

    def test_fifo_record_is_refused(self) -> None:
        self.record_path.parent.mkdir(parents=True)
        os.mkfifo(self.record_path)

        self.assert_refused_without_write("unreadable digest record")

        self.assertTrue(stat.S_ISFIFO(os.lstat(self.record_path).st_mode))

    def test_invalid_existing_record_is_refused_and_untouched(self) -> None:
        for content, expected in (
            ("{not json", "not valid JSON"),
            ("[1, 2]", "not a JSON object"),
            ("null", "not a JSON object"),
        ):
            with self.subTest(content=content):
                self.write_record(content)
                self.assert_refused_without_write(expected)
                self.assertEqual(self.record_path.read_text(encoding="utf-8"), content)

    def test_symlinked_state_dir_is_refused(self) -> None:
        real = self.state_dir / "real-qwen"
        real.mkdir(parents=True)
        os.symlink(real, self.record_path.parent)

        # The parent-dir validation in record_model_pin now catches the symlink
        # before _write_pin_record is reached, raising "unreadable digest record".
        self.assert_refused_without_write("unreadable digest record")

        self.assertEqual(list(real.iterdir()), [])

    def test_symlinked_state_dir_refused_on_already_current_path(self) -> None:
        """already-current early return must not bypass the symlinked-parent check."""
        real = self.state_dir / "real-qwen"
        real.mkdir(parents=True)
        # Write the current digest directly into the real dir so _read_pin_record
        # (which follows the link) would find it and trigger the early return.
        (real / "model_digest.json").write_text(
            json.dumps({MODEL: RUNNING_DIGEST}), encoding="utf-8"
        )
        os.symlink(real, self.record_path.parent)

        self.assert_refused_without_write("unreadable digest record")

        # The target record must be untouched.
        self.assertEqual(
            json.loads((real / "model_digest.json").read_text(encoding="utf-8")),
            {MODEL: RUNNING_DIGEST},
        )

    def test_malformed_digest_writes_nothing(self) -> None:
        """An empty, whitespace-only, or non-hex digest from /api/tags is refused."""
        cases: list[tuple[str, str]] = [
            ("empty string", ""),
            ("whitespace only", "   "),
            ("too short hex", "9ec8abc123"),
            ("non-hex chars", "!" * 64),
            ("sha256 prefix wrong length", "sha256:" + "a" * 63),
        ]
        for label, bad_digest in cases:
            with self.subTest(label):
                self.tags_response = {"models": [{"name": MODEL, "digest": bad_digest}]}
                self.assert_refused_without_write("running digest unavailable")
                self.assertFalse(self.record_path.exists())

    def test_valid_digest_forms_are_accepted(self) -> None:
        """Bare 64-hex and sha256:<64-hex> forms both succeed."""
        for label, digest_value in (
            ("bare hex", RUNNING_DIGEST),
            ("sha256 prefix", f"sha256:{RUNNING_DIGEST}"),
        ):
            with self.subTest(label):
                self.record_path.unlink(missing_ok=True)
                self.tags_response = {"models": [{"name": MODEL, "digest": digest_value}]}
                result = qwen.record_model_pin(MODEL)
                self.assertTrue(result.written)

    def test_readback_error_returns_readback_ok_false_not_exception(self) -> None:
        """A ModelPinError during post-write readback must not escape record_model_pin."""

        original_read = qwen._read_pin_record
        call_count = [0]

        def flaky_read(path: object) -> dict[str, object]:
            call_count[0] += 1
            if call_count[0] > 1:  # first call is the pre-write read; fail the readback
                raise qwen.ModelPinError("simulated transient read error")
            return original_read(path)  # type: ignore[arg-type]

        with mock.patch.object(qwen, "_read_pin_record", side_effect=flaky_read):
            result = qwen.record_model_pin(MODEL)

        self.assertTrue(result.written)
        self.assertFalse(result.readback_ok)
        self.assertEqual(result.reason, "written")


class CheckModelPinTests(PinRecordCase):
    def test_statuses(self) -> None:
        cases: list[tuple[str, str | None, dict[str, object], str, str | None, str | None]] = [
            ("match", RUNNING_DIGEST, self.tags_response, "match", RUNNING_DIGEST, RUNNING_DIGEST),
            ("mismatch", OLD_DIGEST, self.tags_response, "mismatch", OLD_DIGEST, RUNNING_DIGEST),
            ("unpinned", None, self.tags_response, "unpinned", None, RUNNING_DIGEST),
            ("unverified", RUNNING_DIGEST, {"models": []}, "unverified", RUNNING_DIGEST, None),
        ]
        for label, recorded, tags, status, want_recorded, want_running in cases:
            with self.subTest(label):
                if recorded is None:
                    self.record_path.unlink(missing_ok=True)
                else:
                    self.write_record(json.dumps({MODEL: recorded}))
                self.tags_response = tags

                pin = qwen.check_model_pin(MODEL)

                self.assertEqual(pin.status, status)
                self.assertEqual(pin.recorded_digest, want_recorded)
                self.assertEqual(pin.running_digest, want_running)

    def test_check_never_writes(self) -> None:
        qwen.check_model_pin(MODEL)

        self.assertFalse(self.record_path.parent.exists())


if __name__ == "__main__":
    unittest.main()
