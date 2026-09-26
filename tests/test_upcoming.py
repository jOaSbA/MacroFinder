"""Upcoming deals. Milestone 18.

Jumbo publishes next week's folder a day early and AH sometimes does too, so a
product can have two promo observations from the same day: this week's and
next week's. Picking "the latest promo row" then picks whichever was inserted
last, and if that is next week's, this week's deal vanishes from the ranking
until the new one starts. Measured on the 2026-09-22 ingest: 1,512 Jumbo SKUs
had a promo starting the next day.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from pathlib import Path

import pytest

from bonusrank import appdb
from bonusrank.db import connect
from bonusrank.ranking import rank, upcoming
from bonusrank.seed import load_seed

TODAY = date(2026, 9, 22)


@pytest.fixture()
def conn():
    connection = connect(path=Path(":memory:"))
    load_seed(connection)
    return connection


def _product(conn, sku="wi1"):
    ft = conn.execute("SELECT id FROM food_types WHERE key='kwark_mager'").fetchone()[0]
    conn.execute(
        "INSERT INTO products (chain, sku, name, raw_unit_text, food_type_id, "
        "match_method, match_score, first_seen) "
        "VALUES ('ah',?,'AH Magere kwark','500 g',?,'alias_exact',1.0,?)",
        (sku, ft, TODAY.isoformat()),
    )
    return conn.execute("SELECT id FROM products WHERE sku=?", (sku,)).fetchone()[0]


def _promo(conn, pid, price, *, text, start, end, seen=TODAY):
    conn.execute(
        "INSERT INTO price_observations (product_id, observed_at, shelf_price, "
        "promo_mechanic, promo_raw_text, required_quantity, effective_unit_price, "
        "is_personal_offer, valid_from, valid_to) VALUES (?,?,?,?,?,1,?,0,?,?)",
        (pid, seen.isoformat(), 1.99, "fixed_price", text, price,
         start.isoformat(), end.isoformat()),
    )


@pytest.fixture()
def both(conn):
    """This week's promo, then next week's, inserted in that order."""
    pid = _product(conn)
    _promo(conn, pid, 1.49, text="nu 1.49",
           start=TODAY - timedelta(days=1), end=TODAY + timedelta(days=5))
    _promo(conn, pid, 0.99, text="volgende week 0.99",
           start=TODAY + timedelta(days=6), end=TODAY + timedelta(days=12))
    return conn


def test_next_weeks_promo_does_not_hide_this_weeks(both):
    offers = rank(both, chain="ah", on=TODAY)
    assert [o.promo_raw_text for o in offers] == ["nu 1.49"]


def test_the_upcoming_promo_takes_over_once_it_starts(both):
    offers = rank(both, chain="ah", on=TODAY + timedelta(days=7))
    assert [o.promo_raw_text for o in offers] == ["volgende week 0.99"]


def test_upcoming_lists_only_promos_that_have_not_started(both):
    items = upcoming(both, chain="ah", on=TODAY)
    assert [o.promo_raw_text for o in items] == ["volgende week 0.99"]
    assert items[0].valid_from == (TODAY + timedelta(days=6)).isoformat()


def test_nothing_upcoming_ever_appears_in_the_active_ranking(conn):
    for i in range(5):
        pid = _product(conn, sku=f"wi{i}")
        _promo(conn, pid, 1.0 + i, text=f"later {i}",
               start=TODAY + timedelta(days=1 + i), end=TODAY + timedelta(days=8 + i))
    assert rank(conn, chain="ah", on=TODAY) == []
    assert len(upcoming(conn, chain="ah", on=TODAY)) == 5


def test_an_expired_promo_is_neither_active_nor_upcoming(conn):
    pid = _product(conn)
    _promo(conn, pid, 1.0, text="vorige week",
           start=TODAY - timedelta(days=10), end=TODAY - timedelta(days=3),
           seen=TODAY - timedelta(days=8))
    assert rank(conn, chain="ah", on=TODAY) == []
    assert upcoming(conn, chain="ah", on=TODAY) == []


def test_the_app_database_carries_both_lanes(both, tmp_path):
    out = appdb.build_full(both, tmp_path / "full.sqlite", on=TODAY)
    db = sqlite3.connect(out)
    rows = db.execute(
        "SELECT lane, promo_text, valid_from FROM prices ORDER BY lane").fetchall()
    db.close()
    assert [(r[0], r[1]) for r in rows] == [
        ("promo", "nu 1.49"), ("upcoming", "volgende week 0.99")]
