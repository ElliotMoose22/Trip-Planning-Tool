"""Weekly report as HTML (to open/share) + Markdown (GitHub summary) + plan.json (for the globe)."""
from __future__ import annotations

import datetime as dt
import html
import json
from dataclasses import dataclass
from pathlib import Path

from .config import Settings
from .plan import Plan, Stop
from .providers import Quote
from .recommend import LegResult, km, option_comparison
from .signals import Signal, evaluate
from .store import Store

COLORS = {"BUY": "#1a7f4b", "WATCH": "#b26b00", "WAIT": "#5b6170", "BOOKED": "#3a5bd9"}
esc = html.escape


@dataclass
class StayResult:
    stop: Stop
    quote: Quote | None
    signal: Signal
    series: list[float]
    budget: float | None


def money(v, cur="") -> str:
    return "–" if v is None else f"${v:,.0f}{(' ' + cur) if cur else ''}"


def _series(store: Store, item_id: str, source: str, travel_date: dt.date | None = None) -> list[float]:
    by_check: dict[dt.date, float] = {}
    for checked, travel, price in store.history(item_id, source):
        if travel_date and travel != travel_date:
            continue
        by_check[checked] = min(price, by_check.get(checked, price))
    return [by_check[k] for k in sorted(by_check)]


def leg_signal(lr: LegResult, store: Store, source: str, today: dt.date) -> tuple[Signal, list[float]]:
    f = lr.leg.flight
    series = _series(store, lr.leg.id, source, f.date)
    cat = "long_haul" if km(lr.leg.origin, lr.leg.destination) > 4000 else "regional"
    return evaluate(series, (f.date - today).days, cat, f.booked), series


def _spark(series: list[float], w=130, h=30) -> str:
    if len(series) < 2:
        return '<span class="muted small">trend after 2+ weeks</span>'
    lo, hi = min(series), max(series)
    span = (hi - lo) or 1
    pts = [(i * w / (len(series) - 1), h - 3 - (v - lo) / span * (h - 6)) for i, v in enumerate(series)]
    line = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}"><polyline points="{line}" fill="none" '
            f'stroke="currentColor" stroke-width="1.6"/><circle cx="{pts[-1][0]:.1f}" cy="{pts[-1][1]:.1f}" '
            f'r="2.6" fill="currentColor"/></svg> <span class="muted small">low {money(lo)} · high {money(hi)}</span>')


def _chg(sig: Signal) -> str:
    if sig.change_pct is None:
        return ""
    if sig.change_pct == 0:
        return '<span class="muted small">flat wk</span>'
    up = sig.change_pct > 0
    return f'<span class="{"up" if up else "down"}">{"▲" if up else "▼"} {abs(sig.change_pct)}% wk</span>'


def _flight_card(lr: LegResult, sig: Signal, series: list[float], cur: str) -> str:
    f, leg = lr.leg.flight, lr.leg
    title = f"{leg.origin.name} → {leg.destination.name}"
    sub = f"{f.date:%a %b %-d}" + (f" · {esc(f.flight_no)}" if f.flight_no else "") + \
          (" · option B" if f.option == "B" else "") + (" · from calendar" if f.source == "calendar" else "")
    if f.booked:
        return (f'<div class="card booked"><div class="top"><span class="pill" style="background:{COLORS["BOOKED"]}">'
                f'BOOKED</span><span class="kind">Flight</span></div><h3>{esc(title)}</h3><div class="when">{sub}</div>'
                f'<div class="muted small">Paid {money(f.cost, cur)} per person</div></div>')
    now = lr.plan_price
    vs = ""
    if now is not None and f.cost:
        d = now - f.cost
        vs = (f'<span class="vs {"good" if d < 0 else "bad" if d > 0 else ""}">sheet {money(f.cost)} · '
              f'{"▼" if d < 0 else "▲" if d > 0 else "="} {money(abs(d))}</span>')
    elif f.cost:
        vs = f'<span class="vs">sheet {money(f.cost)}</span>'
    sugg = "".join(
        f'<li class="{s.kind}"><b>{esc(s.text)}</b> — {money(s.price)}'
        f'{f" · saves {money(s.saves)}" if s.saves and s.saves > 0 else (f" · {money(-s.saves)} more" if s.saves and s.saves < 0 else "")}</li>'
        for s in lr.suggestions)
    flex = ""
    if len(lr.by_date) > 1:
        lo = min(lr.by_date.values())
        cells = "".join(
            f'<td class="{"best" if p == lo else ""}{" plan" if d == f.date else ""}">{d:%a %-d}<br><b>{money(p)}</b></td>'
            for d, p in sorted(lr.by_date.items()))
        flex = f'<table class="flex"><tr>{cells}</tr></table>'
    link = f' · <a href="{esc(lr.plan_link)}">open</a>' if lr.plan_link else ""
    return f"""<div class="card">
  <div class="top"><span class="pill" style="background:{COLORS[sig.verdict]}">{sig.verdict}</span>
    <span class="kind">Flight</span><span class="days">{sig.days_out} days out</span></div>
  <h3>{esc(title)}</h3><div class="when">{sub}</div>
  <div class="price"><b>{money(now, cur) if now is not None else "not priced yet"}</b>
    <span class="muted">per person</span> {_chg(sig)}</div>
  <div>{vs}</div>
  <div class="spark">{_spark(series)}</div>
  <p class="reason">{esc(sig.reason)}</p>
  {f'<ul class="sugg">{sugg}</ul>' if sugg else ''}
  <div class="muted small">{esc(lr.plan_detail)}{link}</div>{flex}
</div>"""


