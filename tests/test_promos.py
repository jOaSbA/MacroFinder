"""Promo-mechanic parser tests. Written before the parser.

Priority 3 of three. Covers the full brief section 3.2 table, the real AH typed
vocabulary observed on 2026-09-16, and the hard requirement that an unparsed
mechanic never silently becomes "no discount".

Two numbers matter and they are different: the effective multiplier and the
required quantity. Both are asserted everywhere.
"""

from __future__ import annotations

import pytest

from bonusrank.parsers.promos import PromoKind, parse_ah_label, parse_promo_text


# -- brief section 3.2, row by row -------------------------------------------


@pytest.mark.parametrize("text", ["25% korting", "25% KORTING", "Alles 25% korting"])
def test_percent_off(text):
    p = parse_promo_text(text)
    assert p.kind is PromoKind.PERCENT_OFF
    assert p.required_quantity == 1
    assert p.effective_multiplier == pytest.approx(0.75)


def test_percent_off_thirty_five():
    p = parse_promo_text("Alles 35% korting")
    assert p.effective_multiplier == pytest.approx(0.65)
    assert p.required_quantity == 1


@pytest.mark.parametrize("text", ["2e halve prijs", "2E HALVE PRIJS", "2e HALVE PRIJS"])
def test_second_half_price(text):
    p = parse_promo_text(text)
    assert p.kind is PromoKind.SECOND_HALF_PRICE
    assert p.required_quantity == 2
    assert p.effective_multiplier == pytest.approx(0.75)


@pytest.mark.parametrize("text", ["1+1 gratis", "1 + 1 GRATIS"])
def test_one_plus_one_free(text):
    p = parse_promo_text(text)
    assert p.kind is PromoKind.X_PLUS_Y_FREE
    assert p.required_quantity == 2
    assert p.effective_multiplier == pytest.approx(0.50)


def test_two_plus_one_free():
    p = parse_promo_text("2+1 gratis")
    assert p.required_quantity == 3
    assert p.effective_multiplier == pytest.approx(2 / 3)


@pytest.mark.parametrize(
    "text, qty, mult",
    [
        ("2+2 gratis", 4, 0.5),
        ("5+1 gratis", 6, 5 / 6),
        ("3+1 gratis", 4, 0.75),
    ],
)
def test_x_plus_y_free_is_general(text, qty, mult):
    """1+1 and 2+1 are not special cases - AH ships 2+2 and 5+1 too."""
    p = parse_promo_text(text)
    assert p.required_quantity == qty
    assert p.effective_multiplier == pytest.approx(mult)


@pytest.mark.parametrize(
    "text, qty, total",
    [
        ("2 voor 3.00", 2, 3.00),
        ("3 voor 5.00", 3, 5.00),
        ("2 VOOR 0.99", 2, 0.99),
        ("4 voor 9,99", 4, 9.99),
    ],
)
def test_x_for_y(text, qty, total):
    p = parse_promo_text(text)
    assert p.kind is PromoKind.X_FOR_Y
    assert p.required_quantity == qty
    assert p.total_promo_price == total
    # Multiplier is unknowable without the shelf price.
    assert p.effective_multiplier is None


@pytest.mark.parametrize("text", ["nu 1.99", "voor 1.99", "VOOR 1.99"])
def test_fixed_price(text):
    p = parse_promo_text(text)
    assert p.kind is PromoKind.FIXED_PRICE
    assert p.required_quantity == 1
    assert p.total_promo_price == 1.99
    assert p.effective_multiplier is None


def test_second_percent_off():
    p = parse_promo_text("50% korting op de 2e")
    assert p.kind is PromoKind.SECOND_PERCENT_OFF
    assert p.required_quantity == 2
    assert p.effective_multiplier == pytest.approx(0.75)


@pytest.mark.parametrize(
    "text, qty, mult",
    [
        ("vanaf 3 stuks 30% korting", 3, 0.70),
        ("10% korting per 2 stuks", 2, 0.90),
        ("vanaf 2 stuks 25% korting", 2, 0.75),
    ],
)
def test_bulk_tier(text, qty, mult):
    p = parse_promo_text(text)
    assert p.kind is PromoKind.BULK_TIER
    assert p.required_quantity == qty
    assert p.effective_multiplier == pytest.approx(mult)


@pytest.mark.parametrize("text", ["Prijsfavoriet", "Elke dag lage prijs", "PRIJSFAVORIET"])
def test_not_a_promo(text):
    p = parse_promo_text(text)
    assert p.kind is PromoKind.NOT_A_PROMO
    assert p.effective_multiplier == 1.0
    assert p.required_quantity == 1
    assert not p.needs_review


# -- the hard requirement: never silently default ----------------------------


@pytest.mark.parametrize("text", [None, "", "ACTIE", "BONUS", "???", "zie verpakking"])
def test_unknown_never_defaults_to_no_discount(text):
    """Brief section 3.2: any unparsed mechanic goes to a review queue. Never
    silently default to 'no discount' or 'assume 25%'."""
    p = parse_promo_text(text)
    assert p.kind is PromoKind.UNKNOWN
    assert p.needs_review
    assert p.effective_multiplier is None, "an unknown mechanic must not claim a multiplier"
    assert p.effective_unit_price(shelf_price=4.00) is None, "must refuse to price an unknown"


def test_unknown_is_distinct_from_not_a_promo():
    """'Prijsfavoriet' means no discount (multiplier 1.0). 'ACTIE' means we do not
    know. Collapsing the two would quietly mis-rank every unparsed offer."""
    assert parse_promo_text("Prijsfavoriet").effective_multiplier == 1.0
    assert parse_promo_text("ACTIE").effective_multiplier is None


