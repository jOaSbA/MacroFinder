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


def _reject_shared_aliases(rows: list[dict], owner_file: dict[str, Path]) -> None:
    """An alias may belong to exactly one food type.

    The duplicate-KEY check above is what stopped anyone noticing this for a
    milestone: milestone 12 added `rucola`, `ijsbergsla` and `biefstuk` as new
    keys, each of which collided with an alias an existing row already claimed
    (`sla` had both leaves; `runderbiefstuk_mager` had three spellings of
    steak). A distinct key is not a distinct food, and whichever row the
    matcher reached first decided which macros a product was costed with -
    a coincidence of iteration order, silently.
    """
    owners: dict[str, list[str]] = {}
    for row in rows:
        for alias in row.get("aliases") or []:
            owners.setdefault(alias.strip().lower(), []).append(row["key"])

    clashes = {alias: keys for alias, keys in owners.items() if len(keys) > 1}
    if clashes:
        detail = "; ".join(
            f"{alias!r} claimed by {', '.join(keys)} "
            f"({', '.join(sorted({owner_file[k].name for k in keys}))})"
            for alias, keys in sorted(clashes.items())
        )
        raise ValueError(f"an alias may belong to only one food type: {detail}")


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

    _reject_shared_aliases(rows, seen)

    # Aliases are derived entirely from these files and nothing else writes
    # them, so they are rebuilt wholesale rather than upserted - the same
    # delete-and-reinsert `load_archetypes` does for compositions and
    # `load_templates` for slots.
    #
    # Upserting made `load_seed` additive-only, which meant every alias ever
    # REMOVED from the seed stayed live forever. That is not a tidiness point:
    # it made a correctness fix a no-op. Moving the bare word "linzen" from the
    # dry row to the tin edited the YAML and changed nothing, because the old
    # alias was still in the table pointing at the dry row. It also covers a
    # food type dropped from the seed entirely - its row cannot be deleted
    # (products and compositions reference it) but stripping its aliases makes
    # the matcher unable to reach it, which is the part that decides what a
    # product gets costed with.
    # Wholesale, including for a single-file load: `path=` means "these files
    # ARE the seed", so a food type absent from them is absent, full stop.
    conn.execute("DELETE FROM food_type_aliases")

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
                (food_type_id, alias.strip().lower()),
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
    "day_parts", "max_prep_minutes", "meal_kind",
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
        # day_parts is a JSON list in the column; the seed writes a YAML list.
        values[_ARCHETYPE_COLUMNS.index("day_parts")] = (
            json.dumps(row["day_parts"]) if row.get("day_parts") else None
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


# --- meal templates (milestone 12) ---------------------------------------

TEMPLATE_GLOB = "templates*.yaml"

_SEVERITIES = ("incomplete", "wrong", "note")
_RULE_KINDS = ("requirement", "incompatible")


def template_files(directory: Path | None = None) -> list[Path]:
    """Every meal-template seed file. Its own glob, like `archetype_files`."""
    return sorted((directory or SEED_DIR).glob(TEMPLATE_GLOB))


def load_templates(conn: sqlite3.Connection, path: Path | None = None) -> dict[str, int]:
    """Load meal templates, their slots, candidates and compatibility rules.

    A template is a shape with holes in it; an archetype is a whole dish
    somebody wrote down. Both are authored, and this loader validates with the
    same discipline `load_archetypes` uses: a bad row fails with the template's
    key in the message rather than as a bare CHECK violation.

    Re-runnable, and slots/candidates/rules are replaced wholesale per template
    for the same reason compositions are - an edited template drops candidates,
    and an upsert would keep the removed ones.

    Note that this means `template_slots.id` changes on every run. Nothing
    outside this database may key on it; saved meals on the phone key on
    (template_key, slot_key, food_type_key) strings for exactly that reason.
    """
    paths = [path] if path else template_files()
    rows: list[dict] = []
    seen: dict[str, Path] = {}
    for file in paths:
        for row in yaml.safe_load(file.read_text(encoding="utf-8")) or []:
            key = row["key"]
            if key in seen:
                raise ValueError(
                    f"duplicate template key {key!r} in {file.name} "
                    f"(already defined in {seen[key].name})"
                )
            seen[key] = file
            rows.append(row)

    known_food_types = {
        r["key"]: r["id"] for r in conn.execute("SELECT id, key FROM food_types")
    }
    counts = {"templates": 0, "slots": 0, "candidates": 0, "rules": 0}

    for row in rows:
        _validate_template(row, known_food_types)
        conn.execute(
            "INSERT INTO meal_templates (key, name, meal_kind, base_prep_minutes) "
            "VALUES (?,?,?,?) ON CONFLICT(key) DO UPDATE SET "
            "name=excluded.name, meal_kind=excluded.meal_kind, "
            "base_prep_minutes=excluded.base_prep_minutes",
            (row["key"], row["name"], row["meal_kind"], row.get("base_prep_minutes")),
        )
        template_id = conn.execute(
            "SELECT id FROM meal_templates WHERE key=?", (row["key"],)
        ).fetchone()[0]
        counts["templates"] += 1

        conn.execute("DELETE FROM template_slots WHERE template_id=?", (template_id,))
        conn.execute("DELETE FROM template_rules WHERE template_id=?", (template_id,))

        for order, slot in enumerate(row["slots"]):
            default_grams = slot["default_grams"]
            conn.execute(
                "INSERT INTO template_slots "
                "(template_id, key, name, required, sort_order, default_grams) "
                "VALUES (?,?,?,?,?,?)",
                (template_id, slot["key"], slot["name"],
                 int(slot.get("required", True)), order, default_grams),
            )
            slot_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            counts["slots"] += 1

            for candidate in slot["candidates"]:
                conn.execute(
                    "INSERT INTO template_slot_candidates "
                    "(slot_id, food_type_id, grams, pantry_price_eur_per_kg, source) "
                    "VALUES (?,?,?,?,'seed')",
                    (slot_id, known_food_types[candidate["food_type"]],
                     candidate.get("grams", default_grams),
                     candidate.get("pantry_price_eur_per_kg")),
                )
                counts["candidates"] += 1

        for rule in row.get("rules") or []:
            conn.execute(
                "INSERT INTO template_rules (template_id, kind, when_predicate, "
                "requires, min_satisfied, severity, note) VALUES (?,?,?,?,?,?,?)",
                (template_id, rule["kind"], json.dumps(rule["when"]),
                 json.dumps(rule.get("requires")) if rule.get("requires") else None,
                 rule.get("min_satisfied", 1), rule["severity"], rule["note"]),
            )
            counts["rules"] += 1

    conn.commit()
    return counts


def _validate_template(row: dict, known_food_types: dict[str, int]) -> None:
    key = row.get("key")
    if not key or not row.get("name"):
        raise ValueError(f"template needs both a key and a name: {row!r}")

    meal_kind = row.get("meal_kind")
    if meal_kind not in ("meal", "snack", "drink"):
        raise ValueError(
            f"{key}: meal_kind must be meal/snack/drink, got {meal_kind!r}. "
            "It decides which macro-floor profile a composed meal is judged against."
        )

    slots = row.get("slots") or []
    if not slots:
        raise ValueError(f"{key}: a template with no slots has nothing to customise")

    slot_keys: set[str] = set()
    # Every food type offered anywhere in this template. A rule may only speak
    # about these - see the rule loop below for why that matters.
    offered: set[str] = set()
    for slot in slots:
        slot_key = slot.get("key")
        label = f"{key}/{slot_key}"
        if not slot_key or not slot.get("name"):
            raise ValueError(f"{key}: every slot needs both a key and a name: {slot!r}")
        if slot_key in slot_keys:
            raise ValueError(f"{key}: duplicate slot key {slot_key!r}")
        slot_keys.add(slot_key)

        if not slot.get("default_grams", 0) > 0:
            raise ValueError(
                f"{label}: default_grams must be positive. Every slot states a "
                "serving size so no candidate can end up without one."
            )

        candidates = slot.get("candidates") or []
        if not candidates:
            raise ValueError(f"{label}: a slot with no candidates cannot be filled")

        in_this_slot: set[str] = set()
        for candidate in candidates:
            food_type = candidate.get("food_type")
            if food_type not in known_food_types:
                raise ValueError(
                    f"{label}: unknown food_type {food_type!r}. Add it to a "
                    "food_types seed file, or fix the typo."
                )
            # Across slots is fine and intended; twice in ONE slot would hit
            # template_slot_candidates' primary key as a bare IntegrityError.
            if food_type in in_this_slot:
                raise ValueError(f"{label}: {food_type} listed twice in one slot")
            in_this_slot.add(food_type)
            if not candidate.get("grams", slot["default_grams"]) > 0:
                raise ValueError(f"{label}: {food_type} needs positive grams")
            offered.add(food_type)

    for index, rule in enumerate(row.get("rules") or []):
        label = f"{key}/rule[{index}]"
        if rule.get("kind") not in _RULE_KINDS:
            raise ValueError(
                f"{label}: kind must be one of {_RULE_KINDS}, got {rule.get('kind')!r}"
            )
        if rule.get("severity") not in _SEVERITIES:
            raise ValueError(
                f"{label}: severity must be one of {_SEVERITIES}, got "
                f"{rule.get('severity')!r}. 'incomplete' (unfinished dish) and "
                "'wrong' (these do not go together) are different messages."
            )
        note = rule.get("note")
        if not (isinstance(note, str) and note.strip()):
            raise ValueError(
                f"{label}: note is required and must say WHY, in your own words "
                "- it is the only thing the app shows the user about this rule."
            )

        requires = rule.get("requires") or []
        if not requires:
            raise ValueError(
                f"{label}: every rule needs a `requires` list - it is the other "
                "side of the rule (what must also be there, or what must not be)"
            )
        predicates = [rule.get("when"), *requires]
        min_satisfied = rule.get("min_satisfied", 1)
        if not 1 <= min_satisfied <= len(requires):
            raise ValueError(
                f"{label}: min_satisfied is {min_satisfied}, which no combination "
                f"of its {len(requires)} predicates can reach"
            )
        for predicate in predicates:
            if not isinstance(predicate, dict) or not predicate:
                raise ValueError(f"{label}: a predicate must be a non-empty mapping")
            slot_key = predicate.get("slot")
            if slot_key is not None and slot_key not in slot_keys:
                raise ValueError(
                    f"{label}: predicate names slot {slot_key!r}, which this "
                    f"template does not have. Slots are {sorted(slot_keys)}."
                )
            for food_type in predicate.get("food_types") or []:
                if food_type not in known_food_types:
                    raise ValueError(
                        f"{label}: unknown food_type {food_type!r} in a predicate"
                    )
                if food_type not in offered:
                    raise ValueError(
                        f"{label}: predicate names {food_type!r}, which no slot of "
                        "this template offers - the rule could never fire. Add it "
                        "as a candidate, or remove it from the rule."
                    )