def _stay_card(sr: StayResult, cur: str) -> str:
    st, sig, q = sr.stop, sr.signal, sr.quote
    over = sr.budget and q and q.price > sr.budget
    link = f' · <a href="{esc(q.link)}">open</a>' if q and q.link else ""
    return f"""<div class="card">
  <div class="top"><span class="pill" style="background:{COLORS[sig.verdict]}">{sig.verdict}</span>
    <span class="kind">Stay</span><span class="days">{sig.days_out} days out</span></div>
  <h3>{esc(st.place.name)} · {st.nights} nights{' <span class="tag">assumed</span>' if st.assumed else ''}</h3>
  <div class="when">{st.check_in:%a %b %-d} → {st.check_out:%a %b %-d}</div>
  <div class="price"><b>{money(q.price, cur) if q else "not priced yet"}</b> <span class="muted">per night</span> {_chg(sig)}</div>
  <div class="muted small">budget {money(sr.budget)}{' · over budget' if over else ''}
    {f" · about {money(q.price * st.nights)} total" if q else ""}</div>
  <div class="spark">{_spark(sr.series)}</div>
  <p class="reason">{esc(sig.reason)}</p>
  <div class="muted small">{esc(q.detail) if q else ''}{link}</div>
</div>"""


CSS = """
:root { --bg:#f6f4ef; --card:#fff; --ink:#1d1f24; --muted:#6b7080; --line:#e6e2d8; --good:#1a7f4b; --bad:#c0392b; }
@media (prefers-color-scheme: dark) { :root { --bg:#14161a; --card:#1d2026; --ink:#eceae4; --muted:#9aa0ad; --line:#2c3038; --good:#4cc38a; --bad:#ff7a6b; } }
* { box-sizing:border-box } body { margin:0; font:15px/1.45 -apple-system,system-ui,"Segoe UI",sans-serif; background:var(--bg); color:var(--ink) }
.wrap { max-width:1120px; margin:auto; padding:0 24px }
header { padding:32px 0 6px } h1 { font-size:28px; margin:0 0 4px; letter-spacing:-.02em } h2 { font-size:19px; margin:28px 0 10px }
h3 { margin:6px 0 0; font-size:18px } .sub,.muted { color:var(--muted) } .small { font-size:12px }
.totals { display:flex; gap:28px; flex-wrap:wrap; margin:18px 0 4px } .totals div b { display:block; font-size:24px }
.banner { margin-top:14px; padding:8px 12px; border:1px dashed var(--muted); border-radius:8px; color:var(--muted); display:inline-block }
.checks { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:6px 18px }
.checks li { margin:9px 0 } .checks .fix::marker { content:"⚠  " } .checks .heads-up::marker { content:"ℹ  " }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(330px,1fr)); gap:14px }
.card { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px } .card.booked { opacity:.75 }
.top { display:flex; gap:8px; align-items:center; font-size:12px } .days { margin-left:auto; color:var(--muted) }
.pill { color:#fff; font-weight:700; padding:2px 9px; border-radius:99px; letter-spacing:.04em }
.kind { color:var(--muted); text-transform:uppercase; letter-spacing:.06em } .when { color:var(--muted); font-size:13px }
.price { margin-top:10px; font-size:20px } .vs { font-size:13px; color:var(--muted) } .vs.good { color:var(--good) } .vs.bad { color:var(--bad) }
.tag { font-size:11px; font-weight:500; border:1px solid var(--line); border-radius:6px; padding:1px 6px; color:var(--muted) }
.spark { display:flex; align-items:center; gap:8px; margin:6px 0 } .reason { margin:6px 0 }
.up { color:var(--bad); font-size:13px } .down { color:var(--good); font-size:13px } a { color:inherit }
.sugg { margin:6px 0 8px; padding-left:18px; font-size:14px } .sugg li { margin:3px 0 } .sugg li::marker { content:"→ " }
.sugg .date b, .sugg .nearby b { color:var(--good) }
.flex { width:100%; border-collapse:collapse; margin-top:10px; font-size:12px; text-align:center }
.flex td { border:1px solid var(--line); padding:5px 2px } .flex td.best { background:rgba(26,127,75,.14) } .flex td.plan { outline:2px solid var(--muted); outline-offset:-2px }
.opt { background:var(--card); border:1px solid var(--line); border-radius:14px; padding:16px; display:grid; grid-template-columns:1fr 1fr; gap:18px }
.ground { width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); border-radius:14px; overflow:hidden }
.ground td { padding:10px 14px; border-top:1px solid var(--line) } .ground tr:first-child td { border-top:0 } .ground .num { text-align:right; font-variant-numeric:tabular-nums; color:var(--muted) }
footer { padding:28px 0 36px; color:var(--muted); font-size:12px }
"""


