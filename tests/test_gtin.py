"""Milestone 35: barcodes. Pure parser, no I/O."""

from bonusrank.parsers.gtin import gs1_valid, jumbo_image_gtin, normalise_gtin


def test_check_digit():
    assert gs1_valid("8718452994274")
    assert not gs1_valid("8718452994275")
    assert gs1_valid("96385074")          # EAN-8
    assert not gs1_valid("12345")


def test_normalise_strips_the_gtin14_padding():
    assert normalise_gtin("08710400241645") == "8710400241645"
    assert normalise_gtin(" 8710400241645 ") == "8710400241645"
    assert normalise_gtin("8710400241646") is None     # bad check digit
    assert normalise_gtin(None) is None


def test_jumbo_image_with_ean_before_the_index():
    url = ("https://www.jumbo.com/dam-images/fit-in/360x360/Products/"
           "10092026_1789058693520_1789058703978_8718452994274_1.png")
    assert jumbo_image_gtin(url) == "8718452994274"


def test_jumbo_image_with_padded_ean():
    url = ("https://www.jumbo.com/dam-images/fit-in/360x360/Products/"
           "12032026_1773288694685_1773288700488_100005_PAK_04014400400007_C1N1.png")
    assert jumbo_image_gtin(url) == "4014400400007"


def test_jumbo_image_repeating_the_ean():
    url = ("https://www.jumbo.com/dam-images/fit-in/360x360/Products/"
           "4016598132067_1788880531985_04016598132067_C1N0.png")
    assert jumbo_image_gtin(url) == "4016598132067"


def test_millisecond_timestamps_are_never_barcodes():
    # 1789058693520 happens to be 13 digits; it is a timestamp.
    url = "https://www.jumbo.com/dam-images/Products/10092026_1789058693520_1.png"
    assert jumbo_image_gtin(url) is None


def test_two_different_barcodes_is_no_answer():
    url = ("https://www.jumbo.com/dam-images/Products/"
           "8718452994274_4016598132067_1.png")
    assert jumbo_image_gtin(url) is None


def test_other_urls():
    assert jumbo_image_gtin(None) is None
    assert jumbo_image_gtin("https://static.ah.nl/dam/product/AHI_6743?rendition=400x400") is None
