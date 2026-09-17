"""GS1/GDSN nutrition tests. Written before the parser.

The brief (section 1.1) documents AH nutrition as a Dutch-keyed table of strings
("Eiwitten": "6.4 g"). Verified against the live FIR endpoint on 2026-09-16, it is
not: `tradeItem.nutritionalInformation` is GS1 structured data with numeric values
and GS1 nutrient codes. Both shapes are supported - the string parser still covers
Open Food Facts, other chains and older snapshots.

Fixture below mirrors a real response (Alpro plantaardige kwark, webshopId 486626).
"""

from __future__ import annotations

import pytest

from bonusrank.parsers.nutrition import parse_gs1_nutrition


def _nutrient(code, label, value, unit, precision="APPROXIMATELY"):
    return {
        "nutrientTypeCode": {"value": code, "label": label},
        "quantityContained": [{"value": value, "measurementUnitCode": {"value": unit}}],
        "measurementPrecisionCode": {"value": precision},
    }


REAL_BLOCK = {
    "nutrientHeaders": [
        {
            "nutrientBasisQuantity": {"value": 100.0, "measurementUnitCode": {"value": "g"}},
            "nutrientDetail": [
                _nutrient("ENER-", "Energie", 61.0, "kcal"),
                _nutrient("ENER-", "Energie", 255.0, "kJ"),
                _nutrient("FAT", "Vet", 3.3, "g"),
                _nutrient("FASAT", "waarvan verzadigd", 0.6, "g"),
                _nutrient("CHOAVL", "Koolhydraten", 0.0, "g"),
                _nutrient("SUGAR-", "waarvan suikers", 0.0, "g"),
                _nutrient("FIBTG", "Voedingsvezel", 1.3, "g"),
                _nutrient("PRO-", "Eiwitten", 5.8, "g"),
                _nutrient("SALTEQ", "Zout", 0.33, "g"),
                _nutrient("CA", "Calcium", 120.0, "mg"),
            ],
        }
    ]
}


def test_parses_the_real_gs1_block():
    m = parse_gs1_nutrition(REAL_BLOCK)
    assert m.protein_per_100g == 5.8
    assert m.kcal_per_100g == 61.0
    assert m.fat_per_100g == 3.3
    assert m.saturated_per_100g == 0.6
    assert m.fiber_per_100g == 1.3
    assert m.salt_per_100g == 0.33
    assert not m.needs_review


def test_kcal_comes_from_the_kcal_entry_not_derived_from_kj():
    """ENER- appears twice, once per unit. Picking the wrong one is a 4.2x error."""
    m = parse_gs1_nutrition(REAL_BLOCK)
    assert m.kcal_per_100g == 61.0
    assert not m.kcal_is_derived


def test_a_real_zero_is_zero_not_missing():
    """Alpro kwark genuinely has 0.0 g carbohydrate. Collapsing that to None would
    send a correctly-labelled product to needs_review for no reason."""
    m = parse_gs1_nutrition(REAL_BLOCK)
    assert m.carbs_per_100g == 0.0
    assert m.sugars_per_100g == 0.0
    assert m.carbs_per_100g is not None


def test_basis_quantity_and_unit_are_recorded():
    m = parse_gs1_nutrition(REAL_BLOCK)
    assert m.basis_quantity == 100.0
    assert m.basis_unit == "g"


def test_per_100_ml_basis_is_recorded_not_silently_treated_as_grams():
    """Brief section 2: a handful of foods are expressed per 100 ml. Treating ml as
    g silently would misprice every drink by its density."""
    block = {
        "nutrientHeaders": [
            {
                "nutrientBasisQuantity": {"value": 100.0, "measurementUnitCode": {"value": "ml"}},
                "nutrientDetail": [
                    _nutrient("ENER-", "Energie", 46.0, "kcal"),
                    _nutrient("PRO-", "Eiwitten", 3.4, "g"),
                ],
            }
        ]
    }
    m = parse_gs1_nutrition(block)
    assert m.basis_unit == "ml"
    assert m.protein_per_100g == 3.4


def test_non_hundred_basis_is_normalised():
    block = {
        "nutrientHeaders": [
            {
                "nutrientBasisQuantity": {"value": 250.0, "measurementUnitCode": {"value": "g"}},
                "nutrientDetail": [
                    _nutrient("PRO-", "Eiwitten", 25.0, "g"),
                    _nutrient("ENER-", "Energie", 150.0, "kcal"),
                ],
            }
        ]
    }
    m = parse_gs1_nutrition(block)
    assert m.protein_per_100g == pytest.approx(10.0)
    assert m.kcal_per_100g == pytest.approx(60.0)
    assert m.basis_quantity == 100.0


def test_missing_protein_goes_to_review():
    block = {
        "nutrientHeaders": [
            {
                "nutrientBasisQuantity": {"value": 100.0, "measurementUnitCode": {"value": "g"}},
                "nutrientDetail": [_nutrient("ENER-", "Energie", 61.0, "kcal")],
            }
        ]
    }
    m = parse_gs1_nutrition(block)
    assert m.protein_per_100g is None
    assert m.needs_review


@pytest.mark.parametrize("block", [None, {}, {"nutrientHeaders": []}])
def test_absent_nutrition_goes_to_review(block):
    m = parse_gs1_nutrition(block)
    assert m.protein_per_100g is None
    assert m.kcal_per_100g is None
    assert m.needs_review


def test_unmapped_gs1_codes_are_collected_not_dropped():
    m = parse_gs1_nutrition(REAL_BLOCK)
    assert "CA" in m.unmapped_keys


def test_kj_only_derives_kcal_and_marks_it():
    block = {
        "nutrientHeaders": [
            {
                "nutrientBasisQuantity": {"value": 100.0, "measurementUnitCode": {"value": "g"}},
                "nutrientDetail": [
                    _nutrient("ENER-", "Energie", 255.0, "kJ"),
                    _nutrient("PRO-", "Eiwitten", 5.8, "g"),
                ],
            }
        ]
    }
    m = parse_gs1_nutrition(block)
    assert m.kcal_per_100g == pytest.approx(60.9, abs=0.5)
    assert m.kcal_is_derived
