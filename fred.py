# ============================================================
# fred.py -- Macro indicator fetching
# Mean Reversion Macro Insights
# ============================================================
#
# PUBLIC FUNCTION (called by main.py):
#   fetch_fred_data() -> list[dict]
#
# WHAT THIS DOES:
#   Fetches all 17 macro series in parallel (20s timeout each).
#   Routes each series by its id:
#     _YAHOO_*       -> Yahoo Finance (gold GC=F, WTI oil CL=F)
#     _SCRAPE_MULTPL -> multpl.com by-month table (Shiller CAPE)
#     anything else  -> standard FRED API (limit=500, sort desc)
#   Returns dicts with: label, id, group, freq, current, mo3, mo12,
#     trend, date (display), obs_date (ISO, used for freshness checks),
#     sig (insight text), insight (description)
#
# FRESHNESS FIX (Sep 29 2026): DAILY RATES
#   10Y, 2Y and Fed Funds used FRED's MONTHLY averages (GS10, GS2,
#   FEDFUNDS), so the dashboard showed August's 10Y (4.68%) when the
#   market was at 5.24%, and "Fed on hold" after the Sep 16 hike.
#   Now: DGS10, DGS2 (daily, ~1 business day lag) and DFF (daily
#   effective fed funds). WTI comes from Yahoo CL=F (FRED's oil lags
#   about a week) with DCOILWTICO as fallback.
#
# WINDOW FIX: each series has a "freq" so the 3-month and 12-month
#   columns look back the right distance:
#     daily 65/260 rows | calendar_daily (DFF) 91/365 | weekly (ICSA) 13/52
#     monthly 3/12. ICSA used to look back 65 WEEKS by mistake.
#
# STILL LAGGING BY NATURE (labelled with their real "as of" date):
#   CPI, PCE, unemployment, consumer sentiment (monthly), GDP (quarterly).
#   The government publishes these late; no data source can be faster.
#
# CAPE FIX: multpl.com's main page has no history table, so 3mo and 12mo
#   silently equalled today's value (41.2 / 41.2 / 41.2). Now read from
#   the by-month table (real values ~40.2 and ~38.6). If that fails the
#   columns show N/A and the dashboard flags it.
#
# INSIGHT TEXT: no leading symbols. The trend arrow and colour already
#   carry direction; the warning triangle is reserved for DATA problems.
#
# DOLLAR: the row is the Fed's Nominal BROAD Dollar Index (26 currencies,
#   base 100 in Jan 2006, level ~120), NOT the ICE DXY (6 currencies,
#   level ~90-110). Renamed "US Dollar Index (Broad)" to stop the
#   confusion.
#
# LEADING INDICATORS:
#   ICSA  -- Initial Jobless Claims, weekly, 4-week average in insight.
#   GDPC1 -- Real GDP, quarterly, YoY % (v0 vs 4 quarters ago).
#   (ISM PMI is intentionally NOT included: ISM had FRED remove it.)
# ============================================================

import os
import re
import concurrent.futures
from datetime import datetime, timedelta, date, timezone
import requests
from bs4 import BeautifulSoup

FRED_API_KEY = os.environ.get("FRED_API_KEY")

# ============================================================
# SERIES DEFINITIONS
# ============================================================

