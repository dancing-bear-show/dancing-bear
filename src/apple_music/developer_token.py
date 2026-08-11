"""Mint and inspect Apple Music developer tokens (ES256 JWTs signed with a MusicKit .p8 key)."""

from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from pathlib import Path

from core.cli_errors import ConfigError

# Apple caps MusicKit developer tokens at 6 months (15777000 seconds).
MAX_TTL_SECONDS = 15777000
DEFAULT_TTL_SECONDS = MAX_TTL_SECONDS

SECONDS_PER_DAY = 86400
# Whole days that fit under Apple's cap: 15777000s is ~182.6 days, so 182 is the
# largest --ttl-days value that will not be rejected.
MAX_TTL_DAYS = MAX_TTL_SECONDS // SECONDS_PER_DAY


@dataclass(frozen=True)
class TokenClaims:
    """Decoded developer-token claims relevant to expiry checks."""

    team_id: str | None
    key_id: str | None
    issued_at: int | None
    expires_at: int | None

    def seconds_remaining(self, now: int | None = None) -> int | None:
        """Return seconds until expiry, negative if already expired."""
        if self.expires_at is None:
            return None
        return self.expires_at - (now if now is not None else int(time.time()))

    def is_expired(self, now: int | None = None) -> bool:
        remaining = self.seconds_remaining(now)
        return remaining is not None and remaining <= 0


def _b64url_encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64url_decode(segment: str) -> bytes:
    padded = segment + "=" * (-len(segment) % 4)
    return base64.urlsafe_b64decode(padded)


def _load_private_key(key_path: str | Path):
    """Load the MusicKit .p8 private key, raising ConfigError with actionable hints."""
    path = Path(key_path).expanduser()
    if not path.is_file():
        raise ConfigError(
            f"MusicKit private key not found: {path}",
            hint="Create a MusicKit key at https://developer.apple.com/account/resources/authkeys/list "
            "and set key_path in credentials.ini. Apple serves the .p8 only once.",
        )
    try:
        # Lazy import: cryptography is an optional/transitive dep in this repo.
        from cryptography.hazmat.primitives.asymmetric import ec  # noqa: PLC0415
        from cryptography.hazmat.primitives.serialization import (  # noqa: PLC0415
            load_pem_private_key,
        )
    except ImportError as exc:  # pragma: no cover - environment-dependent
        raise ConfigError(
            "The 'cryptography' package is required to mint developer tokens.",
            hint="Install it with: pip install cryptography",
        ) from exc

    try:
        key = load_pem_private_key(path.read_bytes(), password=None)
    except Exception as exc:
        raise ConfigError(
            f"Could not read {path} as a PEM private key.",
            hint="MusicKit keys are unencrypted PEM files starting with '-----BEGIN PRIVATE KEY-----'.",
        ) from exc

    if not isinstance(key, ec.EllipticCurvePrivateKey) or key.curve.name != "secp256r1":
        raise ConfigError(
            f"{path} is not an ES256 (P-256) key; Apple Music requires one.",
            hint="Download a MusicKit key from the Apple Developer portal.",
        )
    return key


def _ecdsa_der_to_raw(signature: bytes) -> bytes:
    """Convert a DER-encoded ECDSA signature to the raw r||s form JWS requires."""
    from cryptography.hazmat.primitives.asymmetric.utils import (  # noqa: PLC0415
        decode_dss_signature,
    )

    r, s = decode_dss_signature(signature)
    return r.to_bytes(32, "big") + s.to_bytes(32, "big")


def mint_developer_token(
    key_path: str | Path,
    team_id: str,
    key_id: str,
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
    issued_at: int | None = None,
) -> str:
    """Sign and return an Apple Music developer token (ES256 JWT).

    Args:
        key_path: Path to the MusicKit .p8 private key.
        team_id: Apple Developer team ID (JWT issuer).
        key_id: MusicKit key ID (JWT header kid).
        ttl_seconds: Lifetime in seconds; Apple rejects anything over 6 months.
        issued_at: Unix timestamp for iat; defaults to now.

    Returns:
        The encoded JWT.
    """
    if not team_id:
        raise ConfigError(
            "Missing team_id.",
            hint="Set team_id in the credentials.ini profile (Apple Developer membership details).",
        )
    if not key_id:
        raise ConfigError(
            "Missing key_id.",
            hint="Set key_id in the credentials.ini profile; it matches the AuthKey_<key_id>.p8 filename.",
        )
    if ttl_seconds <= 0 or ttl_seconds > MAX_TTL_SECONDS:
        raise ConfigError(
            f"Token lifetime must be between 1 second and {MAX_TTL_DAYS} days "
            f"(Apple's 6-month cap); got {ttl_seconds / SECONDS_PER_DAY:.1f} days.",
            hint=f"Pass --ttl-days with a value from 1 to {MAX_TTL_DAYS}.",
        )

    key = _load_private_key(key_path)
    now = int(time.time()) if issued_at is None else issued_at

    header = {"alg": "ES256", "kid": key_id, "typ": "JWT"}
    payload = {"iss": team_id, "iat": now, "exp": now + ttl_seconds}
    signing_input = ".".join(
        _b64url_encode(json.dumps(part, separators=(",", ":"), sort_keys=True).encode("utf-8"))
        for part in (header, payload)
    ).encode("ascii")

    from cryptography.hazmat.primitives import hashes  # noqa: PLC0415
    from cryptography.hazmat.primitives.asymmetric import ec  # noqa: PLC0415

    der_signature = key.sign(signing_input, ec.ECDSA(hashes.SHA256()))
    return f"{signing_input.decode('ascii')}.{_b64url_encode(_ecdsa_der_to_raw(der_signature))}"


def decode_claims(token: str) -> TokenClaims:
    """Decode a developer token's claims without verifying its signature.

    Verification is Apple's job; this exists so the CLI can report expiry locally.
    """
    parts = token.split(".")
    if len(parts) != 3:
        raise ConfigError("Developer token is not a well-formed JWT (expected three dot-separated segments).")
    try:
        header = json.loads(_b64url_decode(parts[0]))
        payload = json.loads(_b64url_decode(parts[1]))
    except Exception as exc:
        raise ConfigError("Could not decode developer token claims.") from exc

    return TokenClaims(
        team_id=payload.get("iss"),
        key_id=header.get("kid"),
        issued_at=payload.get("iat"),
        expires_at=payload.get("exp"),
    )
