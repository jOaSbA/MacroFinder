"""Matcher tests. The rule that matters: never guess.

Brief milestone 5 - SKU name to food_type, fuzzy, with a manual override file.
Anything that does not clear the threshold goes to needs_review. A wrong match is
worse than no match, because it silently attaches the wrong protein figure to a
real price and corrupts the ranking with no visible symptom.
"""

from __future__ import annotations

import pytest

from bonusrank.db import connect
from bonusrank.matcher import MatchMethod, Matcher
from bonusrank.seed import load_seed


@pytest.fixture(scope="module")
def matcher():
    conn = connect(path=__import__("pathlib").Path(":memory:"))
    load_seed(conn)
    return Matcher.from_db(conn)


# -- exact and alias matches -------------------------------------------------


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Magere kwark", "kwark_mager"),
        ("AH Magere kwark naturel", "kwark_mager"),
        ("Zaanse Hoeve magere kwark", "kwark_mager"),
        ("Arla Skyr naturel", "skyr_naturel"),
        ("AH Kipfilet", "kipfilet_rauw"),
        ("Hüttenkäse naturel", "huttenkase"),
        ("AH Volkorenbrood", "brood_volkoren"),
        ("Havermout", "havermout"),
        ("AH Tonijnstukken in water", "tonijn_blik_water"),
        ("Pindakaas", "pindakaas"),
    ],
)
def test_matches_common_dutch_skus(matcher, name, expected):
    result = matcher.match(name)
    assert result.food_type_key == expected, f"{name!r} -> {result.food_type_key!r}"
    assert not result.needs_review


def test_brand_prefix_does_not_block_a_match(matcher):
    assert matcher.match("Alpro Plantaardige kwark naturel", brand="Alpro").food_type_key


def test_unit_size_suffix_does_not_block_a_match(matcher):
    assert matcher.match("Magere kwark 500 g").food_type_key == "kwark_mager"
    assert matcher.match("Halfvolle melk 1 l").food_type_key == "melk_halfvol"


# -- the variant distinction the brief insists on ----------------------------


def test_water_and_oil_tuna_are_different_food_types(matcher):
    """Same food, 85 kcal apart. Collapsing them would misprice both."""
    water = matcher.match("Tonijnstukken in water")
    oil = matcher.match("Tonijnstukken in olie")
    assert water.food_type_key == "tonijn_blik_water"
    assert oil.food_type_key == "tonijn_blik_olie"
    assert water.food_type_key != oil.food_type_key


def test_lean_and_full_fat_quark_are_different_food_types(matcher):
    assert matcher.match("Magere kwark").food_type_key == "kwark_mager"
    assert matcher.match("Volle kwark").food_type_key == "kwark_vol"


def test_dry_and_canned_lentils_are_different_food_types(matcher):
    """Dry lentils are 24 g protein/100 g; canned are 7. Same word, 3.4x apart."""
    assert matcher.match("Linzen gedroogd").food_type_key == "linzen_droog"
    assert matcher.match("Linzen uit blik").food_type_key == "linzen_blik"


# -- never guess -------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "Fackelmann voorraadbussen",
        "Curver opbergbakken met deksel",
        "Dreft afwasmiddel",
        "Chateau de Berne Romance",
        "",
    ],
)
def test_non_food_goes_to_review_not_a_guess(matcher, name):
    result = matcher.match(name)
    assert result.food_type_key is None
    assert result.needs_review
    assert result.method is MatchMethod.NONE


def test_a_near_miss_is_still_a_miss(matcher):
    """Something food-shaped but not in the seed must not be forced onto the
    nearest neighbour."""
    result = matcher.match("Sushi handroll zalm avocado")
    if result.food_type_key is not None:
        assert result.score >= matcher.accept_threshold


def test_score_is_reported_for_every_match(matcher):
    result = matcher.match("Magere kwark")
    assert 0.0 < result.score <= 1.0


# -- manual overrides win ----------------------------------------------------


