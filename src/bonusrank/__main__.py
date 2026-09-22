"""CLI.

Output discipline (CLAUDE.md section 2) is enforced here, not left to taste:

  - a macro figure from the seed or a low-confidence source is always suffixed,
    never printed bare;
  - required quantity sits next to every promo price;
  - perishables always show the waste-adjusted price beside the headline;
  - "cheapest in N weeks" leads over "X% off" wherever history exists;
  - unknown is printed as "?" and never as 0.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from pathlib import Path

from . import config
from .adapters import available_chains, get_adapter
from .db import connect
from .models import RawOffer

EUR = "€"


# ---------------------------------------------------------------- fetch

def _print_offer(offer: RawOffer, index: int) -> None:
    window = (
        f"{offer.valid_from} to {offer.valid_to}"
        if offer.valid_from and offer.valid_to
        else "validity not published"
    )
    print(f"  [{index}] {offer.title}")
    print(f"      offer_id     {offer.offer_id}   segment {offer.group_id or '-'}")
    print(f"      category     {offer.category or '-'}")
    print(f"      promo text   {offer.promo_raw_text or '-'}")
    for label in offer.promo_labels:
        price = label.get("price")
        print(f"      chain label  {label.get('code','?')}  "
              f"{label.get('defaultDescription','')!r}"
              f"{f'  price={price}' if price is not None else ''}")
    print(f"      valid        {window}")
    flags = [f for f, on in (
        ("PERSONAL - excluded from headline rankings", offer.is_personal),
        ("store-only", offer.store_only), ("future period", offer.is_future)) if on]
    if flags:
        print(f"      flags        {', '.join(flags)}")
    print()


def cmd_fetch(args: argparse.Namespace) -> int:
    adapter = get_adapter(args.chain)
    offers = adapter.fetch_promotions()
    if not offers:
        print(f"No offers returned for {args.chain}.", file=sys.stderr)
        return 1

    print(f"\n=== {args.chain.upper()} - raw promotions ===\n")
    print(f"  raw offers (deduped on offer_id):  {len(offers)}")
    windows = Counter((o.valid_from, o.valid_to) for o in offers)
    for (start, end), count in sorted(windows.items(), key=lambda kv: (kv[0][0] or "", kv[0][1] or "")):
        print(f"  bonus window {start} to {end}:  {count} offers")
    print(f"  personal offers:    {sum(o.is_personal for o in offers)}")
    stats = adapter._client.stats
    print(f"  http:               {stats['network']} network, {stats['cache']} cached")
    print(f"  raw snapshots:      {config.RAW_DIR / args.chain}\n")
    print(f"--- {min(args.samples, len(offers))} sample offers ---\n")
    for i, offer in enumerate(offers[: args.samples], start=1):
        _print_offer(offer, i)
    return 0


# ----------------------------------------------------------------- seed

def cmd_seed(args: argparse.Namespace) -> int:
    from .seed import load_archetypes, load_seed, load_templates

    with connect() as conn:
        counts = load_seed(conn)
        archetypes = load_archetypes(conn)
        templates = load_templates(conn)
        total = conn.execute("SELECT COUNT(*) FROM food_types").fetchone()[0]
        with_protein = conn.execute(
            "SELECT COUNT(*) FROM food_types WHERE protein_per_100g IS NOT NULL"
        ).fetchone()[0]
    print(f"\nfood_types seeded: {total}  ({with_protein} with a protein figure, "
          f"{counts['aliases']} aliases)")
    print("every seeded row is source='manual', confidence='seed' - these are generic")
    print("published values, not NEVO extractions. Run with --nevo to upgrade.")
    print(f"\narchetypes seeded: {archetypes['archetypes']}  "
          f"({archetypes['compositions']} compositions, {archetypes['items']} items, "
          f"{archetypes['ready_made_rules']} ready-made rules)")
    print("every composition states what it tastes like INSTEAD - see `bonusrank compare`.\n")
    print(f"meal templates seeded: {templates['templates']}  "
          f"({templates['slots']} slots, {templates['candidates']} candidates, "
          f"{templates['rules']} compatibility rules)")
    print("see `bonusrank templates` for what each slot costs this week.\n")
    return 0


# --------------------------------------------------------------- ingest

def cmd_ingest(args: argparse.Namespace) -> int:
    from .ingest import fetch_label_macros, ingest_ah, ingest_flat

    adapter = get_adapter(args.chain)
    with connect() as conn:
        if conn.execute("SELECT COUNT(*) FROM food_types").fetchone()[0] == 0:
            print("food_types is empty - run `bonusrank seed` first.", file=sys.stderr)
            return 1

        # AH's promotions are segments that need expanding into SKUs
        # (`fetch_segment`); a chain without that indirection - Jumbo, Aldi -
        # already gives one SKU per offer and goes through the generic path.
        # This is a capability check, not a chain-name check (CLAUDE.md
        # section 1): adding a chain shaped like AH means adding
        # `fetch_segment`; adding one shaped like Jumbo/Aldi means not adding it.
        if hasattr(adapter, "fetch_segment"):
            stats = ingest_ah(conn, adapter, limit=args.limit)
        else:
            stats = ingest_flat(conn, adapter, limit=args.limit)

        if args.with_macros:
            skus = [r[0] for r in conn.execute(
                "SELECT sku FROM products WHERE chain=? AND food_type_id IS NOT NULL "
                "AND id NOT IN (SELECT product_id FROM product_macros) LIMIT ?",
                (args.chain, args.with_macros)).fetchall()]
            print(f"fetching label macros for {len(skus)} matched SKUs...")
            print(f"  wrote {fetch_label_macros(conn, adapter, skus)} macro rows")

        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("products", "price_observations", "food_types", "needs_review")}
        sample = conn.execute(
            "SELECT p.*, o.* FROM products p JOIN price_observations o ON o.product_id=p.id "
            "WHERE o.required_quantity > 1 AND p.food_type_id IS NOT NULL "
            "ORDER BY o.required_quantity DESC LIMIT 1").fetchone()
        review = conn.execute(
            "SELECT kind, COUNT(*) n FROM needs_review GROUP BY kind ORDER BY n DESC").fetchall()

    print(f"\n=== ingest: {args.chain} ===\n")
    print(f"  segments expanded      {stats.segments}")
    print(f"  products upserted      {stats.products}")
    print(f"  observations appended  {stats.observations}")
    print(f"  matched / unmatched    {stats.matched} / {stats.unmatched}"
          f"   (+{stats.excluded} excluded as non-food)")
    print(f"  http                   {adapter._client.stats}")
    print("\n  row counts:", ", ".join(f"{k}={v}" for k, v in counts.items()))
    print("\n  needs_review queue:")
    for row in review:
        print(f"     {row['n']:>4}  {row['kind']}")

    if sample:
        print("\n--- one full record (a promo with required_quantity > 1) ---\n")
        for key in sample.keys():
            print(f"     {key:<22} {sample[key]}")
    return 0


# ----------------------------------------------------------------- list

def _fmt(value, spec="6.2f", unknown="?"):
    return unknown if value is None else format(value, spec)


def cmd_list(args: argparse.Namespace) -> int:
    from .ranking import rank, sort_offers

    with connect() as conn:
        offers = rank(conn, chain=args.chain, include_personal=args.include_personal)
    if not offers:
        print("Nothing ingested yet - run `bonusrank ingest` first.", file=sys.stderr)
        return 1

    # `bonusrank prices` records plain shelf prices as observations so that DIY
    # compositions can be costed in weeks when nothing is on offer. They are not
    # offers, and this command ranks offers - the history signals and promo
    # mechanics below only mean anything for a promotion. Opt in with the flag.
    if not args.include_shelf_prices:
        offers = [o for o in offers if o.promo_mechanic != "not_a_promo"]

    rated = [o for o in offers if o.eur_per_100g_protein is not None]
    ordered = sort_offers(rated, args.sort)[: args.limit]
    settings = config.user_settings()

    print(f"\n=== {args.chain.upper()} bonus, sorted by {args.sort} ===")
    print(f"    {len(rated)} of {len(offers)} current offers have a usable protein figure")
    print(f"    waste adjustment assumes {settings['daily_consumption_g']} g/day of any one food\n")

    header = (f"  {'':3} {EUR}/100g P   {EUR}/1000kcal   unit    qty  promo              "
              f"product")
    print(header)
    print("  " + "-" * 104)

    for i, o in enumerate(ordered, start=1):
        mark = "*" if o.needs_macro_marking else " "
        print(f"  {i:>2}. {_fmt(o.eur_per_100g_protein, '8.2f')}{mark} "
              f"{_fmt(o.eur_per_1000kcal, '11.2f')}  "
              f"{_fmt(o.effective_unit_price, '6.2f')}  "
              f"{o.required_quantity:>3}x  {(o.promo_raw_text or '-')[:17]:<18} "
              f"{o.name[:34]}")

        detail = []
        # Copy rule 4: perishables always show the honest second number.
        if o.perishable and o.waste_adjusted_eur_per_100g_protein is not None:
            if o.realistically_consumable is not None and o.realistically_consumable < o.required_quantity:
                detail.append(
                    f"but {EUR}{o.waste_adjusted_eur_per_100g_protein:.2f}/100g P if you only "
                    f"get through {o.realistically_consumable} of {o.required_quantity}"
                )
            else:
                detail.append(f"perishable, {o.realistically_consumable}x consumable in time")
        # Copy rule 5: prefer "cheapest in N weeks" over the percentage.
        if o.cheapest_in_weeks is not None:
            detail.append(f"cheapest in {o.cheapest_in_weeks} weeks")
        elif o.observations < 2:
            detail.append("no price history yet")
        if o.total_outlay is not None and o.required_quantity > 1:
            detail.append(f"total outlay {EUR}{o.total_outlay:.2f}")
        if o.is_personal:
            detail.append("PERSONAL OFFER - not available to everyone")
        if detail:
            print(f"      {' | '.join(detail)}")

        print(f"      {o.raw_unit_text or '?'} -> {_fmt(o.cost_basis_g, '.0f')} g costed"
              f"  |  {_fmt(o.protein_per_100g, '.1f')} g P/100g"
              f"  |  food_type {o.food_type or '?'}"
              f"  |  macros: {o.macro_source}/{o.macro_confidence}"
              f"{', kcal derived from kJ' if o.kcal_is_derived else ''}")
        print()

    if any(o.needs_macro_marking for o in ordered):
        print(f"  * macro figures from the generic seed, not this SKU's own label.")
        print(f"    Run `bonusrank ingest --with-macros N` to replace them with label data.\n")

    unrated = len(offers) - len(rated)
    if unrated:
        print(f"  {unrated} current offers are unrated: no food_type match, or no unit size.")
        print(f"  They are held in needs_review, never guessed. See `bonusrank review`.\n")
    return 0


# -------------------------------------------------------------- matches

def cmd_matches(args: argparse.Namespace) -> int:
    """Audit what the matcher decided, so overrides can be written from evidence.

    Containment matching has a residual false-positive tail that no threshold
    removes - the designed remedy is `data/seed/match_overrides.yaml`, and this
    is how you find out what to put in it.
    """
    where = ["p.chain = ?"]
    params: list = [args.chain]
    if args.method:
        where.append("p.match_method = ?")
        params.append(args.method)
    if args.food_type:
        where.append("f.key = ?")
        params.append(args.food_type)

    with connect() as conn:
        rows = conn.execute(
            "SELECT p.name, p.brand, p.sku, p.match_method, p.match_score, p.category, "
            "f.key AS food_type, f.protein_per_100g FROM products p "
            "JOIN food_types f ON f.id = p.food_type_id "
            f"WHERE {' AND '.join(where)} ORDER BY p.match_score, f.key LIMIT ?",
            (*params, args.limit)).fetchall()
        totals = conn.execute(
            "SELECT match_method, COUNT(*) n FROM products WHERE chain=? "
            "AND food_type_id IS NOT NULL GROUP BY match_method ORDER BY n DESC",
            (args.chain,)).fetchall()

    print()
    print(f"=== {args.chain.upper()} matches ===")
    print()
    for row in totals:
        print(f"  {row['n']:>4}  {row['match_method']}")
    print()
    print("  Weakest first. Anything wrong here goes in match_overrides.yaml")
    print("  as a `contains:` rule or a `never_match:` entry.")
    print()

    for row in rows:
        print(f"  {row['match_score']:.3f} {row['match_method'][:15]:<16} "
              f"{row['name'][:44]:<46} -> {row['food_type']} "
              f"({_fmt(row['protein_per_100g'], '.1f')} g P/100g)")
        if args.verbose_rows:
            print(f"        sku ah:{row['sku']}  category {row['category'] or '-'}")
    return 0


# --------------------------------------------------------------- prices

def cmd_prices(args: argparse.Namespace) -> int:
    """What a kilo of each food type costs right now, on promo or not.

    The ranking only ever knew prices for SKUs that turned up in the bonus
    folder. Pricing a DIY composition needs a price for every food type in it in
    every week, so this is the lane that fills the gaps - and the lane whose
    review queue tells you which food types the search cannot find.
    """
    from .prices import food_type_price, refresh_food_type_prices

    keys = [args.food_type] if args.food_type else None

    with connect() as conn:
        if args.refresh:
            adapter = get_adapter(args.chain)
            try:
                stats = refresh_food_type_prices(
                    conn, adapter, keys=keys,
                    max_requests=None if args.all else args.limit)
            except NotImplementedError as exc:
                print(exc, file=sys.stderr)
                return 1
            print(f"\nqueried {stats.queried} food types: {stats.matched} matched, "
                  f"{stats.unmatched} queued for review, "
                  f"{stats.observations} new price observations")
            if stats.skipped_no_price:
                print(f"  {stats.skipped_no_price} matched but carried no price")

        rows = conn.execute(
            "SELECT key, name_nl FROM food_types "
            + ("WHERE key = ? " if args.food_type else "")
            + "ORDER BY key",
            (args.food_type,) if args.food_type else (),
        ).fetchall()
        priced = [
            (row, food_type_price(conn, row["key"], chain=args.chain,
                                  include_personal=args.include_personal))
            for row in rows
        ]

    known = [(row, price) for row, price in priced if price is not None]
    if not known and not args.refresh:
        print("No food type has a price yet. Run `bonusrank prices --refresh` "
              "(or `bonusrank ingest`) first.", file=sys.stderr)
        return 1

    known.sort(key=lambda pair: pair[1].eur_per_kg)
    print(f"\n=== {args.chain.upper()} price catalogue ===")
    print(f"    {len(known)} of {len(priced)} food types have a current price\n")
    print(f"  {EUR}/kg    on promo  food type              cheapest SKU")
    print("  " + "-" * 100)

    for row, price in known[: None if args.all else args.limit]:
        # Copy rule 3: a promo price without its required quantity is a trap.
        promo = (f"{price.promo_raw_text or price.promo_mechanic}"
                 f"{f' ({price.required_quantity}x)' if price.required_quantity > 1 else ''}"
                 if price.is_promo else "-")
        print(f"  {_fmt(price.eur_per_kg, '7.2f')}  {promo[:9]:<9} "
              f"{row['key'][:22]:<23} {price.product_name[:32]:<34} "
              f"{price.mass_g:.0f} g @ {EUR}{price.unit_price:.2f}")

    missing = [row["key"] for row, price in priced if price is None]
    if missing:
        print(f"\n  {len(missing)} food types have no current price. A composition "
              "using one of them")
        print("  prices as '?' rather than as the sum of the rest. To fill them in:")
        print("    bonusrank prices --refresh --all")
        print(f"  first few: {', '.join(missing[:8])}\n")
    return 0


# ------------------------------------------------------------ templates

def cmd_templates(args: argparse.Namespace) -> int:
    """What each slot of each meal template costs this week. Milestone 12.

    This is the review lane for the customiser, the way `bonusrank matches` is
    the review lane for the matcher: the ranked candidate list a slot offers is
    only trustworthy if you can read it. Run it against two chains and the
    orders should differ - that is the proof the ranking is price-driven.
    """
    from .templates import price_templates

    with connect() as conn:
        templates = price_templates(
            conn, chain=args.chain, include_personal=args.include_personal
        )

    if args.template:
        templates = tuple(t for t in templates if t.key == args.template)
        if not templates:
            print(f"No template {args.template!r}. Run `bonusrank seed`, or see "
                  "data/seed/templates.yaml.", file=sys.stderr)
            return 1
    if not templates:
        print("No templates seeded - run `bonusrank seed` first.", file=sys.stderr)
        return 1

    print(f"\n=== {args.chain.upper()} meal templates ===\n")

    for template in templates:
        prep = f"{template.base_prep_minutes} min" if template.base_prep_minutes else "?"
        print(f"{template.name}  ({template.meal_kind}, ~{prep})")

        for slot in template.slots:
            tag = "" if slot.required else "  (optional)"
            print(f"\n  {slot.name}{tag}")
            for candidate in slot.candidates:
                # Copy rule 3: a candidate that is cheapest because of a 2-for
                # deal means two of them in the fridge, so say so here.
                note = ""
                price = candidate.price
                if price is not None and price.required_quantity > 1:
                    note = f"  (buy {price.required_quantity})"
                if price is not None and price.promo_raw_text:
                    note += f"  {price.promo_raw_text[:26]}"
                if candidate.is_pantry:
                    note += "  (pantry price, not promo data)"
                print(f"    {candidate.name_nl[:26]:<28}"
                      f"{candidate.grams:5.0f} g  "
                      f"{EUR}{_fmt(candidate.eur, '5.2f')}  "
                      f"{_fmt(candidate.protein_g, '5.1f')} g P  "
                      f"{_fmt(candidate.eur_per_g_protein, '6.3f')} {EUR}/g P{note}")

        if template.rules:
            print("\n  Combination rules (authored - the app warns, never blocks):")
            for rule in template.rules:
                print(f"    [{rule.severity}] {rule.note}")
        print()

    print("An unpriced candidate is shown with ? and ranked last, never dropped -")
    print("\"we have no price for this right now\" is not \"this is not an option\".\n")
    return 0


# -------------------------------------------------------------- compare

def cmd_compare(args: argparse.Namespace) -> int:
    """Ready-made versus DIY for each archetype. Brief section 4.

    The engine is allowed to say "just buy it" and does (section 4.5). Every DIY
    block states what it tastes like INSTEAD of the original, never that it
    tastes the same - copy rule 2, and the whole reason the user would trust a
    second suggestion after acting on a first.
    """
    from .archetypes import compare
    from .optimiser import OptimisedComposition

    with connect() as conn:
        comparisons = compare(
            conn, archetype_key=args.archetype, chain=args.chain,
            include_personal=args.include_personal,
            max_prep_minutes=args.max_prep_minutes,
        )

    if not comparisons:
        if args.archetype:
            print(f"No archetype {args.archetype!r}. Run `bonusrank seed`, or see "
                  "data/seed/archetypes.yaml.", file=sys.stderr)
        else:
            print("No archetypes seeded - run `bonusrank seed` first.", file=sys.stderr)
        return 1

    marked = False
    print(f"\n=== {args.chain.upper()} ready-made vs DIY ===\n")

    for comparison in comparisons:
        archetype = comparison.archetype
        serving = f"{archetype.serving_g:.0f} g serving" if archetype.serving_g else "per serving"
        print(f"{archetype.name} - {serving}")
        print()

        ready = comparison.ready_made
        if ready is None:
            print("  Ready-made   nothing on the shelf matches this week")
        else:
            offer = ready.offer
            mark = "*" if offer.needs_macro_marking else " "
            marked = marked or offer.needs_macro_marking
            print(f"  Ready-made   {offer.name[:38]:<40} "
                  f"{EUR}{_fmt(ready.eur, '5.2f')}  "
                  f"{_fmt(ready.protein_g, '4.1f')} g P{mark} "
                  f"{_fmt(ready.eur_per_g_protein, '6.3f')} {EUR}/g P   0 min")
            detail = [f"matched by {ready.matched_by}", offer.promo_raw_text or "no promo"]
            # Copy rule 3: never a promo price without the quantity it demands.
            if offer.required_quantity > 1:
                detail.append(f"needs {offer.required_quantity}x, "
                              f"total outlay {EUR}{_fmt(offer.total_outlay, '.2f')}")
            # Copy rule 4: the honest second number for anything perishable.
            if offer.perishable and offer.waste_adjusted_eur_per_100g_protein is not None:
                detail.append(f"perishable, {offer.realistically_consumable}x "
                              "consumable in time")
            # Copy rule 5: the history signal beats a percentage.
            if offer.cheapest_in_weeks is not None:
                detail.append(f"cheapest in {offer.cheapest_in_weeks} weeks")
            if offer.is_personal:
                detail.append("PERSONAL OFFER - not available to everyone")
            print(f"               {' | '.join(detail)}")
        print()

        if not comparison.compositions:
            print("  DIY          no composition seeded within the effort limit")
        for composition in comparison.compositions:
            marked = True  # composition macros are seed-sourced by construction
            first = True
            for item in composition.items:
                lead = "  DIY         " if first else "              "
                first = False
                note = " (pantry price, not promo data)" if item.is_pantry else ""
                if item.price is not None and item.price.is_promo:
                    note = f" ({item.price.promo_raw_text or item.price.promo_mechanic})"
                cost = f"{EUR}{item.eur:.2f}" if item.eur is not None else f"{EUR}  ?"
                print(f"{lead} + {item.grams:>5.0f} g {item.name_nl[:26]:<28} "
                      f"{cost:>7}{note}")

            total = f"{EUR}{composition.eur:.2f}" if composition.eur is not None else f"{EUR}?"
            print(f"               {'':>5}  {composition.name[:28]:<28} "
                  f"{total:>7}  {_fmt(composition.protein_g, '4.1f')} g P* "
                  f"{_fmt(composition.eur_per_g_protein, '6.3f')} {EUR}/g P   "
                  f"{composition.effort_minutes or 0} min")
            if composition.unpriced:
                print(f"               price unknown: no current price for "
                      f"{', '.join(composition.unpriced)}.")
                print(f"               Not the sum of the rest - that would understate DIY. "
                      f"Try `bonusrank prices --refresh`.")
            # Section 4.3: authored, never computed, and never softened.
            print(f"               Taste delta ({composition.similarity_confidence}): "
                  f"{composition.taste_delta_note}")
            if composition.texture_delta_note:
                print(f"               Texture delta: {composition.texture_delta_note}")
            if composition.equipment:
                print(f"               Needs: {composition.equipment}")
            print()

        # Milestone 9: the solver-picked mix, alongside the hand-authored ones.
        optimised = comparison.optimised
        if isinstance(optimised, OptimisedComposition):
            parts = ", ".join(f"{item.grams:.0f} g {item.name_nl}" for item in optimised.items)
            print(f"  Optimised    {parts}")
            print(f"               -> {EUR}{optimised.eur:.2f}, "
                  f"{optimised.protein_g:.1f} g protein / {optimised.carbs_g:.1f} g carbs / "
                  f"{optimised.fat_g:.1f} g fat, {optimised.kcal:.0f} kcal")
            print()
        elif optimised is not None:  # RejectedPlan
            print(f"  Optimised    no plausible combination found - {optimised.reason}")
            print()

        print(f"  -> {comparison.verdict.text}")
        print()

    if marked:
        print("  * macro figures from the generic food_types seed, not a product label.")
        print("    Compositions are always seed-sourced: a recipe has no label.\n")
    return 0


# --------------------------------------------------------------- export

def cmd_export(args: argparse.Namespace) -> int:
    """Write the JSON snapshot the Android app fetches. Milestone 10.

    Computes nothing new - it serializes what `compare()` and `rank()` already
    produce for every chain, so the app sees exactly the same numbers and the
    same "why is this cheap" text the CLI prints.
    """
    from .export import DEFAULT_CHAINS, write_export

    chains = tuple(args.chains) if args.chains else DEFAULT_CHAINS
    with connect() as conn:
        payload = write_export(conn, Path(args.out), chains=chains)

    counts = {
        chain: (len(data["archetypes"]), len(data["offers"]))
        for chain, data in payload["chains"].items()
    }
    print(f"wrote {args.out}")
    for chain, (n_archetypes, n_offers) in counts.items():
        print(f"  {chain}: {n_archetypes} archetypes, {n_offers} ranked offers")
    return 0


# --------------------------------------------------------------- build-db

def cmd_build_db(args: argparse.Namespace) -> int:
    """Build the app database release assets. Milestone 14 (PLAN-V2 section 5).

    Like `export`, this computes nothing new - it is a projection of the dev
    database into the read-optimised shape the app syncs. Unlike `export`, its
    output never enters git: release assets can be deleted, git history cannot.
    """
    from . import appdb

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with connect() as conn:
        built = appdb.build_full(conn, out_dir / "build.tmp")

    # Named after its own content, so an unchanged catalogue keeps its name and
    # the refresh job can see there is nothing worth publishing.
    full = out_dir / appdb.full_filename(built)
    built.replace(full)
    print(f"full   {full.name}  {full.stat().st_size:,} bytes")

    deltas = []
    for previous in (Path(p) for p in args.against or []):
        if not previous.exists():
            print(f"  skipped {previous}: not found")
            continue
        if appdb.version_of(previous) == appdb.version_of(full):
            print(f"  skipped {previous.name}: identical to this build")
            continue
        delta = appdb.build_delta(
            previous, full, out_dir / appdb.delta_filename(previous, full)
        )
        deltas.append(delta)
        share = delta.stat().st_size / full.stat().st_size
        print(f"delta  {delta.name}  {delta.stat().st_size:,} bytes "
              f"({share:.1%} of a full download)")

        # A delta that does not reproduce the full build is worse than no
        # delta: it fails silently, on the user's phone, weeks later.
        check = appdb.apply_delta(previous, delta, out_dir / "verify.tmp")
        identical = appdb.sha256_of(check) == appdb.sha256_of(full)
        check.unlink()
        if not identical:
            print(f"  REFUSED: {delta.name} does not reproduce {full.name}")
            delta.unlink()
            deltas.pop()

    manifest = appdb.write_manifest(out_dir / "manifest.json", full=full, deltas=deltas)
    print(f"manifest  version {manifest['full']['version']}, "
          f"{manifest['full']['products']:,} products, {len(deltas)} delta(s)")
    return 0


# --------------------------------------------------------------- review

def cmd_review(args: argparse.Namespace) -> int:
    with connect() as conn:
        rows = conn.execute(
            "SELECT kind, ref, payload, first_seen FROM needs_review "
            "WHERE resolved_at IS NULL AND (? IS NULL OR kind = ?) "
            "ORDER BY kind, first_seen LIMIT ?",
            (args.kind, args.kind, args.limit)).fetchall()
        totals = conn.execute(
            "SELECT kind, COUNT(*) n FROM needs_review WHERE resolved_at IS NULL "
            "GROUP BY kind ORDER BY n DESC").fetchall()

    print("\n=== needs_review ===\n")
    for row in totals:
        print(f"  {row['n']:>4}  {row['kind']}")
    print()
    for row in rows:
        try:
            payload = json.dumps(json.loads(row["payload"]), ensure_ascii=False)
        except (json.JSONDecodeError, TypeError):
            payload = row["payload"]
        print(f"  [{row['kind']}] {row['ref']}")
        print(f"      {payload[:300]}")
    return 0


# ------------------------------------------------------------------ main

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="bonusrank", description=__doc__)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    fetch = sub.add_parser("fetch", help="fetch and summarise current promotions")
    fetch.add_argument("--chain", default="ah", choices=available_chains())
    fetch.add_argument("--samples", type=int, default=5)
    fetch.set_defaults(func=cmd_fetch)

    seed = sub.add_parser("seed", help="load the food_types seed")
    seed.set_defaults(func=cmd_seed)

    ingest = sub.add_parser("ingest", help="fetch, parse, match and store observations")
    ingest.add_argument("--chain", default="ah", choices=available_chains())
    ingest.add_argument("--limit", type=int, help="only ingest the first N offers")
    ingest.add_argument("--with-macros", type=int, metavar="N",
                        help="also fetch label macros for N matched SKUs (1 request each)")
    ingest.set_defaults(func=cmd_ingest)

    lst = sub.add_parser("list", help="rank current offers")
    lst.add_argument("--chain", default="ah", choices=available_chains())
    lst.add_argument("--sort", default="protein-per-euro",
                     choices=["protein-per-euro", "kcal-per-euro", "waste-adjusted", "price"])
    lst.add_argument("--limit", type=int, default=20)
    lst.add_argument("--include-personal", action="store_true",
                     help="include personal offers, which are not available to everyone")
    lst.add_argument("--include-shelf-prices", action="store_true",
                     help="also rank plain shelf prices from `bonusrank prices`, "
                          "not just what is on offer")
    lst.set_defaults(func=cmd_list)

    matches = sub.add_parser("matches", help="audit what the matcher decided")
    matches.add_argument("--chain", default="ah", choices=available_chains())
    matches.add_argument("--method", help="filter to one lane, e.g. fuzzy, alias_contained")
    matches.add_argument("--food-type", help="filter to one food_type key")
    matches.add_argument("--limit", type=int, default=40)
    matches.add_argument("--verbose-rows", action="store_true", help="show sku and category")
    matches.set_defaults(func=cmd_matches)

    prices = sub.add_parser("prices", help="what a kilo of each food type costs now")
    prices.add_argument("--chain", default="ah", choices=available_chains())
    prices.add_argument("--refresh", action="store_true",
                        help="fetch fresh shelf prices (1 request per food type, 6h cached)")
    prices.add_argument("--food-type", help="only this food_type key")
    prices.add_argument("--limit", type=int, default=30,
                        help="cap rows, and cap requests on --refresh")
    prices.add_argument("--all", action="store_true",
                        help="no cap: on --refresh this is ~190 live requests, about 95 s")
    prices.add_argument("--include-personal", action="store_true")
    prices.set_defaults(func=cmd_prices)

    cmp_ = sub.add_parser("compare", help="ready-made vs DIY for each archetype")
    cmp_.add_argument("--chain", default="ah", choices=available_chains())
    cmp_.add_argument("--archetype", help="one archetype key, e.g. skyr_met_fruit")
    cmp_.add_argument("--max-prep-minutes", type=int,
                      default=config.user_settings().get("max_prep_minutes"),
                      help="drop compositions that take longer")
    cmp_.add_argument("--include-personal", action="store_true",
                      help="include personal offers, which are not available to everyone")
    cmp_.set_defaults(func=cmd_compare)

    tmpl = sub.add_parser("templates", help="what each meal-template slot costs now")
    tmpl.add_argument("--chain", default="ah", choices=available_chains())
    tmpl.add_argument("--template", help="one template key, e.g. pasta")
    tmpl.add_argument("--include-personal", action="store_true",
                      help="include personal offers, which are not available to everyone")
    tmpl.set_defaults(func=cmd_templates)

    export = sub.add_parser("export", help="write a JSON snapshot for the Android app")
    export.add_argument("--out", default="docs/data/latest.json",
                        help="output path, committed by the refresh-data workflow")
    export.add_argument("--chain", action="append", dest="chains",
                        help="repeatable; defaults to every registered chain")
    export.set_defaults(func=cmd_export)

    build_db = sub.add_parser("build-db",
                              help="build the app database release assets")
    build_db.add_argument("--out-dir", default="dist/data",
                          help="where the assets are written; never committed")
    build_db.add_argument("--against", action="append",
                          help="a previous full build to cut a delta against; "
                               "repeatable, missing files are skipped")
    build_db.set_defaults(func=cmd_build_db)

    review = sub.add_parser("review", help="show the review queue")
    review.add_argument("--kind")
    review.add_argument("--limit", type=int, default=20)
    review.set_defaults(func=cmd_review)

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    if not config.CONTACT:
        logging.getLogger(__name__).debug("BONUSRANK_CONTACT unset; using a generic User-Agent.")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
