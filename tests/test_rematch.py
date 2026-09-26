"""Re-running the matcher over products already stored.

Matcher and seed fixes used to reach a product only when it was next
ingested; catalogue-only products waited up to a week for the Monday crawl.
`rematch_all` applies them to every stored product at once. It changes the
match, never a price row.
"""

from pathlib import Path

from bonusrank.db import connect
from bonusrank.ingest import rematch_all
from bonusrank.matcher import Matcher
from bonusrank.seed import load_seed


def _conn():
    c = connect(path=Path(":memory:"))
    load_seed(c)
    return c


def _product(c, sku, name, key, category=None):
    fid = c.execute("SELECT id FROM food_types WHERE key=?", (key,)).fetchone()[0] if key else None
    c.execute("INSERT INTO products (chain, sku, name, category, food_type_id, match_method, "
              "match_score, first_seen) VALUES ('ah',?,?,?,?,'alias_contained',0.95,'2026-09-26')",
              (sku, name, category, fid))


def _key(c, sku):
    row = c.execute("SELECT f.key FROM products p LEFT JOIN food_types f ON f.id=p.food_type_id "
                    "WHERE p.sku=?", (sku,)).fetchone()
    return row[0]


def test_a_wrong_old_match_is_cleared_and_a_missing_one_is_found():
    c = _conn()
    _product(c, "1", "HiPRO Protein Kwark Banaan 200 g", "banaan")
    _product(c, "2", "AH Magere kwark", None)
    changed = rematch_all(c, Matcher.from_db(c))
    assert _key(c, "1") is None
    assert _key(c, "2") == "kwark_mager"
    assert changed == 2


def test_an_unchanged_match_is_left_alone():
    c = _conn()
    _product(c, "1", "AH Magere kwark", "kwark_mager")
    assert rematch_all(c, Matcher.from_db(c)) == 0


def test_a_non_food_category_stays_excluded():
    c = _conn()
    _product(c, "1", "Kwark gezichtsmasker", "kwark_mager", category="Drogisterij")
    rematch_all(c, Matcher.from_db(c))
    assert _key(c, "1") is None
