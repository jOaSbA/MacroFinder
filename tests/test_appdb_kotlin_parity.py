"""The Python producer and the Kotlin consumer must agree. Milestone 17.

`appdb.apply_delta` and `CatalogueStore.applyDelta` are two implementations of
the same operation in two languages, and only one of them runs in CI. If they
drift, nothing fails: the Python side keeps producing correct deltas, the app
keeps applying them, and the result is a device whose catalogue is quietly
missing rows - which surfaces weeks later as "why does this product still show
last week's price".

The failure mode is specific and cheap to prevent. A table added to `_TABLES`
and not to `DELTA_TABLES` means that table never syncs. A key expression that
disagrees means deletions silently miss. So this reads the Kotlin source and
checks the two lists against each other.

Reading source text is a blunt instrument, and it is the right one here: the
alternative is an instrumented test that needs an emulator and therefore does
not run in CI, which is exactly where this drift would otherwise be caught too
late. The emulator test exists as well (`android/app/src/androidTest`) and
covers the actual SQL; this covers the part that rots.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from bonusrank import appdb

KOTLIN = (
    Path(__file__).resolve().parents[1]
    / "android/app/src/main/kotlin/com/macrofinder/app/data/sync/CatalogueStore.kt"
)


@pytest.fixture(scope="module")
def source() -> str:
    assert KOTLIN.exists(), f"{KOTLIN} has moved; this test needs its new path"
    return KOTLIN.read_text(encoding="utf-8")


def _kotlin_list(source: str, name: str) -> list[str]:
    """The string entries of a `val name = listOf(...)` block."""
    match = re.search(rf"val {name} = listOf\((.*?)\)", source, re.S)
    assert match, f"{name} not found in CatalogueStore.kt"
    return re.findall(r'"([^"]+)"', match.group(1))


def _kotlin_map(source: str, name: str) -> dict[str, list[str]]:
    """The entries of a `val name = mapOf("a" to ..., ...)` block."""
    match = re.search(rf"val {name} = mapOf\((.*?)\n        \)", source, re.S)
    assert match, f"{name} not found in CatalogueStore.kt"
    out: dict[str, list[str]] = {}
    for key, value in re.findall(r'"([^"]+)"\s+to\s+([^\n]+)', match.group(1)):
        out[key] = re.findall(r'"([^"]+)"', value)
    return out


def test_the_app_syncs_every_table_the_delta_carries(source):
    """A table the producer diffs and the consumer does not apply is a table
    that never reaches the device, with nothing anywhere reporting it."""
    assert _kotlin_list(source, "DELTA_TABLES") == list(appdb._TABLES)


def test_the_two_key_expressions_agree_table_for_table(source):
    """Deletions are matched on this expression on both sides. A disagreement
    means a row deleted upstream is never deleted on the device - the app keeps
    showing a delisted product, or a stale price lane, forever."""
    composite = _kotlin_map(source, "COMPOSITE_KEYS")
    single = _kotlin_map(source, "SINGLE_KEYS")

    for table, columns in appdb._TABLES.items():
        if len(columns) == 1:
            assert single.get(table) == [columns[0]], table
            assert table not in composite, f"{table} is single-keyed in Python"
        else:
            assert composite.get(table) == list(columns), table
            assert table not in single, f"{table} is composite-keyed in Python"


def test_the_composite_separator_is_the_same_character(source):
    """`char(31)` on both sides. A different separator makes every composite
    deletion miss, and it would miss quietly."""
    assert "char(31)" in appdb._KEY_SEP
    assert 'joinToString(" || char(31) || ")' in source


def test_deletions_are_applied_before_upserts_on_both_sides():
    """Order matters: the other way round lets a stale deletion erase a fresh
    upsert. Python's own ordering is asserted here so the Kotlin comment that
    cites it cannot end up citing something that changed."""
    body = (Path(appdb.__file__)).read_text(encoding="utf-8")
    apply_body = body[body.index("def apply_delta") : body.index("def _delta_meta")]

    delete_at = apply_body.index("DELETE FROM main.")
    insert_at = apply_body.index("INSERT OR REPLACE INTO main.")
    assert delete_at < insert_at, "apply_delta stopped deleting before it upserts"


def test_the_app_knows_which_schema_version_it_is_reading(source):
    """The app reads `meta.schema_version` rather than declaring one. That is
    the whole reason this is not Room: a hardcoded version that disagrees with
    the file is a crash, where a read one is a decision."""
    assert "schema_version" in source
    assert str(appdb.SCHEMA_VERSION) not in _kotlin_list(source, "DELTA_TABLES")


def test_the_app_reads_the_schema_the_build_writes():
    """A mismatch means every phone refuses every catalogue as incompatible,
    or worse, installs one it can't read."""
    plan = (KOTLIN.parent / "SyncPlan.kt").read_text(encoding="utf-8")
    match = re.search(r"const val APP_SCHEMA_VERSION = (\d+)", plan)
    assert match, "APP_SCHEMA_VERSION not found in SyncPlan.kt"
    assert int(match.group(1)) == appdb.SCHEMA_VERSION
