"""The base price catalogue. Brief milestone 8 groundwork.

Ranking only ever needed a price for SKUs that turned up in the bonus folder.
Pricing a DIY composition needs a price for *every* food type in the recipe, in
every week, whether or not it is on offer. So `prices.food_type_price` answers
"what does a kilo of this food cost me right now", from the cheapest current
observation across all of that food type's SKUs.

The rules defended here:

  * a live bonus beats the plain shelf price, and an expired one does not;
  * the mass money is divided by comes from the same `_resolve_mass` the ranking
    uses, so a litre of milk is costed through its density, not as 1000 g;
  * a search result the matcher rejects is queued for review, never guessed at.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from bonusrank.db import connect
from bonusrank.prices import food_type_price, refresh_food_type_prices
from bonusrank.seed import load_seed

TODAY = date(2026, 9, 17)
NEXT_WEEK = (TODAY + timedelta(days=7)).isoformat()
LAST_WEEK = (TODAY - timedelta(days=7)).isoformat()
LONG_AGO = (TODAY - timedelta(days=30)).isoformat()


@pytest.fixture()
def conn():
    connection = connect(path=Path(":memory:"))
    load_seed(connection)
    return connection


def _product(conn, sku, name, food_type_key, raw_unit_text):
    food_type_id = conn.execute(
        "SELECT id FROM food_types WHERE key=?", (food_type_key,)
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO products (chain, sku, name, raw_unit_text, food_type_id, "
        "match_method, match_score, first_seen) VALUES ('ah',?,?,?,?,'alias_exact',1.0,?)",
        (sku, name, raw_unit_text, food_type_id, TODAY.isoformat()),
    )
    return conn.execute("SELECT id FROM products WHERE sku=?", (sku,)).fetchone()[0]


def _observe(conn, product_id, *, price, observed_at=None, mechanic="not_a_promo",
             raw_text=None, valid_from=None, valid_to=None, required=1, personal=0):
    conn.execute(
        "INSERT INTO price_observations (product_id, observed_at, shelf_price, "
        "promo_mechanic, promo_raw_text, required_quantity, effective_unit_price, "
        "is_personal_offer, valid_from, valid_to) VALUES (?,?,?,?,?,?,?,?,?,?)",
        (product_id, observed_at or TODAY.isoformat(), price, mechanic, raw_text,
         required, price, personal, valid_from, valid_to),
    )


# -- which observation wins ------------------------------------------------

def test_shelf_price_is_used_when_nothing_is_on_promo(conn):
    pid = _product(conn, "wi1", "AH Magere kwark", "kwark_mager", "500 g")
    _observe(conn, pid, price=1.20)

    price = food_type_price(conn, "kwark_mager", on=TODAY)
    assert price is not None
    assert price.eur_per_kg == pytest.approx(2.40)
    assert price.is_promo is False


def test_a_live_bonus_beats_the_shelf_price(conn):
    shelf = _product(conn, "wi1", "AH Magere kwark", "kwark_mager", "500 g")
    bonus = _product(conn, "wi2", "Melkunie Magere kwark", "kwark_mager", "500 g")
    _observe(conn, shelf, price=1.20)
    _observe(conn, bonus, price=0.80, mechanic="x_plus_y_free", raw_text="1+1 gratis",
             required=2, valid_from=LAST_WEEK, valid_to=NEXT_WEEK)

    price = food_type_price(conn, "kwark_mager", on=TODAY)
    assert price.sku == "wi2"
    assert price.eur_per_kg == pytest.approx(1.60)
    assert price.is_promo is True
    assert price.required_quantity == 2


def test_an_expired_bonus_falls_back_to_the_shelf_price(conn):
    """Bonus weeks do not align across chains, so the window is always checked."""
    shelf = _product(conn, "wi1", "AH Magere kwark", "kwark_mager", "500 g")
    bonus = _product(conn, "wi2", "Melkunie Magere kwark", "kwark_mager", "500 g")
    _observe(conn, shelf, price=1.20)
    _observe(conn, bonus, price=0.80, mechanic="x_plus_y_free", raw_text="1+1 gratis",
             observed_at=LONG_AGO, valid_from=LONG_AGO, valid_to=LAST_WEEK)

    price = food_type_price(conn, "kwark_mager", on=TODAY)
    assert price.sku == "wi1"
    assert price.eur_per_kg == pytest.approx(2.40)


def test_personal_offers_are_excluded_unless_asked_for(conn):
    """Copy rule corollary: a personal offer is not available to everyone."""
    shelf = _product(conn, "wi1", "AH Magere kwark", "kwark_mager", "500 g")
    personal = _product(conn, "wi2", "Melkunie Magere kwark", "kwark_mager", "500 g")
    _observe(conn, shelf, price=1.20)
    _observe(conn, personal, price=0.50, mechanic="percent_off", raw_text="25% korting",
             valid_from=LAST_WEEK, valid_to=NEXT_WEEK, personal=1)

    assert food_type_price(conn, "kwark_mager", on=TODAY).sku == "wi1"
    assert food_type_price(conn, "kwark_mager", on=TODAY,
                           include_personal=True).sku == "wi2"


def test_only_the_latest_observation_per_sku_counts(conn):
    """A price that has since risen must not keep pricing today's recipe."""
    pid = _product(conn, "wi1", "AH Magere kwark", "kwark_mager", "500 g")
    _observe(conn, pid, price=0.90, observed_at=LONG_AGO)
    _observe(conn, pid, price=1.20)

    assert food_type_price(conn, "kwark_mager", on=TODAY).eur_per_kg == pytest.approx(2.40)


