"""Tests for workflow.utils."""

from workflow.utils import dedupe_preserving_order


def test_dedupe_preserving_order_basic():
    assert dedupe_preserving_order(["a", "b", "a", "c", "b"]) == ["a", "b", "c"]


def test_dedupe_preserving_order_empty():
    assert dedupe_preserving_order([]) == []


def test_dedupe_preserving_order_no_duplicates():
    assert dedupe_preserving_order(["a", "b", "c"]) == ["a", "b", "c"]


def test_dedupe_preserving_order_all_duplicates():
    assert dedupe_preserving_order(["x", "x", "x"]) == ["x"]


def test_dedupe_preserving_order_tuple_input():
    assert dedupe_preserving_order(("x", "y", "x")) == ["x", "y"]


def test_dedupe_preserving_order_int_values():
    assert dedupe_preserving_order([1, 2, 1, 3, 2]) == [1, 2, 3]
