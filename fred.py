# ============================================================
# fred.py -- FRED macro indicator fetching
# Mean Reversion Macro Insights
# ============================================================
#
# PUBLIC FUNCTION (called by main.py):
#   fetch_fred_data() -> list[dict]
#
# WHAT THIS DOES:
#   Fetches all 15 macro series in parallel (20s timeout each).
#   Routes to the correct source per series id:
#     _YAHOO_GCF     -> Yahoo Finance GC=F (gold futures)
#     _SCRAPE_MULTPL -> multpl.com (Shiller CAPE)
#     anything else  -> standard FRED API (limit=500, sort desc)
#   Returns a list of enriched dicts with keys:
#     label, id, group, current, mo3, mo12, trend, date, sig, insight
#
# GOLD FIX (Sep 2026):
#   GOLDAMGBD228NLBM discontinued by FRED in 2025 with no replacement.
#   Now uses Yahoo Finance GC=F (Comex front-month futures).
#   Tracks spot gold closely (~$5-10 spread) and updates daily.
#
# CAPE FIX (Sep 2026):
#   SHILLER_CAPE was never a valid FRED series ID.
#   FRED does not host Shiller CAPE. Now scraped from multpl.com
#   which pulls directly from Shiller's Yale dataset, updates daily.
#
# COLOR LOGIC for trend arrows (what direction is GOOD for equities):
#   INFLATION:     UP=red(bad)        DOWN=green(good)
#   RATES:         UP=red(bad)        DOWN=green -- EXCEPT Yield Curve
#   Yield Curve:   UP=green(steepen)  DOWN=red(flatten/invert)
#   CREDIT:        UP=red(widen=bad)  DOWN=green(tighten=good)
#   LABOR:         UP=red(unemp bad)  DOWN=green(tight labor)
#   WTI:           UP=red(inflation)  DOWN=green
#   GOLD:          UP=amber(ambiguous -- fear OR inflation signal)
#   DXY:           UP=amber(helps US stocks, hurts intl ADRs)
#   CONSUMER SENT: UP=green(confident) DOWN=red
#   VALUATION/CAPE:UP=red(pricier)   DOWN=green(cheaper)
# ============================================================

import os
import re
import concurrent.futures
from datetime import datetime, timedelta, date
import requests
from bs4 import BeautifulSoup

FRED_API_KEY = os.environ.get("FRED_API_KEY")

# ============================================================
# SERIES DEFINITIONS
# ============================================================

FRED_SERIES = [
    # ---- INFLATION ----
    {"label": "CPI Inflation",        "id": "CPIAUCSL",      "is_index": True,  "group": "INFLATION",
     "insight": "Headline CPI incl food & energy · hist avg ~3%"},
    {"label": "Core CPI",             "id": "CPILFESL",      "is_index": True,  "group": "INFLATION",
     "insight": "CPI ex food/energy · Fed watches this · avg ~2.5%"},
    {"label": "PCE Inflation",        "id": "PCEPI",         "is_index": True,  "group": "INFLATION",
     "insight": "Fed preferred gauge (broader than CPI) · avg ~2.2%"},
    {"label": "Core PCE",             "id": "PCEPILFE",      "is_index": True,  "group": "INFLATION",
     "insight": "THE key number · Fed 2% target · >3% = rates stay high"},
    # ---- RATES ----
    {"label": "10Y Treasury",         "id": "GS10",          "is_index": False, "group": "RATES",
     "insight": "Risk-free rate · rising compresses P/E multiples · avg ~4%"},
    {"label": "2Y Treasury",          "id": "GS2",           "is_index": False, "group": "RATES",
     "insight": "Fed expectations proxy · rising = no rate cuts priced in"},
    {"label": "Yield Curve (10Y-2Y)", "id": "T10Y2Y",        "is_index": False, "group": "RATES",
     "insight": "Negative = inverted = recession signal 12-18mo ahead"},
    {"label": "Fed Funds Rate",       "id": "FEDFUNDS",      "is_index": False, "group": "RATES",
     "insight": "Cost of borrowing · cutting = tailwind for equities"},
    # ---- CREDIT ----
    {"label": "HY Credit Spread",     "id": "BAMLH0A0HYM2", "is_index": False, "group": "CREDIT",
     "insight": "Junk bond premium · <3%=calm · >6%=credit fear/stress"},
    # ---- LABOR ----
    {"label": "Unemployment",         "id": "UNRATE",        "is_index": False, "group": "LABOR",
     "insight": "Labor health · rising = consumer risk · hist avg ~5.7%"},
    # ---- COMMODITIES ----
    {"label": "WTI Crude Oil",        "id": "DCOILWTICO",    "is_index": False, "group": "COMMODITIES",
     "prefix": "$", "insight": "Energy price · >$85 = inflation pressure & input cost risk"},
    # Gold: _YAHOO_GCF routes to Yahoo Finance GC=F (FRED discontinued GOLDAMGBD228NLBM in 2025)
    {"label": "Gold Price",           "id": "_YAHOO_GCF",    "is_index": False, "group": "COMMODITIES",
     "prefix": "$", "no_pct": True,
     "insight": "Fear/inflation hedge · rising+lowVIX = stealth fear signal"},
    # ---- CURRENCY ----
    {"label": "US Dollar (DXY)",      "id": "DTWEXBGS",      "is_index": False, "group": "CURRENCY",
     "no_pct": True,
     "insight": "Dollar strength · weak dollar = tailwind for intl ADRs (EQNR,PBR,SNY etc)"},
    # ---- CONSUMER SENTIMENT ----
    {"label": "Consumer Sentiment",   "id": "UMCSENT",       "is_index": False, "group": "SENTIMENT_FRED",
     "no_pct": True, "insight": "U of Michigan 0-100 · avg ~75 · <60 = consumer stress"},
    # CAPE: _SCRAPE_MULTPL routes to multpl.com (FRED never hosted Shiller CAPE)
    {"label": "Shiller CAPE (US)",    "id": "_SCRAPE_MULTPL","is_index": False, "group": "VALUATION",
     "no_pct": True,
     "insight": "Cyclically Adj PE · 10yr smoothed · hist avg 17x · ~41 = 2nd highest ever"},
]