def test_a_later_shelf_price_does_not_hide_a_live_bonus_from_the_ranking(conn):
    """The two lanes coexist. `prices --refresh` must not delete this week's bonus.

    Storage is append-only, so the reader disambiguates: `rank` takes the latest
    observation per lane, not simply the latest row.
    """
    from bonusrank.ranking import rank

    pid = _product(conn, "wi1", "AH Magere kwark", "kwark_mager", "500 g")
    _observe(conn, pid, price=0.80, observed_at=LAST_WEEK, mechanic="x_plus_y_free",
             raw_text="1+1 gratis", required=2, valid_from=LAST_WEEK, valid_to=NEXT_WEEK)
    _observe(conn, pid, price=1.20, raw_text="shelf price (search)")

    offers = rank(conn, on=TODAY)
    mechanics = {o.promo_mechanic for o in offers}
    assert "x_plus_y_free" in mechanics
    assert "not_a_promo" in mechanics


# -- mass resolution -------------------------------------------------------

def test_a_litre_of_milk_is_costed_through_its_density(conn):
    """Not 1000 g. `_resolve_mass` owns this, and prices must go through it."""
    pid = _product(conn, "wi1", "AH Halfvolle melk", "melk_halfvol", "1 L")
    _observe(conn, pid, price=1.03)

    density = conn.execute(
        "SELECT density_g_per_ml FROM food_types WHERE key='melk_halfvol'"
    ).fetchone()[0]
    assert density, "seed must carry a density for milk or this test proves nothing"

    price = food_type_price(conn, "melk_halfvol", on=TODAY)
    assert price.eur_per_kg == pytest.approx(1.03 / (1000 * density) * 1000, rel=1e-6)
    assert price.eur_per_kg != pytest.approx(1.03)


def test_a_sku_with_an_unparseable_size_is_not_priced(conn):
    """No mass means no per-kilo price. Unknown stays unknown."""
    pid = _product(conn, "wi1", "AH Magere kwark", "kwark_mager", "per stuk")
    _observe(conn, pid, price=1.20)

    assert food_type_price(conn, "kwark_mager", on=TODAY) is None


def test_an_unknown_food_type_is_none_not_an_error(conn):
    assert food_type_price(conn, "niet_bestaand", on=TODAY) is None


# -- the refresh lane ------------------------------------------------------

class _FakeAdapter:
    """Stands in for AHAdapter.search_products. One canned result set per query."""

    chain = "ah"

    def __init__(self, results):
        self._results = results
        self.queries: list[str] = []

    def search_products(self, query, *, size=10):
        self.queries.append(query)
        return self._results.get(query, [])


class _FakeProduct:
    def __init__(self, sku, name, raw_unit_text, shelf_price, brand=None, category=None):
        self.chain = "ah"
        self.sku = sku
        self.name = name
        self.brand = brand
        self.raw_unit_text = raw_unit_text
        self.shelf_price = shelf_price
        self.bonus_price = None
        self.category = category
        self.ean = None
        self.url = None
        self.stated_unit_price_text = None


def test_refresh_stores_a_shelf_price_for_a_matched_search_hit(conn):
    adapter = _FakeAdapter({
        "magere kwark": [_FakeProduct("wi9", "AH Magere kwark", "500 g", 1.15)],
    })
    stats = refresh_food_type_prices(conn, adapter, keys=["kwark_mager"])

    assert stats.matched == 1
    price = food_type_price(conn, "kwark_mager", on=TODAY)
    assert price.sku == "wi9"
    assert price.is_promo is False
    assert price.eur_per_kg == pytest.approx(2.30)


