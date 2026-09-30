# validate_routine.py -- checks and repairs clauderoutinedata.json before the routine commits it.
# Run from the repository root:   python3 validate_routine.py YYYY-MM-DD
#   (YYYY-MM-DD = today's date in Boise; set ACCEPT_JUMPS=1 to skip the "moved a lot since yesterday" checks)
# Prints "OK" and exits 0, or prints "PROBLEM: ..." lines and exits 1.
# What it does: recalculates change_pct and direction itself, checks every number is a real number,
# checks the ETF P/E source is iShares/BlackRock, checks prices look like the index (not an ETF or futures)
# by comparing with yesterday's committed file, and checks the structure the dashboard needs.
# The Claude Routine runs this file; it must never be replaced or shortened by the routine.
import json, os, re, subprocess, sys
TODAY = sys.argv[1]
F = "clauderoutinedata.json"
ACCEPT = os.environ.get("ACCEPT_JUMPS") == "1"
bad, notes = [], []
def num(v): return isinstance(v, (int, float)) and not isinstance(v, bool)
try:
    d = json.load(open(F, encoding="utf-8"))
except Exception as e:
    print("PROBLEM: file is not valid JSON:", e); sys.exit(1)
try:
    prior = json.loads(subprocess.run(["git", "show", "HEAD:" + F], capture_output=True, text=True).stdout)
except Exception:
    prior = {}
for k in ["date","time_collected_utc","futures","etf_pe","rates_commodities","macro_events",
          "sector_movers","global_markets","open_focus","market_prices","data_notes"]:
    if k not in d: bad.append(f"missing key: {k}")
for k in ["futures","etf_pe","rates_commodities","sector_movers","global_markets","market_prices"]:
    if not isinstance(d[k], dict): bad.append(f"{k} must be an object (use null values INSIDE it, never null for the whole section)")
if not isinstance(d["macro_events"], list): bad.append("macro_events must be a list (use [] when empty)")
if bad: print("\n".join("PROBLEM: " + b for b in bad)); sys.exit(1)
if d["date"] != TODAY: bad.append(f"date is {d['date']}, must be {TODAY}")
if not re.fullmatch(r"\d\d:\d\d", str(d["time_collected_utc"])): bad.append("time_collected_utc must be HH:MM")
def direction(x): return "flat" if abs(x) < 0.05 else ("up" if x > 0 else "down")
for k in ["sp500","nasdaq100","dow"]:
    f = d["futures"].get(k) or {}
    if f.get("change_pct") is None: f["direction"] = None
    elif num(f["change_pct"]): f["direction"] = direction(f["change_pct"])
    else: bad.append(f"futures.{k}.change_pct must be a number or null")
    d["futures"][k] = f
if d["futures"].get("sentiment") not in ("bullish","neutral","bearish"): bad.append("futures.sentiment must be bullish, neutral or bearish")
pe_prior = prior.get("etf_pe", {})
for t in ["URTH","EFA"]:
    e = d["etf_pe"].get(t) or {}
    v = e.get("pe_ttm")
    if v is not None:
        if not num(v) or not 5 <= v <= 60: bad.append(f"{t} pe_ttm must be a number between 5 and 60 or null")
        elif not re.search(r"ishares|blackrock", str(e.get("source","")), re.I): bad.append(f"{t} source must be ishares.com (or blackrock.com), not '{e.get('source')}'")
        elif not re.fullmatch(r"\d{4}-\d\d-\d\d", str(e.get("as_of",""))): bad.append(f"{t} needs as_of date YYYY-MM-DD")
        else:
            p = (pe_prior.get(t) or {}).get("pe_ttm")
            if num(p) and abs(v/p - 1) > 0.12 and "ishares" in str((pe_prior.get(t) or {}).get("source","")).lower() and not ACCEPT:
                bad.append(f"CHECK {t} P/E {v} moved more than 12% from yesterday's {p}; re-check the value")
rc = d["rates_commodities"]
y, o = rc.get("treasury_10yr_pct"), rc.get("crude_oil_usd")
if y is not None:
    if not num(y) or not 0 < y < 15: bad.append("treasury_10yr_pct must be a percent number such as 5.24")
    else:
        py = (prior.get("rates_commodities") or {}).get("treasury_10yr_pct")
        if num(py) and abs(y - py) > 0.5 and not ACCEPT: bad.append(f"CHECK 10Y {y} differs from yesterday's {py} by more than 0.5; cross-check a second source")
if o is not None and (not num(o) or not 5 < o < 400): bad.append("crude_oil_usd must be a number in dollars per barrel")
if rc.get("crude_oil_type") not in ("WTI","Brent"): bad.append("crude_oil_type must be WTI or Brent")
if not isinstance(d["macro_events"], list) or len(d["macro_events"]) > 3: bad.append("macro_events must be a list of at most 3 strings")
for grp in ["leading","lagging"]:
    if not isinstance(d["sector_movers"].get(grp), list): bad.append(f"sector_movers.{grp} must be a list")
for g in ["europe","asia"]:
    if not isinstance(d["global_markets"].get(g), dict): bad.append(f"global_markets.{g} must be an object")
if not isinstance(d["data_notes"], list): bad.append("data_notes must be a list")
mp = d["market_prices"]
if mp != {}:
    pmp = prior.get("market_prices") or {}
    for k in ["sp500","rut","vix"]:
        m = mp.get(k) or {}
        if not (num(m.get("prev_close")) and num(m.get("current")) and m["prev_close"] > 0 and m["current"] > 0):
            bad.append(f"market_prices.{k} needs numeric prev_close and current (or set market_prices to {{}})"); continue
        m["change_pct"] = round((m["current"] - m["prev_close"]) / m["prev_close"] * 100, 2)
        if k != "vix":
            m["source_time_et"] = m.get("source_time_et", "")
            if not re.fullmatch(r"\d\d:\d\d", str(m["source_time_et"])): bad.append(f"market_prices.{k}.source_time_et must be HH:MM")
        pc = (pmp.get(k) or {}).get("current")
        if num(pc) and not ACCEPT and abs(m["prev_close"]/pc - 1) > (0.6 if k == "vix" else 0.06):
            bad.append(f"CHECK {k} prev_close {m['prev_close']} is far from yesterday's level {pc}: is this the index itself (not SPY, ETF or futures)?")
        mp[k] = m
if bad: print("\n".join("PROBLEM: " + b for b in bad)); sys.exit(1)
json.dump(d, open(F, "w", encoding="utf-8"), indent=2, ensure_ascii=False)
filled = {"futures": sum(num((d["futures"].get(k) or {}).get("change_pct")) for k in ["sp500","nasdaq100","dow"]),
          "pe": sum(num((d["etf_pe"].get(t) or {}).get("pe_ttm")) for t in ["URTH","EFA"]),
          "10y": int(num(y)), "oil": int(num(o)), "prices": 0 if d["market_prices"] == {} else 3,
          "events": len(d["macro_events"]), "sectors": len(d["sector_movers"].get("leading") or []) + len(d["sector_movers"].get("lagging") or [])}
print("OK: file valid. Filled values:", filled, "(futures of 3, pe of 2, 10y of 1, oil of 1, prices 0 or 3, events up to 3, sectors up to 4)")