def render_html(s: Settings, plan: Plan, legs: list[LegResult], sigs: dict, stays: list[StayResult],
                today: dt.date, source: str) -> str:
    cur = s.currency
    live = [lr for lr in legs if lr.leg.flight.date >= today]
    a = [lr for lr in live if lr.leg.flight.option == "A"]
    sheet_total = sum(lr.leg.flight.cost or 0 for lr in a)
    now_vals = [lr.leg.flight.cost if lr.leg.flight.booked else lr.plan_price for lr in a]
    priced = [v for v in now_vals if v is not None]
    now_total = sum(priced) + sum((lr.leg.flight.cost or 0) for lr, v in zip(a, now_vals) if v is None)
    buys = [lr for lr in live if sigs[lr.leg.id][0].verdict == "BUY"] + [x for x in stays if x.signal.verdict == "BUY"]
    n_sugg = sum(1 for lr in live for x in lr.suggestions if (x.saves or 0) > 0)

    fixes = [c for c in plan.checks if c.level == "fix"]
    ups = [c for c in plan.checks if c.level != "fix"]
    checks_html = ""
    recs = getattr(plan, "recs", [])
    if recs:
        items = "".join(f'<li><span class="tag">{esc(r.kind)}</span> <b>{esc(r.title)}</b><br>'
                        f'<span class="muted">{esc(r.detail)}</span></li>' for r in recs)
        checks_html = f'<h2>Recommendations</h2><ul class="checks recs">{items}</ul>'
    elif plan.checks:
        items = "".join(f'<li class="{c.level}">{esc(c.text)}</li>' for c in fixes + ups)
        checks_html = f'<h2>Things to fix in the sheet</h2><ul class="checks">{items}</ul>'

    opt = option_comparison(plan, live)
    opt_html = ""
    if opt:
        def col(name, legs_, sheet, now):
            route = " → ".join([legs_[0].origin.name] + [l.destination.name for l in legs_])
            return (f'<div><div class="kind small">{name}</div><h3>{esc(route)}</h3>'
                    f'<div class="price"><b>{money(now)}</b> <span class="muted">now · sheet {money(sheet)}</span></div></div>')
        better = ""
        if opt["a_now"] and opt["b_now"]:
            diff = opt["a_now"] - opt["b_now"]
            better = f'<p class="reason">Right now option {"B" if diff > 0 else "A"} is {money(abs(diff))} cheaper per person.</p>'
        opt_html = (f'<h2>Your two options for getting home</h2><div class="opt">{col("Option A", opt["a"], opt["a_sheet"], opt["a_now"])}'
                    f'{col("Option B", opt["b"], opt["b_sheet"], opt["b_now"])}</div>{better}')

    flight_cards = "".join(_flight_card(lr, *sigs[lr.leg.id], cur) for lr in live)
    ground_rows = "".join(
        f'<tr><td>by {g.by:%a %b %-d}</td><td><b>{esc(g.origin.name)} → {esc(g.destination.name)}</b></td>'
        f'<td>{esc(g.mode)}</td><td class="num">~{g.km:,.0f} km</td><td class="num">~{g.hours:.0f} hrs</td></tr>'
        for g in plan.ground)
    ground_html = (f'<h2>On the ground <span class="muted small">buses / trains inside each country, '
                   f'estimated, not price-tracked</span></h2><table class="ground">{ground_rows}</table>'
                   if plan.ground else "")
    stay_cards = "".join(_stay_card(x, cur) for x in stays)
    demo = '<div class="banner">Demo prices — add the SERPAPI_KEY secret to track real ones.</div>' if source == "demo" else ""
    headline = (f"<b>{len(buys)}</b> worth booking this week: " + ", ".join(
        esc(f"{x.leg.origin.name} → {x.leg.destination.name}" if isinstance(x, LegResult) else x.stop.place.name)
        for x in buys)) if buys else "Nothing to book this week — hold."
    first, last = plan.stops[0].check_in if plan.stops else today, plan.stops[-1].check_out if plan.stops else today
    return f"""<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{esc(s.name)} — {today}</title><style>{CSS}</style></head>
<body><div class="wrap"><header><h1>{esc(s.name)} · weekly report</h1>
<div class="sub">{today:%A %B %-d, %Y} · based on your Google Sheet · {first:%b %-d} – {last:%b %-d, %Y}</div>
<div class="totals"><div><span class="muted small">Flights in your sheet</span><b>{money(sheet_total, cur)}</b></div>
<div><span class="muted small">Same flights today</span><b>{money(now_total, cur)}</b></div>
<div><span class="muted small">Cheaper swaps found</span><b>{n_sugg}</b></div></div>
<p>{headline}</p>{demo}</header>
{checks_html}
<h2>Flights <span class="muted small">per person · option A unless marked</span></h2><div class="grid">{flight_cards}</div>
{ground_html}
{opt_html}
<h2>Stays <span class="muted small">per night for the room, 4★+ hotels</span></h2><div class="grid">{stay_cards}</div>
<footer>BUY / WATCH / WAIT are rules of thumb from price history and how far out you are — not guarantees.
Totals use today's price where we have one and your sheet's price otherwise. Edit the Google Sheet and next Sunday's report follows it.</footer>
</div></body></html>"""


