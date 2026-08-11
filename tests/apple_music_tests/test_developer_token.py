"""Tests for apple_music/developer_token.py minting and claim decoding."""

from __future__ import annotations

import base64
import json
import unittest

from core.cli_errors import ConfigError

from apple_music.developer_token import (
    MAX_TTL_DAYS,
    MAX_TTL_SECONDS,
    SECONDS_PER_DAY,
    decode_claims,
    mint_developer_token,
)

TEAM_ID = "TEAMID1234"
KEY_ID = "KEYID56789"


def _write_key(tmpdir) -> str:
    """Generate a P-256 key on disk, matching what Apple issues for MusicKit."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PrivateFormat,
    )

    key = ec.generate_private_key(ec.SECP256R1())
    pem = key.private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption())
    path = tmpdir / "AuthKey_TEST.p8"
    path.write_bytes(pem)
    return str(path)


class TestTtlBounds(unittest.TestCase):
    def test_max_ttl_days_stays_under_apples_cap(self):
        """MAX_TTL_DAYS must be usable: days * 86400 cannot exceed the second cap."""
        self.assertLessEqual(MAX_TTL_DAYS * SECONDS_PER_DAY, MAX_TTL_SECONDS)

    def test_one_day_past_the_cap_would_exceed_it(self):
        """Guards against MAX_TTL_DAYS drifting below the real limit."""
        self.assertGreater((MAX_TTL_DAYS + 1) * SECONDS_PER_DAY, MAX_TTL_SECONDS)


class TestMintDeveloperToken(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.key_path = _write_key(Path(self._tmp.name))

    def test_mints_a_three_segment_jwt(self):
        token = mint_developer_token(self.key_path, TEAM_ID, KEY_ID)
        self.assertEqual(len(token.split(".")), 3)

    def test_header_and_claims_match_apples_requirements(self):
        token = mint_developer_token(self.key_path, TEAM_ID, KEY_ID)
        header_segment = token.split(".")[0]
        header = json.loads(base64.urlsafe_b64decode(header_segment + "=="))
        self.assertEqual(header["alg"], "ES256")
        self.assertEqual(header["kid"], KEY_ID)

        claims = decode_claims(token)
        self.assertEqual(claims.team_id, TEAM_ID)
        self.assertEqual(claims.key_id, KEY_ID)
        self.assertFalse(claims.is_expired())

    def test_signature_is_raw_r_s_not_der(self):
        """JWS ES256 requires a 64-byte r||s signature; DER would be rejected by Apple."""
        signature = mint_developer_token(self.key_path, TEAM_ID, KEY_ID).split(".")[2]
        raw = base64.urlsafe_b64decode(signature + "=" * (-len(signature) % 4))
        self.assertEqual(len(raw), 64)

    def test_max_ttl_days_is_accepted(self):
        token = mint_developer_token(
            self.key_path, TEAM_ID, KEY_ID, ttl_seconds=MAX_TTL_DAYS * SECONDS_PER_DAY
        )
        self.assertFalse(decode_claims(token).is_expired())

    def test_ttl_over_the_cap_is_rejected_in_days(self):
        with self.assertRaises(ConfigError) as ctx:
            mint_developer_token(
                self.key_path, TEAM_ID, KEY_ID, ttl_seconds=(MAX_TTL_DAYS + 1) * SECONDS_PER_DAY
            )
        self.assertIn("days", str(ctx.exception))

    def test_zero_ttl_is_rejected(self):
        with self.assertRaises(ConfigError):
            mint_developer_token(self.key_path, TEAM_ID, KEY_ID, ttl_seconds=0)

    def test_missing_team_id_is_rejected(self):
        with self.assertRaises(ConfigError):
            mint_developer_token(self.key_path, "", KEY_ID)

    def test_missing_key_id_is_rejected(self):
        with self.assertRaises(ConfigError):
            mint_developer_token(self.key_path, TEAM_ID, "")

    def test_missing_key_file_is_rejected_with_a_hint(self):
        with self.assertRaises(ConfigError) as ctx:
            mint_developer_token("/nonexistent/AuthKey_X.p8", TEAM_ID, KEY_ID)
        self.assertIn("not found", str(ctx.exception))


class TestDecodeClaims(unittest.TestCase):
    def test_expired_token_reports_expired(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            key_path = _write_key(Path(tmp))
            # Issue in the past with a short life so it is already expired.
            token = mint_developer_token(
                key_path, TEAM_ID, KEY_ID, ttl_seconds=60, issued_at=1_000_000
            )
        claims = decode_claims(token)
        self.assertTrue(claims.is_expired())
        self.assertLess(claims.seconds_remaining(), 0)

    def test_malformed_token_is_rejected(self):
        with self.assertRaises(ConfigError):
            decode_claims("not-a-jwt")


if __name__ == "__main__":
    unittest.main()