GROUP_META = {
    "INFLATION":      {"icon": "🔥", "color": "#c81e1e", "label": "Inflation"},
    "RATES":          {"icon": "📊", "color": "#1a56db", "label": "Interest Rates"},
    "CREDIT":         {"icon": "💳", "color": "#7f1d1d", "label": "Credit"},
    "LABOR":          {"icon": "👷", "color": "#b45309", "label": "Labor"},
    "COMMODITIES":    {"icon": "🛢️", "color": "#d97706", "label": "Commodities"},
    "CURRENCY":       {"icon": "💵", "color": "#6366f1", "label": "Currency"},
    "SENTIMENT_FRED": {"icon": "🎭", "color": "#059669", "label": "Consumer Sentiment"},
    "VALUATION":      {"icon": "📐", "color": "#7c3aed", "label": "Valuation"},
}


# ============================================================
# TREND COLOR
# ============================================================

def trend_color(label, group, trend):
    """
    Return hex color for a trend arrow based on what direction is GOOD for equity investors.
    Green = good. Red = bad. Amber = ambiguous/context-dependent.
    """
    if group == "INFLATION":
        return "#057a55" if trend == "▼" else "#c81e1e" if trend == "▲" else "#6b7280"
    elif group == "RATES":
        if "Yield Curve" in label:
            return "#057a55" if trend == "▲" else "#c81e1e" if trend == "▼" else "#6b7280"
        return "#c81e1e" if trend == "▲" else "#057a55" if trend == "▼" else "#6b7280"
    elif group in ("CREDIT", "LABOR"):
        return "#c81e1e" if trend == "▲" else "#057a55" if trend == "▼" else "#6b7280"
    elif group == "COMMODITIES":
        if "Gold" in label:
            return "#b45309" if trend == "▲" else "#6b7280"
        return "#c81e1e" if trend == "▲" else "#057a55" if trend == "▼" else "#6b7280"
    elif group == "CURRENCY":
        return "#b45309" if trend == "▲" else "#059669" if trend == "▼" else "#6b7280"
    elif group == "SENTIMENT_FRED":
        return "#057a55" if trend == "▲" else "#c81e1e" if trend == "▼" else "#6b7280"
    elif group == "VALUATION":
        return "#c81e1e" if trend == "▲" else "#057a55" if trend == "▼" else "#6b7280"
    return "#6b7280"


# ============================================================
# SPARKLINE SVG
# ============================================================

