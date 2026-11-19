"""Catalog of credential token shapes recognizable by value alone (no key= context).

One catalog, several policies: ``memory.redaction`` blocks exact shapes and warns
on heuristic ones, ``mail.utils.shield`` masks any match. Consumers own the
policy; this module owns only the patterns.

Every pattern is linear-time: a start is anchored at a token boundary (a
lookbehind or ``\\b``) so a long run of token characters is scanned once, not
once per start offset. ``tests/core_tests/test_token_shapes.py`` pins this.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["TOKEN_SHAPES", "TokenShape", "contains_token_shape"]


@dataclass(frozen=True)
class TokenShape:
    """One credential shape.

    Attributes:
        name: Stable id (e.g. ``github-token``); memory uses it as its rule id.
        label: Upper-case tag for placeholders (e.g. ``GITHUB_TOKEN``).
        pattern: Compiled regex matching the token.
        description: Human-readable summary of the shape.
        exact: True for vendor formats precise enough to block on; False for
            heuristics that also match ordinary text now and then.
    """

    name: str
    label: str
    pattern: re.Pattern[str]
    description: str
    exact: bool = True


TOKEN_SHAPES: tuple[TokenShape, ...] = (
    TokenShape(
        name="aws-access-key",
        label="AWS_KEY",
        pattern=re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b", re.ASCII),
        description="AWS access key (AKIA/ASIA prefix)",
    ),
    TokenShape(
        name="private-key-block",
        label="PRIVATE_KEY",
        pattern=re.compile(
            r"-----BEGIN[ \t]++(?:[A-Z0-9]++[ \t]++)*PRIVATE[ \t]++KEY(?:[ \t][^\n]*)?-----"
        ),
        description="PEM private key block header (RSA/EC/DSA/OPENSSH/ENCRYPTED or bare)",
    ),
    TokenShape(
        name="github-token",
        label="GITHUB_TOKEN",
        pattern=re.compile(
            r"(?:(?:ghp|gho|ghu|ghs|ghr)_\w{36,255}|github_pat_\w{22,255})",
            re.ASCII,
        ),
        description="GitHub token (ghp_/gho_/ghu_/ghs_/ghr_ or fine-grained github_pat_ prefix)",
    ),
    TokenShape(
        name="anthropic-key",
        label="ANTHROPIC_KEY",
        pattern=re.compile(r"\bsk-ant-[A-Za-z0-9]+-[A-Za-z0-9_\-]{20,}", re.ASCII),
        description="Anthropic API key (sk-ant-<kind>- prefix, e.g. api03/admin01)",
    ),
    TokenShape(
        name="slack-token",
        label="SLACK_TOKEN",
        pattern=re.compile(r"(?:xox[abiposr]|xapp-\d)-[A-Za-z0-9\-]{20,}"),
        description="Slack token (xox<kind>- or app-level xapp-<n>- prefix)",
    ),
    TokenShape(
        name="openai-key",
        label="OPENAI_KEY",
        pattern=re.compile(
            r"(?<![A-Za-z0-9_\-])sk-(?:(?:proj|svcacct|admin)-[A-Za-z0-9_\-]{40,}"
            r"|[A-Za-z0-9]{48}(?![A-Za-z0-9_\-]))",
            re.ASCII,
        ),
        description="OpenAI API key (sk-proj-/sk-svcacct-/sk-admin- prefix, or legacy sk- + 48)",
    ),
    TokenShape(
        name="google-api-key",
        label="GOOGLE_KEY",
        pattern=re.compile(r"(?<![A-Za-z0-9_\-])AIza[0-9A-Za-z_\-]{30,}", re.ASCII),
        description="Google API key (AIza prefix; real keys are 39 chars, matched from 34)",
    ),
    TokenShape(
        name="google-oauth-token",
        label="GOOGLE_OAUTH_TOKEN",
        pattern=re.compile(r"(?<![A-Za-z0-9_\-])ya29\.[A-Za-z0-9_\-.]{20,}", re.ASCII),
        description="Google OAuth access token (ya29. prefix)",
    ),
    TokenShape(
        name="jwt",
        label="JWT",
        pattern=re.compile(
            r"(?<![A-Za-z0-9_\-])eyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}",
            re.ASCII,
        ),
        description="JSON Web Token (three base64url segments, header starts eyJ)",
    ),
    TokenShape(
        name="stripe-key",
        label="STRIPE_KEY",
        pattern=re.compile(r"(?<!\w)[sr]k_live_[0-9A-Za-z]{24,}", re.ASCII),
        description="Stripe live secret/restricted key (sk_live_/rk_live_ prefix)",
    ),
    TokenShape(
        name="npm-token",
        label="NPM_TOKEN",
        pattern=re.compile(r"(?<!\w)npm_[A-Za-z0-9]{36}(?![A-Za-z0-9])", re.ASCII),
        description="npm access token (npm_ prefix, 36 alphanumerics)",
    ),
    TokenShape(
        name="grafana-token",
        label="GRAFANA_TOKEN",
        pattern=re.compile(
            r"(?<!\w)glsa_[A-Za-z0-9]{32}_[A-Fa-f0-9]{8}(?!\w)",
            re.ASCII,
        ),
        description="Grafana service account token (glsa_ + 32 alphanumerics + _ + 8 hex)",
    ),
    # Heuristic shapes: plausible tokens, but loose enough to hit ordinary text.
    TokenShape(
        name="stripe-test-key",
        label="STRIPE_TEST_KEY",
        pattern=re.compile(r"(?<!\w)[sr]k_test_[0-9A-Za-z]{24,}", re.ASCII),
        description="Stripe test-mode key (sk_test_/rk_test_ prefix)",
        exact=False,
    ),
    TokenShape(
        name="msal-token",
        label="MSAL_TOKEN",
        pattern=re.compile(r"(?<![A-Za-z0-9._!*$\-])M\.[A-Za-z0-9._!*$\-]{20,}\b", re.ASCII),
        description="MSAL/Graph opaque token (M. prefix, 20+ chars)",
        exact=False,
    ),
    TokenShape(
        name="api-dash-token",
        label="API_TOKEN",
        pattern=re.compile(r"\bapi-[A-Z0-9]{16,}\b", re.ASCII | re.IGNORECASE),
        description="Vendor API token with api- prefix (e.g. LaunchDarkly)",
        exact=False,
    ),
    TokenShape(
        name="rootly-token",
        label="ROOTLY_TOKEN",
        pattern=re.compile(r"\brootly_[A-Z0-9]{16,}\b", re.ASCII | re.IGNORECASE),
        description="Rootly API token (rootly_ prefix)",
        exact=False,
    ),
)


def contains_token_shape(text: str) -> bool:
    """Return True when any catalog shape, exact or heuristic, matches ``text``."""
    return any(shape.pattern.search(text) for shape in TOKEN_SHAPES)
