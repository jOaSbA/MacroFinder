"""Milestone 35: barcodes filled from data already on disk."""

import json
from pathlib import Path

import pytest

from bonusrank.db import connect
from bonusrank.ingest import fill_eans

JUMBO_IMG = ("https://www.jumbo.com/dam-images/fit-in/360x360/Products/"
             "10092026_1789058693520_1789058703978_8718452994274_1.png")


@pytest.fixture()
def conn():
    c = connect(path=Path(":memory:"))
    for chain, sku, img in (("jumbo", "735840BAK", JUMBO_IMG), ("ah", "100232", None),
                            ("jumbo", "1", "https://www.jumbo.com/Products/no_code_1.png")):
        c.execute("INSERT INTO products (chain, sku, name, first_seen, image_url) "
                  "VALUES (?,?,?,?,?)", (chain, sku, sku, "2026-09-26", img))
    return c


def _ean(conn, chain, sku):
    return conn.execute("SELECT ean FROM products WHERE chain=? AND sku=?", (chain, sku)).fetchone()[0]


def test_jumbo_from_the_image_and_ah_from_the_saved_detail_call(conn, tmp_path):
    folder = tmp_path / "ah" / "mobile-services-product-detail-v4-fir-100232"
    folder.mkdir(parents=True)
    (folder / "2026-09-17.json").write_text(json.dumps({"tradeItem": {"gtin": "08710400241645"}}))

    assert fill_eans(conn, raw_root=tmp_path) == {"jumbo": 1, "ah": 1}
    assert _ean(conn, "jumbo", "735840BAK") == "8718452994274"
    assert _ean(conn, "ah", "100232") == "8710400241645"
    assert _ean(conn, "jumbo", "1") is None


def test_a_second_run_changes_nothing(conn, tmp_path):
    fill_eans(conn, raw_root=tmp_path)
    assert fill_eans(conn, raw_root=tmp_path) == {"jumbo": 0, "ah": 0}
