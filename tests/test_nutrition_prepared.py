"""Dried products list two nutrition tables: as sold and as prepared.

Hak's dried split peas carry a PREPARED header first (8.4 g protein, 126 kcal
per 100 g cooked) and an UNPREPARED one second (about 24 g, 359 kcal as
sold). Prices are per pack as sold, so dividing them by cooked figures made
the protein three times as expensive as it is. BRIEF section 3's dry-versus-
cooked trap, arriving through the label lane.
"""

from bonusrank.parsers.nutrition import parse_gs1_nutrition


def _header(state, kcal, protein):
    header = {
        "nutrientBasisQuantity": {"value": 100.0, "measurementUnitCode": {"value": "g"}},
        "nutrientDetail": [
            {"nutrientTypeCode": {"value": "ENER-"},
             "quantityContained": [{"value": kcal, "measurementUnitCode": {"value": "kcal"}}]},
            {"nutrientTypeCode": {"value": "PRO-"},
             "quantityContained": [{"value": protein, "measurementUnitCode": {"value": "g"}}]},
        ],
    }
    if state:
        header["preparationStateCode"] = {"value": state}
    return header


def test_the_as_sold_table_wins_over_the_cooked_one():
    info = {"nutrientHeaders": [_header("PREPARED", 126.0, 8.4), _header("UNPREPARED", 359.0, 24.0)]}
    macros = parse_gs1_nutrition(info)
    assert macros.kcal_per_100g == 359.0
    assert macros.protein_per_100g == 24.0


def test_a_single_table_is_used_whatever_it_says():
    macros = parse_gs1_nutrition({"nutrientHeaders": [_header("PREPARED", 126.0, 8.4)]})
    assert macros.protein_per_100g == 8.4


def test_no_state_at_all_keeps_the_first_table():
    info = {"nutrientHeaders": [_header(None, 100.0, 10.0), _header(None, 200.0, 20.0)]}
    assert parse_gs1_nutrition(info).protein_per_100g == 10.0
