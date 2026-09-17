"""Unit-size parser tests. Written before the parser (CLAUDE.md section 1).

Priority 1 of the three testing priorities: unit sizes are the main source of bugs.
The mandated cases from the brief are marked MANDATED.
"""

from __future__ import annotations

import pytest

from bonusrank.parsers.units import SizeKind, parse_unit_size


# -- the eight mandated cases ------------------------------------------------


def test_mandated_one_kilo():
    u = parse_unit_size("1 kg")
    assert u.kind is SizeKind.MASS
    assert u.count == 1
    assert u.unit_size_g == 1000.0
    assert u.total_g == 1000.0
    assert not u.needs_review


def test_mandated_five_hundred_grams():
    u = parse_unit_size("500 g")
    assert u.kind is SizeKind.MASS
    assert u.total_g == 500.0
    assert u.count == 1


def test_mandated_multipack_mass():
    u = parse_unit_size("6 x 125 g")
    assert u.count == 6
    assert u.unit_size_g == 125.0
    assert u.total_g == 750.0


def test_mandated_litres_with_comma_decimal():
    u = parse_unit_size("1,5 L")
    assert u.kind is SizeKind.VOLUME
    assert u.total_ml == 1500.0
    assert u.total_g is None  # needs food_type density to become mass


def test_mandated_per_stuk():
    u = parse_unit_size("per stuk")
    assert u.kind is SizeKind.COUNT
    assert u.count == 1
    assert u.total_g is None
    # Not a parser failure - a countable legitimately has no mass until the
    # food_type supplies g_per_unit (brief section 3.1).
    assert not u.needs_review
    assert u.needs_food_type_mass


def test_mandated_approximate():
    u = parse_unit_size("ca. 300 g")
    assert u.total_g == 300.0
    assert u.is_approximate


def test_mandated_drained_weight():
    u = parse_unit_size("400 g (uitlekgewicht 240 g)")
    assert u.total_g == 400.0
    assert u.drained_g == 240.0


def test_mandated_multipack_volume():
    u = parse_unit_size("2 x 200 ml")
    assert u.kind is SizeKind.VOLUME
    assert u.count == 2
    assert u.unit_size_ml == 200.0
    assert u.total_ml == 400.0


# -- the canned-legume trap (brief section 3.1) ------------------------------


def test_cost_basis_prefers_drained_mass():
    """The single biggest trap in the domain model.

    A 400 g tin draining to 240 g shows ~40% better protein-per-euro if you cost
    it on net weight. Cost metrics must use drained mass.
    """
    tin = parse_unit_size("400 g (uitlekgewicht 240 g)")
    assert tin.cost_basis_g == 240.0
    assert tin.cost_basis_g != tin.total_g


def test_cost_basis_falls_back_to_net_when_not_drained():
    assert parse_unit_size("500 g").cost_basis_g == 500.0


@pytest.mark.parametrize(
    "text, net, drained",
    [
        ("400 g (uitlekgewicht 240 g)", 400.0, 240.0),
        ("425 ml (uitlekgewicht 265 g)", None, 265.0),
        ("580 g, uitlekgewicht 350 g", 580.0, 350.0),
    ],
)
def test_drained_weight_variants(text, net, drained):
    u = parse_unit_size(text)
    assert u.drained_g == drained
    if net is not None:
        assert u.total_g == net


# -- real-world Dutch shelf strings ------------------------------------------


@pytest.mark.parametrize(
    "text, expected_g",
    [
        ("300 gram", 300.0),
        ("250gr", 250.0),
        ("1 kilo", 1000.0),
        ("0,5 kg", 500.0),
        ("2 x 0,5 kg", 1000.0),
        ("4 x 100 g", 400.0),
        ("1,02 kg", 1020.0),
    ],
)
def test_mass_variants(text, expected_g):
    assert parse_unit_size(text).total_g == expected_g


@pytest.mark.parametrize(
    "text, expected_ml",
    [
        ("750 ml", 750.0),
        ("1 l", 1000.0),
        ("1,5 liter", 1500.0),
        ("6 x 250 ml", 1500.0),
        ("33 cl", 330.0),
    ],
)
def test_volume_variants(text, expected_ml):
    assert parse_unit_size(text).total_ml == expected_ml


@pytest.mark.parametrize(
    "text, expected_count",
    [
        ("per stuk", 1),
        ("stuk", 1),
        ("10 stuks", 10),
        ("4 stuks", 4),
        ("6 eieren", 6),
    ],
)
def test_countable_variants(text, expected_count):
    u = parse_unit_size(text)
    assert u.kind is SizeKind.COUNT
    assert u.count == expected_count
    assert u.needs_food_type_mass


@pytest.mark.parametrize("text", ["ca. 300 g", "ca 300 g", "± 300 g", "±300g", "circa 300 g"])
def test_approximation_markers(text):
    u = parse_unit_size(text)
    assert u.is_approximate
    assert u.total_g == 300.0


# -- failure must be loud, never a silent zero -------------------------------


@pytest.mark.parametrize("text", [None, "", "   ", "naar keuze", "diverse smaken", "???"])
def test_unparseable_goes_to_review_never_defaults(text):
    u = parse_unit_size(text)
    assert u.kind is SizeKind.UNKNOWN
    assert u.needs_review, "unparseable unit sizes must reach needs_review"
    assert u.total_g is None
    assert u.total_ml is None
    assert u.cost_basis_g is None, "must never invent a mass"


def test_raw_text_is_always_retained():
    assert parse_unit_size("6 x 125 g").raw_text == "6 x 125 g"
    assert parse_unit_size(None).raw_text is None


# -- "N container à value unit" multipacks -----------------------------------
# Found on Jumbo 2026-09-17: "24 blikken à 33cl" was falling through to the
# SINGLE-unit pattern (matching only "33 cl"), silently dropping the "24" and
# producing a unit price ~24x too high. Not "6 x 125 g" - no "x" at all, a count
# word instead ("blikken", "flesjes", "rollen", ...) followed by "à".


@pytest.mark.parametrize("text,count,per_unit_ml", [
    ("24 blikken à 33cl", 24, 330.0),
    ("24 blikken à 33 cl", 24, 330.0),
    ("6 flesjes à 200 ml", 6, 200.0),
    ("12 blikjes à 0,33 l", 12, 330.0),
])
def test_container_a_multipack_volume(text, count, per_unit_ml):
    u = parse_unit_size(text)
    assert u.kind is SizeKind.VOLUME
    assert u.count == count
    assert u.unit_size_ml == per_unit_ml
    assert u.total_ml == count * per_unit_ml


@pytest.mark.parametrize("text,count,per_unit_g", [
    ("8 rollen à 250 g", 8, 250.0),
    ("4 zakjes à 100 gram", 4, 100.0),
    ("6 pakjes à 200 gram", 6, 200.0),
])
def test_container_a_multipack_mass(text, count, per_unit_g):
    u = parse_unit_size(text)
    assert u.kind is SizeKind.MASS
    assert u.count == count
    assert u.unit_size_g == per_unit_g
    assert u.total_g == count * per_unit_g


def test_container_a_multipack_does_not_regress_the_plain_x_form():
    """The new pattern must not shadow the existing, already-verified one."""
    u = parse_unit_size("6 x 125 g")
    assert u.count == 6
    assert u.unit_size_g == 125.0


def test_container_a_multipack_with_van_instead_of_a():
    u = parse_unit_size("4 pakken van 250 g")
    assert u.kind is SizeKind.MASS
    assert u.count == 4
    assert u.unit_size_g == 250.0
