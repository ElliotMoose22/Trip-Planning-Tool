import datetime as dt

from triptool.signals import cheapest_per_check, evaluate


def test_close_in_is_buy():
    assert evaluate([500, 520], days_out=10, category="regional").verdict == "BUY"


def test_far_out_is_wait():
    assert evaluate([1200, 1180, 1210], days_out=300, category="long_haul").verdict == "WAIT"


def test_lowest_seen_is_buy_even_when_early():
    assert evaluate([1300, 1250, 1280, 1100], days_out=300, category="long_haul").verdict == "BUY"


def test_sweet_spot_above_median_is_watch():
    assert evaluate([200, 210, 205, 260], days_out=60, category="regional").verdict == "WATCH"


def test_over_budget_stay_not_bought_on_low_rank():
    s = evaluate([300, 290, 280, 270], days_out=200, category="stay", budget=200)
    assert s.verdict != "BUY" and "budget" in s.reason


def test_booked():
    assert evaluate([1], days_out=50, category="regional", booked=True).verdict == "BOOKED"


def test_cheapest_per_check():
    d1, d2 = dt.date(2026, 11, 1), dt.date(2026, 11, 8)
    t = dt.date(2027, 6, 1)
    rows = [(d1, t, 300), (d1, t, 250), (d2, t, 280), (d2, t, 290)]
    assert cheapest_per_check(rows) == [250, 280]