FRED_SERIES = [
    # ---- INFLATION (monthly, published mid/late month for the prior month) ----
    {"label": "CPI Inflation",        "id": "CPIAUCSL",      "freq": "monthly", "is_index": True,  "group": "INFLATION",
     "insight": "Headline CPI incl food & energy · hist avg ~3%"},
    {"label": "Core CPI",             "id": "CPILFESL",      "freq": "monthly", "is_index": True,  "group": "INFLATION",
     "insight": "CPI ex food/energy · Fed watches this · avg ~2.5%"},
    {"label": "PCE Inflation",        "id": "PCEPI",         "freq": "monthly", "is_index": True,  "group": "INFLATION",
     "insight": "Fed preferred gauge (broader than CPI) · avg ~2.2%"},
    {"label": "Core PCE",             "id": "PCEPILFE",      "freq": "monthly", "is_index": True,  "group": "INFLATION",
     "insight": "THE key number · Fed 2% target · >3% = rates stay high"},
    # ---- RATES (DAILY series: no more month-old averages) ----
    {"label": "10Y Treasury",         "id": "DGS10",         "freq": "daily", "is_index": False, "group": "RATES",
     "insight": "Risk-free rate · rising compresses P/E multiples · avg ~4%"},
    {"label": "2Y Treasury",          "id": "DGS2",          "freq": "daily", "is_index": False, "group": "RATES",
     "insight": "Fed expectations proxy · rising = no rate cuts priced in"},
    {"label": "Yield Curve (10Y-2Y)", "id": "T10Y2Y",        "freq": "daily", "is_index": False, "group": "RATES",
     "insight": "Negative = inverted = recession signal 12-18mo ahead"},
    {"label": "Fed Funds Rate",       "id": "DFF",           "freq": "calendar_daily", "is_index": False, "group": "RATES",
     "insight": "Effective rate, daily · cutting = tailwind for equities"},
    # ---- CREDIT ----
    {"label": "HY Credit Spread",     "id": "BAMLH0A0HYM2",  "freq": "daily", "is_index": False, "group": "CREDIT",
     "insight": "Junk bond premium · <3%=calm · >6%=credit fear/stress"},
    # ---- LABOR ----
    {"label": "Unemployment",         "id": "UNRATE",        "freq": "monthly", "is_index": False, "group": "LABOR",
     "insight": "Labor health · rising = consumer risk · hist avg ~5.7%"},
    # ---- COMMODITIES (Yahoo futures: same-day; FRED oil is ~1 week late) ----
    {"label": "WTI Crude Oil",        "id": "_YAHOO_CL",     "freq": "daily", "is_index": False, "group": "COMMODITIES",
     "yahoo": "CL=F", "fmt": "usd1", "fallback_id": "DCOILWTICO", "prefix": "$",
     "insight": "Energy price · >$85 = inflation pressure & input cost risk"},
    {"label": "Gold Price",           "id": "_YAHOO_GCF",    "freq": "daily", "is_index": False, "group": "COMMODITIES",
     "yahoo": "GC=F", "fmt": "usd0", "prefix": "$", "no_pct": True,
     "insight": "Fear/inflation hedge · rising+lowVIX = stealth fear signal"},
    # ---- CURRENCY ----
    # Fed Nominal BROAD Dollar Index (26 currencies, Jan 2006 = 100). NOT the ICE DXY.
    # The Fed publishes this once a week (Mondays, data through the prior Friday), so it can be
    # up to 10-11 days old on a normal day: max_age_days stops a false "late" warning.
    {"label": "US Dollar Index (Broad)", "id": "DTWEXBGS",   "freq": "daily", "is_index": False, "group": "CURRENCY",
     "no_pct": True, "max_age_days": 11,
     "insight": "Fed broad dollar index · 26 currencies · Jan 2006 = 100 · above 100 = stronger than 2006 · falling helps intl ADRs"},
    # ---- CONSUMER SENTIMENT ----
    {"label": "Consumer Sentiment",   "id": "UMCSENT",       "freq": "monthly", "is_index": False, "group": "SENTIMENT_FRED",
     "no_pct": True, "insight": "U of Michigan 0-100 · avg ~75 · <60 = consumer stress"},
    # ---- VALUATION ----
    {"label": "Shiller CAPE (US)",    "id": "_SCRAPE_MULTPL","freq": "daily", "is_index": False, "group": "VALUATION",
     "no_pct": True,
     "insight": "Cyclically Adj PE · 10yr smoothed · hist avg 17x · ~41 = 2nd highest ever"},
    # ---- LEADING INDICATORS ----
    # ICSA leads the monthly unemployment rate by 6-8 weeks: <250K=healthy, >300K=stress.
    {"label": "Jobless Claims (ICSA)", "id": "ICSA",         "freq": "weekly", "is_index": False, "group": "LABOR",
     "no_pct": True,
     "insight": "Weekly initial claims · <250K=healthy · >300K=stress · leads unemployment 6-8wk"},
    # GDPC1: quarterly. YoY % = v0 vs 4 quarters ago. 3mo col = prior quarter's YoY.
    {"label": "GDP Growth YoY",       "id": "GDPC1",         "freq": "quarterly", "is_index": False, "group": "GROWTH",
     "insight": "Real GDP YoY · >2%=above trend · <1%=stagnation · negative=recession"},
]

# Rows to look back for the "3mo ago" and "12mo ago" columns, by frequency
LOOKBACK = {
    "daily":          (65, 260),
    "calendar_daily": (91, 365),
    "weekly":         (13, 52),
    "monthly":        (3, 12),
}

