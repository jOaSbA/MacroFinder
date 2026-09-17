"""Load the food_types seed into the database.

Every seeded row is `source='manual'`, `confidence='seed'`. That is deliberate:
the brief wants NEVO (RIVM) as the authority with the NEVO code in `source_ref`,
but that dataset carries usage conditions you have to accept yourself, so it is
neither committed here nor impersonated. `confidence='seed'` is the honest label
for "a widely-published generic value that nobody has traced to a source yet".

`load_nevo` upgrades rows in place once you have downloaded the dataset to
`data/external/`.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import yaml

from . import config

SEED_DIR = config.PROJECT_ROOT / "data" / "seed"
SEED_GLOB = "food_types*.yaml"

_COLUMNS = (
    "key", "name_nl", "name_en", "state", "density_g_per_ml", "drained_fraction",
    "edible_fraction", "dry_to_cooked_factor", "g_per_unit", "protein_per_100g",
    "kcal_per_100g", "carbs_per_100g", "fat_per_100g", "fiber_per_100g",
    "shelf_life_days_unopened", "shelf_life_days_opened", "freezable",
    "optimise_max_grams", "meal_kind",
)

_MEAL_KINDS = ("meal", "snack", "drink", "ingredient")


def seed_files(directory: Path | None = None) -> list[Path]:
    """Every seed file, so you can drop your own in without touching the code."""
    return sorted((directory or SEED_DIR).glob(SEED_GLOB))


def load_seed(conn: sqlite3.Connection, path: Path | None = None) -> dict[str, int]:
    """Insert or refresh seed food types from every seed file. Returns counts."""
    paths = [path] if path else seed_files()
    rows: list[dict] = []
    seen: dict[str, Path] = {}
    for file in paths:
        for row in yaml.safe_load(file.read_text(encoding="utf-8")) or []:
            key = row["key"]
            if key in seen:
                raise ValueError(
                    f"duplicate food_type key {key!r} in {file.name} "
                    f"(already defined in {seen[key].name})"
                )
            seen[key] = file
            rows.append(row)

    for row in rows:
        if row.get("meal_kind") not in _MEAL_KINDS:
            raise ValueError(
                f"{row['key']}: meal_kind must be one of {_MEAL_KINDS}, "
                f"got {row.get('meal_kind')!r}. Milestone 11: this decides which "
                "app tab a matched offer of this food type appears in."
            )

    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    inserted = aliases = gaps = 0

    for row in rows:
        values = [row.get(c) for c in _COLUMNS]
        placeholders = ",".join("?" * (len(_COLUMNS) + 3))
        conn.execute(
            f"INSERT INTO food_types ({','.join(_COLUMNS)},source,source_ref,confidence) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT(key) DO UPDATE SET "
            + ",".join(f"{c}=excluded.{c}" for c in _COLUMNS[1:]),
            (*values, "manual", None, "seed"),
        )
        food_type_id = conn.execute(
            "SELECT id FROM food_types WHERE key=?", (row["key"],)
        ).fetchone()[0]
        inserted += 1

        # The canonical name is itself an alias, so the matcher has one code path.
        for alias in {row["name_nl"], *(row.get("aliases") or [])}:
            conn.execute(
                "INSERT INTO food_type_aliases (food_type_id, alias) VALUES (?,?) "
                "ON CONFLICT DO NOTHING",
                (food_type_id, alias.lower()),
            )
            aliases += 1

        # A seeded food with no protein figure is useless for ranking; say so
        # rather than letting it sit silently unusable.
        if row.get("protein_per_100g") is None:
            gaps += 1
            conn.execute(
                "INSERT INTO needs_review (kind, ref, payload, first_seen) VALUES (?,?,?,?) "
                "ON CONFLICT (kind, ref) DO NOTHING",
                ("missing_macros", f"food_type:{row['key']}",
                 f"seed row {row['key']} has no protein_per_100g", now),
            )

    conn.commit()
    return {"food_types": inserted, "aliases": aliases, "gaps": gaps}


def load_nevo(conn: sqlite3.Connection, path: Path, mapping: dict[str, str]) -> int:
    """Upgrade seeded rows with NEVO values.

    `mapping` is food_type key -> NEVO code. Rows upgraded this way become
    `source='nevo'`, `confidence='high'`, with the NEVO code in `source_ref` so
    the number is traceable (brief section 2).

    The dataset is not committed - it has usage conditions. Keep it in
    `data/external/`, which is gitignored.
    """
    if not path.exists():
        raise FileNotFoundError(
            f"NEVO dataset not found at {path}. Download it from rivm.nl yourself "
            "(you must accept its usage conditions) and place it in data/external/."
        )

    by_code: dict[str, dict[str, str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for record in csv.DictReader(fh, delimiter=";"):
            code = (record.get("NEVO-code") or record.get("NEVO_code") or "").strip()
            if code:
                by_code[code] = record

    upgraded = 0
    for key, code in mapping.items():
        record = by_code.get(code)
        if record is None:
            continue
        conn.execute(
            "UPDATE food_types SET protein_per_100g=?, kcal_per_100g=?, carbs_per_100g=?, "
            "fat_per_100g=?, fiber_per_100g=?, source='nevo', source_ref=?, confidence='high' "
            "WHERE key=?",
            (
                _num(record.get("PROT")), _num(record.get("ENERCC")),
                _num(record.get("CHO")), _num(record.get("FAT")),
                _num(record.get("FIBT")), f"NEVO:{code}", key,
            ),
        )
        upgraded += conn.total_changes and 1
    conn.commit()
    return upgraded


def _num(value: str | None) -> float | None:
    if value in (None, "", "-"):
        return None
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


# --- archetypes and compositions (brief section 4, milestone 8) -----------

ARCHETYPE_GLOB = "archetypes*.yaml"

_ARCHETYPE_COLUMNS = (
    "key", "name", "serving_g", "target_protein_g", "texture", "temperature",
    "meal_slots", "max_prep_minutes", "meal_kind",
)
_COMPOSITION_COLUMNS = (
    "name", "effort_minutes", "equipment", "similarity_confidence",
    "taste_delta_note", "texture_delta_note",
)


def archetype_files(directory: Path | None = None) -> list[Path]:
    """Every archetype seed file. Separate glob: `load_seed` globs food types."""
    return sorted((directory or SEED_DIR).glob(ARCHETYPE_GLOB))


def load_archetypes(conn: sqlite3.Connection, path: Path | None = None) -> dict[str, int]:
    """Load archetypes, their compositions and their ready-made rules.

    Validation happens here rather than being left to the schema's constraints,
    so a bad seed row fails with the archetype's name in the message instead of
    a bare CHECK violation. Three things are rejected outright:

      * an empty `taste_delta_note` - copy rule 2 means a composition that does
        not say what differs must not exist at all;
      * a `food_type` that is not in the food_types seed, which would otherwise
        silently leave a composition unpriceable;
      * a duplicate archetype key across files, matching `load_seed`.

    Re-runnable: compositions are replaced wholesale per archetype, because a
    recipe edit changes its items and a partial upsert would leave the old ones
    behind.
    """
    paths = [path] if path else archetype_files()
    rows: list[dict] = []
    seen: dict[str, Path] = {}
    for file in paths:
        for row in yaml.safe_load(file.read_text(encoding="utf-8")) or []:
            key = row["key"]
            if key in seen:
                raise ValueError(
                    f"duplicate archetype key {key!r} in {file.name} "
                    f"(already defined in {seen[key].name})"
                )
            seen[key] = file
            rows.append(row)

    known_food_types = {
        r["key"]: r["id"] for r in conn.execute("SELECT id, key FROM food_types")
    }
    counts = {"archetypes": 0, "compositions": 0, "items": 0, "ready_made_rules": 0}

    for row in rows:
        _validate_archetype(row, known_food_types)
        values = [row.get(c) for c in _ARCHETYPE_COLUMNS]
        # meal_slots is a JSON list in the column; the seed writes a YAML list.
        values[_ARCHETYPE_COLUMNS.index("meal_slots")] = (
            json.dumps(row["meal_slots"]) if row.get("meal_slots") else None
        )
        conn.execute(
            f"INSERT INTO archetypes ({','.join(_ARCHETYPE_COLUMNS)}) "
            f"VALUES ({','.join('?' * len(_ARCHETYPE_COLUMNS))}) "
            f"ON CONFLICT(key) DO UPDATE SET "
            + ",".join(f"{c}=excluded.{c}" for c in _ARCHETYPE_COLUMNS[1:]),
            values,
        )
        archetype_id = conn.execute(
            "SELECT id FROM archetypes WHERE key=?", (row["key"],)
        ).fetchone()[0]
        counts["archetypes"] += 1

        # Replace, do not merge: an edited recipe drops items, and an upsert
        # would keep the removed ones. Seed data only - nothing is lost.
        conn.execute("DELETE FROM compositions WHERE archetype_id=?", (archetype_id,))
        conn.execute("DELETE FROM archetype_ready_made_rules WHERE archetype_id=?",
                     (archetype_id,))

        for rule_kind, values_list in (
            ("food_type", (row.get("ready_made") or {}).get("food_types") or []),
            ("contains", (row.get("ready_made") or {}).get("contains") or []),
        ):
            for value in values_list:
                conn.execute(
                    "INSERT INTO archetype_ready_made_rules (archetype_id, kind, value) "
                    "VALUES (?,?,?) ON CONFLICT DO NOTHING",
                    (archetype_id, rule_kind, str(value).lower()),
                )
                counts["ready_made_rules"] += 1

        # Milestone 9: hand-authored carb/fat companions for the optimiser's
        # candidate pool. Not automatic - see CLAUDE.md milestone 9.
        conn.execute("DELETE FROM archetype_optimise_extras WHERE archetype_id=?",
                     (archetype_id,))
        for food_type in row.get("optimise_extra_food_types") or []:
            conn.execute(
                "INSERT INTO archetype_optimise_extras (archetype_id, food_type_id) "
                "VALUES (?,?) ON CONFLICT DO NOTHING",
                (archetype_id, known_food_types[food_type]),
            )
            counts["optimise_extras"] = counts.get("optimise_extras", 0) + 1

        for composition in row.get("compositions") or []:
            conn.execute(
                f"INSERT INTO compositions (archetype_id,{','.join(_COMPOSITION_COLUMNS)}) "
                f"VALUES (?,{','.join('?' * len(_COMPOSITION_COLUMNS))})",
                (archetype_id, *(composition.get(c) for c in _COMPOSITION_COLUMNS)),
            )
            composition_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            counts["compositions"] += 1

            for item in composition["items"]:
                conn.execute(
                    "INSERT INTO composition_items (composition_id, food_type_id, grams, "
                    "pantry_price_eur_per_kg) VALUES (?,?,?,?)",
                    (composition_id, known_food_types[item["food_type"]],
                     item["grams"], item.get("pantry_price_eur_per_kg")),
                )
                counts["items"] += 1

    conn.commit()
    return counts


def _validate_archetype(row: dict, known_food_types: dict[str, int]) -> None:
    key = row.get("key")
    if not key or not row.get("name"):
        raise ValueError(f"archetype needs both a key and a name: {row!r}")

    meal_kind = row.get("meal_kind")
    if meal_kind not in ("meal", "snack", "drink"):
        raise ValueError(
            f"{key}: meal_kind must be meal/snack/drink, got {meal_kind!r}. "
            "Milestone 9: this decides which macro-floor profile the optimiser "
            "applies (a drink is allowed to stay protein-forward; a meal is not)."
        )

    for food_type in row.get("optimise_extra_food_types") or []:
        if food_type not in known_food_types:
            raise ValueError(
                f"{key}: unknown optimise_extra_food_types entry {food_type!r}. "
                "Add it to a food_types seed file, or fix the typo."
            )

    for composition in row.get("compositions") or []:
        label = f"{key}/{composition.get('name')}"
        note = composition.get("taste_delta_note")
        if not (isinstance(note, str) and note.strip()):
            raise ValueError(
                f"{label}: taste_delta_note is required and must say what differs "
                "(copy rule 2 - never claim a composition tastes the same)"
            )
        confidence = composition.get("similarity_confidence")
        if confidence not in ("high", "medium", "low"):
            raise ValueError(
                f"{label}: similarity_confidence must be high/medium/low, "
                f"got {confidence!r}. Section 4.3: similarity is authored, not computed."
            )
        items = composition.get("items") or []
        if not items:
            raise ValueError(f"{label}: a composition with no items cannot be priced")
        for item in items:
            food_type = item.get("food_type")
            if food_type not in known_food_types:
                raise ValueError(
                    f"{label}: unknown food_type {food_type!r}. Add it to a "
                    "food_types seed file, or fix the typo - an unpriceable item "
                    "would otherwise make the whole composition unpriceable."
                )
            if not item.get("grams", 0) > 0:
                raise ValueError(f"{label}: {food_type} needs positive grams")