def test_sku_override_beats_fuzzy(matcher):
    m = Matcher(
        aliases=matcher.aliases,
        overrides={"sku": {"ah:999999": "havermout"}},
    )
    result = m.match("Something totally unrecognisable", chain="ah", sku="999999")
    assert result.food_type_key == "havermout"
    assert result.method is MatchMethod.OVERRIDE_SKU
    assert not result.needs_review


def test_contains_override_beats_fuzzy(matcher):
    m = Matcher(aliases=matcher.aliases, overrides={"contains": {"protein pudding": "proteine_pudding"}})
    result = m.match("Alpro Protein pudding chocolade smaak")
    assert result.food_type_key == "proteine_pudding"
    assert result.method is MatchMethod.OVERRIDE_CONTAINS


def test_never_match_list_suppresses_review_noise(matcher):
    """Statiegeld entries are not food and are not worth reviewing every week."""
    m = Matcher(aliases=matcher.aliases, overrides={"never_match": ["statiegeld"]})
    result = m.match("Statiegeld fles 0,25")
    assert result.food_type_key is None
    assert result.method is MatchMethod.EXCLUDED
    assert not result.needs_review, "excluded items must not fill the review queue"


def test_override_to_unknown_food_type_is_reported_not_silent(matcher):
    m = Matcher(aliases=matcher.aliases, overrides={"sku": {"ah:1": "does_not_exist"}})
    result = m.match("whatever", chain="ah", sku="1")
    assert result.food_type_key is None
    assert result.needs_review


# -- a prepared dish is not its named ingredient -----------------------------


@pytest.mark.parametrize(
    "name",
    [
        "AH Tagliatelle met roomsaus verspakket",
        "AH Disney Mike's macaroni verspakket",
        "AH Gesneden verspakket orzo groente en feta",
        "AH Kip-shoarma wraps met groente verspakket",
        "Unox Bruine bonensoep",
        "AH Maaltijdsalade kip pesto",
        "Dr. Oetker Pizza mozzarella",
    ],
)
def test_composite_dishes_are_not_matched_to_an_ingredient(matcher, name):
    """A meal kit that contains pasta is not dry pasta.

    Measured on the real AH catalogue, containment matching filed 'Tagliatelle
    met roomsaus verspakket' as pasta_droog (12 g protein, 360 kcal/100 g dry).
    The kit is fresh pasta plus sauce - nothing like those numbers - so the
    ranking would have been confidently wrong.
    """
    result = matcher.match(name)
    assert result.food_type_key is None, f"{name!r} matched {result.food_type_key!r}"
    assert result.needs_review


def test_the_plain_ingredient_still_matches(matcher):
    """The guard must not cost us the real thing."""
    assert matcher.match("AH Tagliatelle").food_type_key == "pasta_droog"
    assert matcher.match("Griekse feta").food_type_key == "feta"
    assert matcher.match("Unox bruine bonen").food_type_key == "bruine_bonen_blik"


# -- fuzzy is the risky lane and carries a higher bar ------------------------


@pytest.mark.parametrize(
    "name",
    ["Coca-Cola Vanilla", "Beemster Jong belegen 48+ stuk", "Eru Plantaardiger naturel"],
)
def test_weak_fuzzy_matches_are_refused(matcher, name):
    """Real false positives from the first full ingest. SequenceMatcher rates
    unrelated short Dutch strings around 0.82-0.84, so fuzzy needs its own bar."""
    result = matcher.match(name)
    assert result.food_type_key is None
    assert result.needs_review


def test_strong_fuzzy_matches_still_pass(matcher):
    assert matcher.match("Lassie Zilvervlies rijst").food_type_key == "rijst_zilvervlies_droog"
    assert matcher.match("Lassie Pandan rijst").food_type_key == "rijst_wit_droog"


# -- compound dish words (markers must match as substrings) ------------------


