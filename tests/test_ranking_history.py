"""The "cheapest in N weeks" signal. docs/AUDIT.md finding 3.2.

BRIEF section 9 rule 5 prefers "cheapest in 14 weeks" over "25% korting" as the
headline, and it is the right preference - but the claim has to be true and it
has to mean something. With five days of observations the old code answered
"cheapest in 0 weeks" for 246 AH offers at once: not false exactly, but not a
claim either, and it crowded out the honest alternative the same code path
already had.

There is a second reason to be strict here. `refresh-data.yml` starts from a
fresh checkout and `data/bonusrank.sqlite3` is gitignored, so in production
every run ingests into an empty database and history never accumulates at all.
Until that changes (PLAN-V2 M21), `None` is the only honest answer this can
give there - and `None` already renders as "no price history yet".
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from bonusrank.db import connect
from bonusrank.ranking import MIN_HISTORY_WEEKS, rank
from bonusrank.seed import load_seed

TODAY = date(2026, 9, 22)


@pytest.fixture()
def conn():
    connection = connect(path=Path(":memory:"))
    load_seed(connection)
    return connection


def _observe(conn, price, *, on, sku="wi1"):
    row = conn.execute("SELECT id FROM products WHERE chain='ah' AND sku=?", (sku,)).fetchone()
    if row is None:
        ft = conn.execute("SELECT id FROM food_types WHERE key='kwark_mager'").fetchone()[0]
        conn.execute(
            "INSERT INTO products (chain, sku, name, raw_unit_text, food_type_id, "
            "match_method, match_score, first_seen) "
            "VALUES ('ah',?,'AH Magere kwark','500 g',?,'alias_exact',1.0,?)",
            (sku, ft, on.isoformat()),
        )
        row = conn.execute("SELECT id FROM products WHERE chain='ah' AND sku=?", (sku,)).fetchone()
    conn.execute(
        "INSERT INTO price_observations (product_id, observed_at, shelf_price, "
        "promo_mechanic, promo_raw_text, required_quantity, effective_unit_price, "
        "is_personal_offer) VALUES (?,?,?,'not_a_promo',NULL,1,?,0)",
        (row[0], on.isoformat(), price, price),
    )


def _offer(conn):
    return rank(conn, chain="ah", on=TODAY)[0]


def test_a_single_observation_makes_no_history_claim(conn):
    _observe(conn, 1.20, on=TODAY)

    assert _offer(conn).cheapest_in_weeks is None


def test_less_than_a_week_of_history_makes_no_claim(conn):
    """The bug: 246 AH offers all said "cheapest in 0 weeks" at once."""
    _observe(conn, 1.50, on=TODAY - timedelta(days=5))
    _observe(conn, 1.20, on=TODAY)

    assert _offer(conn).cheapest_in_weeks is None


def test_a_claim_appears_once_there_is_a_week_to_claim_over(conn):
    _observe(conn, 1.50, on=TODAY - timedelta(days=14))
    _observe(conn, 1.20, on=TODAY)

    assert _offer(conn).cheapest_in_weeks == 2


def test_the_claim_counts_back_to_the_last_time_it_was_cheaper(conn):
    """Not to the oldest observation. "Cheapest in 3 weeks" means it has not
    been this cheap for three weeks, which is a different thing from "we have
    watched it for three weeks"."""
    _observe(conn, 0.99, on=TODAY - timedelta(days=56))   # cheaper, 8 weeks ago
    _observe(conn, 1.80, on=TODAY - timedelta(days=21))
    _observe(conn, 1.20, on=TODAY)

    assert _offer(conn).cheapest_in_weeks == 8


def test_a_price_that_has_never_been_beaten_counts_from_the_oldest_record(conn):
    _observe(conn, 1.50, on=TODAY - timedelta(days=70))
    _observe(conn, 1.20, on=TODAY)

    assert _offer(conn).cheapest_in_weeks == 10


def test_the_floor_is_one_whole_week(conn):
    """Pinned so nobody lowers it to make the signal appear more often - the
    whole point is that it appears only when it means something."""
    assert MIN_HISTORY_WEEKS == 1

    _observe(conn, 1.50, on=TODAY - timedelta(days=6), sku="six_days")
    _observe(conn, 1.20, on=TODAY, sku="six_days")
    _observe(conn, 1.50, on=TODAY - timedelta(days=7), sku="seven_days")
    _observe(conn, 1.20, on=TODAY, sku="seven_days")

    by_sku = {offer.sku: offer.cheapest_in_weeks for offer in rank(conn, chain="ah", on=TODAY)}

    assert by_sku["six_days"] is None
    assert by_sku["seven_days"] == 1