def sparkline_svg(cur_str, mo3_str, mo12_str):
    """Return a tiny 3-point SVG sparkline (12mo ago -> 3mo ago -> today)."""
    try:
        def parse(s):
            return float(re.sub(r"[^0-9.\-]", "", str(s)))
        v12 = parse(mo12_str)
        v3  = parse(mo3_str)
        v0  = parse(cur_str)
        mn  = min(v12, v3, v0)
        mx  = max(v12, v3, v0)
        r   = mx - mn if mx != mn else 1

        def y(v, h=24):
            return round(h - (v - mn) / r * (h - 4) + 2, 1)

        pts      = f"0,{y(v12)} 20,{y(v3)} 40,{y(v0)}"
        line_col = "#c81e1e" if v0 > v12 else "#057a55"
        return (
            f'<svg width="42" height="28" viewBox="0 0 42 28" '
            f'style="display:inline-block;vertical-align:middle;">'
            f'<polyline points="{pts}" fill="none" stroke="{line_col}" '
            f'stroke-width="1.8" stroke-linejoin="round"/>'
            f'<circle cx="40" cy="{y(v0)}" r="2.5" fill="{line_col}"/>'
            f'</svg>'
        )
    except Exception:
        return ""


# ============================================================
# INSIGHT GENERATOR
# ============================================================