@pytest.mark.parametrize(
    "name, marker",
    [
        ("AH Terra Pureersoep pompoen linzen", "soep"),
        ("AH Saladbowl geitenkaas bacon", "salad"),
        ("Alpro Plantaardige variatie vla vanillesmaak", "smaak"),
        ("Hak Easy eats! pasta pomodoro", "pomodoro"),
        ("M&M'S Pinda melkchocolade you're the best mix", "chocolade"),
        ("AH Roerbak zalm knoflook", "roerbak"),
        ("Unox Bruine bonensoep", "soep"),
    ],
)
def test_dish_markers_match_inside_compound_words(matcher, name, marker):
    """Dutch compounds hide the dish word: 'pureersoep', 'bonensoep',
    'saladbowl', 'vanillesmaak'. Token-level markers miss every one of them.
    """
    result = matcher.match(name)
    assert result.food_type_key is None, f"{name!r} matched {result.food_type_key!r}"
    assert result.needs_review


# -- a mix of foods is not any one of them ----------------------------------


def test_multiple_distinct_foods_means_composite(matcher):
    """'Roerbak zalm pangasius garnalen zeezout' names three different food types.
    Whichever one wins, the macros are wrong. No keyword list can enumerate these,
    so the signal is the multiplicity itself."""
    result = matcher.match("Verse mix zalm pangasius garnalen")
    assert result.food_type_key is None
    assert result.needs_review
    assert "distinct food" in result.reason


def test_a_variant_pair_is_not_a_composite(matcher):
    """'magere kwark' and 'kwark' are the same food at different specificity -
    that must not read as two foods."""
    assert matcher.match("Zaanse Hoeve magere kwark").food_type_key == "kwark_mager"


def test_single_food_with_qualifiers_still_matches(matcher):
    """The guard must not fire on ordinary flavour and format qualifiers."""
    assert matcher.match("Grand' Italia Mini penne tradizionali").food_type_key == "pasta_droog"
    assert matcher.match("AH Pangasiusfilet knoflook-citroen").food_type_key == "pangasius"


# -- a drink that mentions fruit is not fruit -------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "Fuze Tea Green ice tea mango chamomile",
        "Karvan Cevitam Siroop go aardbeien",
        "Batu Kombucha passion fruit & mango",
        "Autodrop Most wanted tollende banaan wagens",
        "Danerolles Pistache croissants",
        "S. Pellegrino Clementina",
    ],
)
def test_drinks_and_sweets_naming_fruit_are_not_that_fruit(matcher, name):
    """Adding produce to the seed opened this surface: every soft drink, syrup
    and sweet that names a fruit started matching the fruit itself."""
    result = matcher.match(name)
    assert result.food_type_key is None, f"{name!r} matched {result.food_type_key!r}"


def test_the_actual_fruit_still_matches(matcher):
    assert matcher.match("AH Bananen").food_type_key == "banaan"
    assert matcher.match("AH Verse aardbeien").food_type_key == "aardbeien"


# -- plant-based is a variant, not a synonym --------------------------------


def test_plant_based_mince_is_not_beef_mince(matcher):
    """'AH Terra Plantaardige gehakt' matched rundergehakt (21 g protein, 130
    kcal) because the alias 'gehakt' is contained in it. Plant vs animal is a
    variant dimension like magere vs volle, not a detail."""
    result = matcher.match("AH Terra Plantaardige gehakt gebraden")
    assert result.food_type_key != "rundergehakt"
    if result.food_type_key is not None:
        assert result.food_type_key.startswith("vega")


def test_animal_mince_still_matches(matcher):
    assert matcher.match("AH Rundergehakt").food_type_key == "rundergehakt"


def test_override_rescues_a_food_its_own_dish_marker_would_block(matcher):
    """'sap' is a dish marker so that "Groentesap rode biet appel" stops matching
    apple - but that also blocks genuine juice. The override lane runs before the
    dish guard, which is exactly what the file is for."""
    from bonusrank.matcher import load_overrides
    m = Matcher(aliases=matcher.aliases, overrides=load_overrides())
    assert m.match("AH Sinaasappelsap vers").food_type_key == "sinaasappelsap"
    assert m.match("AH 80% Groentesap rode biet appel").food_type_key is None


