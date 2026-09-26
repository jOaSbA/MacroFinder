"""The four metrics and the macro buckets. Milestone 20.

The rule that matters most: a product with unknown macros gets NULL metrics
and no macro buckets. Zero would rank it first on every "cheapest protein"
sort, which is the worst lie this app could tell.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from bonusrank import appdb, metrics
from bonusrank.db import connect
from bonusrank.seed import load_seed

TODAY = date(2026, 9, 22)


# -- the four metrics ---------------------------------------------------------

def test_protein_density_is_the_label_figure():
    assert metrics.protein_density(10.3) == 10.3


def test_protein_ratio_is_grams_per_100_kcal():
    assert metrics.protein_ratio(10.0, 60.0) == pytest.approx(16.667, rel=1e-3)


def test_eur_per_100g_protein():
    # 500 g pot at €1.00 with 10 g/100 g protein holds 50 g protein.
    assert metrics.eur_per_100g_protein(1.00, 500, 10.0) == pytest.approx(2.00)


def test_eur_per_1000kcal():
    # 500 g at 60 kcal/100 g is 300 kcal.
    assert metrics.eur_per_1000kcal(1.00, 500, 60.0) == pytest.approx(3.333, rel=1e-3)


@pytest.mark.parametrize("args", [
    (None, 500, 10.0), (1.0, None, 10.0), (1.0, 500, None), (1.0, 0, 10.0), (1.0, 500, 0.0),
])
def test_any_unknown_input_gives_none_never_zero(args):
    assert metrics.eur_per_100g_protein(*args) is None
    assert metrics.eur_per_1000kcal(*args) is None


def test_ratio_with_unknown_or_zero_kcal_is_none():
    assert metrics.protein_ratio(10.0, None) is None
    assert metrics.protein_ratio(None, 100) is None
    assert metrics.protein_ratio(10.0, 0) is None


# -- buckets -----------------------------------------------------------------

def _b(**kw):
    base = dict(protein=None, kcal=None, mass_g=None, meal_kind=None, food_type=None,
                freezable=False, name="", eur_per_1000kcal=None, bulk_cutoff=None)
    base.update(kw)
    return metrics.buckets(**base)


def test_eiwitbom_at_20g():
    assert "eiwitbom" in _b(protein=20.0)
    assert "eiwitbom" not in _b(protein=19.9)


def test_cut_at_10g_per_100kcal():
    assert "cut" in _b(protein=12.0, kcal=100.0)
    assert "cut" not in _b(protein=9.0, kcal=100.0)


def test_bulk_is_the_cheap_kcal_quartile():
    assert "bulk" in _b(eur_per_1000kcal=1.0, bulk_cutoff=1.5)
    assert "bulk" not in _b(eur_per_1000kcal=2.0, bulk_cutoff=1.5)


def test_snel_eiwit_is_a_ready_snack_with_15g_a_serving():
    assert "snel_eiwit" in _b(protein=30.0, mass_g=60, meal_kind="snack")
    assert "snel_eiwit" not in _b(protein=30.0, mass_g=40, meal_kind="snack")  # 12 g
    assert "snel_eiwit" not in _b(protein=30.0, mass_g=500, meal_kind="ingredient")


def test_ontbijt_needs_the_list_and_20g_a_serving():
    assert "ontbijt" in _b(protein=10.0, mass_g=500, food_type="skyr_naturel")
    assert "ontbijt" not in _b(protein=10.0, mass_g=150, food_type="skyr_naturel")
    assert "ontbijt" not in _b(protein=10.0, mass_g=500, food_type="kipfilet_rauw")


def test_meal_prep_is_freezable_protein():
    assert "meal_prep" in _b(protein=22.0, freezable=True, meal_kind="ingredient")
    assert "meal_prep" not in _b(protein=22.0, freezable=False, meal_kind="ingredient")


def test_supplement_by_name_even_without_a_food_type():
    assert "supplement" in _b(name="AH Whey proteïne vanille")
    assert "supplement" in _b(food_type="whey_poeder")
    assert "supplement" not in _b(name="Kwark naturel")


def test_unknown_macros_get_no_macro_buckets():
    # Only the diet tag, which is about what skyr is, not what's in it.
    assert _b(mass_g=500, meal_kind="snack", food_type="skyr_naturel", freezable=True) == ["vegetarisch"]


def test_bulk_cutoff_is_the_bottom_quartile():
    assert metrics.bulk_cutoff([4.0, 1.0, 3.0, 2.0, None]) == pytest.approx(1.75)
    assert metrics.bulk_cutoff([None, None]) is None


# -- in the published database ------------------------------------------------

@pytest.fixture()
def built(tmp_path):
    conn = connect(path=Path(":memory:"))
    load_seed(conn)
    ft = conn.execute("SELECT id FROM food_types WHERE key='kwark_mager'").fetchone()[0]
    rows = [("wi1", "AH Magere kwark", "500 g", ft), ("wi2", "Mystery product", "500 g", None)]
    for sku, name, unit, fid in rows:
        conn.execute(
            "INSERT INTO products (chain, sku, name, raw_unit_text, food_type_id, category, "
            "first_seen) VALUES ('ah',?,?,?,?,'Zuivel, eieren','2026-09-22')",
            (sku, name, unit, fid))
        pid = conn.execute("SELECT id FROM products WHERE sku=?", (sku,)).fetchone()[0]
        conn.execute(
            "INSERT INTO price_observations (product_id, observed_at, shelf_price, "
            "promo_mechanic, promo_raw_text, required_quantity, effective_unit_price, "
            "is_personal_offer, valid_from, valid_to) "
            "VALUES (?,?,1.99,'fixed_price','nu 1.00',1,1.00,0,'2026-09-20','2026-09-27')",
            (pid, TODAY.isoformat()))
    out = appdb.build_full(conn, tmp_path / "full.sqlite", on=TODAY)
    db = sqlite3.connect(out)
    db.row_factory = sqlite3.Row
    yield db
    db.close()


def test_a_known_product_has_all_four_metrics(built):
    p = built.execute(
        "SELECT p.*, pr.eur_per_100g_protein, pr.eur_per_1000kcal, pr.discount_pct "
        "FROM products p JOIN prices pr ON pr.product_id=p.id WHERE p.sku='wi1'").fetchone()
    assert p["protein_per_100g"] is not None
    assert p["protein_per_100kcal"] is not None
    assert p["eur_per_100g_protein"] is not None
    assert p["eur_per_1000kcal"] is not None
    assert p["discount_pct"] == pytest.approx(49.7, abs=0.1)
    assert p["macro_source"] and p["macro_confidence"]


def test_unknown_macros_are_null_not_zero(built):
    p = built.execute(
        "SELECT p.*, pr.eur_per_100g_protein, pr.eur_per_1000kcal "
        "FROM products p JOIN prices pr ON pr.product_id=p.id WHERE p.sku='wi2'").fetchone()
    for col in ("protein_per_100g", "kcal_per_100g", "protein_per_100kcal",
                "eur_per_100g_protein", "eur_per_1000kcal"):
        assert p[col] is None, col
    assert p["buckets"] == ""


def test_a_macro_sort_leaves_unknowns_out(built):
    ranked = built.execute(
        "SELECT p.sku FROM products p JOIN prices pr ON pr.product_id=p.id "
        "WHERE pr.eur_per_100g_protein IS NOT NULL ORDER BY pr.eur_per_100g_protein").fetchall()
    assert [r[0] for r in ranked] == ["wi1"]