def _insight(label, cur_str, mo3_str, mo12_str, trend):
    """
    Generate contextual insight text for each indicator.
    Compares current value to historical norms, not just recent direction.
    """
    try:
        cur  = float(re.sub(r"[%$,]", "", str(cur_str)))
        mo3  = float(re.sub(r"[%$,]", "", str(mo3_str)))
        mo12 = float(re.sub(r"[%$,]", "", str(mo12_str)))
    except Exception:
        return ""

    dir3  = "↑" if cur > mo3  + 0.05 else "↓" if cur < mo3  - 0.05 else "→"
    dir12 = "↑" if cur > mo12 + 0.05 else "↓" if cur < mo12 - 0.05 else "→"

    if label == "Core PCE":
        pct = round((cur / 2.0 - 1) * 100)
        if cur <= 2.0:
            return f"✅ AT Fed 2% target · {dir3}3mo {dir12}12mo"
        elif cur > 3.0 and dir3 == "↑" and dir12 == "↑":
            return f"⚠️ SUSTAINED RISE · {pct}% above 2% target · rates stay elevated"
        elif cur > 3.0:
            return f"⚠️ {pct}% above 2% target · {dir3}3mo {dir12}12mo"
        return f"→ Elevated but {dir3}3mo · {dir12}12mo · watch direction"

    elif label in ("CPI Inflation", "PCE Inflation", "Core CPI"):
        mood = ("⚠️ Heating" if dir3 == "↑" and dir12 == "↑"
                else "📉 Cooling" if dir3 == "↓" else "→ Mixed")
        return f"{mood} · {dir3}3mo {dir12}12mo"

    elif label == "Fed Funds Rate":
        if cur >= 5.0:   return f"⚠️ Restrictive (avg ~2.5%) · {dir3}3mo · growth headwind"
        elif cur <= 3.0: return f"✅ Accommodative · {dir3}3mo"
        elif dir3 == "↓": return "📉 Cutting cycle · positive for rate-sensitive equities"
        elif dir3 == "↑": return "⚠️ Rising rates · tightening · headwind for P/E multiples"
        return f"→ On hold at {cur:.2f}% · {dir12}12mo"

    elif label == "10Y Treasury":
        if cur >= 5.0 and dir3 == "↑":
            return f"⚠️ High & rising at {cur:.2f}% · P/E compression intensifying"
        elif cur >= 5.0:
            return f"⚠️ Elevated at {cur:.2f}% (avg ~4%) · P/E compression risk"
        elif cur <= 3.5:
            return f"✅ Low at {cur:.2f}% · supports higher valuations · {dir3}3mo"
        return f"{dir3}3mo {dir12}12mo · rising = headwind, falling = tailwind for all equities"

    elif label == "2Y Treasury":
        if cur >= 4.5 and dir3 == "↑":
            return "⚠️ High & rising · market pricing in NO rate cuts"
        elif dir3 == "↓":
            return f"✅ Falling · rate cuts being priced in · {dir12}12mo"
        return f"→ {cur:.2f}% · {dir3}3mo · Fed expectations proxy"

    elif label == "Yield Curve (10Y-2Y)":
        if cur < -0.5:  return f"⚠️ DEEPLY INVERTED {cur:.2f}% · strong recession signal (12-18mo lead)"
        elif cur < 0:   return f"⚠️ Inverted {cur:.2f}% · historically predicts recession"
        elif cur < 0.3: return f"→ Nearly flat {cur:.2f}% · {dir3}3mo · watch for re-inversion"
        return f"✅ Positive {cur:.2f}% · steepening = growth expectations improving"

    elif label == "HY Credit Spread":
        if cur <= 2.5:  return f"⚠️ Historically tight {cur:.2f}% · credit fully complacent · no fear priced in"
        elif cur <= 3.5: return f"→ Tight {cur:.2f}% (normal ~4-5%) · {dir3}3mo"
        elif cur >= 6.0: return f"⚠️ WIDE {cur:.2f}% · credit stress · fear of defaults rising"
        return f"→ {cur:.2f}% · {dir3}3mo {dir12}12mo"

    elif label == "Unemployment":
        if cur >= 5.0:   return f"⚠️ Elevated {cur:.1f}% (hist avg ~5.7%) · {dir3}3mo"
        elif cur <= 4.0: return f"✅ Tight labor market {cur:.1f}% · {dir3}3mo"
        return f"→ {cur:.1f}% · {dir3}3mo {dir12}12mo"

    elif label == "WTI Crude Oil":
        if cur >= 90 and dir3 == "↑":
            return f"⚠️ HIGH & RISING ${cur:.0f} · inflation pressure + recession risk"
        elif cur >= 90:
            return f"⚠️ Elevated ${cur:.0f} (avg ~$65) · inflationary · {dir3}3mo"
        elif cur <= 60:
            return f"✅ Low ${cur:.0f} · consumer-friendly · {dir3}3mo"
        return f"${cur:.0f} · {dir3}3mo {dir12}12mo · >$85 = inflation concern"

    elif label == "Gold Price":
        pct12 = round((cur / mo12 - 1) * 100) if mo12 else 0
        flag  = "⚠️ Stealth fear signal (VIX low, gold surging)" if pct12 > 20 else "→"
        return f"{flag} ${cur:,.0f} · {pct12:+d}% vs 12mo · {dir3}3mo"

    elif label == "US Dollar (DXY)":
        pct12 = round((cur / mo12 - 1) * 100) if mo12 else 0
        intl  = "tailwind for intl ADRs" if dir3 == "↓" else "headwind for intl ADRs"
        return f"DXY {cur:.1f} · {pct12:+d}% vs 12mo · {dir3}3mo · {intl}"

    elif label == "Consumer Sentiment":
        note = "well below avg ~75" if cur < 65 else "below avg" if cur < 72 else "near avg ~75"
        return f"{cur:.1f}/100 ({note}) · {dir3}3mo {dir12}12mo"

    elif label == "Shiller CAPE (US)":
        pct = round((cur / 17.0 - 1) * 100)
        if cur >= 40:
            return (f"⚠️ EXTREME {cur:.1f}x · {pct}% above hist avg 17x · "
                    f"98th pctile since 1881 · only exceeded at dot-com peak 44.2x")
        elif cur >= 30:
            return f"⚠️ Elevated {cur:.1f}x · {pct}% above hist avg 17x · {dir3}3mo"
        elif cur >= 20:
            return f"→ Moderate {cur:.1f}x · {pct}% above hist avg · {dir3}3mo"
        return f"✅ Reasonable {cur:.1f}x vs hist avg 17x · {dir3}3mo"

    return f"{dir3}3mo {dir12}12mo"


# ============================================================
# INDIVIDUAL SERIES FETCH
# ============================================================

