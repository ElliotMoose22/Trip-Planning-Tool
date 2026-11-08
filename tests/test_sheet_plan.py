"""Sheet reading + plan checks, on a small made-up sheet in the same layout as ours."""
import datetime as dt

from triptool.plan import build_plan
from triptool.sheet import parse_calendar, parse_flights

CAL = [
    ["SUNDAY", "", "MONDAY", "", "TUESDAY", "", "WEDNESDAY", "", "THURSDAY", "", "FRIDAY", "", "SATURDAY"],
    [],
    ["June 6", "", "June 7", "", "June 8", "", "June 9", "", "June 10", "", "June 11", "", "June 12", "", "Concert in bali"],
    ["TRAVEL", "", "JAPAN - TOKYO", "", "JAPAN - TOKYO", "", "JAPAN - Tokyo to Fukuoka", "", "JAPAN", "", "JAPAN to THAILAND", "", "THAILAND"],
    ["Toronto to Tokyo", "", "", "", "", "", "Flight GK509 $132 CAD", "", "Fukuoka to Kagoshima", "", "", "", ""],
    [],
    ["June 13", "", "June 14", "", "June 15", "", "June 16"],
    ["THAILAND", "", "THAILAND", "", "THAILAND to INDONESIA", "", "INDONESIA - BALI"],
]
FLIGHTS = [
    ["", "FLIGHTS"],
    ["", "Date", "Depart", "Arrive", "Cost", "Length (hrs)", "Flight Number", "Booked"],
    ["", "June 6", "Toronto", "Tokyo", "630", "", "", "TRUE"],
    ["", "June 11", "Fukuoka", "Bangkok", "250", "", "", "FALSE", "maybe from Kagoshima"],
    ["", "June 15", "Phuket (Thailand)", "Bali", "145", "", "QZ 247", "FALSE", "", "OR"],
    ["", "June 20", "Bali", "Toronto", "900", "", "", "FALSE", "", "June 15", "Bangkok", "Bali", "130"],
    ["", "Total", "", "", "1925"],
]
TODAY = dt.date(2026, 11, 8)


def test_year_from_weekday_columns():
    days = parse_calendar(CAL, today=TODAY)
    assert days[0].date == dt.date(2027, 6, 6)   # June 6 sits under SUNDAY -> 2027


def test_flights_tab_and_option_b():
    fl = parse_flights(FLIGHTS, 2027)
    a = [f for f in fl if f.option == "A"]
    b = [f for f in fl if f.option == "B"]
    assert len(a) == 4 and a[0].booked and a[1].note == "maybe from Kagoshima"
    assert b[0].origin == "Bangkok" and b[0].cost == 130


def test_plan_checks():
    plan = build_plan(parse_calendar(CAL, today=TODAY), parse_flights(FLIGHTS, 2027))
    text = " ".join(c.text for c in plan.checks)
    assert "Tokyo → Fukuoka (GK509)" in text            # calendar-only flight
    assert "Kagoshima the night before" in text          # notes say you moved on
    assert "never gets you there from Bangkok" in text   # Phuket departure with no way there
    assert "Concert in bali" in text                     # side note in the wrong week
    cal_leg = next(l for l in plan.legs if l.flight.source == "calendar")
    assert cal_leg.flight.cost == 132
    assert [s.place.name for s in plan.stops][:4] == ["Tokyo", "Fukuoka", "Kagoshima", "Bangkok"]


def test_real_date_cells_with_wrong_hidden_year():
    """Google Sheets stores 'June 6' as a full date (here 2026); the weekday columns must win."""
    import io
    import openpyxl
    from triptool.sheet import grids_from_xlsx
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Calendar"
    ws.append(["SUNDAY", None, "MONDAY"])
    ws.append([dt.datetime(2026, 6, 6), None, dt.datetime(2026, 6, 7)])
    ws.append(["TRAVEL", None, "JAPAN - TOKYO"])
    buf = io.BytesIO()
    wb.save(buf)
    days = parse_calendar(grids_from_xlsx(buf.getvalue())["Calendar"], today=TODAY)
    assert [d.date for d in days] == [dt.date(2027, 6, 6), dt.date(2027, 6, 7)]
