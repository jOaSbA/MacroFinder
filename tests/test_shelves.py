"""Shelf taxonomy. Milestone 19.

`tests/fixtures/categories_seen.json` is every (chain, category) pair in the
real catalogue on 2026-09-22 with its product count. It lets the unmapped-rate
check run in CI without scraping anything. The data workflow checks the live
rate on every build as well.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bonusrank import shelves
from bonusrank.db import connect

SEEN = json.loads(
    (Path(__file__).parent / "fixtures/categories_seen.json").read_text("utf-8")
)["counts"]


def test_every_mapping_points_at_a_real_shelf():
    m = shelves.load()
    for chain, table in m.chains.items():
        for category, shelf in table.items():
            assert shelf in m.shelves, f"{chain}: {category!r} -> unknown shelf {shelf!r}"


def test_there_are_eighteen_shelves():
    assert len(shelves.load().shelves) == 18


def test_at_least_95_percent_of_the_real_catalogue_is_mapped():
    m = shelves.load()
    total = sum(n for _, _, n in SEEN)
    mapped = sum(n for chain, cat, n in SEEN if m.shelf_for(chain, cat))
    assert mapped / total >= 0.95, f"only {mapped / total:.1%} mapped"


def test_the_build_fails_above_10_percent_unmapped():
    m = shelves.load()
    fake = [("ah", "Iets nieuws", 900), ("ah", "Kaas", 100)]
    with pytest.raises(shelves.TooManyUnmapped):
        m.check_rate(fake)
    m.check_rate([("ah", "Iets nieuws", 50), ("ah", "Kaas", 950)])


def test_an_unknown_category_has_no_shelf_rather_than_a_guess():
    m = shelves.load()
    assert m.shelf_for("ah", "Glutenvrij") is None
    assert m.shelf_for("aldi", "offer") is None
    assert m.shelf_for("ah", None) is None


def test_unmapped_categories_go_to_review():
    conn = connect(path=Path(":memory:"))
    for sku, cat in (("1", "Kaas"), ("2", "Glutenvrij"), ("3", "Glutenvrij")):
        conn.execute(
            "INSERT INTO products (chain, sku, name, category, first_seen) "
            "VALUES ('ah', ?, 'x', ?, '2026-09-22')", (sku, cat))
    counts = shelves.record_unmapped(conn, observed_at="2026-09-22")
    rows = conn.execute(
        "SELECT ref FROM needs_review WHERE kind='unmapped_category'").fetchall()
    assert [r[0] for r in rows] == ["ah:Glutenvrij"]
    assert sorted(counts) == [("ah", "Glutenvrij", 2), ("ah", "Kaas", 1)]