def render_markdown(s: Settings, plan: Plan, legs, sigs, stays, today, source) -> str:
    out = [f"# {s.name} — weekly report {today}", ""]
    if source == "demo":
        out += ["> Demo prices — add the `SERPAPI_KEY` secret to track real ones.", ""]
    if getattr(plan, "recs", []):
        out += ["## Recommendations", *[f"- **{r.kind}** · {r.title} — {r.detail}" for r in plan.recs], ""]
    elif plan.checks:
        out += ["## Things to fix in the sheet", *[f"- {'⚠️' if c.level == 'fix' else 'ℹ️'} {c.text}" for c in plan.checks], ""]
    out += ["## Flights (per person)", "| | Flight | Date | Now | Sheet | Best swap |", "|---|---|---|---|---|---|"]
    for lr in legs:
        f = lr.leg.flight
        if f.date < today:
            continue
        sig = sigs[lr.leg.id][0]
        best = next((f"{x.text}: {money(x.price)}" for x in lr.suggestions if (x.saves or 0) > 0), "")
        out.append(f"| **{sig.verdict}** | {lr.leg.origin.name} → {lr.leg.destination.name}{' (B)' if f.option == 'B' else ''} "
                   f"| {f.date:%b %-d} | {money(lr.plan_price)} | {money(f.cost)} | {best} |")
    if plan.ground:
        out += ["", "## On the ground (estimated)", *[f"- by {g.by:%b %-d}: {g.origin.name} → {g.destination.name} · "
                                                      f"{g.mode} · ~{g.km:,.0f} km · ~{g.hours:.0f} hrs" for g in plan.ground]]
    out += ["", "## Stays (per night)", "| | Where | Dates | Now | Budget |", "|---|---|---|---|---|"]
    for x in stays:
        out.append(f"| **{x.signal.verdict}** | {x.stop.place.name} | {x.stop.check_in:%b %-d}–{x.stop.check_out:%b %-d} "
                   f"| {money(x.quote.price if x.quote else None)} | {money(x.budget)} |")
    return "\n".join(out) + "\n"