def test_raw_text_is_always_retained():
    assert parse_promo_text("1 + 1 GRATIS").raw_text == "1 + 1 GRATIS"
    assert parse_promo_text("ACTIE").raw_text == "ACTIE"


# -- effective unit price ----------------------------------------------------


@pytest.mark.parametrize(
    "text, shelf, expected",
    [
        ("25% korting", 4.00, 3.00),
        ("1+1 gratis", 4.00, 2.00),
        ("2+1 gratis", 3.00, 2.00),
        ("2e halve prijs", 4.00, 3.00),
        ("2 voor 3.00", 2.00, 1.50),
        ("3 voor 5.00", 2.00, 5 / 3),
        ("voor 1.99", 2.99, 1.99),
        ("Prijsfavoriet", 2.50, 2.50),
    ],
)
def test_effective_unit_price(text, shelf, expected):
    assert parse_promo_text(text).effective_unit_price(shelf_price=shelf) == pytest.approx(expected)


def test_total_outlay_reflects_required_quantity():
    """Copy rule 3: always show required quantity next to a promo price. A 1+1 on
    1 kg kwark is great per unit and still means 2 kg in the fridge."""
    p = parse_promo_text("1+1 gratis")
    assert p.effective_unit_price(shelf_price=4.00) == pytest.approx(2.00)
    assert p.total_outlay(shelf_price=4.00) == pytest.approx(4.00)
    assert p.required_quantity == 2


# -- AH typed labels (observed 2026-09-16) -----------------------------------


def _label(code, desc, price=None):
    return {"code": code, "defaultDescription": desc, "price": price}


def test_ah_x_for_y_label():
    p = parse_ah_label(_label("DISCOUNT_X_FOR_Y", "2 voor 0.99", 0.99))
    assert p.kind is PromoKind.X_FOR_Y
    assert p.required_quantity == 2
    assert p.total_promo_price == 0.99


def test_ah_percentage_label():
    p = parse_ah_label(_label("DISCOUNT_PERCENTAGE", "40% korting"))
    assert p.kind is PromoKind.PERCENT_OFF
    assert p.effective_multiplier == pytest.approx(0.60)


def test_ah_fixed_price_label():
    p = parse_ah_label(_label("DISCOUNT_FIXED_PRICE", "voor 1.49", 1.49))
    assert p.kind is PromoKind.FIXED_PRICE
    assert p.total_promo_price == 1.49


def test_ah_x_plus_y_free_label():
    p = parse_ah_label(_label("DISCOUNT_X_PLUS_Y_FREE", "2+2 gratis"))
    assert p.required_quantity == 4
    assert p.effective_multiplier == pytest.approx(0.5)


def test_ah_fallback_label_is_a_real_price_not_an_unknown():
    """DISCOUNT_FALLBACK looks generic ('ACTIE' headline) but carries a real price.
    Treating it as unknown would discard 7 of 232 offers for no reason."""
    p = parse_ah_label(_label("DISCOUNT_FALLBACK", "voor 0.55", 0.55))
    assert p.kind is PromoKind.FIXED_PRICE
    assert p.total_promo_price == 0.55
    assert not p.needs_review


@pytest.mark.parametrize("code, desc", [("DISCOUNT_ACTION", "ACTIE"), ("DISCOUNT_BONUS", "BONUS")])
def test_ah_contentless_labels_go_to_review(code, desc):
    """These carry no number anywhere. They are the genuine review cases."""
    p = parse_ah_label(_label(code, desc))
    assert p.kind is PromoKind.UNKNOWN
    assert p.needs_review
    assert p.effective_multiplier is None


def test_ah_amount_off_label():
    p = parse_ah_label(_label("DISCOUNT_AMOUNT", "€1.50 euro korting"))
    assert p.kind is PromoKind.AMOUNT_OFF
    assert p.amount_off == 1.50
    assert p.effective_unit_price(shelf_price=5.00) == pytest.approx(3.50)


def test_ah_weight_label_prices_per_hundred_grams():
    """'per 100 GRAM voor EUR 1.69' is a price per weight, not per pack. Without the
    pack mass there is no unit price, and inventing one would corrupt the ranking."""
    p = parse_ah_label(_label("DISCOUNT_WEIGHT", "per 100 GRAM voor €1.69", 1.69))
    assert p.kind is PromoKind.PRICE_PER_WEIGHT
    assert p.price_per_100g == 1.69
    assert p.effective_unit_price(shelf_price=5.00) is None
    assert p.effective_unit_price(shelf_price=5.00, unit_size_g=500.0) == pytest.approx(8.45)


def test_ah_percentage_per_amount_label_is_a_bulk_tier():
    p = parse_ah_label(_label("DISCOUNT_PERCENTAGE_PER_AMOUNT", "10% korting per 2 STUKS"))
    assert p.kind is PromoKind.BULK_TIER
    assert p.required_quantity == 2
    assert p.effective_multiplier == pytest.approx(0.90)


def test_unknown_ah_code_goes_to_review_not_a_guess():
    p = parse_ah_label(_label("DISCOUNT_SOMETHING_NEW_2027", "wat dan ook"))
    assert p.kind is PromoKind.UNKNOWN
    assert p.needs_review


def test_ah_label_beats_headline_string():
    """discountDescription is sometimes None while the typed label has the data."""
    p = parse_ah_label(_label("DISCOUNT_X_FOR_Y", "3 voor 5.00", 5.00), headline=None)
    assert p.kind is PromoKind.X_FOR_Y
    assert p.required_quantity == 3