def test_refresh_queues_review_when_the_matcher_rejects_every_hit(conn):
    """A search for kwark must not settle for a kwarktaart. Review, never guess."""
    adapter = _FakeAdapter({
        "magere kwark": [_FakeProduct("wi9", "Kwarktaart citroen diepvries", "400 g", 3.49)],
    })
    stats = refresh_food_type_prices(conn, adapter, keys=["kwark_mager"])

    assert stats.matched == 0
    assert stats.unmatched == 1
    row = conn.execute(
        "SELECT ref FROM needs_review WHERE kind='unmatched_sku' AND ref LIKE 'food_type:%'"
    ).fetchone()
    assert row["ref"] == "food_type:kwark_mager"
    assert food_type_price(conn, "kwark_mager", on=TODAY) is None


def test_refresh_skips_a_multipack_it_cannot_cost_and_takes_the_next_hit(conn):
    """AH's search puts multipacks first. "2 stuks" gives no mass, so no price.

    Taking the first accepted hit regardless would leave the food type unpriced
    while the run reported a match - the worst of both.
    """
    adapter = _FakeAdapter({
        "magere kwark": [
            _FakeProduct("wi8", "AH Magere kwark 4-pack", "4 stuks", 4.60),
            _FakeProduct("wi9", "AH Magere kwark", "500 g", 1.15),
        ],
    })
    stats = refresh_food_type_prices(conn, adapter, keys=["kwark_mager"])

    assert stats.matched == 1
    assert food_type_price(conn, "kwark_mager", on=TODAY).sku == "wi9"


def test_only_unpriceable_hits_are_a_unit_size_gap_not_a_match_gap(conn):
    """Different queue, because the fix is a g_per_unit, not a match override."""
    adapter = _FakeAdapter({
        "magere kwark": [_FakeProduct("wi8", "AH Magere kwark 4-pack", "4 stuks", 4.60)],
    })
    stats = refresh_food_type_prices(conn, adapter, keys=["kwark_mager"])

    assert stats.matched == 0
    assert stats.reviews == {"unparsed_unit_size": 1}
    row = conn.execute(
        "SELECT kind FROM needs_review WHERE ref='food_type:kwark_mager'").fetchone()
    assert row["kind"] == "unparsed_unit_size"


def test_refresh_respects_max_requests(conn):
    """A careless run must not sweep 190 live queries. Counts requests, not foods."""
    adapter = _FakeAdapter({})
    refresh_food_type_prices(conn, adapter, max_requests=3)
    assert len(adapter.queries) == 3


def test_an_alias_is_tried_when_the_canonical_name_finds_nothing(conn):
    """"skyr met fruit" returns Coca-Cola multipacks; "skyr aardbei" finds it."""
    adapter = _FakeAdapter({
        "skyr aardbei": [_FakeProduct("wi7", "Isey Skyr aardbei", "170 g", 1.09)],
    })
    stats = refresh_food_type_prices(conn, adapter, keys=["skyr_fruit"])

    assert adapter.queries[0] == "skyr met fruit", "canonical name is tried first"
    assert "skyr aardbei" in adapter.queries
    assert stats.matched == 1
    assert food_type_price(conn, "skyr_fruit", on=TODAY).sku == "wi7"


def test_no_alias_request_is_made_when_the_canonical_name_works(conn):
    """The extra requests land on the gaps, not on the whole sweep."""
    adapter = _FakeAdapter({
        "magere kwark": [_FakeProduct("wi9", "AH Magere kwark", "500 g", 1.15)],
    })
    refresh_food_type_prices(conn, adapter, keys=["kwark_mager"])
    assert adapter.queries == ["magere kwark"]


def test_refresh_is_append_only(conn):
    """Two refreshes on different days leave two rows, not one overwritten one."""
    adapter = _FakeAdapter({
        "magere kwark": [_FakeProduct("wi9", "AH Magere kwark", "500 g", 1.15)],
    })
    refresh_food_type_prices(conn, adapter, keys=["kwark_mager"], observed_at=LAST_WEEK)
    refresh_food_type_prices(conn, adapter, keys=["kwark_mager"], observed_at=TODAY.isoformat())

    count = conn.execute("SELECT COUNT(*) FROM price_observations").fetchone()[0]
    assert count == 2