# -- flavour mentions and snack formats -------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "AH Zeewiercrackers paprika",
        "AH Rijst rondjes zeezout",
        "1Fruit Appel drink",
        "AH Terra Rode biet aardbei spread",
        "AH Tapenade zongedroogde tomaat",
        "Mora Loempia kip & ham",
        "AH Kipgrillworst met Zaanlander kaas",
        "Hertog Ijssalon mini aardbeien meringue",
        "Weleda Amandel verzachtende gezichtscreme",
    ],
)
def test_flavour_mentions_are_not_the_food(matcher, name):
    """Residual containment false positives from the 2026-09-16 ingest. In each
    the food word is a flavour or a minor ingredient and the product is
    something else entirely - crisps, a spread, a spring roll, a face cream."""
    result = matcher.match(name)
    assert result.food_type_key is None, f"{name!r} matched {result.food_type_key!r}"


def test_a_flavoured_crisp_is_handled_by_name_not_by_category(matcher):
    """'Chio Heartbreakers paprika' carries no dish word - the only signal that it
    is crisps and not a pepper is the product line name.

    Its category ('Borrel, chips, snacks') cannot be excluded wholesale: doing so
    cost 80 matches, because cashewnoten, amandelen, pecannoten and pindas live
    there too and are among the better protein-per-euro buys in the folder. So
    this one goes in the override file by name."""
    assert matcher.match("Chio Heartbreakers paprika").food_type_key is None
    assert matcher.match("AH Ongezouten cashewnoten").food_type_key == "cashewnoten"


def test_the_plain_foods_behind_those_still_match(matcher):
    """The guard must not cost the real thing."""
    assert matcher.match("AH Paprika").food_type_key == "paprika_groente"
    assert matcher.match("AH Verse aardbeien").food_type_key == "aardbeien"
    assert matcher.match("AH Amandelen").food_type_key == "amandelen"
    # 'drink' is a whole-token marker precisely so these compounds survive it.
    assert matcher.match("AH Biologisch haverdrink ongezoet").food_type_key == "haverdrink"


@pytest.mark.parametrize(
    "name",
    [
        "AH Kleintje aioli zongedroogde tomaat",
        "AH Kleintje miso met roomboter",
        "AH Luchtige boter basilicum tomaat",
        "AH Gemarineerde kaasblokjes tomaat kruiden",
        "AH Glutenvrij Haverkoekjes hazelnoot",
    ],
)
def test_seasoning_words_do_not_win_over_the_product(matcher, name):
    """Dips, flavoured butters and biscuits where a seasoning or inclusion word
    is the only thing the matcher can see. 'Luchtige boter basilicum tomaat' is
    butter, not a tomato (0.7 vs 0.9 g protein, 740 vs 20 kcal/100 g)."""
    assert matcher.match(name).food_type_key is None


def test_plain_butter_and_biscuit_ingredients_still_resolve(matcher):
    assert matcher.match("AH Roomboter ongezouten").food_type_key == "boter"
    assert matcher.match("AH Hazelnoten").food_type_key == "hazelnoten"


def test_a_packing_medium_is_not_the_product(matcher):
    """'Princes Tonijnmoot in extra vierge olijfolie' matched the food_type
    olijfolie - it is tuna packed IN oil, not oil. The label macros happened to
    be right (25 g protein, from the tuna), which is exactly what makes this
    class of error dangerous: the ranking looked fine."""
    result = matcher.match("Princes Tonijnmoot in extra vierge olijfolie")
    assert result.food_type_key == "tonijn_blik_olie"


def test_the_oil_itself_still_matches(matcher):
    assert matcher.match("AH Extra vierge olijfolie").food_type_key == "olijfolie"
