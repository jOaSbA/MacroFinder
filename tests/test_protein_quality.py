"""PLAN-V2 section 4.3: the protein quality flag."""

from pathlib import Path

from bonusrank import appdb
from bonusrank.db import connect
from bonusrank.seed import load_seed


def test_every_flagged_key_is_a_real_food_type_and_listed_once():
    conn = connect(path=Path(":memory:"))
    load_seed(conn)
    keys = {r[0] for r in conn.execute("SELECT key FROM food_types")}
    quality = appdb.protein_quality()      # raises on a duplicate
    assert set(quality) <= keys, sorted(set(quality) - keys)
    assert set(quality.values()) <= {"complete", "incomplete", "blend"}


def test_the_legume_trap_is_flagged():
    q = appdb.protein_quality()
    assert q["linzen_droog"] == "incomplete"
    assert q["tofu_naturel"] == "complete"
    assert q["kipfilet_rauw"] == "complete"