def _fetch_one_fred(cfg, start_date, end_date):
    """
    Fetch a single series. Routes based on id:
      _YAHOO_GCF     -> Yahoo Finance GC=F
      _SCRAPE_MULTPL -> multpl.com Shiller CAPE
      anything else  -> FRED API
    """
    label    = cfg["label"]
    sid      = cfg["id"]
    is_index = cfg["is_index"]
    no_pct   = cfg.get("no_pct", False)
    prefix   = cfg.get("prefix", "")
    empty    = {**cfg, "current": "N/A", "mo3": "N/A", "mo12": "N/A",
                "trend": "?", "date": "N/A", "sig": ""}

    # ----------------------------------------------------------
    # GOLD: Yahoo Finance GC=F
    # GOLDAMGBD228NLBM discontinued by FRED in 2025.
    # GC=F tracks spot gold closely, updates daily.
    # range=400d gives ~280 trading days (enough for mo12_idx=260).
    # ----------------------------------------------------------
    if sid == "_YAHOO_GCF":
        try:
            hdrs = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept": "application/json",
            }
            url  = "https://query1.finance.yahoo.com/v8/finance/chart/GC=F?interval=1d&range=400d"
            resp = requests.get(url, headers=hdrs, timeout=12)
            data = resp.json()
            timestamps = data["chart"]["result"][0]["timestamp"]
            closes     = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]

            pairs = [(t, c) for t, c in zip(timestamps, closes) if c is not None]
            if len(pairs) < 10:
                return {**empty, "sig": "Gold: insufficient data from Yahoo GC=F"}

            v0  = pairs[-1][1]
            v3  = pairs[max(0, len(pairs) - 65)][1]
            v12 = pairs[max(0, len(pairs) - 260)][1]
            pub = datetime.fromtimestamp(pairs[-1][0]).strftime("%b %d %Y")

            dc    = f"${v0:,.0f}"
            dm3   = f"${v3:,.0f}"
            dm12  = f"${v12:,.0f}"
            trend = "▲" if v0 > v3 * 1.001 else "▼" if v0 < v3 * 0.999 else "→"
            sig   = _insight(label, dc, dm3, dm12, trend)
            return {**cfg, "current": dc, "mo3": dm3, "mo12": dm12,
                    "trend": trend, "date": pub, "sig": sig}
        except Exception as e:
            return {**empty, "sig": f"Gold Yahoo fetch failed: {str(e)[:50]}"}

    # ----------------------------------------------------------
    # SHILLER CAPE: multpl.com
    # FRED never hosted Shiller CAPE. SHILLER_CAPE was always invalid.
    # multpl.com pulls from Shiller's Yale dataset, updates daily.
    # #current div = today's value. datatable = historical monthly values.
    # ----------------------------------------------------------
    if sid == "_SCRAPE_MULTPL":
        try:
            hdrs = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
            resp = requests.get("https://www.multpl.com/shiller-pe",
                                headers=hdrs, timeout=15)
            soup = BeautifulSoup(resp.text, "html.parser")

            div = soup.find("div", {"id": "current"})
            if not div:
                return {**empty, "sig": "CAPE: multpl.com #current div not found"}
            match = re.search(r"(\d+\.\d+)", div.get_text())
            if not match:
                return {**empty, "sig": "CAPE: could not parse number from multpl.com"}
            v0 = float(match.group(1))

            v3  = v0
            v12 = v0
            table = soup.find("table", {"id": "datatable"})
            if table:
                rows = table.find_all("tr")

                def _row_val(row):
                    cells = row.find_all("td")
                    if len(cells) >= 2:
                        try:
                            return float(cells[1].get_text(strip=True))
                        except Exception:
                            pass
                    return None

                if len(rows) > 3:
                    v = _row_val(rows[3])
                    if v:
                        v3 = v
                if len(rows) > 12:
                    v = _row_val(rows[12])
                    if v:
                        v12 = v

            pub   = datetime.now().strftime("%b %d %Y")
            dc    = f"{v0:.1f}"
            dm3   = f"{v3:.1f}"
            dm12  = f"{v12:.1f}"
            trend = "▲" if v0 > v3 + 0.2 else "▼" if v0 < v3 - 0.2 else "→"
            sig   = _insight(label, dc, dm3, dm12, trend)
            return {**cfg, "current": dc, "mo3": dm3, "mo12": dm12,
                    "trend": trend, "date": pub, "sig": sig}
        except Exception as e:
            return {**empty, "sig": f"CAPE multpl.com failed: {str(e)[:50]}"}

    # ----------------------------------------------------------
    # STANDARD FRED API (all other 13 series)
    # limit=500 handles both daily (WTI, DXY) and monthly series.
    # Auto-detects daily vs monthly by date gap between obs[0..1].
    # ----------------------------------------------------------
    try:
        url  = (
            f"https://api.stlouisfed.org/fred/series/observations"
            f"?series_id={sid}&api_key={FRED_API_KEY}&file_type=json"
            f"&observation_start={start_date}&observation_end={end_date}"
            f"&sort_order=desc&limit=500"
        )
        resp = requests.get(url, timeout=20)
        obs  = [o for o in resp.json().get("observations", []) if o["value"] != "."]
        if not obs:
            return empty

        is_daily = False
        if len(obs) >= 2:
            try:
                d0 = datetime.strptime(obs[0]["date"], "%Y-%m-%d")
                d1 = datetime.strptime(obs[1]["date"], "%Y-%m-%d")
                is_daily = abs((d0 - d1).days) <= 7
            except Exception:
                is_daily = False

        if is_daily:
            mo3_idx  = min(65,  len(obs) - 1)
            mo12_idx = min(260, len(obs) - 1)
        else:
            mo3_idx  = min(3,  len(obs) - 1)
            mo12_idx = min(12, len(obs) - 1)

        v0  = float(obs[0]["value"])
        v3  = float(obs[mo3_idx]["value"])
        v12 = float(obs[mo12_idx]["value"])

        if is_index and v12:
            cur    = (v0 - v12) / v12 * 100
            v15_idx = min(mo12_idx + mo3_idx, len(obs) - 1)
            v15    = float(obs[v15_idx]["value"])
            mo3v   = (v3 - v15) / v15 * 100 if v15 else cur
            dc     = f"{cur:.1f}%"
            dm3    = f"{mo3v:.1f}%"
            dm12   = f"{mo3v:.1f}%"
            trend  = "▼" if cur < mo3v - 0.05 else "▲" if cur > mo3v + 0.05 else "→"
        elif no_pct:
            def fmt(v):
                return (f"{prefix}{v:,.0f}" if v > 999
                        else f"{prefix}{v:.2f}" if prefix
                        else f"{v:.1f}")
            dc    = fmt(v0)
            dm3   = fmt(v3)
            dm12  = fmt(v12)
            trend = "▲" if v0 > v3 + 0.05 else "▼" if v0 < v3 - 0.05 else "→"
        elif prefix:
            dc    = f"{prefix}{v0:.1f}"
            dm3   = f"{prefix}{v3:.1f}"
            dm12  = f"{prefix}{v12:.1f}"
            trend = "▲" if v0 > v3 + 0.05 else "▼" if v0 < v3 - 0.05 else "→"
        else:
            dc    = f"{v0:.2f}%"
            dm3   = f"{v3:.2f}%"
            dm12  = f"{v12:.2f}%"
            trend = "▲" if v0 > v3 + 0.05 else "▼" if v0 < v3 - 0.05 else "→"

        pub = datetime.strptime(obs[0]["date"], "%Y-%m-%d").strftime("%b %d %Y")
        sig = _insight(label, dc, dm3, dm12, trend)
        return {**cfg, "current": dc, "mo3": dm3, "mo12": dm12,
                "trend": trend, "date": pub, "sig": sig}

    except Exception as e:
        return {**empty, "sig": str(e)[:50]}


