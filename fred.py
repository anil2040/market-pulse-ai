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
# INSIGHT PHILOSOPHY (Sep 2026 rewrite):
#   The 'sig' field shown in the Insights column must be INTERPRETIVE,
#   not descriptive. The table already shows current/3mo/12mo values
#   and trend arrows. The insight column should answer "what does this
#   mean for a value investor?" -- not restate what the numbers show.
#   WRONG: "↑3mo ↑12mo" (that's what the trend arrow already says)
#   RIGHT: "Disinflation stalled -- Fed has no room to cut soon"
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
    # Gold: _YAHOO_GCF routes to Yahoo Finance GC=F
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
    # CAPE: _SCRAPE_MULTPL routes to multpl.com
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
# INSIGHT GENERATOR -- INTERPRETIVE, NOT DESCRIPTIVE
# ============================================================

def _insight(label, cur_str, mo3_str, mo12_str, trend):
    """
    Generate interpretive macro insight for each indicator.
    Answers "what does this mean?" not "what is the number?".
    The table already shows current/3mo/12mo and trend arrows.
    Do NOT restate those -- interpret the macro implication.
    """
    try:
        cur  = float(re.sub(r"[%$,]", "", str(cur_str)))
        mo3  = float(re.sub(r"[%$,]", "", str(mo3_str)))
        mo12 = float(re.sub(r"[%$,]", "", str(mo12_str)))
    except Exception:
        return ""

    # Direction helpers -- used only to inform interpretation, not to display
    rising3  = cur > mo3  + 0.05
    falling3 = cur < mo3  - 0.05
    rising12 = cur > mo12 + 0.05

    # ----------------------------------------------------------
    # INFLATION GROUP
    # ----------------------------------------------------------

    if label == "Core PCE":
        # THE key number for the Fed
        above_pct = round((cur / 2.0 - 1) * 100)
        if cur <= 2.0:
            return "✅ Fed target achieved -- door open for cuts, tailwind for rate-sensitive equities"
        elif cur > 3.0 and rising3:
            return f"⚠️ Re-accelerating at {above_pct}% above Fed target -- hike risk rising, PE compression ahead"
        elif cur > 3.0 and falling3:
            return f"→ Still {above_pct}% above target but cooling -- Fed will want more evidence before cutting"
        elif cur > 3.0:
            return f"⚠️ Stuck {above_pct}% above target with no momentum -- rates stay higher for longer"
        elif rising3:
            return "⚠️ Ticking back up toward 3% -- watch next print, cuts may be off the table"
        return "→ Elevated but drifting toward target -- cuts possible in 2-3 meetings if trend holds"

    elif label == "CPI Inflation":
        if cur > 4.0 and rising3:
            return "⚠️ Broad inflation re-igniting -- input costs rising across sectors, margin compression risk"
        elif cur > 3.5 and rising3:
            return "⚠️ Above historical avg and accelerating -- pushes Fed toward holding or hiking"
        elif cur > 3.0 and falling3:
            return "→ Above avg but decelerating -- progress toward 2% but not there yet"
        elif cur <= 2.5 and falling3:
            return "✅ Returning to normal range -- removes a key macro headwind for equities"
        elif falling3 and not rising12:
            return "→ Disinflation trend intact -- confirms Fed has room to hold or cut"
        return "→ Tracking near historical avg -- not a swing factor today"

    elif label == "Core CPI":
        if cur > 3.5 and rising3:
            return "⚠️ Shelter and services inflation sticky -- Fed cannot declare victory, rates stay restrictive"
        elif cur > 3.0 and falling3:
            return "→ Slowly cooling but still above comfort zone -- Fed patience required"
        elif cur <= 2.5:
            return "✅ Approaching target -- supports case for eventual cuts"
        elif rising3:
            return "⚠️ Re-heating -- service sector inflation erodes real returns and PE expansion"
        return "→ Moderate -- not forcing Fed's hand in either direction"

    elif label == "PCE Inflation":
        if cur > 3.5:
            return "⚠️ Fed's own preferred gauge well above target -- gap between Wall St optimism and reality"
        elif cur > 3.0 and rising3:
            return "⚠️ Fed preferred measure re-accelerating -- cuts pushed further out, duration risk rises"
        elif falling3:
            return "→ PCE cooling -- early signal Fed may eventually get the all-clear"
        return "→ Elevated but not accelerating -- watch next month's print for direction"

    # ----------------------------------------------------------
    # RATES GROUP
    # ----------------------------------------------------------

    elif label == "10Y Treasury":
        if cur >= 5.0 and rising3:
            return "⚠️ Surging past 5% -- PE multiples compress mechanically, bond math now competes directly with equities"
        elif cur >= 5.0:
            return "⚠️ Above 5% -- discount rate headwind is severe, especially for long-duration growth names"
        elif cur >= 4.5 and rising3:
            return "⚠️ Approaching levels where bonds compete with equities on yield -- watch spread compression"
        elif cur >= 4.0 and rising3:
            return "→ Rising toward 4.5% -- gradual valuation headwind, especially painful at CAPE 40x+"
        elif cur <= 3.5 and falling3:
            return "✅ Falling yields reduce the discount rate -- supports PE expansion and mean reversion setups"
        elif falling3:
            return "→ Easing -- early tailwind for rate-sensitive sectors and international ADRs"
        return "→ Holding steady -- not adding incremental pressure on multiples today"

    elif label == "2Y Treasury":
        if cur >= 4.5 and rising3:
            return "⚠️ Market pricing in zero rate cuts -- tight monetary policy embedded for the foreseeable future"
        elif cur >= 4.0 and falling3:
            return "→ Starting to price in eventual cuts -- watch 10Y-2Y spread for curve re-steepening signal"
        elif falling3:
            return "✅ Falling 2Y = market expecting cuts -- historically a tailwind for value stocks 6-12mo out"
        elif rising3:
            return "⚠️ Higher 2Y locks in restrictive financial conditions -- reduces room for P/E expansion"
        return "→ Stable -- no new signal on Fed timing from short end of the curve"

    elif label == "Yield Curve (10Y-2Y)":
        if cur < -0.5:
            return "⚠️ Deep inversion -- historically the strongest single recession predictor; 12-18mo lead time"
        elif cur < 0.0:
            return "⚠️ Inverted -- recession signal intact; value investors: watch credit spreads for the turn"
        elif cur < 0.3:
            return "→ Nearly flat -- disinversion underway but not yet a steepening growth signal; watch direction"
        elif cur >= 0.5 and rising3:
            return "✅ Steepening curve -- growth expectations improving, historically positive for cyclicals and banks"
        return "✅ Positive slope -- no inversion signal; normal credit environment for long-term investors"

    elif label == "Fed Funds Rate":
        if cur >= 5.0 and rising3:
            return "⚠️ Fed actively tightening -- max pressure on leveraged companies and rate-sensitive sectors"
        elif cur >= 5.0:
            return "⚠️ Restrictive territory -- financial conditions tight, separates quality from fragile businesses"
        elif falling3:
            return "✅ Cutting cycle -- historically the single strongest tailwind for mean reversion value setups"
        elif cur <= 3.0:
            return "✅ Accommodative -- cheap capital supports business investment and consumer spending"
        return "→ On hold -- Fed is watching; next move direction matters more than current level"

    # ----------------------------------------------------------
    # CREDIT GROUP
    # ----------------------------------------------------------

    elif label == "HY Credit Spread":
        if cur <= 2.5:
            return "⚠️ Historically tight -- credit markets fully complacent; no risk premium for bad outcomes"
        elif cur <= 3.5 and falling3:
            return "→ Tight and tightening further -- credit calm signals no systemic fear, but leaves no buffer"
        elif cur <= 3.5:
            return "→ Tight spreads confirm equity calm is credit-supported -- watch for any widening as an early warning"
        elif cur >= 6.0 and rising3:
            return "⚠️ Wide and widening -- credit stress signal; historically precedes equity drawdowns by 2-4 weeks"
        elif cur >= 6.0:
            return "⚠️ Elevated stress -- forced sellers and credit fear creating value opportunities in quality names"
        elif cur >= 4.5:
            return "→ Widening toward historical average -- credit pricing in some risk; watch for acceleration"
        return "→ Near normal range -- credit not flashing a directional macro signal today"

    # ----------------------------------------------------------
    # LABOR GROUP
    # ----------------------------------------------------------

    elif label == "Unemployment":
        if cur >= 5.5:
            return "⚠️ Labor loosening materially -- consumer spending risk, but also reduces wage inflation pressure"
        elif cur >= 4.5 and rising3:
            return "→ Rising unemployment softens consumer balance sheets -- watch retail and discretionary sectors"
        elif cur <= 4.0 and falling3:
            return "→ Very tight labor keeps wage inflation sticky -- good for workers, complicates Fed pivot timing"
        elif cur <= 4.0:
            return "→ Tight labor market -- supports consumer spending but keeps services inflation elevated"
        elif rising3:
            return "→ Gradual cooling -- reduces wage pressure; Fed may gain more flexibility on cuts"
        return "→ Near historical norm -- labor not a swing factor for macro direction today"

    # ----------------------------------------------------------
    # COMMODITIES GROUP
    # ----------------------------------------------------------

    elif label == "WTI Crude Oil":
        if cur >= 100 and rising3:
            return "⚠️ Above $100 and rising -- stagflation risk: energy tax on consumers, input cost spike for industry"
        elif cur >= 90 and rising3:
            return "⚠️ Energy price surge -- feeds directly into CPI and PPI; gives Fed another reason to hold"
        elif cur >= 90:
            return "⚠️ Elevated energy costs compress margins across industrials, transport, chemicals -- watch pass-through"
        elif cur <= 60 and falling3:
            return "✅ Low energy costs -- consumer disposable income rises, input costs ease, disinflation support"
        elif falling3:
            return "✅ Easing energy prices -- removes one inflationary pressure; positive for Fed flexibility"
        return "→ Moderate energy pricing -- not a dominant swing factor for the macro picture today"

    elif label == "Gold Price":
        pct12 = round((cur / mo12 - 1) * 100) if mo12 else 0
        if pct12 > 25 and cur > 3000:
            return f"⚠️ Gold +{pct12}% in 12mo with low VIX -- classic stealth fear signal; smart money hedging"
        elif pct12 > 15 and rising3:
            return f"→ Gold surging +{pct12}% yr -- real rates concern or dollar debasement fear; watch DXY correlation"
        elif falling3 and pct12 < 0:
            return "✅ Gold retreating -- fear premium fading; risk appetite improving"
        elif falling3:
            return "→ Gold cooling -- taking some heat out of the inflation/fear narrative"
        return f"→ Gold +{pct12:+d}% yr -- modest hedge; not yet a panic signal"

    # ----------------------------------------------------------
    # CURRENCY GROUP
    # ----------------------------------------------------------

    elif label == "US Dollar (DXY)":
        pct12 = round((cur / mo12 - 1) * 100) if mo12 else 0
        if cur >= 110 and rising3:
            return "⚠️ Strong dollar headwind -- crushes earnings of multinationals and makes intl ADRs cheaper in USD"
        elif falling3 and pct12 < -3:
            return f"✅ Dollar weakening {pct12:+d}% yr -- direct tailwind for EQNR, PBR, SNY, NVO, SHEL and other intl ADRs"
        elif falling3:
            return "→ Dollar softening -- gradually improving backdrop for international ADR positions"
        elif rising3 and pct12 > 5:
            return f"⚠️ Dollar strengthening {pct12:+d}% yr -- headwind for intl ADR earnings translated back to USD"
        return "→ Dollar stable -- currency not adding incremental tailwind or headwind today"

    # ----------------------------------------------------------
    # CONSUMER SENTIMENT GROUP
    # ----------------------------------------------------------

    elif label == "Consumer Sentiment":
        if cur < 55:
            return "⚠️ Consumer deeply pessimistic -- spending contraction risk; watch retail and discretionary sectors"
        elif cur < 65 and falling3:
            return "⚠️ Deteriorating consumer confidence -- historically leads spending cuts by 2-3 months"
        elif cur < 65:
            return "→ Below-average sentiment -- consumer cautious but not collapsing; watch for inflection"
        elif cur >= 85:
            return "⚠️ Euphoric sentiment -- peak optimism historically a contrarian signal for mean reversion investors"
        elif cur >= 75 and rising3:
            return "→ Recovering confidence -- consumer spending should support GDP; watch for sentiment-driven momentum"
        elif rising3:
            return "→ Improving -- early sign consumers are adjusting to higher rates; reduces recession risk"
        return "→ Subdued but stable -- consumers cautious; not a crash signal, not a boom signal"

    # ----------------------------------------------------------
    # VALUATION GROUP
    # ----------------------------------------------------------

    elif label == "Shiller CAPE (US)":
        pct   = round((cur / 17.0 - 1) * 100)
        ratio = round(cur / 17.0, 1)
        if cur >= 40:
            return (f"⚠️ {ratio}x the 145yr avg -- only dot-com peak (44x) was higher; "
                    f"10yr forward returns historically near zero from this level")
        elif cur >= 35:
            return (f"⚠️ {pct}% above hist avg -- top decile of all valuations since 1881; "
                    f"long-term mean reversion case strongly favors ex-US and deep value")
        elif cur >= 30:
            return f"⚠️ {pct}% above hist avg -- elevated; patience and selectivity essential"
        elif cur >= 20:
            return f"→ Moderately above avg -- reasonable entry possible with strong Left Leg and MoS"
        return f"✅ Near or below hist avg 17x -- historically one of the most reliable buy signals"

    # Fallback -- should never reach here if all 15 labels are matched above
    return ""


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