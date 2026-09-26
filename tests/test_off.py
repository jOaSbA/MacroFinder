"""Milestone 36: Open Food Facts label macros for products with a barcode."""

from datetime import date
from pathlib import Path

import httpx
import pytest

from bonusrank import off
from bonusrank.db import connect
from bonusrank.seed import load_seed

TODAY = date(2026, 9, 26)


def _payload(protein=10.0, kcal=60.0, carbs=4.0, fat=0.2, **extra):
    n = {"proteins_100g": protein, "energy-kcal_100g": kcal,
         "carbohydrates_100g": carbs, "fat_100g": fat, **extra}
    return {"status": 1, "product": {"product_name": "Magere kwark", "nutriments": n}}


def test_parses_label_figures():
    m = off.parse_off(_payload())
    assert (m.protein_per_100g, m.kcal_per_100g, m.carbs_per_100g, m.fat_per_100g) == (10.0, 60.0, 4.0, 0.2)
    assert not m.kcal_is_derived


def test_kcal_from_kj_is_marked_derived():
    p = _payload(kcal=None)
    p["product"]["nutriments"].pop("energy-kcal_100g")
    p["product"]["nutriments"]["energy-kj_100g"] = 251
    m = off.parse_off(p)
    assert m.kcal_is_derived and m.kcal_per_100g == pytest.approx(60.0, abs=0.1)


def test_no_protein_or_not_found_is_nothing():
    assert off.parse_off(_payload(protein=None)) is None
    assert off.parse_off({"status": 0}) is None


def test_implausible_entries_are_rejected():
    assert off.parse_off(_payload(protein=150)) is None            # over 100 g
    assert off.parse_off(_payload(protein=10, kcal=900, carbs=4, fat=0.2)) is None  # energy doesn't add up


def test_known_product_without_nutrition_is_missing_not_rejected(conn):
    client = FakeClient({e: {"status": 1, "product": {"nutriments": {}}}
                         for e in ("8718452994274", "8710400241645", "4016598132067")})
    assert off.fetch_off_macros(conn, client, limit=10, on=TODAY) == {"written": 0, "missing": 3, "rejected": 0}


def test_seed_disagreement():
    assert not off.disagrees_with_seed(9.5, 8.0)
    assert off.disagrees_with_seed(1.0, 8.0)       # kwark with a banana's protein
    assert not off.disagrees_with_seed(0.5, 0.0)   # oils: tiny numbers either way


class FakeClient:
    def __init__(self, answers):
        self.answers, self.calls = answers, []

    def get_json(self, url, **_):
        self.calls.append(url)
        ean = url.rsplit("/", 1)[1].split(".")[0]
        answer = self.answers[ean]
        if answer == 404:
            raise httpx.HTTPStatusError("404", request=httpx.Request("GET", url),
                                        response=httpx.Response(404))
        return answer


@pytest.fixture()
def conn():
    c = connect(path=Path(":memory:"))
    load_seed(c)
    ft = c.execute("SELECT id FROM food_types WHERE key='kwark_mager'").fetchone()[0]
    for sku, ean in (("1", "8718452994274"), ("2", "8710400241645"), ("3", "4016598132067")):
        c.execute("INSERT INTO products (chain, sku, name, first_seen, food_type_id, ean) "
                  "VALUES ('jumbo',?,?,?,?,?)", (sku, f"kwark {sku}", "2026-09-26", ft, ean))
    return c


def test_fetch_writes_rejects_and_remembers(conn):
    client = FakeClient({"8718452994274": _payload(), "8710400241645": 404,
                         "4016598132067": _payload(protein=1.0, kcal=60, carbs=13, fat=0.2)})
    stats = off.fetch_off_macros(conn, client, limit=10, on=TODAY)
    assert stats == {"written": 1, "missing": 1, "rejected": 1}
    row = conn.execute("SELECT protein_per_100g, source, confidence FROM product_macros").fetchone()
    assert tuple(row) == (10.0, "off", "medium")

    # A second run asks nothing: one has macros, two were looked up recently.
    client.calls.clear()
    assert off.fetch_off_macros(conn, client, limit=10, on=TODAY) == {"written": 0, "missing": 0, "rejected": 0}
    assert client.calls == []
