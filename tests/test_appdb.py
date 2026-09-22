"""The published app database. Milestone 14 (PLAN-V2 section 5).

Two properties carry this whole milestone, and everything else here exists to
protect them.

**The build is a pure function of the dev database's contents.** Two builds of
the same content are byte-identical files, whatever order anything was inserted
in and whatever churn the source went through. That is what makes a `sha256` in
`manifest.json` mean anything at all: the app checks a hash rather than trusting
a download, and the CI job can tell "nothing changed this week" from "the
catalogue moved" without diffing 20 MB.

**A delta applied to the previous full build reproduces the next full build,
byte for byte.** PLAN-V2's acceptance criterion says "byte-identical", and the
strictest reading of that is the one taken here: not "the same rows", not "the
same content hash" - the same file. `VACUUM INTO` normalises away page layout,
free lists and insertion history, so the strict reading turned out to be
reachable rather than aspirational, and a weaker one would have hidden a whole
class of delta bug.

No network anywhere. Fixtures are built by hand into an in-memory dev DB.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import date
from pathlib import Path

import pytest

from bonusrank import appdb
from bonusrank.db import connect
from bonusrank.seed import load_seed

# The separator `appdb` joins a composite primary key with, so a deletion of
# a (product, lane) row has one unambiguous identifier.
SEP = chr(31)

TODAY = date(2026, 9, 22)
LATER = date(2026, 9, 29)


@pytest.fixture()
def conn():
    connection = connect(path=Path(":memory:"))
    load_seed(connection)
    return connection


def _product(conn, sku, name, food_type_key=None, *, chain="ah",
             raw_unit_text="500 g", brand="AH", category="Zuivel, eieren"):
    food_type_id = None
    if food_type_key is not None:
        food_type_id = conn.execute(
            "SELECT id FROM food_types WHERE key=?", (food_type_key,)
        ).fetchone()[0]
    conn.execute(
        "INSERT INTO products (chain, sku, name, brand, raw_unit_text, category, "
        "food_type_id, match_method, match_score, first_seen) "
        "VALUES (?,?,?,?,?,?,?,'alias_exact',1.0,?)",
        (chain, sku, name, brand, raw_unit_text, category, food_type_id,
         TODAY.isoformat()),
    )
    return conn.execute(
        "SELECT id FROM products WHERE chain=? AND sku=?", (chain, sku)
    ).fetchone()[0]


def _price(conn, product_id, price, *, on=TODAY, mechanic="not_a_promo",
           promo_text=None, required=1, valid_to="2026-12-31"):
    conn.execute(
        "INSERT INTO price_observations (product_id, observed_at, shelf_price, "
        "promo_mechanic, promo_raw_text, required_quantity, effective_unit_price, "
        "is_personal_offer, valid_from, valid_to) VALUES (?,?,?,?,?,?,?,0,?,?)",
        (product_id, on.isoformat(), price, mechanic, promo_text, required, price,
         on.isoformat(), valid_to),
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(path: Path, sql: str):
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in db.execute(sql)]
    finally:
        db.close()


# -- the build produces something usable --------------------------------------

def test_a_built_database_carries_the_products_it_was_given(conn, tmp_path):
    _price(conn, _product(conn, "wi1", "AH Magere kwark", "kwark_mager"), 1.20)
    _price(conn, _product(conn, "wi2", "AH Kipfilet", "kipfilet_rauw"), 3.99)

    out = appdb.build_full(conn, tmp_path / "full.sqlite", on=TODAY)

    # PLAN-V2's own acceptance check, run as a test.
    assert _rows(out, "SELECT count(*) n FROM products")[0]["n"] == 2
    names = {r["name"] for r in _rows(out, "SELECT name FROM products")}
    assert names == {"AH Magere kwark", "AH Kipfilet"}


def test_every_product_keeps_a_stable_text_id_across_builds(conn, tmp_path):
    """`{chain}:{sku}` and never an integer.

    The dev database's `products.id` is an autoincrement. Rebuild the dev
    database from the raw snapshots and every id shifts, which would silently
    re-point every delta row at a different product - the exact failure
    milestone 13 already avoided once by keying saved meals on strings.
    """
    _price(conn, _product(conn, "wi1", "AH Magere kwark", "kwark_mager"), 1.20)

    first = appdb.build_full(conn, tmp_path / "a.sqlite", on=TODAY)
    assert _rows(first, "SELECT id FROM products")[0]["id"] == "ah:wi1"

    # A second dev database, same content, ids allocated differently.
    other = connect(path=Path(":memory:"))
    load_seed(other)
    _product(other, "wi0", "Filler that takes id 1", "kwark_mager")
    _price(other, _product(other, "wi1", "AH Magere kwark", "kwark_mager"), 1.20)
    second = appdb.build_full(other, tmp_path / "b.sqlite", on=TODAY)

    assert "ah:wi1" in {r["id"] for r in _rows(second, "SELECT id FROM products")}


def test_an_unmatched_product_is_kept_with_a_null_food_type(conn, tmp_path):
    """PLAN-V2 section 4: the catalogue is a lookup layer for everything, and
    roughly 90% of scraped SKUs match no food type. Dropping them would make
    the catalogue useless for the one thing it exists for."""
    _price(conn, _product(conn, "wi9", "Zeer Speciaal Iets", None), 2.50)

    out = appdb.build_full(conn, tmp_path / "full.sqlite", on=TODAY)

    row = _rows(out, "SELECT id, food_type FROM products")[0]
    assert row["id"] == "ah:wi9"
    assert row["food_type"] is None


def test_macros_carry_their_provenance(conn, tmp_path):
    """BRIEF section 9 rule 1, and docs/AUDIT.md finding 3.3: the app cannot
    mark an estimated macro if the data never told it the macro was estimated.
    Every seeded row is source='manual', confidence='seed'."""
    _price(conn, _product(conn, "wi1", "AH Magere kwark", "kwark_mager"), 1.20)

    out = appdb.build_full(conn, tmp_path / "full.sqlite", on=TODAY)

    row = _rows(out, "SELECT * FROM food_types WHERE key='kwark_mager'")[0]
    assert row["macro_source"] == "manual"
    assert row["macro_confidence"] == "seed"
    assert row["protein_per_100g"] is not None


def test_only_the_latest_observation_per_product_is_published(conn, tmp_path):
    """The app database is a current-prices lookup, not the price history.
    History stays in the dev database, which is where the milestone 21/22
    signals are computed - shipping every observation would multiply the
    catalogue by the number of weeks it has been running."""
    product_id = _product(conn, "wi1", "AH Magere kwark", "kwark_mager")
    _price(conn, product_id, 1.50, on=date(2026, 9, 15))
    _price(conn, product_id, 1.20, on=TODAY)

    out = appdb.build_full(conn, tmp_path / "full.sqlite", on=TODAY)

    prices = _rows(out, "SELECT * FROM prices")
    assert len(prices) == 1
    assert prices[0]["shelf_price"] == 1.20


def test_a_product_with_no_price_is_still_in_the_catalogue(conn, tmp_path):
    """Unknown is unknown, never zero and never absent - the rule this project
    keeps everywhere else."""
    _product(conn, "wi7", "Nooit Geprijsd", "kwark_mager")

    out = appdb.build_full(conn, tmp_path / "full.sqlite", on=TODAY)

    assert _rows(out, "SELECT count(*) n FROM products")[0]["n"] == 1
    assert _rows(out, "SELECT count(*) n FROM prices")[0]["n"] == 0


# -- determinism ---------------------------------------------------------------

def test_two_builds_of_the_same_content_are_byte_identical(conn, tmp_path):
    _price(conn, _product(conn, "wi1", "AH Magere kwark", "kwark_mager"), 1.20)
    _price(conn, _product(conn, "wi2", "AH Kipfilet", "kipfilet_rauw"), 3.99)

    a = appdb.build_full(conn, tmp_path / "a.sqlite", on=TODAY)
    b = appdb.build_full(conn, tmp_path / "b.sqlite", on=TODAY)

    assert _sha(a) == _sha(b)


def test_insertion_order_and_churn_do_not_change_the_bytes(conn, tmp_path):
    """The source database's own history must not leak into the artifact.

    Without this, a re-ingest that touched nothing would still publish a
    different hash, and the app would re-download 20 MB for no reason.
    """
    _price(conn, _product(conn, "wi1", "AH Magere kwark", "kwark_mager"), 1.20)
    _price(conn, _product(conn, "wi2", "AH Kipfilet", "kipfilet_rauw"), 3.99)
    a = appdb.build_full(conn, tmp_path / "a.sqlite", on=TODAY)

    churned = connect(path=Path(":memory:"))
    load_seed(churned)
    # Reverse order, plus a product that is inserted and then removed again.
    _price(churned, _product(churned, "wi2", "AH Kipfilet", "kipfilet_rauw"), 3.99)
    doomed = _product(churned, "wi3", "Tijdelijk", "kwark_mager")
    churned.execute("DELETE FROM products WHERE id=?", (doomed,))
    _price(churned, _product(churned, "wi1", "AH Magere kwark", "kwark_mager"), 1.20)
    b = appdb.build_full(churned, tmp_path / "b.sqlite", on=TODAY)

    assert _sha(a) == _sha(b)


def test_the_generated_at_stamp_does_not_enter_the_bytes(conn, tmp_path):
    """`generated_at` lives in the manifest, not in the database.

    A timestamp inside the artifact would change the hash on every build and
    destroy the "did anything actually change?" signal the hash exists to give.
    """
    _price(conn, _product(conn, "wi1", "AH Magere kwark", "kwark_mager"), 1.20)

    a = appdb.build_full(conn, tmp_path / "a.sqlite", on=TODAY)
    b = appdb.build_full(conn, tmp_path / "b.sqlite", on=LATER)

    assert _sha(a) == _sha(b)
    assert _rows(a, "SELECT count(*) n FROM meta WHERE key='generated_at'")[0]["n"] == 0


# -- deltas --------------------------------------------------------------------

def _two_generations(conn, tmp_path):
    """Two consecutive refreshes, and the diff between them.

    The second generation is built from a **fresh** dev database rather than by
    mutating the first, because that is literally what production does:
    `refresh-data.yml` checks out the repo, and `data/bonusrank.sqlite3` is
    gitignored, so every scheduled run starts from an empty database holding
    only that run's scrape. A product that fell out of the folder is therefore
    simply absent next time - deletions are the common case here, not an exotic
    one, and a delta format without them would be wrong twice a day.

    It is also the only way to write this fixture at all: the append-only
    trigger on `price_observations` refuses to let a test delete its way to the
    second generation, which is the trigger doing its job.

    Returns (prev, next, delta).
    """
    _price(conn, _product(conn, "wi1", "AH Magere kwark", "kwark_mager"), 1.20)
    _price(conn, _product(conn, "wi2", "AH Kipfilet", "kipfilet_rauw"), 3.99)
    _price(conn, _product(conn, "wi3", "Seizoensartikel", "kwark_mager"), 0.99)
    prev = appdb.build_full(conn, tmp_path / "prev.sqlite", on=TODAY)

    later = connect(path=Path(":memory:"))
    load_seed(later)
    # 1. unchanged
    _price(later, _product(later, "wi1", "AH Magere kwark", "kwark_mager"), 1.20)
    # 2. same product, the price moved and it is on promo now
    _price(later, _product(later, "wi2", "AH Kipfilet", "kipfilet_rauw"), 2.99,
           on=LATER, mechanic="x_plus_y_free", promo_text="1+1 gratis", required=2)
    # 3. 'Seizoensartikel' is gone from the folder entirely
    # 4. a product appears
    _price(later, _product(later, "wi4", "AH Skyr", "skyr_naturel"), 1.79, on=LATER)

    nxt = appdb.build_full(later, tmp_path / "next.sqlite", on=LATER)
    delta = appdb.build_delta(prev, nxt, tmp_path / "delta.sqlite")
    return prev, nxt, delta


def test_a_delta_applied_to_the_previous_build_reproduces_the_next_one_byte_for_byte(
        conn, tmp_path):
    """PLAN-V2's acceptance criterion, read strictly. This is the test the
    whole milestone hangs on."""
    prev, nxt, delta = _two_generations(conn, tmp_path)

    rebuilt = appdb.apply_delta(prev, delta, tmp_path / "rebuilt.sqlite")

    assert _sha(rebuilt) == _sha(nxt)


def test_a_delta_carries_only_what_changed(conn, tmp_path):
    """The point of the whole mechanism. An unchanged row in the delta is a
    row the user pays mobile data for twice."""
    _prev, _nxt, delta = _two_generations(conn, tmp_path)

    products = {r["id"] for r in _rows(delta, "SELECT id FROM products")}
    assert products == {"ah:wi4"}          # only the genuinely new one
    assert "ah:wi1" not in products        # untouched, so absent

    prices = {r["product_id"] for r in _rows(delta, "SELECT product_id FROM prices")}
    assert prices == {"ah:wi2", "ah:wi4"}  # the moved price and the new product


def test_a_delta_records_deletions_explicitly(conn, tmp_path):
    """A row that vanished cannot be expressed as an upsert. Without a
    deletions table the app would keep showing a product the store dropped,
    forever, with no way to ever learn otherwise short of a full re-download.
    """
    _prev, _nxt, delta = _two_generations(conn, tmp_path)

    gone = {(r["tbl"], r["id"]) for r in _rows(delta, "SELECT tbl, id FROM deletions")}
    assert ("products", "ah:wi3") in gone
    assert ("prices", f"ah:wi3{SEP}shelf") in gone


def test_losing_one_price_lane_is_recorded_as_a_deletion(conn, tmp_path):
    """The case that made `deletions` need a composite key.

    `wi2` was a plain shelf price last week and is on promo this week. Its
    shelf row is genuinely gone, not changed. Keyed on `product_id` alone the
    deletion is invisible, the app keeps last week's shelf price beside this
    week's bonus, and the two disagree about what the product costs with
    nothing to say which is current.
    """
    _prev, _nxt, delta = _two_generations(conn, tmp_path)

    gone = {(r["tbl"], r["id"]) for r in _rows(delta, "SELECT tbl, id FROM deletions")}
    assert ("prices", f"ah:wi2{SEP}shelf") in gone
    # ...and the promo lane that replaced it arrives as an upsert.
    lanes = _rows(delta, "SELECT product_id, lane FROM prices WHERE product_id='ah:wi2'")
    assert [(r["product_id"], r["lane"]) for r in lanes] == [("ah:wi2", "promo")]


def test_a_delta_between_identical_builds_is_empty_but_still_valid(conn, tmp_path):
    _price(conn, _product(conn, "wi1", "AH Magere kwark", "kwark_mager"), 1.20)
    a = appdb.build_full(conn, tmp_path / "a.sqlite", on=TODAY)
    b = appdb.build_full(conn, tmp_path / "b.sqlite", on=LATER)

    delta = appdb.build_delta(a, b, tmp_path / "delta.sqlite")

    assert _rows(delta, "SELECT count(*) n FROM products")[0]["n"] == 0
    assert _rows(delta, "SELECT count(*) n FROM deletions")[0]["n"] == 0
    assert _sha(appdb.apply_delta(a, delta, tmp_path / "out.sqlite")) == _sha(b)


def test_applying_a_delta_to_the_wrong_base_is_refused(conn, tmp_path):
    """A delta is only meaningful against the exact build it was cut from.
    Applying it to anything else produces a database that looks fine and is
    quietly wrong, which is worse than a failed sync."""
    prev, _nxt, delta = _two_generations(conn, tmp_path)

    other = connect(path=Path(":memory:"))
    load_seed(other)
    _price(other, _product(other, "wi99", "Iets Anders", "kwark_mager"), 5.00)
    wrong_base = appdb.build_full(other, tmp_path / "wrong.sqlite", on=TODAY)

    with pytest.raises(ValueError, match="cut from"):
        appdb.apply_delta(wrong_base, delta, tmp_path / "out.sqlite")

    assert prev.exists()  # nothing was mutated in place


# -- the manifest --------------------------------------------------------------

def test_the_manifest_names_every_asset_with_its_hash_and_size(conn, tmp_path):
    prev, nxt, delta = _two_generations(conn, tmp_path)

    manifest = appdb.write_manifest(
        tmp_path / "manifest.json", full=nxt, deltas=[delta], generated_at=LATER,
    )
    payload = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))

    assert payload == manifest
    assert payload["full"]["sha256"] == _sha(nxt)
    assert payload["full"]["bytes"] == nxt.stat().st_size
    assert payload["full"]["file"] == nxt.name
    assert payload["deltas"][0]["sha256"] == _sha(delta)
    assert payload["deltas"][0]["from"] == appdb.version_of(prev)
    assert payload["deltas"][0]["to"] == appdb.version_of(nxt)


def test_the_manifest_carries_a_status_field_from_the_very_first_version(
        conn, tmp_path):
    """PLAN-V2 section 7 and milestone 30: the app must be able to show a
    maintenance message if a chain asks the project to stop.

    It ships now, reading `ok`, because a kill switch added later only reaches
    the installs that have already updated - which is exactly the set that does
    not need it. One string, and it has to be in version one.
    """
    _price(conn, _product(conn, "wi1", "AH Magere kwark", "kwark_mager"), 1.20)
    full = appdb.build_full(conn, tmp_path / "full.sqlite", on=TODAY)

    manifest = appdb.write_manifest(tmp_path / "manifest.json", full=full,
                                    deltas=[], generated_at=TODAY)

    assert manifest["status"] == "ok"
    assert manifest["schema_version"] == appdb.SCHEMA_VERSION


def test_the_manifest_is_the_only_place_a_timestamp_lives(conn, tmp_path):
    _price(conn, _product(conn, "wi1", "AH Magere kwark", "kwark_mager"), 1.20)
    full = appdb.build_full(conn, tmp_path / "full.sqlite", on=TODAY)

    manifest = appdb.write_manifest(tmp_path / "manifest.json", full=full,
                                    deltas=[], generated_at=TODAY)

    assert manifest["generated_at"].startswith("2026-09-22")


# -- versioning ----------------------------------------------------------------

def test_a_builds_version_is_its_own_content_hash_not_a_clock(conn, tmp_path):
    """Two builds of the same catalogue are the same version, even a week
    apart. That is what lets the refresh job say "nothing changed" instead of
    publishing an identical 20 MB asset under a new name every night."""
    _price(conn, _product(conn, "wi1", "AH Magere kwark", "kwark_mager"), 1.20)

    a = appdb.build_full(conn, tmp_path / "a.sqlite", on=TODAY)
    b = appdb.build_full(conn, tmp_path / "b.sqlite", on=LATER)

    assert appdb.version_of(a) == appdb.version_of(b)


def test_changing_one_price_changes_the_version(conn, tmp_path):
    product_id = _product(conn, "wi1", "AH Magere kwark", "kwark_mager")
    _price(conn, product_id, 1.20)
    a = appdb.build_full(conn, tmp_path / "a.sqlite", on=TODAY)

    _price(conn, product_id, 0.99, on=LATER)
    b = appdb.build_full(conn, tmp_path / "b.sqlite", on=LATER)

    assert appdb.version_of(a) != appdb.version_of(b)
