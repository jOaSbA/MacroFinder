"""Nutrition-string parser tests. Written before the parser.

Priority 2 of three. AH returns Dutch-keyed strings with units attached, energy as
a dual kJ/kcal string, and comma decimals throughout.
"""

from __future__ import annotations

import pytest

from bonusrank.parsers.nutrition import parse_energy, parse_nutrient, parse_nutrition_block


# -- the mandated cases ------------------------------------------------------


def test_mandated_dual_energy_string():
    e = parse_energy("2244 kJ (538 kcal)")
    assert e.kj == 2244.0
    assert e.kcal == 538.0
    assert not e.kcal_is_derived
    assert not e.needs_review


def test_mandated_plain_gram_value():
    n = parse_nutrient("6.4 g")
    assert n.value == 6.4
    assert n.unit == "g"
    assert not n.is_upper_bound


def test_mandated_upper_bound_is_flagged():
    """'< 0,5 g' parses to 0.5 but must carry the flag - it is a ceiling, not a value."""
    n = parse_nutrient("< 0,5 g")
    assert n.value == 0.5
    assert n.is_upper_bound
    assert not n.needs_review


# -- Dutch comma decimals ----------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        ("6,4 g", 6.4),
        ("6.4 g", 6.4),
        ("0,5 g", 0.5),
        ("54 g", 54.0),
        ("1,2 g", 1.2),
        ("0 g", 0.0),
        ("32 g", 32.0),
        ("1.200 mg", 1200.0),
    ],
)
def test_comma_and_dot_decimals(text, expected):
    assert parse_nutrient(text).value == expected


@pytest.mark.parametrize("text", ["< 0,5 g", "<0,5 g", "&lt; 0,5 g", "minder dan 0,5 g"])
def test_upper_bound_variants(text):
    n = parse_nutrient(text)
    assert n.value == 0.5
    assert n.is_upper_bound


def test_milligram_is_converted_to_grams():
    n = parse_nutrient("1200 mg")
    assert n.value == 1200.0
    assert n.unit == "mg"
    assert n.value_g == 1.2


# -- energy -----------------------------------------------------------------


@pytest.mark.parametrize(
    "text, kj, kcal",
    [
        ("2244 kJ (538 kcal)", 2244.0, 538.0),
        ("2244kJ (538kcal)", 2244.0, 538.0),
        ("1.674 kJ (400 kcal)", 1674.0, 400.0),
        ("398 kJ / 94 kcal", 398.0, 94.0),
    ],
)
def test_energy_formats(text, kj, kcal):
    e = parse_energy(text)
    assert e.kj == kj
    assert e.kcal == kcal


def test_kcal_only_is_accepted():
    e = parse_energy("538 kcal")
    assert e.kcal == 538.0
    assert e.kj is None
    assert not e.kcal_is_derived


def test_kj_only_derives_kcal_and_marks_it():
    """Deriving kcal from kJ is arithmetic, not a guess - but output must mark it
    (copy rule 1: never display a derived/estimated value unmarked)."""
    e = parse_energy("2244 kJ")
    assert e.kj == 2244.0
    assert e.kcal == pytest.approx(536.3, abs=0.5)
    assert e.kcal_is_derived


# -- failure must be loud ----------------------------------------------------


@pytest.mark.parametrize("text", [None, "", "   ", "n.v.t.", "onbekend", "-"])
def test_unparseable_nutrient_goes_to_review(text):
    n = parse_nutrient(text)
    assert n.value is None, "must never invent a macro value"
    assert n.needs_review


@pytest.mark.parametrize("text", [None, "", "geen opgave"])
def test_unparseable_energy_goes_to_review(text):
    e = parse_energy(text)
    assert e.kj is None and e.kcal is None
    assert e.needs_review


def test_raw_text_is_retained():
    assert parse_nutrient("< 0,5 g").raw_text == "< 0,5 g"


# -- the whole AH block ------------------------------------------------------


AH_BLOCK = {
    "Energie": "2244 kJ (538 kcal)",
    "Eiwitten": "6.4 g",
    "Koolhydraten": "54 g",
    "Waarvan suikers": "2.7 g",
    "Vet": "32 g",
    "Waarvan verzadigd": "3.9 g",
    "Voedingsvezel": "4.8 g",
    "Zout": "< 0,5 g",
}


def test_parses_the_observed_ah_block():
    macros = parse_nutrition_block(AH_BLOCK)
    assert macros.kcal_per_100g == 538.0
    assert macros.protein_per_100g == 6.4
    assert macros.carbs_per_100g == 54.0
    assert macros.fat_per_100g == 32.0
    assert macros.fiber_per_100g == 4.8
    assert macros.salt_per_100g == 0.5
    assert not macros.needs_review


def test_missing_protein_is_none_not_zero():
    """Unknown means unknown. A missing protein row must not become 0.0, which
    would rank the product as worthless rather than unrated."""
    macros = parse_nutrition_block({"Energie": "2244 kJ (538 kcal)"})
    assert macros.protein_per_100g is None
    assert macros.needs_review


def test_unknown_dutch_keys_are_collected_not_dropped():
    macros = parse_nutrition_block({**AH_BLOCK, "Cafeïne": "32 mg"})
    assert "Cafeïne" in macros.unmapped_keys
