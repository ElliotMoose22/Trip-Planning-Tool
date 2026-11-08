import datetime as dt

from triptool.tables import build_from_tables, parse_legs, parse_places

PLACES = [["Places"], ["hint"],
          ["Country", "City", "Priority", "Min nights", "Max nights", "Fixed dates / must-do", "Arrive", "Leave", "Nights", "Notes (updated weekly)"],
          ["Japan", "Tokyo", "Must", "5", "7", "", "Mon Jun 7", "Fri Jun 11", "4", ""],
          ["Thailand", "Bangkok", "Want", "", "", "", "Fri Jun 11", "", "", ""],
          ["Thailand", "Phuket", "Must", "", "", "", "", "Tue Jun 15", "", ""],
          ["Indonesia", "Bali", "Must", "3", "6", "", "Wed Jun 16", "Sun Jun 20", "4", ""],
          ["Indonesia", "Somewhere odd", "Maybe", "", "", "", "Sun Jun 20", "Mon Jun 21", "1", ""]]
LEGS = [["Legs"], ["hint"],
        ["From", "To", "Mode", "Earliest", "Latest", "Date", "Status", "Price (per person)", "Length", "Flight / service no.", "Booking ref", "Notes (updated weekly)"],
        ["Toronto", "Tokyo", "Flight", "", "", "2027-06-06", "Booked", "$630", "", "", "", ""],
        ["Tokyo", "Bangkok", "Flight", "Jun 10", "Jun 12", "Jun 11", "Planned", "$300", "", "", "", ""],
        ["Bangkok", "Phuket", "Bus", "", "Jun 14", "", "Idea", "", "", "", "", ""],
        ["Phuket", "Bali", "Flight", "", "", "Jun 15", "Planned", "", "", "", "", ""]]


def test_tables_plan():
    places, cols = parse_places(PLACES, 2027)
    legs, table = parse_legs(LEGS, 2027)
    plan = build_from_tables(places, legs, dt.date(2027, 6, 6), dt.date(2027, 6, 25))
    text = " | ".join(c.text for c in plan.checks)
    assert "at least 5" in text                         # Tokyo 4 nights < min 5
    assert "Bangkok: needs a Leave date" in text
    assert "Must, but it has no Arrive / Leave" in text  # Phuket
    assert "can't place" in text                        # Somewhere odd
    assert "1 night not planned between Jun 15 and Jun 16" in text   # Phuket -> Bali gap
    assert "4 nights before Jun 25" in text
    bkk = next(l for l in plan.legs if l.destination.name == "Bali")
    assert [p.name for p in bkk.alt_origins] == ["Bangkok"]          # skip-the-bus option
    tb = next(l for l in plan.legs if l.origin.name == "Tokyo")
    assert tb.window == (dt.date(2027, 6, 10), dt.date(2027, 6, 12))
    assert [g.mode for g in plan.ground] == ["Bus"]
    assert places[0].notes and places[0].notes[0].startswith("4 nights planned")
    assert table.cols["cost"] == 7 and table.cols["notes"] == 11
