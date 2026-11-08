import datetime as dt
import json

from triptool.plan import build_plan
from triptool.providers import Quote
from triptool.recommend import summarize
from triptool.config import Settings
from triptool.report import leg_signal
from triptool.sheet import parse_calendar, parse_flight_table
from triptool.store import Store
from triptool.writeback import build_updates, col_letter, signed_jwt

FLIGHTS = [
    ["", "CAT FLIGHTS"],
    ["", "Date", "Depart", "Arrive", "Cost", "Length (hrs)", "Flight Number", "Booked"],
    ["", "June 6", "Toronto", "Tokyo", "630", "", "", "TRUE"],
    ["", "Total", "", "", "630"],
    [], [],
    ["", "Elliot Flights - Current Recommendation"],
    ["", "Date", "Depart", "Arrive", "Cost", "Length (hrs)", "Flight Number", "Booked", "Notes (updated weekly)"],
    ["", "June 6", "Toronto", "Tokyo", "630", "", "", "TRUE", "Booked"],
    ["", "June 9", "Tokyo", "Okinawa", "150", "", "", "FALSE", ""],
    ["", "Total"],
]
CAL = [["SUNDAY", "", "MONDAY", "", "TUESDAY", "", "WEDNESDAY"], [],
       ["June 6", "", "June 7", "", "June 8", "", "June 9"],
       ["TRAVEL", "", "JAPAN - TOKYO", "", "JAPAN - TOKYO", "", "JAPAN to OKINAWA"]]
TODAY = dt.date(2026, 11, 8)


def test_col_letter():
    assert [col_letter(i) for i in (0, 4, 8, 25, 26)] == ["A", "E", "I", "Z", "AA"]


def test_updates_only_touch_unbooked_rows_of_my_table(tmp_path):
    table = parse_flight_table(FLIGHTS, 2027, "Elliot Flights")
    for f in table.flights:
        f.source = "my table"
    plan = build_plan(parse_calendar(CAL, today=TODAY), table.flights)
    leg = next(l for l in plan.legs if not l.flight.booked)
    q = Quote(leg.id, "flight", leg.flight.date, 138.4, "CAD", flight_no="NH 123", duration="3 hrs 5 mins", source="serpapi")
    legs = summarize(plan, {(leg.id, leg.flight.date): q}, Settings())
    store = Store(tmp_path / "p.db")
    sigs = {lr.leg.id: leg_signal(lr, store, "serpapi", TODAY) for lr in legs}
    data = {d["range"]: d["values"][0][0] for d in build_updates(table, "flights", legs, sigs, TODAY)}
    assert data["'flights'!E10"] == 138                  # row 10 = Tokyo -> Okinawa
    assert data["'flights'!G10"] == "NH 123"
    assert "▼ $12 vs last week" in data["'flights'!I10"]
    assert not any(k.endswith("9") and "!E" in k for k in data)   # booked row untouched
    assert data["'flights'!I7"].startswith("Last checked")


def test_jwt_is_signed_with_the_service_account_key():
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    import base64
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption()).decode()
    tok = signed_jwt({"client_email": "bot@x.iam.gserviceaccount.com", "private_key": pem}, now=1000)
    head, claims, sig = tok.split(".")
    pad = lambda s: s + "=" * (-len(s) % 4)
    assert json.loads(base64.urlsafe_b64decode(pad(claims)))["iss"] == "bot@x.iam.gserviceaccount.com"
    key.public_key().verify(base64.urlsafe_b64decode(pad(sig)), f"{head}.{claims}".encode(),
                            padding.PKCS1v15(), hashes.SHA256())
