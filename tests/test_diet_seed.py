"""Milestone 32: every food type has exactly one diet."""

from collections import Counter

import yaml

from bonusrank import metrics
from bonusrank.seed import seed_files


def _keys():
    return [r["key"] for f in seed_files() for r in yaml.safe_load(f.read_text(encoding="utf-8"))]


def test_every_food_type_has_exactly_one_diet():
    authored = yaml.safe_load(metrics.DIET_PATH.read_text(encoding="utf-8"))
    listed = Counter(k for keys in authored.values() for k in keys)
    assert [k for k, n in listed.items() if n > 1] == []
    assert sorted(set(_keys()) - set(listed)) == []
    assert sorted(set(listed) - set(_keys())) == []


def _tags(food_type):
    return metrics.buckets(protein=None, kcal=None, mass_g=None, meal_kind=None,
                           food_type=food_type, freezable=False, name="x",
                           eur_per_1000kcal=None, bulk_cutoff=None)


def test_vegan_is_also_vegetarian():
    assert _tags("tofu_naturel") == ["vegetarisch", "vegan"]


def test_dairy_is_vegetarian_not_vegan():
    assert _tags("kwark_mager") == ["vegetarisch"]


def test_meat_fish_and_unknown_get_no_diet_tag():
    assert _tags("kipfilet_rauw") == []
    assert _tags("parmezaanse_kaas") == []
    assert _tags(None) == []
