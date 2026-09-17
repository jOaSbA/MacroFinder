"""Unit-price cross-check tests. Written before the implementation.

Brief section 7: stores publish their own unit price ("prijs per kilo EUR 6.49").
Compare it against the computed unit price on every ingest; a mismatch above 2% is
a parser bug and must be logged loudly.

This is the only self-check the pipeline has against a silently wrong unit-size
parse, which is the bug class the brief names as most likely.
"""

from __future__ import annotations

import pytest

from bonusrank.parsers.unit_price import PriceBasis, compare_unit_price, parse_stated_unit_price
from bonusrank.parsers.units import parse_unit_size


# -- parsing the stated string ----------------------------------------------


@pytest.mark.parametrize(
    "text, price, basis",
    [
        ("normale prijs per kg €3.96", 3.96, PriceBasis.PER_KG),
        ("normale prijs per liter €1.50", 1.50, PriceBasis.PER_LITRE),
        ("prijs per kilo €6.49", 6.49, PriceBasis.PER_KG),
        ("per kg €12,95", 12.95, PriceBasis.PER_KG),
        ("normale prijs per 100 g €1.20", 1.20, PriceBasis.PER_100G),
    ],
)
def test_parse_stated_unit_price(text, price, basis):
    s = parse_stated_unit_price(text)
    assert s.price == price
    assert s.basis is basis
    assert not s.needs_review


@pytest.mark.parametrize("text", [None, "", "zie schap", "per stuk"])
def test_unparseable_stated_price_goes_to_review(text):
    s = parse_stated_unit_price(text)
    assert s.price is None
    assert s.needs_review


# -- the comparison ---------------------------------------------------------


def test_matching_unit_price_passes():
    """755 g at EUR 2.99 is EUR 3.96/kg - exactly what AH states."""
    check = compare_unit_price(
        parse_stated_unit_price("normale prijs per kg €3.96"),
        shelf_price=2.99,
        size=parse_unit_size("755 g"),
    )
    assert check.comparable
    assert check.within_tolerance
    assert check.computed == pytest.approx(3.96, abs=0.01)


def test_mismatch_above_two_percent_is_flagged():
    """A unit size parsed as 500 g when it is really 400 g shows up here as a 25%
    deviation. That is the whole point of the check."""
    check = compare_unit_price(
        parse_stated_unit_price("normale prijs per kg €10.00"),
        shelf_price=4.00,
        size=parse_unit_size("500 g"),
    )
    assert check.comparable
    assert not check.within_tolerance
    assert check.deviation == pytest.approx(0.20, abs=0.01)


def test_just_inside_tolerance_passes():
    check = compare_unit_price(
        parse_stated_unit_price("normale prijs per kg €10.10"),
        shelf_price=1.00,
        size=parse_unit_size("100 g"),
    )
    assert check.within_tolerance  # 1% out


def test_litre_basis_uses_volume():
    check = compare_unit_price(
        parse_stated_unit_price("normale prijs per liter €2.00"),
        shelf_price=1.00,
        size=parse_unit_size("500 ml"),
    )
    assert check.comparable
    assert check.within_tolerance


def test_per_hundred_grams_basis():
    check = compare_unit_price(
        parse_stated_unit_price("normale prijs per 100 g €1.00"),
        shelf_price=2.00,
        size=parse_unit_size("200 g"),
    )
    assert check.within_tolerance


# -- the drained-weight subtlety --------------------------------------------


def test_crosscheck_uses_net_mass_not_drained_mass():
    """AH states price per kg on NET weight. The ranking costs on DRAINED weight.

    Feeding drained mass into the cross-check would fire a false parser alarm on
    every tin of chickpeas, so the check must deliberately use net mass even
    though the ranking must not.
    """
    tin = parse_unit_size("400 g (uitlekgewicht 240 g)")
    assert tin.cost_basis_g == 240.0  # what the ranking uses
    check = compare_unit_price(
        parse_stated_unit_price("normale prijs per kg €2.50"),
        shelf_price=1.00,
        size=tin,
    )
    assert check.within_tolerance, "cross-check must compare on net mass"


# -- refusing to compare ----------------------------------------------------


def test_countable_size_is_not_comparable():
    """'per stuk' has no mass, so there is nothing to compare. Not comparable is
    not the same as failing - it must not be reported as a parser bug."""
    check = compare_unit_price(
        parse_stated_unit_price("normale prijs per kg €5.00"),
        shelf_price=1.00,
        size=parse_unit_size("per stuk"),
    )
    assert not check.comparable
    assert check.within_tolerance is None


def test_basis_mismatch_is_not_comparable():
    """A per-litre claim against a mass-only size cannot be checked without the
    food_type density."""
    check = compare_unit_price(
        parse_stated_unit_price("normale prijs per liter €2.00"),
        shelf_price=1.00,
        size=parse_unit_size("500 g"),
    )
    assert not check.comparable


def test_missing_shelf_price_is_not_comparable():
    check = compare_unit_price(
        parse_stated_unit_price("normale prijs per kg €5.00"),
        shelf_price=None,
        size=parse_unit_size("500 g"),
    )
    assert not check.comparable


def test_a_zero_stated_price_does_not_divide_by_zero():
    """Measured on real Aldi data 2026-09-17: a promo item's basePriceValue
    came through as 0. That is a data-quality artefact, not a comparable basis,
    and must not crash the ingest of every SKU behind it."""
    check = compare_unit_price(
        parse_stated_unit_price("per kg 0"),
        shelf_price=1.99,
        size=parse_unit_size("500 g"),
    )
    assert not check.comparable


# -- a mismatch often reveals the real cost basis ----------------------------


def test_mismatch_reports_the_mass_the_store_implies():
    """Real case, AH 2026-09-16: sun-dried tomatoes labelled '180 g' priced per kg
    on 90 g - the drained weight. The label never says 'uitlekgewicht', so this
    check is the only place the drained mass is visible.
    """
    check = compare_unit_price(
        parse_stated_unit_price("normale prijs per kg \u20ac53.22"),
        shelf_price=4.79,
        size=parse_unit_size("180 g"),
    )
    assert not check.within_tolerance
    assert check.implied_quantity_g == pytest.approx(90.0, abs=1.0)
    assert check.implied_fraction == pytest.approx(0.50, abs=0.01)


def test_matching_check_implies_the_labelled_mass():
    check = compare_unit_price(
        parse_stated_unit_price("normale prijs per kg \u20ac3.96"),
        shelf_price=2.99,
        size=parse_unit_size("755 g"),
    )
    assert check.implied_quantity_g == pytest.approx(755.0, abs=5.0)
