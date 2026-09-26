"""Product names and brands are tidied when the app database is built."""

from bonusrank.appdb import tidy_text


def test_stray_spaces_collapse():
    assert tidy_text(" Baardolie") == "Baardolie"
    assert tidy_text("Parrano  Geraspte Mozzarella") == "Parrano Geraspte Mozzarella"
    assert tidy_text("Jumbo Verse Franse Friet 1 kg ") == "Jumbo Verse Franse Friet 1 kg"


def test_empty_is_null():
    assert tidy_text("") is None
    assert tidy_text("   ") is None
    assert tidy_text(None) is None