def plan_json(plan: Plan, legs: list[LegResult], sigs: dict, stays: list[StayResult], today: dt.date, source: str) -> dict:
    """Everything the globe needs: stops, legs, suggested alternatives."""
    stay_by = {(x.stop.place.name, x.stop.check_in): x for x in stays}
    return {
        "generated": today.isoformat(), "source": source,
        "stops": [{"name": st.place.name, "country": st.place.country, "lat": st.place.lat, "lon": st.place.lon,
                   "check_in": st.check_in.isoformat(), "check_out": st.check_out.isoformat(), "nights": st.nights,
                   "assumed": st.assumed,
                   "hotel_price": (q.price if (x := stay_by.get((st.place.name, st.check_in))) and (q := x.quote) else None)}
                  for st in plan.stops],
        "legs": [{"id": lr.leg.id, "from": lr.leg.origin.name, "to": lr.leg.destination.name,
                  "from_ll": [lr.leg.origin.lat, lr.leg.origin.lon], "to_ll": [lr.leg.destination.lat, lr.leg.destination.lon],
                  "date": lr.leg.flight.date.isoformat(), "option": lr.leg.flight.option, "booked": lr.leg.flight.booked,
                  "flight_no": lr.leg.flight.flight_no, "sheet_price": lr.leg.flight.cost, "price": lr.plan_price,
                  "detail": lr.plan_detail, "link": lr.plan_link, "verdict": sigs[lr.leg.id][0].verdict,
                  "reason": sigs[lr.leg.id][0].reason,
                  "suggestions": [{"text": x.text, "price": x.price, "saves": x.saves, "kind": x.kind} for x in lr.suggestions]}
                 for lr in legs],
        "ground": [{"from": g.origin.name, "to": g.destination.name, "from_ll": [g.origin.lat, g.origin.lon],
                    "to_ll": [g.destination.lat, g.destination.lon], "by": g.by.isoformat(), "mode": g.mode,
                    "km": round(g.km), "hours": round(g.hours, 1)} for g in plan.ground],
        "alternatives": _alternatives(legs),
        "checks": [{"level": c.level, "text": c.text} for c in plan.checks],
        "recommendations": [{"kind": r.kind, "title": r.title, "detail": r.detail, "places": r.places, "legs": r.legs}
                            for r in getattr(plan, "recs", [])],
    }


def _alternatives(legs: list[LegResult]) -> list[dict]:
    """Priced swaps, plus the fly-instead routes for overland legs even before they have a price."""
    out, seen = [], set()
    for lr in legs:
        for x in lr.suggestions:
            if x.route:
                seen.add((lr.leg.id, x.route))
                out.append({"leg": lr.leg.id, "route": x.route, "price": x.price, "saves": x.saves, "kind": x.kind,
                            "from_ll": _ll(x.route.split(" → ")[0]), "to_ll": _ll(x.route.split(" → ")[1])})
        for o in lr.leg.alt_origins:
            route = f"{o.name} → {lr.leg.destination.name}"
            if (lr.leg.id, route) not in seen:
                out.append({"leg": lr.leg.id, "route": route, "price": None, "saves": None, "kind": "calendar",
                            "from_ll": [o.lat, o.lon], "to_ll": [lr.leg.destination.lat, lr.leg.destination.lon]})
    return out


def _ll(name: str):
    from . import places as P
    p = P.lookup(name)
    return [p.lat, p.lon] if p else None


def write_report(s: Settings, plan: Plan, legs, stays, store: Store, source: str, today: dt.date,
                 out_dir: str | Path = "reports") -> Path:
    sigs = {lr.leg.id: leg_signal(lr, store, source, today) for lr in legs}
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    page = render_html(s, plan, legs, sigs, stays, today, source)
    (out / f"{today}.html").write_text(page)
    (out / "latest.html").write_text(page)
    (out / "latest.md").write_text(render_markdown(s, plan, legs, sigs, stays, today, source))
    (out / "plan.json").write_text(json.dumps(plan_json(plan, legs, sigs, stays, today, source), indent=1))
    return out / "latest.html"


def build_stays(plan: Plan, s: Settings, results: dict, store: Store, source: str, today: dt.date) -> list[StayResult]:
    from .recommend import hotel_stops, stay_id
    out = []
    for st in hotel_stops(plan, s):
        if st.check_out <= today:
            continue
        iid = stay_id(st)
        q = results.get((iid, st.check_in))
        series = _series(store, iid, source)
        budget = s.hotel_max_price.get(st.place.country.lower())
        sig = evaluate(series, (st.check_in - today).days, "stay", budget=budget)
        out.append(StayResult(st, q, sig, series, budget))
    return out
