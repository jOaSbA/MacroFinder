"""Price history signals. Milestones 21 and 22, BRIEF section 3.4.

All fixture history; nothing here touches a database.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from bonusrank import history

START = date(2026, 9, 21)


def days(n):
    return START - timedelta(days=n)


# -- reference-price inflation -------------------------------------------------

def test_a_shelf_price_raised_just_before_the_promo_is_flagged():
    shelf = [(days(40), 2.49), (days(20), 2.99), (days(3), 2.99)]
    assert history.reference_inflated(shelf, START, promo_shelf=2.99) is True


def test_a_steady_shelf_price_is_not_flagged():
    shelf = [(days(40), 2.99), (days(20), 2.99), (days(3), 2.99)]
    assert history.reference_inflated(shelf, START, promo_shelf=2.99) is False


def test_a_rise_long_before_the_window_is_not_flagged():
    shelf = [(days(90), 2.49), (days(60), 2.99), (days(20), 2.99)]
    assert history.reference_inflated(shelf, START, promo_shelf=2.99) is False


def test_without_a_price_from_before_the_window_it_is_unknown():
    # Only seen for a week. Can't tell a rise from a price we never saw.
    shelf = [(days(5), 2.99), (days(2), 2.99)]
    assert history.reference_inflated(shelf, START, promo_shelf=2.99) is None


def test_rounding_noise_is_not_inflation():
    shelf = [(days(40), 2.99), (days(3), 3.00)]
    assert history.reference_inflated(shelf, START, promo_shelf=3.00) is False


# -- promo cycle ----------------------------------------------------------------

def test_the_cycle_is_the_median_gap_between_promo_starts():
    starts = [days(84), days(56), days(28), START]
    assert history.cycle_days(starts) == 28


def test_fewer_than_three_promos_is_no_cycle():
    assert history.cycle_days([days(28), START]) is None


def test_repeated_start_dates_count_once():
    starts = [days(56), days(56), days(28), days(28), START]
    assert history.cycle_days(starts) == 28


def test_on_promo_now_means_buy():
    assert history.cycle_hint(28, START, on_promo=True, today=START + timedelta(days=2)) == "buy"


def test_next_promo_close_means_wait():
    # Every 4 weeks, last one 3 weeks ago: the brief's own example.
    assert history.cycle_hint(28, START, on_promo=False,
                              today=START + timedelta(days=21)) == "wait"


def test_next_promo_far_away_means_buy():
    assert history.cycle_hint(56, START, on_promo=False,
                              today=START + timedelta(days=7)) == "buy"


def test_no_cycle_no_hint():
    assert history.cycle_hint(None, START, on_promo=False, today=START) is None


# -- weekly series for the sparkline -------------------------------------------

def test_weekly_series_takes_the_lowest_price_each_week():
    obs = [(date(2026, 9, 14), 2.99), (date(2026, 9, 16), 1.99),
           (date(2026, 9, 21), 2.49), (date(2026, 9, 22), 2.99)]
    assert history.weekly_min(obs) == [("2026-09-14", 1.99), ("2026-09-21", 2.49)]


def test_weekly_series_is_capped():
    obs = [(date(2026, 1, 5) + timedelta(weeks=i), 1.0 + i) for i in range(40)]
    series = history.weekly_min(obs, weeks=26)
    assert len(series) == 26
    assert series[-1][1] == pytest.approx(40.0)
