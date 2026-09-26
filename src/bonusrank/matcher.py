"""SKU name -> food_type. Brief milestone 5.

Lanes, in priority order: manual SKU override, manual substring override, then
alias matching (exact / all-alias-words-contained / fuzzy). Anything that does
not clear its threshold returns no match and is queued for review.

The design rule is that a wrong match is worse than no match. A wrong match
silently attaches the wrong protein figure to a real price, and the ranking then
looks perfectly plausible while being wrong. So the matcher never returns a
best-effort neighbour - below threshold it returns None and says why.

Three guards exist, each added because of a false positive measured on the real
AH catalogue rather than imagined:

  variant      "tonijnstukken in olie" scores 0.837 against the alias
               "tonijnstukken in water" and 0.800 against "tonijn in olie".
  dish         "AH Terra Pureersoep pompoen linzen" was filed as dried lentils
               (24 g protein/100 g) because "soep" hides inside a compound.
  multi-food   "Roerbak zalm pangasius garnalen" names three food types, and
               whichever one wins, the macros are wrong.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import Enum
from pathlib import Path

import yaml

from . import config

OVERRIDES_PATH = config.PROJECT_ROOT / "data" / "seed" / "match_overrides.yaml"

ACCEPT_THRESHOLD = 0.82
# Fuzzy carries its own, higher bar. SequenceMatcher rates unrelated short Dutch
# strings around 0.82-0.84 - on the first full ingest it matched "Coca-Cola
# Vanilla" to vla_vanille at 0.824 and "Unox Bruine bonensoep" to canned beans at
# 0.857. Exact and containment hits are structurally safe; character similarity
# is not, so it needs more evidence.
FUZZY_THRESHOLD = 0.90


class MatchMethod(str, Enum):
    OVERRIDE_SKU = "override_sku"
    OVERRIDE_CONTAINS = "override_contains"
    ALIAS_EXACT = "alias_exact"
    ALIAS_CONTAINED = "alias_contained"
    FUZZY = "fuzzy"
    EXCLUDED = "excluded"
    NONE = "none"


@dataclass(frozen=True)
class MatchResult:
    food_type_key: str | None
    method: MatchMethod
    score: float = 0.0
    needs_review: bool = False
    reason: str = ""


# Words that carry no food identity. Stripped before matching so that
# "AH Voordeelverpakking magere kwark 500 g" and "magere kwark" collapse together.
_NOISE = {
    "ah", "basic", "biologisch", "bio", "voordeelverpakking", "grootverpakking",
    "voordeelpak", "familieverpakking", "verpakking", "vers", "verse", "nieuw",
    "per", "stuk", "stuks", "ca", "circa", "ongeveer", "de", "het", "een", "en",
    "van", "met", "voor", "naturel", "original", "originele", "smaak", "soort",
    "soorten", "alle", "op",
}

_UNIT_NOISE = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:kg|kilo|gram|gr|g|ml|cl|dl|liter|ltr|l|stuks?|x)\b"
    r"|\b\d+\s*[x×]\s*\d+"
    r"|\b\d{1,2}\+\b"          # 48+, 30+ cheese fat notation
    r"|\b\d+\s*%"
)
_PUNCT = re.compile(r"[^a-z0-9\s]+")

# A product whose name says it is a prepared dish is NOT its named ingredient.
# Containment matching is otherwise happy to file "Tagliatelle met roomsaus
# verspakket" as pasta_droog (12 g protein, 360 kcal/100 g dry) - the kit is
# fresh pasta plus sauce and nothing like those numbers. 219 of the first full
# ingest's 247 matches came through containment, so this guard carries the load.
#
# Matched at a WORD BOUNDARY inside compounds, because Dutch compounds hide the
# dish word - "bonen|soep", "pureer|soep", "salad|bowl", "vanille|smaak" - but a
# free substring search is too blunt: "ijs" sits mid-word in "rijst" and would
# reject every bag of rice as ice cream.
_COMPOSITE_MARKERS = (
    # prepared dishes and meal kits
    "verspakket", "maaltijdpakket", "maaltijd", "soep", "saus", "pizza", "pinsa",
    "lasagne", "ovenschotel", "stamppot", "risotto", "curry", "wok", "quiche",
    "tosti", "bereid", "gevuld", "kant-en-klaar", "kantenklaar", "salad",
    "bowl", "burrito", "taart", "flammkuchen", "poke", "roerbak", "pomodoro",
    "pesto", "ragu", "bolognese", "gratin", "schotel", "hachee", "goulash",
    "nasi", "bami", "paella",
    # confectionery and desserts that borrow a food word
    "chocolade", "chocolat", "sorbet", "milkshake", "biscuit", "bonbon",
    "dessert", "mousse", "toetje", "gebak",
    # a flavour reference is not the food: "vanillesmaak", "pindasmaak"
    "smaak", "flavour",
    # Drinks and bakery that merely NAME a fruit. Seeding produce opened this
    # surface: every soft drink, syrup and sweet naming a fruit started
    # matching the fruit itself ("Fuze Tea mango" -> mango, 60 kcal/100 g).
    "siroop", "limonade", "kombucha", "frisdrank", "cola", "ranja",
    "thee", "tea", "smoothie", "sap",
    "croissant", "muffin", "donut", "beignet", "wafel", "drop",
    # Snack and spread formats where the food word is a flavour or a minor
    # ingredient: "Heartbreakers paprika", "Rijst rondjes", "Tapenade
    # zongedroogde tomaat", "Loempia kip & ham", "Amandel gezichtscreme".
    "crackers", "chips", "rondjes", "tapenade", "loempia", "grillworst",
    "choco", "salon", "creme", "spread", "dip", "borrel", "snack",
    "meringue", "tortillachips", "koek", "koekjes", "koekenpan",
    # AH's dip and flavoured-butter ranges, where a seasoning word wins:
    # "Kleintje aioli zongedroogde tomaat" matched tomato, "Luchtige boter
    # basilicum tomaat" matched tomato rather than butter.
    "kleintje", "aioli", "gemarineerde", "luchtige",
    # spreads whose name embeds another food
    "roomkaas", "smeerkaas",
)

# Markers too short or too collision-prone for boundary matching, so they must be
# a whole token. "reep" would otherwise reject "kipfilet reepjes" (chicken
# strips, which really are chicken) and "ijs" would reject "rijst".
_COMPOSITE_WORDS = {
    "ijs", "roomijs", "waterijs", "schepijs", "softijs",
    "reep", "repen", "cake",
    # Whole-token only: "1Fruit Appel drink" is a drink, but haverdrink,
    # sojadrink and amandeldrink are food types in their own right and the
    # boundary form would reject all three.
    "drink", "drinks",
}

# Flavour guard. A dairy or protein product named after its flavour is not the
# flavour: "HiPRO Protein Kwark Banaan" was costed as a banana (EUR 79.55 per
# 100 g protein), "Optimel Drinkyoghurt Aardbei" as strawberries, and John West
# "Protein tonijnmoot olijfolie" as olive oil. 113 such matches measured on
# 2026-09-26. The guard fires only when the carrier word is in the name but not
# in the alias that matched, and the matched food is low in protein, so
# "haverdrink" (its alias has the word) and "protein kipfilet" (22 g) pass.
_CARRIER_WORDS = (
    "kwark", "yoghurt", "yogurt", "skyr", "pudding", "vla", "kefir", "melk", "milk",
    "protein", "proteine", "eiwit", "pancake", "pancakes", "shake", "tonijn",
)
_CARRIER_RE = re.compile(
    "|".join(rf"\b{re.escape(w)}|{re.escape(w)}\b" for w in _CARRIER_WORDS)
)
FLAVOUR_MAX_PROTEIN = 5.0

_WORD_BOUNDARY = r"\b"
_MARKER_RE = re.compile(
    "|".join(
        f"{_WORD_BOUNDARY}{re.escape(m)}|{re.escape(m)}{_WORD_BOUNDARY}"
        for m in _COMPOSITE_MARKERS
    )
)

# Words that qualify a food without changing what it is. Excluded from the
# multi-food count, so "mini penne tradizionali" does not read as a composite.
_QUALIFIERS = {
    "mini", "grote", "kleine", "gesneden", "geraspt", "geraspte", "plakken",
    "stukjes", "blokjes", "reepjes", "filet", "fillet", "mix", "duo", "trio",
    "knoflook", "citroen", "peper", "paprika", "kruiden", "tuinkruiden",
    "zeezout", "zout", "honing", "mosterd", "rozemarijn", "basilicum",
    "mediterraans", "italiaanse", "griekse", "spaanse", "franse", "hollandse",
    "tradizionali", "all", "uovo", "biologisch", "biologische",
    "naturel", "puur", "extra", "vierge", "classic",
}
# NOTE: variant words (magere / halfvolle / volle / droog / blik ...) are
# deliberately NOT qualifiers. Listing "halfvolle" here once made "halfvolle
# kwark" reduce to "kwark", which then collided with "magere kwark" and sent
# every tub of quark to review as a two-food composite.

# Tokens that name a VARIANT rather than a food. Character similarity is blind to
# these, so a clash disqualifies a candidate outright whatever it scored.
# Inflections map to one value so "magere kwark" still matches "kwark mager".
_VARIANT_DIMENSIONS: dict[str, dict[str, str]] = {
    "fat": {
        "mager": "low", "magere": "low", "halfvol": "mid", "halfvolle": "mid",
        "vol": "full", "volle": "full",
    },
    "medium": {
        "water": "water", "olie": "oil", "zonnebloemolie": "oil",
        "olijfolie": "oil", "tomatensaus": "tomato",
    },
    "form": {
        "droog": "dry", "gedroogd": "dry", "gedroogde": "dry", "blik": "canned",
        "diepvries": "frozen",
    },
    "prep": {
        "gerookt": "smoked", "gerookte": "smoked", "rauw": "raw",
        "gekookt": "cooked", "gekookte": "cooked",
    },
    "grain": {"volkoren": "whole", "zilvervlies": "whole", "wit": "white", "witte": "white"},
    # Plant vs animal is a variant like magere vs volle, not a detail. Without
    # it "AH Terra Plantaardige gehakt" matches the alias "gehakt" and is
    # costed as beef mince (21 g protein, 130 kcal/100 g).
    "origin": {
        "plantaardig": "plant", "plantaardige": "plant", "vegetarisch": "plant",
        "vegetarische": "plant", "vega": "plant", "vegan": "plant",
        "rund": "animal", "rundvlees": "animal", "varkens": "animal",
    },
}


def variant_profile(tokens: frozenset[str]) -> dict[str, set[str]]:
    """Which variant dimensions these tokens commit to, and to what."""
    profile: dict[str, set[str]] = {}
    for dimension, mapping in _VARIANT_DIMENSIONS.items():
        values = {mapping[t] for t in tokens if t in mapping}
        if values:
            profile[dimension] = values
    return profile


def variants_conflict(a: dict[str, set[str]], b: dict[str, set[str]]) -> bool:
    """True when both commit to the same dimension and disagree about it."""
    return any(
        not (values & b[dimension]) for dimension, values in a.items() if dimension in b
    )


def variant_overlap(sku: dict[str, set[str]], alias: dict[str, set[str]]) -> int:
    """How many variant dimensions the alias positively agrees with.

    Ranked ahead of raw similarity, because a generic alias otherwise beats a
    specific one on length alone: "Lassie Zilvervlies rijst" contains the alias
    "rijst" (white rice, 7 g protein) as surely as it contains "zilvervlies
    rijst", and silence about a dimension must not outrank agreement with it.
    """
    return sum(1 for dim, values in sku.items() if values & alias.get(dim, set()))


def normalise_name(name: str | None, brand: str | None = None) -> str:
    """Reduce a shelf title to its food-identifying words."""
    if not name:
        return ""
    text = name.lower()
    text = text.replace("ü", "u").replace("é", "e")
    text = text.replace("ë", "e").replace("ï", "i")
    if brand:
        text = text.replace(brand.lower(), " ")
    text = _UNIT_NOISE.sub(" ", text)
    text = _PUNCT.sub(" ", text)
    tokens = [t for t in text.split() if t and t not in _NOISE and not t.isdigit()]
    return " ".join(tokens)


@dataclass
class Matcher:
    aliases: dict[str, str] = field(default_factory=dict)  # alias text -> food_type key
    overrides: dict = field(default_factory=dict)
    accept_threshold: float = ACCEPT_THRESHOLD
    known_keys: set[str] = field(default_factory=set)
    # food type key -> protein per 100 g, for the flavour guard. Empty means
    # the guard can't tell and stays out of the way.
    protein: dict[str, float | None] = field(default_factory=dict)

    @property
    def non_rankable_categories(self) -> set[str]:
        """Chain categories that are not food worth ranking (drogisterij, etc.)."""
        return set(self.overrides.get("non_rankable_categories") or [])

    def __post_init__(self) -> None:
        if not self.known_keys:
            self.known_keys = set(self.aliases.values())
        # Pre-normalise once; matching runs over every SKU on every ingest.
        self._normalised: list[tuple[str, frozenset[str], str]] = [
            (n, frozenset(n.split()), key)
            for alias, key in self.aliases.items()
            if (n := normalise_name(alias))
        ]

    @classmethod
    def from_db(cls, conn: sqlite3.Connection, overrides_path: Path | None = None) -> Matcher:
        rows = conn.execute(
            "SELECT a.alias, f.key FROM food_type_aliases a JOIN food_types f ON f.id=a.food_type_id"
        ).fetchall()
        return cls(
            aliases={r["alias"]: r["key"] for r in rows},
            overrides=load_overrides(overrides_path),
            known_keys={r["key"] for r in rows},
            protein={r["key"]: r["protein_per_100g"] for r in conn.execute(
                "SELECT key, protein_per_100g FROM food_types")},
        )

    def match(
        self, name: str | None, *, brand: str | None = None,
        chain: str | None = None, sku: str | None = None,
    ) -> MatchResult:
        # 1. Exact SKU override.
        if chain and sku:
            key = (self.overrides.get("sku") or {}).get(f"{chain}:{sku}")
            if key:
                return self._resolve(key, MatchMethod.OVERRIDE_SKU, 1.0)

        raw = (name or "").lower()

        # 2. Explicit exclusions - not food, and not worth reviewing weekly.
        for marker in self.overrides.get("never_match") or []:
            if str(marker).lower() in raw:
                return MatchResult(None, MatchMethod.EXCLUDED, 0.0, False,
                                   f"excluded by {marker!r}")

        # 3. Substring override.
        for marker, key in (self.overrides.get("contains") or {}).items():
            if str(marker).lower() in raw:
                return self._resolve(key, MatchMethod.OVERRIDE_CONTAINS, 1.0)

        normalised = normalise_name(name, brand)
        if not normalised:
            return MatchResult(None, MatchMethod.NONE, 0.0, True, "empty after normalisation")

        # 4. Prepared dish: the named ingredient is an ingredient, not the product.
        dish = sorted(set(_MARKER_RE.findall(normalised)))
        dish += sorted(_COMPOSITE_WORDS & set(normalised.split()))
        if dish:
            return MatchResult(
                None, MatchMethod.NONE, 0.0, True,
                f"prepared dish ({', '.join(sorted(dish))}) - macros are not the ingredient's",
            )

        # 5. A mix of foods is not any one of them.
        distinct = self._distinct_foods_named(normalised)
        if len(distinct) > 1:
            return MatchResult(
                None, MatchMethod.NONE, 0.0, True,
                f"names {len(distinct)} distinct food types "
                f"({', '.join(sorted(distinct))}) - a mix is not any one of them",
            )

        best_key, best_method = None, MatchMethod.NONE
        best_rank: tuple[int, float, int] = (-1, 0.0, 0)
        best_score = 0.0
        tokens = frozenset(normalised.split())
        sku_variants = variant_profile(tokens)
        blocked = 0
        best_alias = ""

        for alias_norm, alias_tokens, key in self._normalised:
            alias_variants = variant_profile(alias_tokens)
            if variants_conflict(sku_variants, alias_variants):
                blocked += 1
                continue

            if alias_norm == normalised:
                score, method = 1.0, MatchMethod.ALIAS_EXACT
            elif alias_tokens and alias_tokens <= tokens:
                # Every word of the alias is present: "magere kwark" inside
                # "zaanse hoeve magere kwark". Strong, but below an exact hit.
                score, method = 0.95, MatchMethod.ALIAS_CONTAINED
            else:
                score = SequenceMatcher(None, alias_norm, normalised).ratio()
                method = MatchMethod.FUZZY

            # Agreement on a variant first, then similarity, then specificity.
            candidate = (variant_overlap(sku_variants, alias_variants), score, len(alias_tokens))
            if candidate > best_rank:
                best_key, best_rank, best_score, best_method = key, candidate, score, method
                best_alias = alias_norm

        threshold = (
            FUZZY_THRESHOLD if best_method is MatchMethod.FUZZY else self.accept_threshold
        )
        if best_key is None or best_score < threshold:
            detail = f" ({blocked} candidates blocked on a variant clash)" if blocked else ""
            return MatchResult(
                None, MatchMethod.NONE, best_score, True,
                f"best candidate {best_key!r} scored {best_score:.2f} "
                f"< {threshold} ({best_method.value} lane){detail}",
            )
        carriers = set(_CARRIER_RE.findall(normalised)) - set(_CARRIER_RE.findall(best_alias))
        protein = self.protein.get(best_key)
        if carriers and protein is not None and protein < FLAVOUR_MAX_PROTEIN:
            return MatchResult(
                None, MatchMethod.NONE, best_score, True,
                f"{best_key!r} is the flavour of a {', '.join(sorted(carriers))} product, "
                "not the product",
            )
        return self._resolve(best_key, best_method, best_score)

    def _distinct_foods_named(self, normalised: str) -> set[str]:
        """Food types whose alias appears in full, ignoring pure qualifiers.

        Aliases that nest ("kwark" inside "magere kwark") are the same food at
        different specificity and must not count as two.
        """
        tokens = frozenset(normalised.split())
        hits: dict[str, frozenset[str]] = {}
        for _alias_norm, alias_tokens, key in self._normalised:
            content = alias_tokens - _QUALIFIERS
            if not content or not (content <= tokens):
                continue
            # Compare on CONTENT tokens, not the raw alias. Nesting is a
            # relationship between meanings: "olijfolie" nests inside
            # "tonijnmoot in olijfolie" (tuna packed in oil is one food), but
            # the raw alias "extra vierge olijfolie" does not, so comparing raw
            # aliases sent every tin of tuna-in-olive-oil to review.
            if key not in hits or len(content) > len(hits[key]):
                hits[key] = content

        keys = list(hits)
        return {
            k for k in keys
            if not any(other != k and hits[k] < hits[other] for other in keys)
        }

    def _resolve(self, key: str, method: MatchMethod, score: float) -> MatchResult:
        if self.known_keys and key not in self.known_keys:
            # An override pointing at a food_type that does not exist is a typo in
            # a hand-edited file. Surface it; do not fall through to fuzzy.
            return MatchResult(None, MatchMethod.NONE, 0.0, True,
                               f"override targets unknown food_type {key!r}")
        return MatchResult(key, method, score)


def load_overrides(path: Path | None = None) -> dict:
    target = path or OVERRIDES_PATH
    if not target.exists():
        return {}
    return yaml.safe_load(target.read_text(encoding="utf-8")) or {}
