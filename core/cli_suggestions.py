"""Fuzzy "did you mean" suggestions for CLI subcommands and flags.

Provides ranked suggestions when a user types an invalid subcommand or
unrecognized flag.  Pure-function API, no side effects.

Scoring:
    100  exact match (case-insensitive)
     90  starts-with
     70  contains
     60+ word-part overlap (Jaccard-style on '-'/'_' splits)
     50  character-subsequence match (in-order, >50% of query chars matched)

Flag suggestions use difflib.get_close_matches (cutoff 0.6, max 3).
"""
from __future__ import annotations

import difflib


def _word_parts(token: str) -> list[str]:
    """Split on '-' and '_' into lowercase parts."""
    import re
    return [p for p in re.split(r"[-_]", token.lower()) if p]


def _char_subseq_score(query: str, candidate: str) -> float:
    """Return fraction of query chars found in order within candidate."""
    q = query.lower()
    c = candidate.lower()
    qi = 0
    for ch in c:
        if qi < len(q) and ch == q[qi]:
            qi += 1
    return qi / len(q) if q else 0.0


def _score_candidate(query: str, candidate: str) -> int:
    """Return a 0–100 score for how well query matches candidate."""
    q = query.lower()
    c = candidate.lower()

    if q == c:
        return 100
    if c.startswith(q):
        return 90
    if q in c:
        return 70

    # Word-part overlap (Jaccard-style)
    q_parts = set(_word_parts(query))
    c_parts = set(_word_parts(candidate))
    if q_parts and c_parts:
        overlap = len(q_parts & c_parts)
        union = len(q_parts | c_parts)
        if overlap:
            jaccard = overlap / union
            score = 60 + int(jaccard * 10)
            return score

    # Character-subsequence (keep if >50% of query chars match in order)
    subseq = _char_subseq_score(query, candidate)
    if subseq > 0.5:
        return 50

    return 0


def suggest_command(query: str, choices: list[str], max_results: int = 3) -> list[str]:
    """Return ranked suggestions for a mistyped subcommand.

    Args:
        query: The unrecognized subcommand string the user typed.
        choices: All valid subcommand names for this parser level.
        max_results: Maximum number of suggestions to return.

    Returns:
        List of suggested command names, best match first (may be empty).
    """
    if not query or not choices:
        return []
    scored = [(c, _score_candidate(query, c)) for c in choices]
    scored = [(c, s) for c, s in scored if s > 0]
    scored.sort(key=lambda x: (-x[1], x[0]))
    return [c for c, _ in scored[:max_results]]


def suggest_flags(
    unrecognized_flag: str,
    all_flags: list[str],
    max_results: int = 3,
) -> list[str]:
    """Return suggestions for a mistyped flag using difflib.

    Args:
        unrecognized_flag: The flag string the user typed (e.g. '--verbse').
        all_flags: All valid flag option_strings for the current parser.
        max_results: Maximum number of suggestions.

    Returns:
        List of close-matching flag strings, best match first.
    """
    if not unrecognized_flag or not all_flags:
        return []
    matches = difflib.get_close_matches(
        unrecognized_flag,
        all_flags,
        n=max_results,
        cutoff=0.6,
    )
    return list(matches)