GROUP_META = {
    "INFLATION":      {"icon": "🔥", "color": "#c81e1e", "label": "Inflation"},
    "RATES":          {"icon": "📊", "color": "#1a56db", "label": "Interest Rates"},
    "CREDIT":         {"icon": "💳", "color": "#7f1d1d", "label": "Credit"},
    "LABOR":          {"icon": "👷", "color": "#b45309", "label": "Labor"},
    "COMMODITIES":    {"icon": "🛢️", "color": "#d97706", "label": "Commodities"},
    "CURRENCY":       {"icon": "💵", "color": "#6366f1", "label": "Currency"},
    "SENTIMENT_FRED": {"icon": "🎭", "color": "#059669", "label": "Consumer Sentiment"},
    "VALUATION":      {"icon": "📐", "color": "#7c3aed", "label": "Valuation"},
    "GROWTH":         {"icon": "📈", "color": "#059669", "label": "Economic Growth"},
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
    elif group == "GROWTH":
        # GDP: rising YoY = good for equities
        return "#057a55" if trend == "▲" else "#c81e1e" if trend == "▼" else "#6b7280"
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

def _insight_text(label, cur_str, mo3_str, mo12_str, trend):
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

    rising3  = cur > mo3  + 0.05
    falling3 = cur < mo3  - 0.05
    rising12 = cur > mo12 + 0.05

    # ----------------------------------------------------------
    # INFLATION GROUP
    # ----------------------------------------------------------

    if label == "Core PCE":
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
            return "⚠️ Surging past 5% -- PE multiples compress mechanically, bond math competes with equities"
        elif cur >= 5.0:
            return "⚠️ Above 5% -- discount rate headwind severe, especially for long-duration growth names"
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
        elif rising3:
            return "⚠️ Fed has been HIKING -- tightening restarted; pressure on long-duration valuations and leveraged balance sheets"
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
            return f"→ Gold surging +{pct12}% yr -- real rates concern or dollar debasement fear; watch the dollar"
        elif falling3 and pct12 < 0:
            return "✅ Gold retreating -- fear premium fading; risk appetite improving"
        elif falling3:
            return "→ Gold cooling -- taking some heat out of the inflation/fear narrative"
        return f"→ Gold {pct12:+d}% yr -- modest hedge; not yet a panic signal"

    # ----------------------------------------------------------
    # CURRENCY GROUP
    # ----------------------------------------------------------

    elif label == "US Dollar Index (Broad)":
        pct12 = round((cur / mo12 - 1) * 100) if mo12 else 0
        if cur >= 125 and rising3:
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
            return (f"⚠️ {ratio}x the 145yr avg -- only dot-com peak (44.2x, Dec 1999) was higher; "
                    f"10yr forward returns historically near zero from this level")
        elif cur >= 35:
            return (f"⚠️ {pct}% above hist avg -- top decile of all valuations since 1881; "
                    f"long-term mean reversion case strongly favors ex-US and deep value")
        elif cur >= 30:
            return f"⚠️ {pct}% above hist avg -- elevated; patience and selectivity essential"
        elif cur >= 20:
            return f"→ Moderately above avg -- reasonable entry possible with strong Left Leg and MoS"
        return f"✅ Near or below hist avg 17x -- historically one of the most reliable buy signals"

    # ----------------------------------------------------------
    # LEADING INDICATORS GROUP
    # ----------------------------------------------------------

    elif label == "Jobless Claims (ICSA)":
        # cur is the raw weekly claims number (e.g. 239000)
        if cur >= 400000:
            return "⚠️ Recession-territory claims -- labor market deteriorating rapidly, cyclical value traps ahead"
        elif cur >= 350000:
            return "⚠️ Elevated stress -- labor cracking 4-8 weeks before unemployment lags; watch cyclicals"
        elif cur >= 300000 and rising3:
            return "⚠️ Rising above 300K -- early labor softening signal; value trap risk in cyclicals growing"
        elif cur >= 300000:
            return "→ Above 300K threshold -- stress emerging but not accelerating; monitor weekly"
        elif cur >= 250000 and rising3:
            return "→ Trending higher from healthy range -- watch for 300K threshold breach"
        elif cur <= 220000:
            return "✅ Very tight labor -- consumer spending well supported; wage inflation risk remains"
        return "✅ Healthy labor market -- no early recession warning from initial claims data"


    elif label == "GDP Growth YoY":
        # cur is the YoY % change (e.g. 2.3)
        if cur < 0:
            return "⚠️ Recession -- GDP contracting; even cheap stocks face earnings deterioration risk"
        elif cur < 1.0:
            return "⚠️ Stagnation -- below-trend growth; mean reversion requires a macro catalyst to materialize"
        elif cur < 2.0:
            return "→ Below-trend growth -- recovery slow; value stocks can outperform in this sluggish regime"
        elif cur >= 3.0 and rising3:
            return "✅ Above-trend expansion accelerating -- strong backdrop for cyclical value recovery"
        elif cur >= 2.0:
            return "✅ At/above trend growth -- healthy macro backdrop; not a headwind for mean reversion"
        return "→ Near trend -- neutral regime; macro not adding tailwind or headwind"

    # Fallback -- should never reach here if all 17 labels are matched above
    return ""


_LEADING_SYMBOL = re.compile(r"^(?:\u26a0\ufe0f|\u26a0|\u2705|\u2713|\u2192|\u26a1)\s*")


def _insight(label, cur_str, mo3_str, mo12_str, trend):
    """Insight text with no leading symbol (the warning triangle is reserved for data problems)."""
    return _LEADING_SYMBOL.sub("", _insight_text(label, cur_str, mo3_str, mo12_str, trend)).strip()


# ============================================================
# INDIVIDUAL SERIES FETCH
# ============================================================

_YAHOO_HDRS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)", "Accept": "application/json"}