# ============================================================
# PUBLIC ENTRY POINT
# ============================================================

def fetch_fred_data():
    """
    Fetch all 15 FRED series in parallel (20s timeout per call).
    Gold routes to Yahoo GC=F, CAPE routes to multpl.com.
    Returns list of enriched dicts in FRED_SERIES definition order.
    """
    print("\n🏦 Fetching FRED macro indicators (parallel, 20s timeout)...")
    end   = date.today().strftime("%Y-%m-%d")
    start = (date.today() - timedelta(days=460)).strftime("%Y-%m-%d")
    rmap  = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as ex:
        futs = {ex.submit(_fetch_one_fred, cfg, start, end): cfg for cfg in FRED_SERIES}
        for f in concurrent.futures.as_completed(futs):
            r    = f.result()
            rmap[r["label"]] = r
            icon = "✅" if r["current"] != "N/A" else "❌"
            print(f"   {icon} {r['label']}: {r['current']} {r['trend']}")

    results = [
        rmap.get(c["label"], {**c, "current": "N/A", "mo3": "N/A", "mo12": "N/A",
                              "trend": "?", "date": "N/A", "sig": ""})
        for c in FRED_SERIES
    ]
    ok = sum(1 for r in results if r["current"] != "N/A")
    status = "✅" if ok == len(results) else "⚠️"
    print(f"   {status} FRED complete: {ok}/{len(results)} indicators fetched")
    return results
