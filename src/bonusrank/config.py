"""Project-wide settings.

Politeness numbers live here and nowhere else, so there is exactly one place to
check them against CLAUDE.md section 1.
"""

from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "bonusrank"
APP_VERSION = "0.1.0"

# The brief forbids spoofing the official mobile app's User-Agent: this tool should
# be honest about being a personal-use script. Operators who want to reach the
# person behind the traffic need a contact, so set BONUSRANK_CONTACT to an address
# or URL you are happy to hand to Albert Heijn and Open Food Facts. It is left
# unset by default rather than guessed - see docs note in CLAUDE.md section 1.
CONTACT = os.environ.get("BONUSRANK_CONTACT", "").strip()

USER_AGENT = (
    f"{APP_NAME}/{APP_VERSION} (personal meal-planning tool; +{CONTACT})"
    if CONTACT
    else f"{APP_NAME}/{APP_VERSION} (personal meal-planning tool; non-commercial, single user)"
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"        # replay source - never delete, never gitignore
CACHE_DIR = DATA_DIR / "cache"    # politeness cache - disposable
EXTERNAL_DIR = DATA_DIR / "external"

# --- user settings -------------------------------------------------------
# Brief section 5: every optimiser input comes from user config, none hardcoded.
# The ranking already needs two of them for the waste adjustment (section 3.3).
# Override any of these in `config.yaml` at the project root.

USER_DEFAULTS: dict[str, object] = {
    "daily_protein_target_g": 150,
    "daily_kcal_floor": 2200,       # a FLOOR. Never an objective (section 5).
    "weekly_budget_eur": 50,
    "max_stores_per_week": 2,
    # How much of one food you would realistically eat per day. Drives the
    # waste adjustment: a 1+1 on 2 kg of kwark is only a deal if you eat it.
    "daily_consumption_g": 250,
    # Freezable items get their shelf life extended to this horizon.
    "freezer_horizon_days": 90,
    "variety_cap_servings_per_week": 7,
    # How much hands-on time a DIY composition may cost before `compare` stops
    # offering it. Section 4.1 puts max_prep_minutes on the archetype; this is
    # the user's own ceiling across all of them.
    "max_prep_minutes": 15,
    # Milestone 9: per-meal optimiser floors, keyed by archetype.meal_kind.
    # Each is a hard floor the LP must satisfy, never an objective term - a
    # meal's carb/fat floors are what stop a cost-minimising solver collapsing
    # onto the cheapest single protein source. A drink is allowed to stay
    # protein-forward on purpose (a shake is supposed to be that), so it
    # carries no carb/fat floor at all; a snack sits in between. Retune these
    # rather than the code when "what counts as a normal meal" needs to change.
    "optimiser_profiles": {
        "meal":  {"kcal": 250, "carbs_g": 20, "fat_g": 8},
        "snack": {"kcal": 80,  "carbs_g": 10},
        "drink": {"kcal": 50},
    },
}


def user_settings() -> dict:
    """User config, falling back to USER_DEFAULTS for anything unset."""
    settings = dict(USER_DEFAULTS)
    path = PROJECT_ROOT / "config.yaml"
    if path.exists():
        import yaml

        settings.update(yaml.safe_load(path.read_text(encoding="utf-8")) or {})
    return settings


# Politeness, per CLAUDE.md section 1. Do not raise these.
MAX_REQUESTS_PER_SECOND = 2.0
CACHE_TTL_SECONDS = 6 * 60 * 60
HTTP_TIMEOUT_SECONDS = 30.0
MAX_RETRIES = 4
BACKOFF_BASE_SECONDS = 1.0