def _empty_row(cfg, sig=""):
    return {**cfg, "current": "N/A", "mo3": "N/A", "mo12": "N/A",
            "trend": "?", "date": "N/A", "obs_date": "", "sig": sig}


def _fetch_yahoo_series(cfg):
    """
    Yahoo Finance daily bars for futures (gold GC=F, oil CL=F).
    Raises on any problem so the caller can use a fallback.
    """
    ticker = cfg["yahoo"]
    url  = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=400d"
    resp = requests.get(url, headers=_YAHOO_HDRS, timeout=12)
    result = resp.json()["chart"]["result"][0]
    pairs  = [(t, c) for t, c in zip(result["timestamp"], result["indicators"]["quote"][0]["close"])
              if c is not None]
    if len(pairs) < 70:
        raise ValueError(f"only {len(pairs)} bars from Yahoo {ticker}")
    meta = result.get("meta", {})
    v0   = float(meta.get("regularMarketPrice") or pairs[-1][1])
    v3   = pairs[max(0, len(pairs) - 65)][1]
    v12  = pairs[max(0, len(pairs) - 260)][1]
    obs  = datetime.fromtimestamp(meta.get("regularMarketTime") or pairs[-1][0], tz=timezone.utc)

    fmt = cfg.get("fmt", "usd0")
    f   = (lambda v: f"${v:,.0f}") if fmt == "usd0" else (lambda v: f"${v:,.1f}")
    dc, dm3, dm12 = f(v0), f(v3), f(v12)
    trend = "▲" if v0 > v3 * 1.001 else "▼" if v0 < v3 * 0.999 else "→"
    sig   = _insight(cfg["label"], dc, dm3, dm12, trend)
    return {**cfg, "current": dc, "mo3": dm3, "mo12": dm12, "trend": trend,
            "date": obs.strftime("%b %d %Y"), "obs_date": obs.strftime("%Y-%m-%d"), "sig": sig}


