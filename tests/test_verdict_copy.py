"""The verdict sentence the Meals tab shows. "-2 g eiwit" read like a typo."""

from bonusrank.archetypes import _protein_phrase


def test_more_protein_says_meer():
    assert _protein_phrase(7.4) == ", 7 g meer eiwit"


def test_less_protein_says_minder():
    assert _protein_phrase(-2.2) == ", 2 g minder eiwit"


def test_a_rounding_difference_is_the_same_protein():
    assert _protein_phrase(0.3) == ", evenveel eiwit"