def _fetch_cape(cfg):
    """
    Shiller CAPE from multpl.com's BY-MONTH table (first row = latest reading,
    then one row per month). 3mo and 12mo are the rows closest to those dates.
    If the table cannot be read, current comes from the main page and the
    history columns show N/A (never silently equal to today's value).
    """
    label = cfg["label"]
    hdrs  = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        resp = requests.get("https://www.multpl.com/shiller-pe/table/by-month",
                            headers=hdrs, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        points = []
        for tr in soup.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 2:
                continue
            try:
                d = datetime.strptime(tds[0].get_text(strip=True), "%b %d, %Y")
                v = float(re.sub(r"[^0-9.]", "", tds[1].get_text(strip=True)))
            except Exception:
                continue
            points.append((d, v))
        if len(points) >= 14:
            points.sort(key=lambda p: p[0], reverse=True)
            d0, v0 = points[0]

            def nearest(days):
                target = d0 - timedelta(days=days)
                return min(points, key=lambda p: abs((p[0] - target).days))[1]

            v3, v12 = nearest(91), nearest(365)
            dc, dm3, dm12 = f"{v0:.1f}", f"{v3:.1f}", f"{v12:.1f}"
            trend = "▲" if v0 > v3 + 0.2 else "▼" if v0 < v3 - 0.2 else "→"
            sig   = _insight(label, dc, dm3, dm12, trend)
            return {**cfg, "current": dc, "mo3": dm3, "mo12": dm12, "trend": trend,
                    "date": d0.strftime("%b %d %Y"), "obs_date": d0.strftime("%Y-%m-%d"), "sig": sig}
        print(f"   ⚠️ CAPE by-month table: only {len(points)} rows parsed -- using main page")
    except Exception as e:
        print(f"   ⚠️ CAPE by-month failed: {str(e)[:60]} -- using main page")

    # Fallback: current value only. History columns are honest N/A.
    try:
        resp = requests.get("https://www.multpl.com/shiller-pe", headers=hdrs, timeout=15)
        soup = BeautifulSoup(resp.text, "html.parser")
        div  = soup.find("div", {"id": "current"})
        v0   = float(re.search(r"(\d+\.\d+)", div.get_text()).group(1))
        today = datetime.now(timezone.utc)
        return {**cfg, "current": f"{v0:.1f}", "mo3": "N/A", "mo12": "N/A", "trend": "?",
                "date": today.strftime("%b %d %Y"), "obs_date": today.strftime("%Y-%m-%d"),
                "sig": _insight(label, f"{v0:.1f}", f"{v0:.1f}", f"{v0:.1f}", "→"),
                "source_note": "history unavailable"}
    except Exception as e:
        return _empty_row(cfg, f"CAPE multpl.com failed: {str(e)[:50]}")


def _fetch_fred_standard(cfg, start_date, end_date):
    """Standard FRED API series (sorted newest first)."""
    label    = cfg["label"]
    sid      = cfg["id"]
    freq     = cfg.get("freq", "monthly")
    is_index = cfg["is_index"]
    no_pct   = cfg.get("no_pct", False)
    prefix   = cfg.get("prefix", "")
    empty    = _empty_row(cfg)

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
        obs_date = obs[0]["date"]

        # ── GDPC1: quarterly GDP YoY special handling ──────────────────────
        # Need v0 vs 4 quarters ago. 3mo col = prior quarter's YoY.
        if sid == "GDPC1":
            n = len(obs)
            if n < 5:
                return {**empty, "sig": "GDP: insufficient observations"}
            try:
                v0  = float(obs[0]["value"])
                v1q = float(obs[min(1, n-1)]["value"])
                v4q = float(obs[min(4, n-1)]["value"])
                v5q = float(obs[min(5, n-1)]["value"])
                v8q = float(obs[min(8, n-1)]["value"]) if n > 8 else v4q
                if not v4q:
                    return {**empty, "sig": "GDP: zero value in denominator"}
                yoy_cur = (v0  - v4q) / v4q * 100
                yoy_1q  = (v1q - v5q) / v5q * 100 if v5q else yoy_cur
                yoy_2yr = (v4q - v8q) / v8q * 100 if v8q else yoy_cur
                dc, dm3, dm12 = f"{yoy_cur:.1f}%", f"{yoy_1q:.1f}%", f"{yoy_2yr:.1f}%"
                trend = ("▲" if yoy_cur > yoy_1q + 0.1
                         else "▼" if yoy_cur < yoy_1q - 0.1 else "→")
                pub_dt  = datetime.strptime(obs[0]["date"], "%Y-%m-%d")
                pub     = f"Q{(pub_dt.month - 1) // 3 + 1} {pub_dt.year}"
                return {**cfg, "current": dc, "mo3": dm3, "mo12": dm12, "trend": trend,
                        "date": pub, "obs_date": obs_date,
                        "sig": _insight(label, dc, dm3, dm12, trend)}
            except Exception as e:
                return {**empty, "sig": f"GDP: {str(e)[:60]}"}

        # ── Standard index / rate / value series ───────────────────────────
        w3, w12  = LOOKBACK.get(freq, LOOKBACK["monthly"])
        mo3_idx  = min(w3,  len(obs) - 1)
        mo12_idx = min(w12, len(obs) - 1)
        v0  = float(obs[0]["value"])
        v3  = float(obs[mo3_idx]["value"])
        v12 = float(obs[mo12_idx]["value"])

        if is_index and v12:
            cur     = (v0 - v12) / v12 * 100
            v15_idx = min(mo12_idx + mo3_idx, len(obs) - 1)
            v15     = float(obs[v15_idx]["value"])
            mo3v    = (v3 - v15) / v15 * 100 if v15 else cur
            dc      = f"{cur:.1f}%"
            dm3     = f"{mo3v:.1f}%"
            dm12    = f"{mo3v:.1f}%"
            trend   = "▼" if cur < mo3v - 0.05 else "▲" if cur > mo3v + 0.05 else "→"
        elif no_pct:
            def fmt(v):
                return (f"{prefix}{v:,.0f}" if v > 999
                        else f"{prefix}{v:.2f}" if prefix
                        else f"{v:.1f}")
            dc, dm3, dm12 = fmt(v0), fmt(v3), fmt(v12)
            trend = "▲" if v0 > v3 + 0.05 else "▼" if v0 < v3 - 0.05 else "→"
        elif prefix:
            dc, dm3, dm12 = f"{prefix}{v0:.1f}", f"{prefix}{v3:.1f}", f"{prefix}{v12:.1f}"
            trend = "▲" if v0 > v3 + 0.05 else "▼" if v0 < v3 - 0.05 else "→"
        else:
            dc, dm3, dm12 = f"{v0:.2f}%", f"{v3:.2f}%", f"{v12:.2f}%"
            trend = "▲" if v0 > v3 + 0.05 else "▼" if v0 < v3 - 0.05 else "→"

        # Display date: day-level for daily/weekly series, month-level for monthly
        d = datetime.strptime(obs_date, "%Y-%m-%d")
        pub = d.strftime("%b %Y") if freq == "monthly" else d.strftime("%b %d %Y")

        sig = _insight(label, dc, dm3, dm12, trend)
        # ICSA: prefix insight with 4-week moving average for trend context
        if sid == "ICSA" and len(obs) >= 4:
            try:
                ma4 = round(sum(float(obs[i]["value"]) for i in range(4)) / 4)
                sig = f"4-wk avg: {ma4:,.0f} | {sig}"
            except Exception:
                pass

        return {**cfg, "current": dc, "mo3": dm3, "mo12": dm12, "trend": trend,
                "date": pub, "obs_date": obs_date, "sig": sig}

    except Exception as e:
        return {**empty, "sig": str(e)[:50]}


def _fetch_one_fred(cfg, start_date, end_date):
    """Route one series to the right source (Yahoo, multpl, or FRED)."""
    sid = cfg["id"]
    if sid.startswith("_YAHOO"):
        try:
            return _fetch_yahoo_series(cfg)
        except Exception as e:
            fb = cfg.get("fallback_id")
            if fb:
                print(f"   ⚠️ {cfg['label']}: Yahoo failed ({str(e)[:50]}) -- using FRED {fb}")
                row = _fetch_fred_standard({**cfg, "id": fb}, start_date, end_date)
                row["id"] = sid
                row["source_note"] = f"FRED {fb} fallback (about a week behind)"
                return row
            return _empty_row(cfg, f"{cfg['label']} Yahoo fetch failed: {str(e)[:50]}")
    if sid == "_SCRAPE_MULTPL":
        return _fetch_cape(cfg)
    return _fetch_fred_standard(cfg, start_date, end_date)


# ============================================================
# PUBLIC ENTRY POINT
# ============================================================

def fetch_fred_data():
    """
    Fetch all 17 FRED series in parallel (20s timeout per call).
    Gold routes to Yahoo GC=F, CAPE routes to multpl.com.
    GDPC1 uses quarterly YoY special handling.
    Returns list of enriched dicts in FRED_SERIES definition order.
    """
    print("\n🏦 Fetching FRED macro indicators (parallel, 20s timeout)...")
    end   = date.today().strftime("%Y-%m-%d")
    # 1200 days ensures GDPC1 gets 13+ quarterly obs (need 9 for correct 2yr comparison).
    # 460 days only gave ~5 quarterly obs -- obs[8] fell back to obs[4] giving 0% (bug).
    # Daily/monthly series unaffected: limit=500 caps the response naturally.
    start = (date.today() - timedelta(days=1200)).strftime("%Y-%m-%d")
    rmap  = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=17) as ex:
        futs = {ex.submit(_fetch_one_fred, cfg, start, end): cfg for cfg in FRED_SERIES}
        for f in concurrent.futures.as_completed(futs):
            r    = f.result()
            rmap[r["label"]] = r
            icon = "✅" if r["current"] != "N/A" else "❌"
            print(f"   {icon} {r['label']}: {r['current']} {r['trend']}")

    results = [
        rmap.get(c["label"], _empty_row(c))
        for c in FRED_SERIES
    ]
    ok = sum(1 for r in results if r["current"] != "N/A")
    status = "✅" if ok == len(results) else "⚠️"
    print(f"   {status} FRED complete: {ok}/{len(results)} indicators fetched")
    return results