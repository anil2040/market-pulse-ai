# ============================================================
# Mean Reversion Macro Insights -- main.py
# Updated: September 2026
# ============================================================
#
# WHAT THIS DOES:
# Runs every weekday at 6:55 AM MT via GitHub Actions.
# Fetches macro data, sentiment, value screens, news emails,
# synthesizes with AI, and publishes an HTML dashboard to
# GitHub Pages. A Chrome extension reads the hidden
# #market-context div and feeds it into stock-level mean
# reversion analysis.
#
# PIPELINE (in execution order):
#   1.  FRED macro indicators -- 15 series parallel (20s timeout)
#       Groups: INFLATION | RATES | CREDIT | LABOR |
#               COMMODITIES | CURRENCY | SENTIMENT_FRED | VALUATION
#       New vs prior version: CAPE (Shiller PE), Gold, DXY added
#   2.  AAII sentiment -- scrape attempt, N/A if Incapsula blocks
#   3.  CNN Fear & Greed -- JSON endpoint, updates intraday
#   4.  Market data -- SPX, RUT, VIX + URTH PE, EFA PE (Yahoo v8)
#   5.  MHS (Macro Heat Score) -- inverted 0-100 composite
#       Now includes CAPE contribution (+15 at current ~41x)
#   6.  Dataroma 13F -- reads cache first, live fetch fallback
#   7.  Magic Formula -- ASP.NET 4-step authenticated scrape
#   8.  Acquirer's Multiple -- RCP login + HTML table scrape
#   9.  Edward Jones daily recap -- web scrape
#  10.  CNBC Morning Squawk -- Yahoo IMAP
#  11.  Yahoo Finance Morning Brief -- Yahoo IMAP
#  12.  McClellan Oscillator -- Yahoo IMAP (weekly Tom McClellan)
#  13.  AI synthesis -- fallback chain:
#         gemini-3.6-flash  (free, 20 RPD quota)
#         gemini-1.5-flash  (free, separate quota pool)
#         claude-haiku-4-5  (paid ~$0.003/run -- SHOWN IN LOG)
#         structured text   (always works, no AI narrative)
#  14.  Build HTML dashboard + hidden #market-context div
#
# MHS SCALE (Macro Heat Score -- replaces old "MRI" acronym):
#   0-33:   GREEN  DEPLOY     -- Panic/dislocation. Deploy aggressively.
#   34-65:  AMBER  SELECTIVE  -- Best setups only. Left Leg <4, MoS >25%.
#   66-100: RED    OVERHEATED -- Build cash. Trim winners. Avoid chasing.
#
# SECRETS REQUIRED (GitHub repo > Settings > Secrets > Actions):
#   GEMINI_API_KEY, ANTHROPIC_API_KEY,
#   YAHOO_EMAIL, YAHOO_APP_PASSWORD, FRED_API_KEY,
#   MFI_EMAIL, MFI_PASSWORD, AM_EMAIL, AM_PASSWORD
#
# FUN FACT: The FRED API processes over 1 million requests per day
# and is completely free. It was built by the St. Louis Federal Reserve
# starting in 1991 -- before the modern web existed.
# ============================================================

import os
import imaplib
import email
import re
import time
import concurrent.futures
from datetime import datetime, timezone, timedelta, date
import requests
from bs4 import BeautifulSoup
import google.genai as genai

# ============================================================
# CONFIGURATION
# ============================================================

GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
YAHOO_EMAIL       = os.environ.get("YAHOO_EMAIL")
YAHOO_PASSWORD    = os.environ.get("YAHOO_APP_PASSWORD")
FRED_API_KEY      = os.environ.get("FRED_API_KEY")
MFI_EMAIL         = os.environ.get("MFI_EMAIL")
MFI_PASSWORD      = os.environ.get("MFI_PASSWORD")
AM_EMAIL          = os.environ.get("AM_EMAIL")
AM_PASSWORD       = os.environ.get("AM_PASSWORD")

# Boise MDT = UTC-6 (summer), MST = UTC-7 (winter after Nov first Sunday)
MT = timezone(timedelta(hours=-6))

# Global run log -- every step appends here, shown collapsed in dashboard
RUN_LOG   = []
RUN_START = time.time()

def log(msg, status="✅"):
    """Append a timestamped entry to the run log."""
    elapsed = round(time.time() - RUN_START)
    RUN_LOG.append(f"{status} [{elapsed}s] {msg}")

print("✅ Configuration loaded")
print(f"📧 Email: {YAHOO_EMAIL}")
print(f"🔑 Anthropic key: {'set' if ANTHROPIC_API_KEY else 'NOT SET -- Haiku fallback unavailable'}")


# ============================================================
# STEP 1: FRED MACRO INDICATORS
# ============================================================
# FRED = Federal Reserve Economic Data (St. Louis Fed, free API).
# Rate limit: 120 req/min per API key. We use 15 parallel calls --
# well within limits. Data covers 800,000+ economic time series.
#
# COLOR LOGIC for trend arrows (what direction is GOOD for equity investors):
#   INFLATION:    UP=red(bad)        DOWN=green(good)
#   RATES:        UP=red(bad)        DOWN=green -- EXCEPT Yield Curve
#   Yield Curve:  UP=green(steepen)  DOWN=red(flatten/invert)
#   CREDIT:       UP=red(widen=bad)  DOWN=green(tighten=good)
#   LABOR:        UP=red(unemp bad)  DOWN=green(tight labor)
#   WTI:          UP=red(inflation)  DOWN=green
#   GOLD:         UP=amber(ambiguous -- fear OR inflation signal)
#   DXY:          UP=amber(helps US stocks, hurts intl ADRs)
#   CONSUMER SENT:UP=green(confident)DOWN=red
#   VALUATION/CAPE:UP=red(pricier)  DOWN=green(cheaper)
#
# NEW SERIES (added Sep 2026):
#   SHILLER_CAPE      -- Shiller CAPE ratio (monthly, Robert Shiller/Yale)
#     Fun fact: Shiller won the 2013 Nobel Prize for showing that high CAPE
#     predicts low 10-year forward returns. At CAPE 41, we are at the 98.8th
#     percentile of 1,749 monthly readings since 1881. Only exceeded at the
#     dot-com peak (44.2x, Dec 1999) -- right before Nasdaq fell 78%.
#   GOLDAMGBD228NLBM  -- Gold London AM fix (daily, LBMA)
#   DTWEXBGS          -- Trade Weighted USD Index broad (weekly, Fed)
# ============================================================

FRED_SERIES = [
    # ---- INFLATION ----
    {"label":"CPI Inflation",        "id":"CPIAUCSL",         "is_index":True,  "group":"INFLATION",
     "insight":"Headline CPI incl food & energy · hist avg ~3%"},
    {"label":"Core CPI",             "id":"CPILFESL",         "is_index":True,  "group":"INFLATION",
     "insight":"CPI ex food/energy · Fed watches this · avg ~2.5%"},
    {"label":"PCE Inflation",        "id":"PCEPI",            "is_index":True,  "group":"INFLATION",
     "insight":"Fed preferred gauge (broader than CPI) · avg ~2.2%"},
    {"label":"Core PCE",             "id":"PCEPILFE",         "is_index":True,  "group":"INFLATION",
     "insight":"THE key number · Fed 2% target · >3% = rates stay high"},
    # ---- RATES ----
    {"label":"10Y Treasury",         "id":"GS10",             "is_index":False, "group":"RATES",
     "insight":"Risk-free rate · rising compresses P/E multiples · avg ~4%"},
    {"label":"2Y Treasury",          "id":"GS2",              "is_index":False, "group":"RATES",
     "insight":"Fed expectations proxy · rising = no rate cuts priced in"},
    {"label":"Yield Curve (10Y-2Y)", "id":"T10Y2Y",           "is_index":False, "group":"RATES",
     "insight":"Negative = inverted = recession signal 12-18mo ahead"},
    {"label":"Fed Funds Rate",       "id":"FEDFUNDS",         "is_index":False, "group":"RATES",
     "insight":"Cost of borrowing · cutting = tailwind for equities"},
    # ---- CREDIT ----
    {"label":"HY Credit Spread",     "id":"BAMLH0A0HYM2",    "is_index":False, "group":"CREDIT",
     "insight":"Junk bond premium · <3%=calm · >6%=credit fear/stress"},
    # ---- LABOR ----
    {"label":"Unemployment",         "id":"UNRATE",           "is_index":False, "group":"LABOR",
     "insight":"Labor health · rising = consumer risk · hist avg ~5.7%"},
    # ---- COMMODITIES ----
    {"label":"WTI Crude Oil",        "id":"DCOILWTICO",       "is_index":False, "group":"COMMODITIES",
     "prefix":"$", "insight":"Energy price · >$85 = inflation pressure & input cost risk"},
    {"label":"Gold Price",           "id":"GOLDAMGBD228NLBM", "is_index":False, "group":"COMMODITIES",
     "prefix":"$", "no_pct":True,
     "insight":"Fear/inflation hedge · rising+lowVIX = stealth fear signal"},
    # ---- CURRENCY ----
    {"label":"US Dollar (DXY)",      "id":"DTWEXBGS",         "is_index":False, "group":"CURRENCY",
     "no_pct":True,
     "insight":"Dollar strength · weak dollar = tailwind for intl ADRs (EQNR,PBR,SNY etc)"},
    # ---- CONSUMER SENTIMENT ----
    {"label":"Consumer Sentiment",   "id":"UMCSENT",          "is_index":False, "group":"SENTIMENT_FRED",
     "no_pct":True, "insight":"U of Michigan 0-100 · avg ~75 · <60 = consumer stress"},
    # ---- VALUATION ----
    # Shiller CAPE: real S&P 500 price / 10yr avg real earnings.
    # Smoothing removes business cycle noise. Robert Shiller won the
    # 2013 Nobel Prize for predicting low future returns when CAPE is high.
    # Current ~41 = 98.8th percentile. Dot-com peak was 44.2x (Dec 1999).
    {"label":"Shiller CAPE (US)",    "id":"SHILLER_CAPE",     "is_index":False, "group":"VALUATION",
     "no_pct":True,
     "insight":"Cyclically Adj PE · 10yr smoothed · hist avg 17x · ~41 = 2nd highest ever"},
]

GROUP_META = {
    "INFLATION":     {"icon":"🔥","color":"#c81e1e","label":"Inflation"},
    "RATES":         {"icon":"📊","color":"#1a56db","label":"Interest Rates"},
    "CREDIT":        {"icon":"💳","color":"#7f1d1d","label":"Credit"},
    "LABOR":         {"icon":"👷","color":"#b45309","label":"Labor"},
    "COMMODITIES":   {"icon":"🛢️","color":"#d97706","label":"Commodities"},
    "CURRENCY":      {"icon":"💵","color":"#6366f1","label":"Currency"},
    "SENTIMENT_FRED":{"icon":"🎭","color":"#059669","label":"Consumer Sentiment"},
    "VALUATION":     {"icon":"📐","color":"#7c3aed","label":"Valuation"},
}


def _trend_color(label, group, trend):
    """
    Return hex color for trend arrow based on what direction is GOOD for equity investors.
    Green = good. Red = bad. Amber = ambiguous/context-dependent.
    Called for every FRED row in the HTML table.
    """
    if group == "INFLATION":
        return "#057a55" if trend=="▼" else "#c81e1e" if trend=="▲" else "#6b7280"
    elif group == "RATES":
        if "Yield Curve" in label:
            return "#057a55" if trend=="▲" else "#c81e1e" if trend=="▼" else "#6b7280"
        else:
            # 10Y, 2Y, Fed Funds: rising = bad for equities
            return "#c81e1e" if trend=="▲" else "#057a55" if trend=="▼" else "#6b7280"
    elif group == "CREDIT":
        return "#c81e1e" if trend=="▲" else "#057a55" if trend=="▼" else "#6b7280"
    elif group == "LABOR":
        return "#c81e1e" if trend=="▲" else "#057a55" if trend=="▼" else "#6b7280"
    elif group == "COMMODITIES":
        if "Gold" in label:
            # Gold rising = ambiguous (fear OR inflation). Amber not red/green.
            return "#b45309" if trend=="▲" else "#6b7280" if trend=="▼" else "#6b7280"
        else:
            # WTI rising = inflation/input cost pressure = bad
            return "#c81e1e" if trend=="▲" else "#057a55" if trend=="▼" else "#6b7280"
    elif group == "CURRENCY":
        # DXY rising = dollar strengthening = headwind for intl ADRs. Amber.
        return "#b45309" if trend=="▲" else "#059669" if trend=="▼" else "#6b7280"
    elif group == "SENTIMENT_FRED":
        # Consumer Sentiment rising = confident = good
        return "#057a55" if trend=="▲" else "#c81e1e" if trend=="▼" else "#6b7280"
    elif group == "VALUATION":
        # CAPE rising = more expensive = bad for future returns
        return "#c81e1e" if trend=="▲" else "#057a55" if trend=="▼" else "#6b7280"
    return "#6b7280"


def _insight(label, cur_str, mo3_str, mo12_str, trend):
    """
    Generate contextual insight text for each indicator.
    Compares current value to historical norms, not just recent direction.
    Replaces old 'Today's Signal' which just restated the trend arrow.
    Uses double-arrow notation: first=vs3mo direction, second=vs12mo direction.
    """
    try:
        cur  = float(re.sub(r"[%$,]","",str(cur_str)))
        mo3  = float(re.sub(r"[%$,]","",str(mo3_str)))
        mo12 = float(re.sub(r"[%$,]","",str(mo12_str)))
    except:
        return ""

    dir3  = "↑" if cur > mo3  + 0.05 else "↓" if cur < mo3  - 0.05 else "→"
    dir12 = "↑" if cur > mo12 + 0.05 else "↓" if cur < mo12 - 0.05 else "→"

    if label == "Core PCE":
        pct = round((cur/2.0 - 1)*100)
        if cur <= 2.0:
            return f"✅ AT Fed 2% target · {dir3}3mo {dir12}12mo"
        elif cur > 3.0 and dir3=="↑" and dir12=="↑":
            return f"⚠️ SUSTAINED RISE · {pct}% above 2% target · rates stay elevated"
        elif cur > 3.0:
            return f"⚠️ {pct}% above 2% target · {dir3}3mo {dir12}12mo"
        else:
            return f"→ Elevated but {dir3}3mo · {dir12}12mo · watch direction"

    elif label in ("CPI Inflation","PCE Inflation","Core CPI"):
        mood = ("⚠️ Heating" if dir3=="↑" and dir12=="↑"
                else "📉 Cooling" if dir3=="↓" else "→ Mixed")
        return f"{mood} · {dir3}3mo {dir12}12mo"

    elif label == "Fed Funds Rate":
        if cur >= 5.0: return f"⚠️ Restrictive (avg ~2.5%) · {dir3}3mo · growth headwind"
        elif cur <= 3.0: return f"✅ Accommodative · {dir3}3mo"
        elif dir3 == "↓": return f"📉 Cutting cycle · positive for rate-sensitive equities"
        elif dir3 == "↑": return f"⚠️ Rising rates · tightening · headwind for P/E multiples"
        else: return f"→ On hold at {cur:.2f}% · {dir12}12mo"

    elif label == "10Y Treasury":
        if cur >= 5.0 and dir3=="↑":
            return f"⚠️ High & rising at {cur:.2f}% · P/E compression intensifying"
        elif cur >= 5.0:
            return f"⚠️ Elevated at {cur:.2f}% (avg ~4%) · P/E compression risk"
        elif cur <= 3.5:
            return f"✅ Low at {cur:.2f}% · supports higher valuations · {dir3}3mo"
        else:
            return f"{dir3}3mo {dir12}12mo · rising = headwind, falling = tailwind for all equities"

    elif label == "2Y Treasury":
        if cur >= 4.5 and dir3=="↑":
            return f"⚠️ High & rising · market pricing in NO rate cuts"
        elif dir3 == "↓":
            return f"✅ Falling · rate cuts being priced in · {dir12}12mo"
        else:
            return f"→ {cur:.2f}% · {dir3}3mo · Fed expectations proxy"

    elif label == "Yield Curve (10Y-2Y)":
        if cur < -0.5: return f"⚠️ DEEPLY INVERTED {cur:.2f}% · strong recession signal (12-18mo lead)"
        elif cur < 0:  return f"⚠️ Inverted {cur:.2f}% · historically predicts recession"
        elif cur < 0.3: return f"→ Nearly flat {cur:.2f}% · {dir3}3mo · watch for re-inversion"
        else: return f"✅ Positive {cur:.2f}% · steepening = growth expectations improving"

    elif label == "HY Credit Spread":
        if cur <= 2.5: return f"⚠️ Historically tight {cur:.2f}% · credit fully complacent · no fear priced in"
        elif cur <= 3.5: return f"→ Tight {cur:.2f}% (normal ~4-5%) · {dir3}3mo"
        elif cur >= 6.0: return f"⚠️ WIDE {cur:.2f}% · credit stress · fear of defaults rising"
        else: return f"→ {cur:.2f}% · {dir3}3mo {dir12}12mo"

    elif label == "Unemployment":
        if cur >= 5.0: return f"⚠️ Elevated {cur:.1f}% (hist avg ~5.7%) · {dir3}3mo"
        elif cur <= 4.0: return f"✅ Tight labor market {cur:.1f}% · {dir3}3mo"
        else: return f"→ {cur:.1f}% · {dir3}3mo {dir12}12mo"

    elif label == "WTI Crude Oil":
        if cur >= 90 and dir3=="↑":
            return f"⚠️ HIGH & RISING ${cur:.0f} · inflation pressure + recession risk"
        elif cur >= 90:
            return f"⚠️ Elevated ${cur:.0f} (avg ~$65) · inflationary · {dir3}3mo"
        elif cur <= 60:
            return f"✅ Low ${cur:.0f} · consumer-friendly · {dir3}3mo"
        else:
            return f"${cur:.0f} · {dir3}3mo {dir12}12mo · >$85 = inflation concern"

    elif label == "Gold Price":
        pct12 = round((cur/mo12-1)*100) if mo12 else 0
        flag  = "⚠️ Stealth fear signal (VIX low, gold surging)" if pct12 > 20 else "→"
        return f"{flag} ${cur:,.0f} · {pct12:+d}% vs 12mo · {dir3}3mo"

    elif label == "US Dollar (DXY)":
        pct12   = round((cur/mo12-1)*100) if mo12 else 0
        intl    = "tailwind for intl ADRs" if dir3=="↓" else "headwind for intl ADRs"
        return f"DXY {cur:.1f} · {pct12:+d}% vs 12mo · {dir3}3mo · {intl}"

    elif label == "Consumer Sentiment":
        note = "well below avg ~75" if cur<65 else "below avg" if cur<72 else "near avg ~75"
        return f"{cur:.1f}/100 ({note}) · {dir3}3mo {dir12}12mo"

    elif label == "Shiller CAPE (US)":
        # Context is everything here -- this is the most important insight row.
        pct = round((cur/17.0 - 1)*100)
        if cur >= 40:
            return (f"⚠️ EXTREME {cur:.1f}x · {pct}% above hist avg 17x · "
                    f"98th pctile since 1881 · only exceeded at dot-com peak 44.2x")
        elif cur >= 30:
            return f"⚠️ Elevated {cur:.1f}x · {pct}% above hist avg 17x · {dir3}3mo"
        elif cur >= 20:
            return f"→ Moderate {cur:.1f}x · {pct}% above hist avg · {dir3}3mo"
        else:
            return f"✅ Reasonable {cur:.1f}x vs hist avg 17x · {dir3}3mo"

    return f"{dir3}3mo {dir12}12mo"


def _fetch_one_fred(cfg, start_date, end_date):
    """
    Fetch a single FRED series and compute current, 3mo, 12mo values.
    For index series (CPI, PCE): converts raw index to YoY % change.
    For level series (rates, spreads): returns raw values.
    Fetches 15 obs (descending) to cover 12+ months of history.
    """
    label    = cfg["label"]
    sid      = cfg["id"]
    is_index = cfg["is_index"]
    no_pct   = cfg.get("no_pct", False)
    prefix   = cfg.get("prefix", "")
    empty    = {**cfg,"current":"N/A","mo3":"N/A","mo12":"N/A","trend":"?","date":"N/A","sig":""}

    try:
        url  = (f"https://api.stlouisfed.org/fred/series/observations"
                f"?series_id={sid}&api_key={FRED_API_KEY}&file_type=json"
                f"&observation_start={start_date}&observation_end={end_date}"
                f"&sort_order=desc&limit=15")
        resp = requests.get(url, timeout=20)
        obs  = [o for o in resp.json().get("observations",[]) if o["value"] != "."]
        if not obs: return empty

        v0  = float(obs[0]["value"])
        v3  = float(obs[min(3,  len(obs)-1)]["value"])
        v12 = float(obs[min(12, len(obs)-1)]["value"])

        if is_index and v12:
            # YoY % change (e.g. CPI raw index -> annual inflation rate)
            cur  = (v0 - v12) / v12 * 100
            v15  = float(obs[min(14,len(obs)-1)]["value"])
            mo3v = (v3 - v15) / v15 * 100 if v15 else cur
            dc   = f"{cur:.1f}%"; dm3 = f"{mo3v:.1f}%"; dm12 = f"{mo3v:.1f}%"
            trend = "▼" if cur < mo3v-0.05 else "▲" if cur > mo3v+0.05 else "→"
        elif no_pct:
            # Raw number (Gold price in $, DXY index, Consumer Sentiment, CAPE)
            fmt  = lambda v: f"{prefix}{v:,.0f}" if v > 999 else f"{prefix}{v:.2f}" if prefix else f"{v:.1f}"
            dc   = fmt(v0); dm3 = fmt(v3); dm12 = fmt(v12)
            trend = "▲" if v0 > v3+0.05 else "▼" if v0 < v3-0.05 else "→"
        elif prefix:
            # Dollar-prefixed level (WTI crude)
            dc   = f"{prefix}{v0:.1f}"; dm3 = f"{prefix}{v3:.1f}"; dm12 = f"{prefix}{v12:.1f}"
            trend = "▲" if v0 > v3+0.05 else "▼" if v0 < v3-0.05 else "→"
        else:
            # Percentage rate (Treasury yields, HY spread, unemployment)
            dc   = f"{v0:.2f}%"; dm3 = f"{v3:.2f}%"; dm12 = f"{v12:.2f}%"
            trend = "▲" if v0 > v3+0.05 else "▼" if v0 < v3-0.05 else "→"

        pub = datetime.strptime(obs[0]["date"],"%Y-%m-%d").strftime("%b %d %Y")
        sig = _insight(label, dc, dm3, dm12, trend)
        return {**cfg, "current":dc, "mo3":dm3, "mo12":dm12, "trend":trend, "date":pub, "sig":sig}

    except Exception as e:
        return {**empty, "sig":str(e)[:50]}


def fetch_fred_data():
    """Fetch all 15 FRED series in parallel (20s timeout per call)."""
    print("\n🏦 Fetching FRED macro indicators (parallel, 20s timeout)...")
    end   = date.today().strftime("%Y-%m-%d")
    start = (date.today() - timedelta(days=460)).strftime("%Y-%m-%d")
    rmap  = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as ex:
        futs = {ex.submit(_fetch_one_fred, cfg, start, end): cfg for cfg in FRED_SERIES}
        for f in concurrent.futures.as_completed(futs):
            r = f.result()
            rmap[r["label"]] = r
            icon = "✅" if r["current"] != "N/A" else "❌"
            print(f"   {icon} {r['label']}: {r['current']} {r['trend']}")

    results = [rmap.get(c["label"], {**c,"current":"N/A","mo3":"N/A","mo12":"N/A","trend":"?","date":"N/A","sig":""})
               for c in FRED_SERIES]
    ok = sum(1 for r in results if r["current"] != "N/A")
    log(f"FRED: {ok}/{len(results)} indicators fetched", "✅" if ok==len(results) else "⚠️")
    return results


# ============================================================
# STEP 2: AAII WEEKLY SENTIMENT SURVEY
# ============================================================
# AAII surveys ~160K retail investors weekly (published Thursdays).
# Contrarian indicator: bears > 50% = historically strong buy.
# Bull-Bear spread < -20% = extreme fear = classic mean reversion signal.
#
# KNOWN ISSUE: aaii.com blocks GitHub Actions runner IPs via Incapsula CDN.
# When blocked, dashboard shows link to check manually.
# Scrape still attempted -- may succeed occasionally if CDN allows it.
# AAII email subscription ("Investor Update") does NOT include the
# Bull/Bear/Neutral percentage data -- only the website has those numbers.
# ============================================================

def fetch_aaii_sentiment():
    print("\n📊 Fetching AAII Weekly Sentiment Survey (may be CDN-blocked)...")
    try:
        hdrs = {
            "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "DNT":             "1",
        }
        resp = requests.get("https://www.aaii.com/sentimentsurvey", headers=hdrs, timeout=15)
        text = resp.text

        if any(x in text for x in ["Incapsula incident","Request unsuccessful","_Incapsula_Resource"]):
            print("   ⚠️ AAII: Blocked by Incapsula CDN")
            print("   💡 Check manually Thursdays: aaii.com/sentimentsurvey")
            log("AAII: Blocked by Incapsula CDN -- check aaii.com manually on Thursdays","⚠️")
            return None

        soup  = BeautifulSoup(text,"html.parser")
        plain = soup.get_text()

        bullish = bearish = neutral = None
        patterns = [
            (r"[Bb]ullish[\s:]*(\d+\.?\d*)\s*%", r"[Bb]earish[\s:]*(\d+\.?\d*)\s*%", r"[Nn]eutral[\s:]*(\d+\.?\d*)\s*%"),
            (r"(\d+\.?\d*)\s*%\s*[Bb]ullish",    r"(\d+\.?\d*)\s*%\s*[Bb]earish",    r"(\d+\.?\d*)\s*%\s*[Nn]eutral"),
            (r"[Bb]ull[^\d]{0,20}(\d+\.?\d*)\s*%",r"[Bb]ear[^\d]{0,20}(\d+\.?\d*)\s*%",r"[Nn]eut[^\d]{0,20}(\d+\.?\d*)\s*%"),
        ]
        for pb,pbe,pn in patterns:
            if bullish is None:
                m=re.search(pb,plain); bullish=float(m.group(1)) if m else None
            if bearish is None:
                m=re.search(pbe,plain); bearish=float(m.group(1)) if m else None
            if neutral is None:
                m=re.search(pn,plain); neutral=float(m.group(1)) if m else None
            if all(v is not None for v in [bullish,bearish,neutral]): break

        if bullish is not None and bearish is not None:
            spread = round(bullish-bearish,1)
            if   spread<=-20: sig="⚠️ Extreme bearish -- strong contrarian buy historically"; col="#c81e1e"
            elif spread<=-10: sig="⚠️ Bearish -- pessimism elevated, watch for entries"; col="#e97316"
            elif spread<=10:  sig="→ Neutral -- no extreme reading"; col="#6b7280"
            elif spread<=20:  sig="🟡 Bullish -- mild optimism, be selective"; col="#059669"
            else:             sig="⚠️ Extreme bullish -- contrarian caution"; col="#1a56db"
            print(f"   ✅ AAII: Bull {bullish}% / Bear {bearish}% | Spread: {spread:+.1f}%")
            log(f"AAII: Bull {bullish}% Bear {bearish}% (spread {spread:+.1f}%)")
            return {"bullish":bullish,"bearish":bearish,"neutral":neutral,"spread":spread,"signal":sig,"color":col}
        else:
            print(f"   ⚠️ AAII: Page loaded but percentages not found")
            log("AAII: Page loaded, parse failed","⚠️")
            return None

    except Exception as e:
        print(f"   ❌ AAII failed: {e}")
        log(f"AAII: {str(e)[:60]}","❌")
        return None


# ============================================================
# STEP 3: CNN FEAR & GREED
# ============================================================
# Composite of 7 market indicators: market momentum, stock price
# strength, stock breadth, put/call ratio, junk bond demand,
# market volatility (VIX), safe haven demand.
# Score 0 = extreme fear (buying opportunity). 100 = extreme greed.
# Updates throughout the trading day.
# ============================================================

def fetch_fear_greed():
    print("\n😨 Fetching CNN Fear & Greed...")
    try:
        hdrs = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        fg   = requests.get("https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
                            headers=hdrs, timeout=10).json().get("fear_and_greed",{})
        score = round(float(fg.get("score",50)))

        if   score<=24: lbl="Extreme Fear"; col="#c81e1e"; sig="Historically strong buying opportunity for mean reversion"
        elif score<=44: lbl="Fear";         col="#e97316"; sig="Pessimism elevated -- watch for entry setups"
        elif score<=55: lbl="Neutral";      col="#6b7280"; sig="No strong directional sentiment signal"
        elif score<=74: lbl="Greed";        col="#059669"; sig="Optimism elevated -- exercise caution on new positions"
        else:           lbl="Extreme Greed";col="#1a56db"; sig="Overheated sentiment -- high mean reversion reversal risk"

        print(f"   ✅ Fear & Greed: {score}/100 ({lbl})")
        log(f"Fear & Greed: {score}/100 ({lbl})")
        return {
            "score":score, "label":lbl, "color":col, "signal":sig,
            "prev_close": round(float(fg.get("previous_close",  score))),
            "prev_week":  round(float(fg.get("previous_1_week", score))),
            "prev_month": round(float(fg.get("previous_1_month",score))),
            "prev_year":  round(float(fg.get("previous_1_year", score))),
        }
    except Exception as e:
        print(f"   ❌ Fear & Greed failed: {e}")
        log(f"Fear & Greed: {str(e)[:60]}","❌")
        return {"score":50,"label":"Unavailable","color":"#6b7280","signal":"Unavailable",
                "prev_close":"N/A","prev_week":"N/A","prev_month":"N/A","prev_year":"N/A"}


# ============================================================
# STEP 4: MARKET DATA (Yahoo Finance v8)
# ============================================================
# Uses Yahoo Finance v8/chart endpoint -- same one used for SPX/VIX.
# SPX, RUT, VIX: core indices
# URTH: iShares MSCI World ETF (~70% US). PE ratio = global valuation proxy.
#   Current PE ~23x (Sep 2026). Compares to US CAPE ~41x (different methodologies).
# EFA: iShares MSCI EAFE ETF (Europe/Australia/Japan -- explicitly EXCLUDES US).
#   Current PE ~14-15x. The real US vs non-US valuation comparison.
#   US at 41x CAPE vs ex-US at 14x trailing PE -- gap hasn't been this wide since 2000.
#   This matters: many AM screen picks are intl ADRs (EQNR, PBR, SNY, NVO, SHEL).
#
# VIX thresholds (match Chrome extension background.js exactly):
#   CALM(<15) NORMAL(<20) CAUTIOUS(<25) FEARFUL(<30) PANIC(>=30)
# ============================================================

def _classify_vix(v):
    if v<15: return "CALM","#059669"
    if v<20: return "NORMAL","#6b7280"
    if v<25: return "CAUTIOUS","#e97316"
    if v<30: return "FEARFUL","#c81e1e"
    return "PANIC","#7f1d1d"

def _classify_idx(c):
    if c>1.0:  return "RALLY","#059669"
    if c>0.1:  return "UP","#86c440"
    if c>-0.1: return "FLAT","#6b7280"
    if c>-1.0: return "DOWN","#e97316"
    return "SELLOFF","#c81e1e"

def _vix_sig(v):
    if v>=30: return "⚠️ Panic -- forced selling, mean reversion entries emerging"
    if v>=25: return "⚠️ Elevated fear -- watch for entry points"
    if v>=20: return "→ Slightly elevated -- no broad panic signal"
    if v>=15: return "→ Normal -- market calm, no stress signal"
    return "✅ Calm · low fear · complacency = less opportunity for value investors"

def _yq(ticker):
    """Fetch price, prev close, % change, market state from Yahoo Finance v8."""
    url  = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2d"
    hdrs = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)","Accept":"application/json"}
    resp = requests.get(url, headers=hdrs, timeout=12)
    meta = resp.json()["chart"]["result"][0]["meta"]
    p    = float(meta.get("regularMarketPrice",0))
    pv   = float(meta.get("previousClose",p))
    chg  = ((p-pv)/pv*100) if pv else 0
    return p, pv, chg, meta.get("marketState","UNKNOWN")

def _yq_pe(ticker):
    """Fetch trailing PE ratio from Yahoo Finance quoteSummary (for URTH, EFA)."""
    try:
        url  = f"https://query1.finance.yahoo.com/v10/finance/quoteSummary/{ticker}?modules=summaryDetail"
        hdrs = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)","Accept":"application/json"}
        resp = requests.get(url, headers=hdrs, timeout=12)
        data = resp.json()
        result = data.get("quoteSummary",{}).get("result",[])
        if result:
            pe = result[0].get("summaryDetail",{}).get("trailingPE",{})
            if isinstance(pe, dict): return pe.get("raw",None)
            return pe if pe else None
    except:
        pass
    return None

def fetch_market_indicators():
    """Fetch SPX, RUT, VIX + URTH and EFA PE ratios in parallel."""
    print("\n📊 Fetching Market Performance (SPX, RUT, VIX, URTH PE, EFA PE)...")
    res = {
        "vix":{"value":"N/A","label":"N/A","color":"#6b7280","signal":"","prev":"N/A"},
        "spx":{"value":"N/A","chg":"N/A","label":"N/A","color":"#6b7280","prev":"N/A"},
        "rut":{"value":"N/A","chg":"N/A","label":"N/A","color":"#6b7280","prev":"N/A"},
        "urth_pe":None, "efa_pe":None,
        "market_state":"UNKNOWN","market_status_label":"","pulse":"",
    }
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
            fv    = ex.submit(_yq,    "%5EVIX")
            fs    = ex.submit(_yq,    "%5EGSPC")
            fr    = ex.submit(_yq,    "%5ERUT")
            furth = ex.submit(_yq_pe, "URTH")
            fefa  = ex.submit(_yq_pe, "EFA")
            vp,vpr,_,vs  = fv.result(timeout=15)
            sp,spr,sc,ss = fs.result(timeout=15)
            rp,rpr,rc,rs = fr.result(timeout=15)
            urth_pe      = furth.result(timeout=15)
            efa_pe       = fefa.result(timeout=15)

        res["urth_pe"] = round(urth_pe,1) if urth_pe else None
        res["efa_pe"]  = round(efa_pe,1)  if efa_pe  else None

        state_map    = {"REGULAR":"OPEN","PRE":"PRE","POST":"POST","CLOSED":"CLOSED"}
        mkt_state    = state_map.get(ss,"OPEN" if abs(sc)>0.005 else "CLOSED")
        status_label = {"OPEN":"","PRE":"Pre-Market","POST":"After-Hours","CLOSED":"Last Close"}.get(mkt_state,"")
        res["market_state"] = mkt_state; res["market_status_label"] = status_label

        vl,vc  = _classify_vix(vp)
        sl,sc2 = _classify_idx(sc)
        rl,rc2 = _classify_idx(rc)

        if mkt_state=="PRE":
            scs="Pre-Market"; rcs="Pre-Market"
            sl="PRE-MKT"; sc2="#6366f1"; rl="PRE-MKT"; rc2="#6366f1"
        elif mkt_state in("POST","CLOSED"):
            scs="Last Close"; rcs="Last Close"
            sl="CLOSED"; sc2="#9ca3af"; rl="CLOSED"; rc2="#9ca3af"
        else:
            scs=f"{sc:+.2f}%"; rcs=f"{rc:+.2f}%"

        res["vix"] = {"value":f"{vp:.2f}","label":vl,"color":vc,"signal":_vix_sig(vp),"prev":f"{vpr:.2f}"}
        res["spx"] = {"value":f"{sp:,.0f}","chg":scs,"label":sl,"color":sc2,"prev":f"{spr:,.0f}"}
        res["rut"] = {"value":f"{rp:,.0f}","chg":rcs,"label":rl,"color":rc2,"prev":f"{rpr:,.0f}"}

        if mkt_state=="OPEN":
            if vp>=30 or sl=="SELLOFF": tone="broad stress -- mean reversion entries emerging"
            elif sl in("UP","RALLY") and rl in("UP","RALLY"): tone="broad strength -- be selective"
            elif sl=="FLAT": tone="indecisive -- focus on individual catalysts"
            else: tone="mixed -- stay selective"
            res["pulse"] = f"S&P {scs} ({sl}) · Russell {rcs} ({rl}) · VIX {vp:.1f} ({vl}) -- {tone}"
        elif mkt_state=="PRE":
            res["pulse"] = f"Pre-Market · S&P last close {sp:,.0f} · Russell {rp:,.0f} · VIX {vp:.1f} ({vl})"
        else:
            res["pulse"] = f"S&P {sp:,.0f} · Russell {rp:,.0f} · VIX {vp:.1f} ({vl})"

        urth_str = f"URTH PE: {urth_pe:.1f}x" if urth_pe else "URTH PE: N/A"
        efa_str  = f"EFA PE: {efa_pe:.1f}x"   if efa_pe  else "EFA PE: N/A"
        print(f"   ✅ S&P 500: {sp:,.0f} ({scs} {sl})")
        print(f"   ✅ Russell: {rp:,.0f} ({rcs} {rl})")
        print(f"   ✅ VIX: {vp:.2f} ({vl}) | State: {mkt_state}")
        print(f"   ✅ {urth_str} | {efa_str}")
        log(f"Market: SPX {sp:,.0f} RUT {rp:,.0f} VIX {vp:.1f} | {urth_str} | {efa_str} | {mkt_state}")

    except Exception as e:
        print(f"   ❌ Market indicators failed: {e}")
        log(f"Market indicators: {str(e)[:60]}","❌")
        res["pulse"] = "Market data unavailable."
    return res

# ============================================================
# STEP 5: MHS -- MACRO HEAT SCORE (replaces old "MRI" acronym)
# ============================================================
# MHS = Macro Heat Score. INVERTED 0-100 scale.
# LOWER score = better mean reversion opportunity (fear/dislocation).
# HIGHER score = overheated/complacent (avoid new positions).
#
# Components and their max possible adjustments:
#   Base:              +50 (neutral starting point)
#   Core PCE:         -10 to +20 (primary inflation gauge)
#   VIX:              -20 to +10 (panic gauge -- high VIX = opportunity)
#   Fear & Greed:     -20 to +20 (broad sentiment composite)
#   HY Credit:        -15 to +12 (credit stress / complacency)
#   Yield Curve:       -8 to +4  (recession indicator)
#   Fed Posture:       -6 to +8  (rate cycle direction)
#   Shiller CAPE:     -15 to +15 (structural valuation -- NEW)
#   Gold Signal:       -3 to +3  (stealth fear vs complacency -- NEW)
#   AAII (if avail):  -12 to +12 (retail sentiment contrarian)
#
# At Sep 2026 readings: CAPE +15 pushes score from ~81 to ~96.
# This reflects that structural overvaluation (CAPE 41 = 98th pctile)
# adds genuine risk ON TOP of the sentiment/momentum overheating.
# ============================================================

def compute_mhs(fred_data, fg_data, mkt_data, aaii_data):
    raw       = 50
    breakdown = []

    def get_fred(lbl):
        r = next((x for x in fred_data if x["label"]==lbl), None)
        if not r or r["current"]=="N/A": return None,None
        try: return float(re.sub(r"[%$,]","",r["current"])), r["trend"]
        except: return None,None

    # Core PCE: primary inflation signal
    cp, cpt = get_fred("Core PCE")
    if cp is not None:
        if   cp>3.5: adj=+15; note=f"Core PCE {cp:.1f}% -- well above 2% target"
        elif cp>3.0: adj=+10; note=f"Core PCE {cp:.1f}% -- above 2% target"
        elif cp>2.5: adj=+5;  note=f"Core PCE {cp:.1f}% -- mildly elevated"
        elif cp>2.0: adj=+2;  note=f"Core PCE {cp:.1f}% -- near target"
        else:        adj=-5;  note=f"Core PCE {cp:.1f}% -- at/below 2% target"
        if cpt=="▲": adj+=5;  note+=" & rising"
        elif cpt=="▼": adj-=5; note+=" & cooling"
        raw+=adj; breakdown.append(f"Inflation {adj:+d} ({note})")

    # VIX: panic = opportunity (high VIX LOWERS score)
    try:
        vix = float(mkt_data["vix"]["value"])
        if   vix>=40: adj=-20; note=f"VIX {vix:.1f} -- panic/forced selling"
        elif vix>=30: adj=-15; note=f"VIX {vix:.1f} -- fear"
        elif vix>=25: adj=-8;  note=f"VIX {vix:.1f} -- cautious"
        elif vix>=20: adj=-3;  note=f"VIX {vix:.1f} -- slightly elevated"
        elif vix>=15: adj=+5;  note=f"VIX {vix:.1f} -- calm/normal"
        else:         adj=+10; note=f"VIX {vix:.1f} -- complacent"
        raw+=adj; breakdown.append(f"VIX {adj:+d} ({note})")
    except: pass

    # Fear & Greed: extreme fear LOWERS score (opportunity)
    try:
        fg = int(fg_data.get("score",50))
        if   fg<=20: adj=-20; note=f"F&G {fg} -- extreme fear"
        elif fg<=35: adj=-12; note=f"F&G {fg} -- fear"
        elif fg<=50: adj=-4;  note=f"F&G {fg} -- mild fear"
        elif fg<=65: adj=+4;  note=f"F&G {fg} -- neutral/mild greed"
        elif fg<=80: adj=+12; note=f"F&G {fg} -- greed"
        else:        adj=+20; note=f"F&G {fg} -- extreme greed"
        raw+=adj; breakdown.append(f"Fear&Greed {adj:+d} ({note})")
    except: pass

    # HY Credit Spread: wide = dislocation = LOWERS score
    hy,_ = get_fred("HY Credit Spread")
    if hy is not None:
        if   hy>=8.0: adj=-15; note=f"HY {hy:.2f}% -- very wide (credit stress)"
        elif hy>=6.0: adj=-10; note=f"HY {hy:.2f}% -- wide"
        elif hy>=4.5: adj=-4;  note=f"HY {hy:.2f}% -- elevated"
        elif hy<=2.5: adj=+12; note=f"HY {hy:.2f}% -- very tight (complacent)"
        elif hy<=3.5: adj=+6;  note=f"HY {hy:.2f}% -- tight"
        else:         adj=+2;  note=f"HY {hy:.2f}% -- normal"
        raw+=adj; breakdown.append(f"Credit {adj:+d} ({note})")

    # Yield Curve
    cv,_ = get_fred("Yield Curve (10Y-2Y)")
    if cv is not None:
        if   cv<-0.5: adj=-8; note=f"Deeply inverted {cv:.2f}%"
        elif cv<0.0:  adj=-4; note=f"Inverted {cv:.2f}%"
        elif cv<0.3:  adj=+2; note=f"Nearly flat {cv:.2f}%"
        elif cv>=0.5: adj=+4; note=f"Steep {cv:.2f}%"
        else:         adj=+2; note=f"Positive {cv:.2f}%"
        raw+=adj; breakdown.append(f"Yield Curve {adj:+d} ({note})")

    # Fed Posture
    fed, fedt = get_fred("Fed Funds Rate")
    if fed is not None:
        if   fedt=="▼": adj=-6; note=f"Fed cutting at {fed:.2f}%"
        elif fedt=="▲": adj=+8; note=f"Fed hiking at {fed:.2f}%"
        elif fed>=5.0:  adj=+6; note=f"Fed restrictive {fed:.2f}%"
        elif fed<=3.0:  adj=-4; note=f"Fed accommodative {fed:.2f}%"
        else:           adj=+2; note=f"Fed on hold {fed:.2f}%"
        raw+=adj; breakdown.append(f"Fed {adj:+d} ({note})")

    # Shiller CAPE: expensive market RAISES score (NEW)
    # At CAPE 41 (98th pctile), structural overvaluation adds meaningful risk.
    # Even if VIX spikes, buying into CAPE 41 is riskier than CAPE 15.
    cape,_ = get_fred("Shiller CAPE (US)")
    if cape is not None:
        if   cape>=40: adj=+15; note=f"CAPE {cape:.1f}x -- extreme (98th pctile, only dot-com was higher)"
        elif cape>=35: adj=+12; note=f"CAPE {cape:.1f}x -- very high (>2x hist avg 17x)"
        elif cape>=30: adj=+8;  note=f"CAPE {cape:.1f}x -- elevated"
        elif cape>=25: adj=+5;  note=f"CAPE {cape:.1f}x -- moderately high"
        elif cape>=20: adj=0;   note=f"CAPE {cape:.1f}x -- fair value range"
        elif cape>=15: adj=-5;  note=f"CAPE {cape:.1f}x -- below avg (opportunity)"
        else:          adj=-15; note=f"CAPE {cape:.1f}x -- deep value territory"
        raw+=adj; breakdown.append(f"CAPE Valuation {adj:+d} ({note})")

    # Gold Signal: gold up + low VIX = stealth fear (RAISES score slightly)
    # When smart money hedges quietly (gold surges, VIX stays calm),
    # that disconnect is a warning that complacency is deeper than it appears.
    gold, gold_trend = get_fred("Gold Price")
    try:
        vix_now = float(mkt_data["vix"]["value"])
        if gold is not None and gold_trend=="▲" and vix_now<20:
            adj=+3; note="Gold rising with low VIX -- stealth fear/inflation signal"
            raw+=adj; breakdown.append(f"Gold Signal {adj:+d} ({note})")
        elif gold is not None and gold_trend=="▼" and vix_now>=25:
            adj=-3; note="Gold falling with high VIX -- fear already priced in"
            raw+=adj; breakdown.append(f"Gold Signal {adj:+d} ({note})")
    except: pass

    # AAII (when available)
    if aaii_data:
        spread = aaii_data.get("spread",0)
        if   spread<=-25: adj=-12; note=f"AAII {spread:+.1f}% extreme bearish"
        elif spread<=-15: adj=-8;  note=f"AAII {spread:+.1f}% bearish"
        elif spread<=-5:  adj=-3;  note=f"AAII {spread:+.1f}% mildly bearish"
        elif spread<=10:  adj=0;   note=f"AAII {spread:+.1f}% neutral"
        elif spread<=20:  adj=+6;  note=f"AAII {spread:+.1f}% bullish"
        else:             adj=+12; note=f"AAII {spread:+.1f}% extreme bullish"
        raw+=adj; breakdown.append(f"AAII {adj:+d} ({note})")

    score = max(0, min(100, round(raw)))

    if   score<=33: lbl="🟢 DEPLOY";     col="#057a55"; action="Aggressive deployment. Macro confirms STRONG BUY. Full position pace."
    elif score<=65: lbl="🟠 SELECTIVE";  col="#b45309"; action="Best setups only. Left Leg <4, MoS >25%. Measured pace. Keep 25%+ cash."
    else:           lbl="⛔ OVERHEATED"; col="#c81e1e"; action="Build cash. Trim winners. No new positions unless Left Leg 0-2 + MoS >30% + extraordinary setup."

    print(f"\n📊 MHS (Macro Heat Score): {score}/100 ({lbl})")
    for b in breakdown: print(f"   {b}")
    log(f"MHS: {score}/100 ({lbl})")
    return {"score":score,"label":lbl,"color":col,"breakdown":breakdown,"action":action}


# ============================================================
# STEP 6: DATAROMA SUPERINVESTOR 13F BUYS
# ============================================================
# 13F SEC filing: institutions >$100M AUM disclose equity holdings
# quarterly. ~45 day lag after quarter end. Dataroma aggregates.
# "Buys" = number of tracked superinvestors who bought this quarter.
#
# CACHE STRATEGY:
# fetch_cache.py runs FIRST in the GitHub Actions workflow and writes
# dataroma_cache.json. main.py reads that file (20hr TTL).
# Prevents HTTP 409 rate-limit errors on repeat manual runs.
# Falls back to live fetch if cache is missing or stale.
# ============================================================

def fetch_superinvestor_buys():
    import json as _json
    CACHE_FILE    = "dataroma_cache.json"
    CACHE_TTL_HRS = 20

    print("\n👑 Fetching Dataroma superinvestor quarterly buys...")

    try:
        with open(CACHE_FILE,"r") as f:
            cached = _json.load(f)
        fetched_at = datetime.fromisoformat(cached.get("fetched_at","2000-01-01T00:00:00"))
        age_hours  = (datetime.now()-fetched_at).total_seconds()/3600
        if age_hours < CACHE_TTL_HRS and cached.get("buys"):
            buys = cached["buys"]
            top3 = sorted(buys.items(),key=lambda x:-x[1])[:3]
            print(f"   ✅ Dataroma (cache {age_hours:.1f}h old): {len(buys)} stocks | Top: {top3}")
            log(f"Dataroma 13F: {len(buys)} stocks (cache {age_hours:.1f}h old)")
            return buys
        else:
            print(f"   Cache stale ({age_hours:.1f}h > {CACHE_TTL_HRS}h) -- fetching live")
    except FileNotFoundError:
        print("   No cache file -- fetching live")
    except Exception as e:
        print(f"   Cache error: {e} -- fetching live")

    try:
        url  = "https://www.dataroma.com/m/g/portfolio_b.php?q=q"
        hdrs = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept":"text/html,application/xhtml+xml","Referer":"https://www.dataroma.com/"}
        resp = requests.get(url,headers=hdrs,timeout=15)
        print(f"   Status: {resp.status_code}")
        if resp.status_code!=200: raise Exception(f"HTTP {resp.status_code}")

        soup  = BeautifulSoup(resp.text,"html.parser")
        buys  = {}
        table = soup.find("table",{"id":"grid"})
        if not table:
            for t in soup.find_all("table"):
                if len(t.find_all("tr"))>5: table=t; break

        if table:
            rows    = table.find_all("tr")
            headers = [th.get_text(strip=True) for th in rows[0].find_all(["th","td"])]
            print(f"   Columns: {headers}")
            sym_idx = next((i for i,h in enumerate(headers) if any(k in h for k in ["Symbol","Ticker"])),0)
            buy_idx = next((i for i,h in enumerate(headers) if any(k in h for k in ["Buy","Count"])),3)
            print(f"   Using: Symbol col={sym_idx}, Buys col={buy_idx}")
            for row in rows[1:]:
                cells = row.find_all("td")
                if len(cells)>max(sym_idx,buy_idx):
                    ticker = re.sub(r"[^A-Z.]","",cells[sym_idx].get_text(strip=True).upper())[:6]
                    if not ticker: continue
                    try:    count=int(cells[buy_idx].get_text(strip=True).replace(",",""))
                    except: count=1
                    buys[ticker]=count

        top3 = sorted(buys.items(),key=lambda x:-x[1])[:3]
        print(f"   ✅ Dataroma: {len(buys)} stocks (live) | Top: {top3}")
        log(f"Dataroma 13F: {len(buys)} stocks (live fetch)")
        return buys
    except Exception as e:
        print(f"   ❌ Dataroma failed: {e}")
        log(f"Dataroma: {str(e)[:60]}","❌")
        return {}


# ============================================================
# STEP 7: MAGIC FORMULA -- ASP.NET AUTHENTICATED SCRAPE
# ============================================================
# Greenblatt ranks stocks by Earnings Yield + Return on Capital.
# Best stocks = cheap AND high quality. Min $2B mktcap, top 30.
#
# ASP.NET anti-forgery token (CSRF protection) flow:
# 1. GET login page -> extract __RequestVerificationToken (random each load)
# 2. POST credentials + token -> session cookie established
# 3. GET screener page -> extract NEW token (each page has its own)
# 4. POST screener form + token -> results HTML table
# requests.Session() carries cookies automatically between steps.
# ============================================================

def fetch_magic_formula():
    print("\n🔮 Fetching Magic Formula top 30 stocks...")
    try:
        sess = requests.Session()
        sess.headers.update({
            "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })
        login_url   = "https://www.magicformulainvesting.com/Account/LogOn"
        resp        = sess.get(login_url,timeout=15)
        soup        = BeautifulSoup(resp.text,"html.parser")
        token_input = soup.find("input",{"name":"__RequestVerificationToken"})
        if not token_input: raise Exception("Login token not found -- site may have changed")
        token = token_input.get("value","")
        print(f"   Got anti-forgery token: {token[:20]}...")

        resp = sess.post(login_url,data={
            "Email":MFI_EMAIL,"Password":MFI_PASSWORD,
            "__RequestVerificationToken":token,
        },timeout=15)
        if any(kw in resp.text for kw in ["Welcome","LogOff","Log Off","Screening"]):
            print("   ✅ Logged into Magic Formula")
        elif any(kw in resp.text.lower() for kw in ["invalid","incorrect"]):
            raise Exception("Login failed -- check MFI_EMAIL / MFI_PASSWORD secrets")
        else:
            print(f"   Login submitted (status {resp.status_code})")

        screener_url = "https://www.magicformulainvesting.com/Screening/StockScreening"
        resp         = sess.get(screener_url,timeout=15)
        soup         = BeautifulSoup(resp.text,"html.parser")
        st_input     = soup.find("input",{"name":"__RequestVerificationToken"})
        if not st_input: raise Exception("Screener token not found")
        screen_token = st_input.get("value","")

        resp    = sess.post(screener_url,data={
            "MinimumMarketCap":"2000","NumberOfStocks":"30",
            "__RequestVerificationToken":screen_token,
        },timeout=20)
        soup    = BeautifulSoup(resp.text,"html.parser")
        tables  = soup.find_all("table")
        print(f"   Tables found: {len(tables)}")

        tickers    = []
        ticker_col = None
        for t in tables:
            rows = t.find_all("tr")
            if len(rows)<3: continue
            hdrs = [th.get_text(strip=True) for th in rows[0].find_all(["th","td"])]
            print(f"   Table headers: {hdrs}")
            for ci,h in enumerate(hdrs):
                if any(k in h.lower() for k in ["ticker","symbol"]):
                    ticker_col=ci; print(f"   Ticker column at index {ci}: '{h}'"); break
            if ticker_col is None and len(rows)>1:
                for ci,cell in enumerate(rows[1].find_all("td")):
                    txt=cell.get_text(strip=True).upper()
                    if re.match(r"^[A-Z]{1,5}$",txt):
                        ticker_col=ci; print(f"   Ticker auto-detected at col {ci}: '{txt}'"); break
            if ticker_col is not None:
                for row in rows[1:]:
                    cells=row.find_all("td")
                    if ticker_col<len(cells):
                        clean=re.sub(r"[^A-Z.]","",cells[ticker_col].get_text(strip=True).upper())
                        if re.match(r"^[A-Z]{1,5}$",clean): tickers.append(clean)
                break

        tickers=list(dict.fromkeys(tickers))
        print(f"   ✅ Magic Formula: {len(tickers)} tickers")
        if tickers: print(f"   Sample: {tickers[:8]}")
        log(f"Magic Formula: {len(tickers)} stocks")
        return set(tickers)
    except Exception as e:
        print(f"   ❌ Magic Formula failed: {e}")
        log(f"Magic Formula: {str(e)[:60]}","❌")
        return set()


# ============================================================
# STEP 8: ACQUIRER'S MULTIPLE -- RCP LOGIN + HTML TABLE
# ============================================================
# Carlisle AM = EV / Operating Earnings. Lower = cheaper.
# Free account: Large Cap 1000 screener only. Updates daily after close.
#
# Login uses Restrict Content Pro (RCP) WordPress plugin.
# Confirmed from Chrome DevTools Elements inspection:
#   form id="rcp_login_form" action="https://acquirersmultiple.com/login/" method="POST"
#   name="rcp_user_login" -- email/username field
#   name="rcp_user_pass"  -- password field
#   name="rcp_action"     -- "login" (hidden)
#   name="rcp_redirect"   -- redirect URL (hidden)
#   name="rcp_login_nonce"-- fresh token each page load (must extract)
#
# Table data confirmed server-side HTML (Chrome DevTools Network tab showed
# NO XHR/Fetch calls for table data). DataTables renders existing HTML.
# ============================================================

def fetch_acquirers_multiple():
    print("\n📐 Fetching Acquirer's Multiple large-cap stocks...")
    try:
        sess = requests.Session()
        sess.headers.update({
            "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language":"en-US,en;q=0.9",
        })
        r0    = sess.get("https://acquirersmultiple.com/login/",timeout=15)
        soup0 = BeautifulSoup(r0.text,"html.parser")
        print(f"   Login page: {r0.status_code} | Cookies: {len(sess.cookies)}")

        nonce_tag = soup0.find("input",{"name":"rcp_login_nonce"})
        nonce     = nonce_tag["value"] if nonce_tag else ""
        print(f"   Nonce: {nonce[:12]}..." if nonce else "   ⚠️ No nonce found -- login may fail")

        r1 = sess.post("https://acquirersmultiple.com/login/",data={
            "rcp_user_login": AM_EMAIL,"rcp_user_pass": AM_PASSWORD,
            "rcp_action":"login","rcp_redirect":"https://acquirersmultiple.com/login/",
            "rcp_login_nonce":nonce,
        },timeout=15,allow_redirects=True)
        print(f"   Login POST: {r1.status_code} | URL: {r1.url}")

        logged_in = "logout" in r1.text.lower() or "log-out" in r1.text.lower()
        print(f"   Logged in: {logged_in}")
        if not logged_in:
            soup_err = BeautifulSoup(r1.text,"html.parser")
            err = soup_err.find(class_=re.compile(r"rcp.error|rcp.notice|error"))
            if err: print(f"   Error: {err.get_text(strip=True)[:120]}")

        r2    = sess.get("https://acquirersmultiple.com/screener/large-cap/",timeout=20)
        soup2 = BeautifulSoup(r2.text,"html.parser")
        title = soup2.find("title")
        print(f"   Screener: {r2.status_code} | Title: {title.get_text(strip=True)[:50] if title else 'none'}")

        tickers = []
        for t in soup2.find_all("table"):
            rows = t.find_all("tr")
            if len(rows)<3: continue
            hdrs = [c.get_text(strip=True) for c in rows[0].find_all(["th","td"])]
            print(f"   Table: {len(rows)} rows | headers: {hdrs[:4]}")
            if hdrs and hdrs[0].strip().lower()=="ticker":
                for row in rows[1:]:
                    cells=row.find_all("td")
                    if cells:
                        ticker=re.sub(r"[^A-Z.]","",cells[0].get_text(strip=True).upper())
                        if re.match(r"^[A-Z]{1,5}$",ticker): tickers.append(ticker)
                break

        tickers=list(dict.fromkeys(tickers))
        print(f"   ✅ Acquirer's Multiple: {len(tickers)} tickers")
        if tickers: print(f"   Sample: {tickers[:8]}")
        log(f"Acquirer's Multiple: {len(tickers)} stocks")
        return set(tickers)
    except Exception as e:
        print(f"   ❌ Acquirer's Multiple failed: {e}")
        log(f"Acquirer's Multiple: {str(e)[:60]}","❌")
        return set()


# ============================================================
# STEPS 9-12: WEB SCRAPE + EMAIL (IMAP)
# ============================================================

def scrape_edward_jones():
    print("\n🔍 Scraping Edward Jones...")
    url  = "https://www.edwardjones.com/us-en/market-news-insights/stock-market-news/daily-market-recap"
    hdrs = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.get(url,headers=hdrs,timeout=15)
        print(f"   Status: {resp.status_code}")
        soup = BeautifulSoup(resp.text,"html.parser")
        for tag in soup(["script","style","nav","footer","header"]): tag.decompose()
        lines = [l.strip() for l in soup.get_text("\n",strip=True).splitlines() if l.strip()]
        text  = "\n".join(lines[:120])
        print(f"   ✅ Edward Jones: {len(text)} chars")
        log(f"Edward Jones: {len(text)} chars")
        return text
    except Exception as e:
        print(f"   ❌ Edward Jones failed: {e}")
        log(f"Edward Jones: {str(e)[:60]}","❌")
        return "Edward Jones data unavailable today."


def _fetch_email(sender, label, char_limit=2500):
    """
    Fetch latest email from a specific sender via Yahoo IMAP SSL (port 993).
    Prefers text/plain MIME part; falls back to HTML parsed by BeautifulSoup.
    Falls back to domain search if exact FROM match returns no results.
    Confirmed senders:
      CNBC: morningsquawk@response.cnbc.com
      Yahoo: finance-morning-brief@newsletters.yahoo.net
      McClellan: admin@mcoscillator.com
    """
    print(f"\n📬 Fetching {label}...")
    try:
        mail   = imaplib.IMAP4_SSL("imap.mail.yahoo.com",993)
        mail.login(YAHOO_EMAIL,YAHOO_PASSWORD)
        mail.select("INBOX")
        status,messages = mail.search(None,f'(FROM "{sender}")')
        if status!="OK" or not messages[0]:
            domain = sender.split("@")[-1] if "@" in sender else sender
            status,messages = mail.search(None,f'(FROM "{domain}")')
        if status!="OK" or not messages[0]:
            print(f"   ❌ No {label} emails found"); mail.logout()
            log(f"{label}: no emails found","❌")
            return f"{label} not found today."

        latest = messages[0].split()[-1]
        _,hdr  = mail.fetch(latest,"(BODY[HEADER.FIELDS (FROM SUBJECT DATE)])")
        if hdr and hdr[0] and hdr[0][1]:
            for line in hdr[0][1].decode("utf-8",errors="ignore").strip().splitlines()[:4]:
                if line.strip(): print(f"   {line.strip()}")

        _,msg_data = mail.fetch(latest,"(RFC822)")
        msg  = email.message_from_bytes(msg_data[0][1])
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type()=="text/plain":
                    body=part.get_payload(decode=True).decode("utf-8",errors="ignore"); break
        if not body:
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type()=="text/html":
                        body=BeautifulSoup(part.get_payload(decode=True).decode("utf-8",errors="ignore"),
                                           "html.parser").get_text("\n",strip=True); break
            else:
                body=BeautifulSoup(msg.get_payload(decode=True).decode("utf-8",errors="ignore"),
                                   "html.parser").get_text("\n",strip=True)
        mail.logout()
        body=body[:char_limit].strip()
        print(f"   ✅ {label}: {len(body)} chars")
        log(f"{label}: {len(body)} chars")
        return body
    except Exception as e:
        print(f"   ❌ {label} IMAP failed: {e}")
        log(f"{label}: {str(e)[:60]}","❌")
        return f"{label} unavailable today."


def fetch_cnbc_email():
    return _fetch_email("morningsquawk@response.cnbc.com","CNBC Morning Squawk")

def fetch_yahoo_morning_brief():
    return _fetch_email("finance-morning-brief@newsletters.yahoo.net","Yahoo Morning Brief",char_limit=2000)

def fetch_mcoscillator_email():
    return _fetch_email("admin@mcoscillator.com","McClellan Oscillator",char_limit=1500)


# ============================================================
# STEP 13: AI SYNTHESIS -- MULTI-MODEL FALLBACK CHAIN
# ============================================================
# Chain (single attempt each, fail-fast to preserve quota):
#   1. gemini-3.6-flash  -- free tier, 20 RPD (requests per day)
#      RPD quota resets midnight UTC = 6 PM MT summer.
#      Development testing can exhaust the daily quota.
#   2. gemini-1.5-flash  -- free tier, SEPARATE quota pool from 3.6
#   3. claude-haiku-4-5  -- Anthropic paid API
#      Cost: ~$0.003/run (input ~2000 tokens + output ~400 tokens)
#      Input: $0.80/M tokens = ~$0.0016 for your prompt
#      Output: $4.00/M tokens = ~$0.0016 for the briefing
#      22 runs/month worst case: ~$0.07/month -- trivially small
#      max_tokens=1000 caps OUTPUT ONLY -- your input can be 5000 tokens
#      Haiku does NOT browse the web. It only reads what you send it.
#      Haiku usage is ALWAYS shown in run log with cost estimate.
#   4. Structured text fallback -- always works, no AI narrative
#
# Why Haiku is right for this task:
#   Your data collection is already done. Haiku just needs to convert
#   structured data into concise, well-organized prose bullets.
#   That is exactly what small models excel at -- fast synthesis of
#   provided context. No web browsing needed.
# ============================================================

def _call_gemini(prompt, model):
    """Call Google Gemini API via the official SDK."""
    client = genai.Client(api_key=GEMINI_API_KEY)
    return client.interactions.create(model=model, input=prompt).output_text


def _call_haiku(prompt):
    """
    Call Anthropic Claude Haiku via the Messages API.
    Primary path: anthropic library (pip install anthropic).
    Fallback path: direct HTTP POST via requests (already imported).
    max_tokens=1000 caps the output length, NOT the input.
    """
    if not ANTHROPIC_API_KEY:
        raise Exception("ANTHROPIC_API_KEY secret not set in GitHub repo")

    try:
        import anthropic
        client  = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model      = "claude-haiku-4-5",
            max_tokens = 1000,
            messages   = [{"role":"user","content":prompt}],
        )
        return message.content[0].text

    except ImportError:
        # anthropic library not installed -- direct HTTP fallback
        print("   ℹ️ anthropic library not found -- using direct HTTP to Anthropic API")
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":         ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            json={
                "model":      "claude-haiku-4-5",
                "max_tokens": 1000,
                "messages":   [{"role":"user","content":prompt}],
            },
            timeout=90,
        )
        if resp.status_code != 200:
            raise Exception(f"Anthropic API error {resp.status_code}: {resp.text[:200]}")
        return resp.json()["content"][0]["text"]


def synthesize_with_ai(ej_text, cnbc_text, yahoo_text, mcoscillator_text,
                       fred_data, fg_data, mkt_data, mhs,
                       si_tickers, mf_tickers, am_tickers, aaii_data):
    print("\n🤖 Sending to AI synthesis...")

    fred_summary = "\n".join([
        f"- {r['label']}: {r['current']} (3mo:{r['mo3']} 12mo:{r['mo12']} trend:{r['trend']})"
        for r in fred_data if r["current"]!="N/A"
    ])

    all_tickers = sorted(set(si_tickers.keys()) | mf_tickers | am_tickers)
    overlap     = []
    for t in all_tickers:
        tags = []
        if si_tickers.get(t,0)>0: tags.append(f"{si_tickers[t]}SI")
        if t in mf_tickers: tags.append("MF")
        if t in am_tickers: tags.append("AM")
        if len(tags)>=2: overlap.append(f"{t}({','.join(tags)})")

    aaii_str = ""
    if aaii_data:
        aaii_str = f"AAII: Bull {aaii_data['bullish']}% Bear {aaii_data['bearish']}% Spread {aaii_data['spread']:+.1f}%"

    cape_val = next((r["current"] for r in fred_data if r["label"]=="Shiller CAPE (US)"),"N/A")
    urth_str = f"URTH(MSCIWorld incl US) PE: {mkt_data.get('urth_pe','N/A')}x"
    efa_str  = f"EFA(MSCI EAFE ex-US) PE: {mkt_data.get('efa_pe','N/A')}x"

    prompt = f"""You are a sharp financial analyst writing a morning briefing for a
deep-value mean reversion investor (Greenblatt, Carlisle, Howard Marks, Terry Smith,
Burry, Pabrai style). US-focused but holds international ADRs. Long-term holder.

STRICT OUTPUT FORMAT -- use EXACTLY these 5 headers, nothing else:
MARKET AND MACRO
EARNINGS AND EVENTS
WHAT TO WATCH
AI FUN FACT
AI LEARNING

RULES:
- MARKET AND MACRO: 4-5 bullets -- key market moves + macro conditions
- EARNINGS AND EVENTS: 3-4 bullets -- specific dates/releases from any source
- WHAT TO WATCH: 3-4 bullets -- mean reversion setups, mention high-conviction tickers
- AI FUN FACT: 1 surprising fact about AI, markets, or investing history (max 25 words)
- AI LEARNING: 1 AI concept relevant to investing, plain English (max 30 words)
- Each bullet: dash (-) prefix, max 20 words, no bold, no markdown
- Do NOT restate the MHS score, VIX number, or SPX/Russell % (shown in dashboard tables)

DATA:
MHS (Macro Heat Score): {mhs['score']}/100 -- {mhs['label']} | Action: {mhs['action']}
VALUATION: US CAPE={cape_val} (hist avg 17x) | {urth_str} | {efa_str}
MARKET: {mkt_data['pulse']}
{aaii_str}
FRED INDICATORS:
{fred_summary}
HIGH CONVICTION (2+ screens): {', '.join(overlap[:15]) if overlap else 'None today'}
EDWARD JONES: {ej_text[:800]}
CNBC SQUAWK: {cnbc_text[:600]}
YAHOO BRIEF: {yahoo_text[:600]}
McCLELLAN (market breadth): {mcoscillator_text[:400]}
"""

    models_to_try = [
        ("gemini-3.6-flash", "Gemini 3.6 Flash (free tier)",   lambda: _call_gemini(prompt,"gemini-3.6-flash")),
        ("gemini-1.5-flash", "Gemini 1.5 Flash (free tier)",   lambda: _call_gemini(prompt,"gemini-1.5-flash")),
        ("claude-haiku-4-5", "Claude Haiku 4.5 (paid ~$0.003)",lambda: _call_haiku(prompt)),
    ]

    for model_id, model_name, call_fn in models_to_try:
        try:
            print(f"   Trying {model_name}...")
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                fut      = ex.submit(call_fn)
                briefing = fut.result(timeout=90)

            if model_id == "claude-haiku-4-5":
                # Haiku usage is always highlighted in the run log
                print(f"   ✅ Claude Haiku used as fallback: {len(briefing)} chars")
                print(f"   💰 Estimated cost: ~$0.003 (input ~2000 tokens + output ~400 tokens)")
                log(f"AI: Claude Haiku (PAID FALLBACK) -- {len(briefing)} chars -- est $0.003","💰")
            else:
                print(f"   ✅ {model_name}: {len(briefing)} chars")
                log(f"AI: {model_name} -- {len(briefing)} chars")
            return briefing, False

        except concurrent.futures.TimeoutError:
            print(f"   ⚠️ {model_name} timed out (>90s)")
            log(f"AI: {model_name} timeout (>90s)","⚠️")
        except Exception as e:
            print(f"   ⚠️ {model_name} failed: {str(e)[:100]}")
            log(f"AI: {model_name} failed: {str(e)[:60]}","⚠️")

    print("   ❌ All AI models failed (Gemini + Haiku) -- using structured fallback")
    log("AI: ALL models failed (Gemini quota + Haiku) -- structured fallback used","❌")

    fallback = """MARKET AND MACRO
- AI synthesis unavailable -- Gemini quota exhausted AND Claude Haiku failed today
- All data sections below are complete and current -- no data loss

EARNINGS AND EVENTS
- Check Yahoo Morning Brief and CNBC Squawk for today's earnings calendar
- Edward Jones recap has previous session summary

WHAT TO WATCH
- Review MHS score and FRED indicator table -- all data is fresh
- High-conviction tickers (2+ screens) are listed in Value Screens section below

AI FUN FACT
- Shiller CAPE at 41x (Sep 2026) is the 2nd highest reading in 145 years of data. Only dot-com peak beat it.

AI LEARNING
- Attention mechanism: lets LLMs weight relationships between all words simultaneously, enabling context-aware understanding."""

    return fallback, True


# ============================================================
# STEP 14: PARSE AI OUTPUT INTO SECTIONS
# ============================================================

def parse_sections(text):
    """
    Parse AI briefing text into named sections dictionary.
    Handles model output variation (Gemini vs Haiku formatting differences).
    Strips markdown artifacts (##, **, numbered lists) models sometimes add.
    Aliases handle cases where the model renames a section slightly.
    """
    secs    = {"MARKET AND MACRO":"","EARNINGS AND EVENTS":"","WHAT TO WATCH":"",
               "AI FUN FACT":"","AI LEARNING":""}
    current = None
    for line in text.splitlines():
        up  = line.upper().strip()
        cln = re.sub(r"^\d+[\.\)]\s*","",up)
        cln = re.sub(r"^#+\s*","",cln)
        cln = re.sub(r"^\*+\s*","",cln)
        cln = cln.encode("ascii","ignore").decode().strip()
        if "MARKET AND MACRO" in cln:    current="MARKET AND MACRO";    continue
        if "EARNINGS AND EVENTS" in cln: current="EARNINGS AND EVENTS"; continue
        if "WHAT TO WATCH" in cln:       current="WHAT TO WATCH";       continue
        if "AI FUN FACT" in cln:         current="AI FUN FACT";         continue
        if "AI LEARNING" in cln:         current="AI LEARNING";         continue
        # Common aliases from model paraphrasing
        if "MARKET SUMMARY" in cln or ("KEY MOVES" in cln and "MACRO" not in cln):
            current="MARKET AND MACRO"; continue
        if "EARNINGS CALENDAR" in cln: current="EARNINGS AND EVENTS"; continue
        if "FUN FACT" in cln and "AI" not in cln: current="AI FUN FACT"; continue
        if current and line.strip():
            secs[current] += line.strip() + "\n"

    for n,c in secs.items():
        icon = "📋" if c.strip() else "⚠️"
        print(f"   {icon} {n}: {len(c)} chars")
    return secs


# ============================================================
# STEP 15: BUILD HTML DASHBOARD
# ============================================================

def fmt_bullets(raw):
    if not raw or not raw.strip(): return "<li>No data available</li>"
    items=""
    for line in raw.strip().splitlines():
        line=re.sub(r"^[-•*]\s*","",line.strip())
        line=re.sub(r"\*\*(.+?)\*\*",r"<strong>\1</strong>",line)
        if line: items+=f"        <li>{line}</li>\n"
    return items or "<li>No data available</li>"


def _badge(raw_lbl, raw_col):
    m={"RALLY":"BULLISH","UP":"BULLISH","CALM":"BULLISH","Greed":"BULLISH","Extreme Greed":"BULLISH","HIGH":"BULLISH",
       "FLAT":"NEUTRAL","NORMAL":"NEUTRAL","Neutral":"NEUTRAL","MID":"NEUTRAL",
       "DOWN":"CAUTIOUS","CAUTIOUS":"CAUTIOUS","Fear":"CAUTIOUS",
       "SELLOFF":"BEARISH","FEARFUL":"BEARISH","PANIC":"BEARISH","Extreme Fear":"BEARISH","LOW":"BEARISH",
       "CLOSED":"CLOSED","PRE-MKT":"PRE-MKT","Unavailable":"N/A"}
    c={"BULLISH":"#057a55","NEUTRAL":"#6b7280","CAUTIOUS":"#b45309","BEARISH":"#c81e1e",
       "CLOSED":"#9ca3af","PRE-MKT":"#6366f1","N/A":"#9ca3af"}
    std=m.get(raw_lbl,raw_lbl); col=c.get(std,raw_col)
    return f'<span style="background:{col};color:white;padding:2px 9px;border-radius:4px;font-size:.68rem;font-weight:700;">{std}</span>'


def _sparkline_svg(cur_str, mo3_str, mo12_str):
    """
    3-point SVG sparkline: 12mo ago -> 3mo ago -> current.
    Red line = rising vs 12mo ago (bad for most indicators).
    Green line = falling vs 12mo ago (good for most indicators).
    Exception: Yield Curve and Consumer Sentiment are inverted.
    Silently returns empty string if values are N/A or unparseable.
    """
    try:
        def parse(s): return float(re.sub(r"[^0-9.\-]","",str(s)))
        v12=parse(mo12_str); v3=parse(mo3_str); v0=parse(cur_str)
        mn=min(v12,v3,v0); mx=max(v12,v3,v0); r=mx-mn if mx!=mn else 1
        def y(v,h=24): return round(h-(v-mn)/r*(h-4)+2,1)
        pts=f"0,{y(v12)} 20,{y(v3)} 40,{y(v0)}"
        line_col="#c81e1e" if v0>v12 else "#057a55"
        return (f'<svg width="42" height="28" viewBox="0 0 42 28" style="display:inline-block;vertical-align:middle;">'
                f'<polyline points="{pts}" fill="none" stroke="{line_col}" stroke-width="1.8" stroke-linejoin="round"/>'
                f'<circle cx="40" cy="{y(v0)}" r="2.5" fill="{line_col}"/>'
                f'</svg>')
    except:
        return ""


def build_html(briefing, ai_failed, ej_text, cnbc_text, yahoo_text, mcoscillator_text,
               fred_data, fg_data, mkt_data, mhs,
               si_tickers, mf_tickers, am_tickers, aaii_data):
    print("\n🎨 Building HTML dashboard...")

    secs    = parse_sections(briefing)
    now_mt  = datetime.now(MT)
    today   = now_mt.strftime("%A, %B %d, %Y")
    now_str = now_mt.strftime("%I:%M %p")

    vix_val=mkt_data["vix"]["value"]; vix_prev=mkt_data["vix"]["prev"]
    vix_lbl=mkt_data["vix"]["label"]; vix_col=mkt_data["vix"]["color"]; vix_sig=mkt_data["vix"]["signal"]
    spx_val=mkt_data["spx"]["value"]; spx_chg=mkt_data["spx"]["chg"]
    spx_lbl=mkt_data["spx"]["label"]; spx_col=mkt_data["spx"]["color"]; spx_prev=mkt_data["spx"]["prev"]
    rut_val=mkt_data["rut"]["value"]; rut_chg=mkt_data["rut"]["chg"]
    rut_lbl=mkt_data["rut"]["label"]; rut_col=mkt_data["rut"]["color"]; rut_prev=mkt_data["rut"]["prev"]
    pulse=mkt_data["pulse"]; mkt_state=mkt_data.get("market_state","UNKNOWN")
    urth_pe=mkt_data.get("urth_pe"); efa_pe=mkt_data.get("efa_pe")

    fg_score=fg_data.get("score",50); fg_lbl=fg_data.get("label","N/A")
    fg_col=fg_data.get("color","#6b7280"); fg_sig=fg_data.get("signal","")

    umich=next((r for r in fred_data if r["label"]=="Consumer Sentiment"),None)
    umich_val=umich["current"] if umich else "N/A"
    umich_mo3=umich["mo3"] if umich else "N/A"; umich_m12=umich["mo12"] if umich else "N/A"
    umich_sig=umich.get("sig","") if umich else ""
    try: umich_num=float(str(umich_val))
    except: umich_num=55
    ucol="#c81e1e" if umich_num<60 else "#6b7280" if umich_num<75 else "#057a55"
    u_lbl_raw="LOW" if umich_num<60 else "MID" if umich_num<75 else "HIGH"

    cape_row=next((r for r in fred_data if r["label"]=="Shiller CAPE (US)"),None)
    cape_val=cape_row["current"] if cape_row else "N/A"
    try: cape_num=float(re.sub(r"[^0-9.]","",str(cape_val)))
    except: cape_num=0

    mhs_score=mhs["score"]; mhs_lbl=mhs["label"]; mhs_col=mhs["color"]; mhs_action=mhs["action"]
    mhs_bdown=(
        '<span style="font-size:.63rem;color:#6b7280;margin-right:8px;">Base +50</span>'
        +"".join([f'<span style="font-size:.63rem;color:#6b7280;margin-right:8px;">{b}</span>' for b in mhs["breakdown"]])
    )

    # Market status banner (PRE/POST only -- removed CLOSED banner per design decision)
    if mkt_state=="PRE":
        mkt_banner='<div style="background:#eef2ff;border:1px solid #c7d2fe;border-radius:5px;padding:4px 8px;margin-bottom:7px;font-size:.72rem;color:#3730a3;">🌅 Pre-Market · Opens 9:30 AM ET (7:30 AM MT)</div>'
    elif mkt_state=="POST":
        mkt_banner='<div style="background:#faf5ff;border:1px solid #e9d5ff;border-radius:5px;padding:4px 8px;margin-bottom:7px;font-size:.72rem;color:#6d28d9;">🌙 After-Hours</div>'
    else:
        mkt_banner=""

    # AI failure alert (mentions both Gemini AND Haiku failed)
    ai_alert=""
    if ai_failed:
        ai_alert="""<div style="background:#fef2f2;border:2px solid #fca5a5;border-radius:8px;padding:10px 16px;margin-bottom:12px;display:flex;align-items:center;gap:10px;">
  <span style="font-size:1.3rem;">⚠️</span>
  <div>
    <div style="font-weight:700;font-size:.82rem;color:#c81e1e;">AI Synthesis Unavailable</div>
    <div style="font-size:.73rem;color:#6b7280;margin-top:2px;">
      Gemini quota exhausted AND Claude Haiku fallback failed. All data sections are complete.
      Check run log for details. Gemini resets at midnight UTC (6 PM MT).
    </div>
  </div>
</div>"""

    # Market performance rows
    def pr(name,val,chg,prev,rl,rc,note=""):
        nh=f'<div style="font-size:.6rem;color:#9ca3af;">{note}</div>' if note else ""
        return (f'<tr style="border-bottom:1px solid #f3f4f6;">'
                f'<td style="padding:7px 10px;"><div style="font-weight:600;font-size:.82rem;">{name}</div>{nh}</td>'
                f'<td style="padding:7px 10px;font-weight:700;font-size:.9rem;">{val}</td>'
                f'<td style="padding:7px 10px;font-size:.78rem;color:#6b7280;">{chg}</td>'
                f'<td style="padding:7px 10px;font-size:.75rem;color:#9ca3af;">prev {prev}</td>'
                f'<td style="padding:7px 10px;">{_badge(rl,rc)}</td></tr>')

    perf_rows=(
        pr("S&P 500 (Large Cap)",spx_val,spx_chg,spx_prev,spx_lbl,spx_col,"Yahoo Finance · large-cap benchmark")
       +pr("Russell 2000 (Small Cap)",rut_val,rut_chg,rut_prev,rut_lbl,rut_col,"Yahoo Finance · small-cap / risk appetite proxy")
    )

    # Sentiment rows
    try: vix_num=float(vix_val)
    except: vix_num=20
    vix_badge_lbl="CALM" if vix_num<15 else "NORMAL" if vix_num<20 else "CAUTIOUS" if vix_num<25 else "FEARFUL" if vix_num<30 else "PANIC"

    def sr(name,val,hist,rl,rc,sig,note=""):
        nh=f'<div style="font-size:.6rem;color:#9ca3af;">{note}</div>' if note else ""
        return (f'<tr style="border-bottom:1px solid #f3f4f6;">'
                f'<td style="padding:7px 10px;"><div style="font-weight:600;font-size:.82rem;">{name}</div>{nh}</td>'
                f'<td style="padding:7px 10px;font-weight:700;font-size:.9rem;">{val}</td>'
                f'<td style="padding:7px 10px;font-size:.75rem;color:#6b7280;">{hist}</td>'
                f'<td style="padding:7px 10px;">{_badge(rl,rc)}</td>'
                f'<td style="padding:7px 10px;font-size:.72rem;color:#374151;">{sig}</td></tr>')

    sent_rows=(
        sr("VIX (Volatility Index)",vix_val,f"prev {vix_prev}",vix_badge_lbl,vix_col,vix_sig,
           "CBOE · CALM<15 · NORMAL<20 · CAUTIOUS<25 · FEARFUL<30 · PANIC>=30")
       +sr("Fear & Greed Index",f"{fg_score}/100",
           f"1wk:{fg_data.get('prev_week','N/A')} 1mo:{fg_data.get('prev_month','N/A')} 1yr:{fg_data.get('prev_year','N/A')}",
           fg_lbl,fg_col,fg_sig,"CNN Business · 7-indicator composite · 0=extreme fear · 100=extreme greed")
       +sr("Consumer Sentiment",f"{umich_val}",f"3mo:{umich_mo3} 12mo:{umich_m12}",
           u_lbl_raw,ucol,umich_sig,"U of Michigan · 0-100 scale · avg ~75 · <60 = consumer stress")
    )

    # Global Valuation block (CAPE + URTH + EFA side by side)
    cape_color="#c81e1e" if cape_num>=35 else "#b45309" if cape_num>=25 else "#057a55"
    urth_disp=f"{urth_pe}x" if urth_pe else "N/A"
    efa_disp=f"{efa_pe}x" if efa_pe else "N/A"
    cape_times=round(cape_num/17,1) if cape_num else "?"

    valuation_block=f"""
<div class="card" style="margin-bottom:12px;border-left:4px solid #7c3aed;">
  <h2>📐 Global Market Valuation
    <span style="font-weight:400;color:var(--muted);font-size:.55rem;">
      &nbsp; US CAPE = Shiller 10yr smoothed · URTH/EFA = trailing 12mo PE · different methods, directional comparison only
    </span>
  </h2>
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:10px;">
    <div style="text-align:center;padding:10px;background:#fdf4ff;border-radius:8px;border:1px solid #e9d5ff;">
      <div style="font-size:.58rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#7c3aed;margin-bottom:4px;">US Shiller CAPE</div>
      <div style="font-size:1.8rem;font-weight:800;color:{cape_color};">{cape_val}</div>
      <div style="font-size:.63rem;color:#6b7280;margin-top:3px;">Hist avg 17x · 2nd highest ever</div>
      <div style="font-size:.6rem;color:{cape_color};margin-top:2px;font-weight:600;">{'⚠️ EXTREME (98th pctile)' if cape_num>=40 else '⚠️ ELEVATED' if cape_num>=30 else '→ MODERATE'}</div>
    </div>
    <div style="text-align:center;padding:10px;background:#f0fdf4;border-radius:8px;border:1px solid #bbf7d0;">
      <div style="font-size:.58rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#059669;margin-bottom:4px;">URTH (MSCI World)</div>
      <div style="font-size:1.8rem;font-weight:800;color:#059669;">{urth_disp}</div>
      <div style="font-size:.63rem;color:#6b7280;margin-top:3px;">incl ~70% US · trailing PE</div>
      <div style="font-size:.6rem;color:#059669;margin-top:2px;font-weight:600;">GLOBAL BLEND</div>
    </div>
    <div style="text-align:center;padding:10px;background:#eff6ff;border-radius:8px;border:1px solid #bfdbfe;">
      <div style="font-size:.58rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#1a56db;margin-bottom:4px;">EFA (ex-US Developed)</div>
      <div style="font-size:1.8rem;font-weight:800;color:#057a55;">{efa_disp}</div>
      <div style="font-size:.63rem;color:#6b7280;margin-top:3px;">Europe/Japan/Aus · trailing PE</div>
      <div style="font-size:.6rem;color:#057a55;margin-top:2px;font-weight:600;">✅ SIGNIFICANTLY CHEAPER</div>
    </div>
  </div>
  <div style="font-size:.67rem;color:#374151;background:#f9fafb;border-radius:5px;padding:6px 10px;line-height:1.6;">
    <strong>Why this matters:</strong> US trades at {cape_times}x the 145-year historical average (CAPE 17x).
    Ex-US developed markets ({efa_disp} trailing PE) offer dramatically better valuation support.
    Many AM screen picks are intl ADRs (EQNR, PBR, SNY, NVO, SHEL, BP) -- they benefit from
    both cheaper valuations AND potential dollar weakness (watch DXY trend above).
    <em>Note: CAPE uses 10yr smoothed earnings; URTH/EFA use trailing 12mo -- not directly comparable but directionally valid.</em>
  </div>
</div>"""

    # FRED table with sparklines and updated column names
    group_order=["INFLATION","RATES","CREDIT","LABOR","COMMODITIES","CURRENCY","SENTIMENT_FRED","VALUATION"]
    fred_rows=""; rn=1
    for g in group_order:
        gm=GROUP_META.get(g,{"icon":"","color":"#374151","label":g})
        items=[r for r in fred_data if r.get("group")==g]
        if not items: continue
        fred_rows+=(f'<tr style="background:#f9fafb;"><td colspan="9" style="padding:6px 10px;font-size:.64rem;'
                    f'font-weight:700;letter-spacing:1px;text-transform:uppercase;color:{gm["color"]};'
                    f'border-bottom:1px solid #e5e7eb;">{gm["icon"]} {gm["label"]}</td></tr>')
        for r in items:
            tc=_trend_color(r["label"],g,r["trend"])
            spark=_sparkline_svg(r["current"],r["mo3"],r["mo12"])
            fred_rows+=(
                f'<tr style="border-bottom:1px solid #f3f4f6;">'
                f'<td style="padding:7px 8px;text-align:center;font-size:.7rem;color:#9ca3af;">{rn}</td>'
                f'<td style="padding:7px 10px;min-width:140px;"><div style="font-weight:600;font-size:.8rem;">{r["label"]}</div>'
                f'<div style="font-size:.59rem;color:#9ca3af;">{r["insight"]}</div></td>'
                f'<td style="padding:7px 10px;text-align:center;font-weight:700;font-size:.88rem;">{r["current"]}</td>'
                f'<td style="padding:7px 10px;text-align:center;font-size:.78rem;color:#6b7280;">{r["mo3"]}</td>'
                f'<td style="padding:7px 10px;text-align:center;font-size:.78rem;color:#6b7280;">{r["mo12"]}</td>'
                f'<td style="padding:7px 10px;text-align:center;font-size:1rem;color:{tc};">{r["trend"]}</td>'
                f'<td style="padding:7px 6px;text-align:center;">{spark}</td>'
                f'<td style="padding:7px 8px;font-size:.67rem;color:#9ca3af;white-space:nowrap;">{r["date"]}</td>'
                f'<td style="padding:7px 10px;font-size:.7rem;color:#1e3a5f;min-width:200px;">{r.get("sig","")}</td>'
                f'</tr>'
            )
            rn+=1

    # Value Screens -- 5 categories with distinct styling
    all_tickers_set=sorted(set(si_tickers.keys())|mf_tickers|am_tickers)
    all3=[]; two3=[]; si_only=[]; mf_only=[]; am_only=[]
    for t in all_tickers_set:
        in_si=si_tickers.get(t,0)>0; in_mf=t in mf_tickers; in_am=t in am_tickers
        cnt=(1 if in_si else 0)+(1 if in_mf else 0)+(1 if in_am else 0)
        if cnt==3: all3.append(t)
        elif cnt==2: two3.append(t)
        elif in_si: si_only.append(t)
        elif in_mf: mf_only.append(t)
        elif in_am: am_only.append(t)

    def chip(t, style="one"):
        tags=[]
        cnt=si_tickers.get(t,0)
        if cnt>0: tags.append(f"{cnt}SI")
        if t in mf_tickers: tags.append("MF")
        if t in am_tickers: tags.append("AM")
        tag_str=",".join(tags)
        if style=="all3":
            return (f'<div style="background:#1a56db;border-radius:6px;padding:5px 9px;white-space:nowrap;display:inline-block;margin:2px;">'
                    f'<span style="font-weight:800;font-size:.82rem;color:white;">{t}</span>'
                    f'<span style="color:rgba(255,255,255,.7);font-size:.65rem;margin-left:3px;">({tag_str})</span></div>')
        elif style=="two":
            return (f'<div style="background:#057a55;border-radius:6px;padding:5px 9px;white-space:nowrap;display:inline-block;margin:2px;">'
                    f'<span style="font-weight:800;font-size:.82rem;color:white;">{t}</span>'
                    f'<span style="color:rgba(255,255,255,.7);font-size:.65rem;margin-left:3px;">({tag_str})</span></div>')
        else:
            return (f'<div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;padding:4px 8px;white-space:nowrap;display:inline-block;margin:2px;">'
                    f'<span style="font-weight:700;font-size:.78rem;color:#374151;">{t}</span>'
                    f'<span style="color:#9ca3af;font-size:.63rem;margin-left:3px;">({tag_str})</span></div>')

    def screen_row(label, chips_html, count):
        empty='<span style="font-size:.75rem;color:#9ca3af;">None today</span>'
        return (f'<div style="margin-bottom:8px;">'
                f'<div style="font-size:.63rem;font-weight:700;color:#374151;margin-bottom:3px;">{label} <span style="color:#9ca3af;font-weight:400;">({count})</span></div>'
                f'<div style="display:flex;flex-wrap:wrap;">{chips_html if chips_html else empty}</div></div>')

    screens_html=(
        screen_row("🔵 All 3 Screens -- SI + MF + AM (highest conviction)",
                   "".join(chip(t,"all3") for t in all3), len(all3))
       +screen_row("🟢 2 of 3 Screens (strong convergence)",
                   "".join(chip(t,"two")  for t in two3), len(two3))
       +screen_row("⭐ Superinvestors only (13F quarterly, ~45d lag)",
                   "".join(chip(t,"one")  for t in si_only[:25]), len(si_only))
       +screen_row("🔮 Magic Formula only (Greenblatt, daily)",
                   "".join(chip(t,"one")  for t in mf_only[:25]), len(mf_only))
       +screen_row("📐 Acquirer's Multiple only (Carlisle, daily)",
                   "".join(chip(t,"one")  for t in am_only[:25]), len(am_only))
    )

    # AI fun fact and learning
    fun_raw=secs.get("AI FUN FACT","").strip(); learn_raw=secs.get("AI LEARNING","").strip()
    if fun_raw:   fun_raw=re.sub(r"^[-•*]\s*","",fun_raw.splitlines()[0].strip())
    else:         fun_raw="Shiller CAPE at 41x (Sep 2026) is the 2nd highest in 145 years of data. Only dot-com peak (44.2x, Dec 1999) was higher."
    if learn_raw: learn_raw=re.sub(r"^[-•*]\s*","",learn_raw.splitlines()[0].strip())
    else:         learn_raw="Attention mechanism: lets LLMs selectively weight relationships between all tokens simultaneously, enabling context-aware reasoning."

    # Hidden #market-context div for Chrome extension
    # Format goals: compressed key=value, no SPX/RUT/VIX (extension fetches live),
    # dual arrows (first=vs3mo, second=vs12mo), all 15 FRED indicators,
    # 5-category screens, MHS explained inline.
    def _ctx(lbl, short):
        r=next((x for x in fred_data if x["label"]==lbl),None)
        if not r or r["current"]=="N/A": return f"{short}=N/A"
        cur=r["current"]; mo3=r["mo3"]; mo12=r["mo12"]; t3=r["trend"]
        try:
            c=float(re.sub(r"[^0-9.\-]","",cur)); m12=float(re.sub(r"[^0-9.\-]","",mo12))
            t12="↑" if c>m12+0.05 else "↓" if c<m12-0.05 else "→"
        except: t12="?"
        a3="↑" if t3=="▲" else "↓" if t3=="▼" else "→"
        return f"{short}={cur}[3m:{mo3},12m:{mo12}]{a3}{t12}"

    ctx_inflation="|".join([_ctx(l,s) for l,s in [
        ("CPI Inflation","CPI"),("Core CPI","CoreCPI"),("PCE Inflation","PCE"),("Core PCE","CorePCE")]])
    ctx_rates="|".join([_ctx(l,s) for l,s in [
        ("10Y Treasury","10Y"),("2Y Treasury","2Y"),("Yield Curve (10Y-2Y)","YldCurve"),("Fed Funds Rate","FedFunds")]])
    ctx_credit=_ctx("HY Credit Spread","HYSpread")+"(Tight<3%=calm,Wide>6%=stress)"
    ctx_labor=_ctx("Unemployment","Unemp")+"(avg~5.7%historic)"
    ctx_commod="|".join([
        _ctx("WTI Crude Oil","WTI")+"(>$85=inflation_risk)",
        _ctx("Gold Price","Gold")+"(rising+lowVIX=stealth_fear)"])
    ctx_fx=_ctx("US Dollar (DXY)","DXY")+"(weak_dollar=tailwind_intl_ADRs)"
    ctx_csent=_ctx("Consumer Sentiment","ConsSent")+"(avg~75,<60=stress)"
    ctx_val=(f"CAPE={cape_val}(USonly,histAvg17x,98thPctileSince1881)"
             f"|URTH_PE={urth_disp}(MSCIWorldInclUS)|EFA_PE={efa_disp}(ExUSdeveloped)")

    def tlist(lst, si_d=None):
        if not lst: return "none"
        if si_d: return "|".join(f"{t}({si_d.get(t,0)}SI)" for t in lst)
        return "|".join(lst)

    mhs_clean=mhs_lbl.replace("🟢 ","").replace("🟠 ","").replace("⛔ ","")

    mctx=(
        f"MHS={mhs_score}/100({mhs_clean})|Scale:0=max_fear/deploy,100=max_greed/overheated\n"
        f"POSTURE={mhs_action}\n"
        f"INFLATION:{ctx_inflation}\n"
        f"RATES:{ctx_rates}\n"
        f"CREDIT:{ctx_credit}\n"
        f"LABOR:{ctx_labor}\n"
        f"COMMODITIES:{ctx_commod}\n"
        f"CURRENCY:{ctx_fx}\n"
        f"SENTIMENT_CONSUMER:{ctx_csent}\n"
        f"SENTIMENT_MARKET:FG={fg_score}/100({fg_lbl})\n"
        f"VALUATION:{ctx_val}\n"
        f"SCREENS_ALL3(highest_conviction):{tlist(all3)}\n"
        f"SCREENS_2OF3(strong_convergence):{tlist(two3)}\n"
        f"SCREENS_SI_ONLY(13F_superinvestors):{tlist(si_only,si_tickers)}\n"
        f"SCREENS_MF_ONLY(Greenblatt_MagicFormula):{tlist(mf_only)}\n"
        f"SCREENS_AM_ONLY(Carlisle_AcquirersMultiple):{tlist(am_only)}"
    )

    # Run log (collapsed by default)
    elapsed=round(time.time()-RUN_START)
    run_log_items="".join([
        f'<div style="font-size:.72rem;padding:2px 0;border-bottom:1px solid #f3f4f6;font-family:monospace;">{entry}</div>'
        for entry in RUN_LOG
    ])
    aaii_note='<div style="font-size:.72rem;padding:4px 0;font-family:monospace;color:#b45309;">⚠️ AAII Sentiment: blocked by Incapsula CDN on GitHub Actions -- check aaii.com/sentimentsurvey manually every Thursday</div>'

    run_log_html=f"""
<div style="margin-top:12px;">
  <button onclick="var d=this.nextElementSibling;d.style.display=d.style.display==='none'?'block':'none';"
          style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;padding:6px 14px;
                 font-size:.72rem;color:#6b7280;cursor:pointer;width:100%;text-align:left;">
    📋 View Run Log &nbsp;·&nbsp; Total time: {elapsed}s &nbsp;·&nbsp; {len(RUN_LOG)} steps
  </button>
  <div style="display:none;background:#f9fafb;border:1px solid #e5e7eb;border-top:none;
              border-radius:0 0 6px 6px;padding:10px 14px;max-height:400px;overflow-y:auto;">
    {run_log_items}
    {aaii_note}
    <div style="font-size:.7rem;color:#9ca3af;margin-top:4px;padding-top:4px;border-top:1px solid #e5e7eb;">
      Total runtime: {elapsed}s &nbsp;·&nbsp; {today} {now_str} MT
    </div>
  </div>
</div>"""

    html=f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Mean Reversion Macro Insights · {today}</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>📈</text></svg>">
<style>
  :root{{--blue:#1a56db;--green:#057a55;--red:#c81e1e;--amber:#b45309;--ink:#111928;--muted:#6b7280;--border:#e5e7eb;--bg:#f3f4f6;--card:#fff;}}
  *{{box-sizing:border-box;margin:0;padding:0;}}
  body{{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--ink);padding-bottom:60px;}}
  .hero{{background:linear-gradient(135deg,#1e3a5f,#1a56db);color:#fff;padding:20px 20px 14px;text-align:center;}}
  .hero h1{{font-size:1.5rem;letter-spacing:3px;font-weight:800;}}
  .hero .sub{{opacity:.8;margin-top:3px;font-size:.82rem;}}
  .hero .ts{{opacity:.5;margin-top:2px;font-size:.68rem;}}
  .container{{max-width:1200px;margin:14px auto;padding:0 14px;}}
  .grid-2{{display:grid;grid-template-columns:1fr 1fr;gap:12px;}}
  .grid-3{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;}}
  .card{{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px 16px;box-shadow:0 1px 3px rgba(0,0,0,.04);}}
  .card h2{{font-size:.62rem;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:var(--blue);margin-bottom:9px;padding-bottom:7px;border-bottom:2px solid var(--border);}}
  .card.ag{{border-left:4px solid var(--green);}} .card.ab{{border-left:4px solid var(--blue);}}
  .card.aa{{border-left:4px solid var(--amber);}} .card.ar{{border-left:4px solid var(--red);}}
  .card ul{{list-style:none;padding:0;margin:0;}}
  .card ul li{{padding:5px 0 5px 13px;border-bottom:1px solid #f3f4f6;font-size:.82rem;line-height:1.5;color:#374151;position:relative;}}
  .card ul li:before{{content:"▸";position:absolute;left:0;color:var(--blue);font-size:.72rem;}}
  .card ul li:last-child{{border-bottom:none;}}
  .tbl{{width:100%;border-collapse:collapse;font-size:.8rem;}}
  .tbl th{{padding:6px 10px;text-align:left;font-size:.58rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);background:#f9fafb;}}
  .footer{{text-align:center;color:var(--muted);font-size:.68rem;margin-top:22px;}}
  .footer a{{color:var(--blue);text-decoration:none;}}
  @media(max-width:680px){{.grid-2,.grid-3{{grid-template-columns:1fr;}}.hero h1{{font-size:1.1rem;}}}}
</style>
</head>
<body>

<!-- Chrome extension reads #market-context innerText for macro context.
     No SPX/RUT/VIX here -- extension fetches those live.
     Dual arrows: first=vs3mo, second=vs12mo (sustained vs recent).
     Format: compressed key=value, designed for LLM input tokens. -->
<div id="market-context" style="display:none;white-space:pre;">{mctx}</div>

<div class="hero">
  <h1>📈 MEAN REVERSION MACRO INSIGHTS</h1>
  <div class="sub">Anil Abraham &nbsp;·&nbsp; {today}</div>
  <div class="ts">Updated {now_str} MT · anil2040.github.io/market-pulse-ai</div>
</div>

<div class="container">

{ai_alert}

<!-- AI BLOCKS: Fun Fact + Learning (side by side) -->
<div class="grid-2" style="margin-bottom:12px;">
  <div style="background:linear-gradient(135deg,#1e3a5f,#1a56db);color:white;border-radius:10px;padding:11px 16px;display:flex;align-items:center;gap:12px;">
    <div style="font-size:1.3rem;flex-shrink:0;">🤖</div>
    <div>
      <div style="font-size:.55rem;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;opacity:.6;margin-bottom:2px;">Fun Fact</div>
      <div style="font-size:.82rem;line-height:1.5;opacity:.92;">{fun_raw}</div>
    </div>
  </div>
  <div style="background:linear-gradient(135deg,#064e3b,#059669);color:white;border-radius:10px;padding:11px 16px;display:flex;align-items:center;gap:12px;">
    <div style="font-size:1.3rem;flex-shrink:0;">🧠</div>
    <div>
      <div style="font-size:.55rem;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;opacity:.6;margin-bottom:2px;">AI Learning</div>
      <div style="font-size:.82rem;line-height:1.5;opacity:.92;">{learn_raw}</div>
    </div>
  </div>
</div>

<!-- MHS: MACRO HEAT SCORE -->
<div class="card" style="margin-bottom:12px;border-left:4px solid {mhs_col};">
  <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;">
    <div style="flex-shrink:0;">
      <div style="font-size:.58rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--muted);margin-bottom:3px;">MHS · Macro Heat Score</div>
      <div style="font-size:2rem;font-weight:800;color:{mhs_col};line-height:1;">{mhs_score}<span style="font-size:.85rem;color:var(--muted);">/100</span></div>
    </div>
    <div>
      <div style="font-size:.9rem;font-weight:700;color:{mhs_col};">{mhs_lbl}</div>
      <div style="margin-top:5px;background:#e5e7eb;border-radius:99px;height:7px;width:220px;overflow:hidden;">
        <div style="width:{mhs_score}%;background:{mhs_col};height:100%;border-radius:99px;"></div>
      </div>
      <div style="font-size:.7rem;color:#374151;margin-top:5px;">📋 {mhs_action}</div>
    </div>
    <div style="font-size:.63rem;color:var(--muted);flex:1;min-width:200px;line-height:1.8;">{mhs_bdown}</div>
  </div>
  <div style="margin-top:8px;font-size:.67rem;color:#374151;background:#f9fafb;border-radius:5px;padding:6px 10px;line-height:1.6;">
    <strong>Scale (LOWER = better mean reversion opportunity):</strong>
    🟢 DEPLOY (0-33): Panic &amp; dislocation -- aggressive deployment ·
    🟠 SELECTIVE (34-65): Best setups only, Left Leg &lt;4 &amp; MoS &gt;25% ·
    ⛔ OVERHEATED (66-100): Build cash, trim winners.
    Base=50. Components adjust up (overheated signals) or down (fear/opportunity signals).
  </div>
</div>

<!-- Market Performance + Sentiment SIDE BY SIDE -->
<div class="grid-2" style="margin-bottom:12px;">
  <div class="card ar">
    <h2>📈 Market Performance</h2>
    {mkt_banner}
    <table class="tbl">
      <thead><tr><th>Index</th><th>Price</th><th>Change</th><th>Prev</th><th>Signal</th></tr></thead>
      <tbody>{perf_rows}</tbody>
    </table>
    <div style="margin-top:6px;font-size:.65rem;color:#9ca3af;">⚡ {pulse}</div>
  </div>
  <div class="card aa">
    <h2>🌡️ Market Sentiment</h2>
    <table class="tbl">
      <thead><tr><th>Indicator</th><th>Current</th><th>History</th><th>Level</th><th>Insight</th></tr></thead>
      <tbody>{sent_rows}</tbody>
    </table>
    <div style="margin-top:6px;font-size:.63rem;color:#9ca3af;">
      AAII blocked by CDN on GitHub Actions ·
      <a href="https://www.aaii.com/sentimentsurvey" target="_blank" style="color:#1a56db;">check aaii.com Thursdays</a> ·
      Bears &gt;50% = strong contrarian buy historically
    </div>
  </div>
</div>

<!-- Global Valuation Block -->
{valuation_block}

<!-- AI Briefing: 3-column grid -->
<div class="grid-3" style="margin-bottom:12px;">
  <div class="card ab">
    <h2>📊 Market &amp; Macro</h2>
    <ul>{fmt_bullets(secs.get("MARKET AND MACRO",""))}</ul>
  </div>
  <div class="card ag">
    <h2>💰 Earnings &amp; Events</h2>
    <ul>{fmt_bullets(secs.get("EARNINGS AND EVENTS",""))}</ul>
  </div>
  <div class="card ag">
    <h2>🔭 What to Watch</h2>
    <ul>{fmt_bullets(secs.get("WHAT TO WATCH",""))}</ul>
  </div>
</div>

<!-- Value Screens: 5 categories -->
<div class="card ab" style="margin-bottom:12px;">
  <h2>📋 Value Screens
    <span style="font-weight:400;color:var(--muted);font-size:.55rem;">
      &nbsp; SI=Superinvestors 13F (~45d lag) · MF=Greenblatt Magic Formula (daily) · AM=Carlisle Acquirer's Multiple (daily)
    </span>
  </h2>
  {screens_html}
  <div style="font-size:.67rem;color:#6b7280;background:#f0f9ff;border-radius:5px;padding:6px 10px;line-height:1.6;margin-top:8px;">
    <strong>How to use:</strong> Blue (All 3) = highest conviction. Green (2 of 3) = strong convergence.
    Cross-reference with Finviz screener. Left Leg &lt;4 + MoS &gt;25% = strong setup.
    13F: ~45d lag after quarter end. MF and AM update daily after market close.
  </div>
</div>

<!-- FRED Macro Indicators: full table with sparklines -->
<div class="card" style="margin-bottom:12px;">
  <h2>🏦 Macro Indicators
    <span style="font-weight:400;color:var(--muted);font-size:.55rem;">
      &nbsp; FRED API (St. Louis Fed) · sparkline = 12mo ago → 3mo ago → today · green=good/red=bad for equities
    </span>
  </h2>
  <div style="overflow-x:auto;">
    <table style="width:100%;border-collapse:collapse;font-size:.78rem;">
      <thead><tr style="background:#f9fafb;">
        <th style="padding:6px 8px;text-align:center;font-size:.55rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">#</th>
        <th style="padding:6px 10px;text-align:left;font-size:.55rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);min-width:140px;">Indicator</th>
        <th style="padding:6px 10px;text-align:center;font-size:.55rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">Current</th>
        <th style="padding:6px 10px;text-align:center;font-size:.55rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">3 Mo</th>
        <th style="padding:6px 10px;text-align:center;font-size:.55rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">12 Mo</th>
        <th style="padding:6px 10px;text-align:center;font-size:.55rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">3Mo Dir</th>
        <th style="padding:6px 10px;text-align:center;font-size:.55rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">Trend (1Y)</th>
        <th style="padding:6px 8px;font-size:.55rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">As Of</th>
        <th style="padding:6px 10px;font-size:.55rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);min-width:220px;">Insights</th>
      </tr></thead>
      <tbody>{fred_rows}</tbody>
    </table>
  </div>
  <div style="margin-top:8px;font-size:.62rem;color:#9ca3af;border-top:1px solid #f3f4f6;padding-top:6px;">
    Trend colors: green=good for equities, red=bad, amber=context-dependent (Gold, DXY) ·
    Sparkline: red line=rising vs 12mo ago, green line=falling ·
    <a href="https://stockcharts.com/h-sc/ui?s=%24SPXA200R" target="_blank" style="color:#1a56db;">$SPXA200R breadth</a>
    (below 25%=deeply oversold · above 75%=be selective) not in free FRED API.
  </div>
</div>

{run_log_html}

<div class="footer" style="margin-top:20px;">
  Built by <strong>Anil Abraham</strong> &nbsp;·&nbsp;
  <a href="https://fred.stlouisfed.org" target="_blank">FRED API</a> &nbsp;·&nbsp;
  <a href="https://www.cnn.com/markets/fear-and-greed" target="_blank">CNN Fear &amp; Greed</a> &nbsp;·&nbsp;
  <a href="https://www.edwardjones.com/us-en/market-news-insights/stock-market-news/daily-market-recap" target="_blank">Edward Jones</a> &nbsp;·&nbsp;
  <a href="https://www.cnbc.com/newsletters/" target="_blank">CNBC Squawk</a> &nbsp;·&nbsp;
  <a href="https://finance.yahoo.com" target="_blank">Yahoo Finance</a> &nbsp;·&nbsp;
  <a href="https://www.dataroma.com" target="_blank">Dataroma 13F</a> &nbsp;·&nbsp;
  <a href="https://www.magicformulainvesting.com" target="_blank">Magic Formula</a> &nbsp;·&nbsp;
  <a href="https://acquirersmultiple.com" target="_blank">Acquirer's Multiple</a> &nbsp;·&nbsp;
  <a href="https://www.mcoscillator.com" target="_blank">McClellan</a> &nbsp;·&nbsp;
  Gemini · Claude Haiku (fallback) · Not financial advice.
</div>

</div>
</body>
</html>"""

    with open("index.html","w",encoding="utf-8") as f: f.write(html)
    elapsed=round(time.time()-RUN_START)
    print(f"   ✅ index.html written | Total runtime: {elapsed}s")
    log(f"Dashboard written | Total runtime: {elapsed}s")


# ============================================================
# MAIN RUNNER
# ============================================================

if __name__ == "__main__":
    print("🚀 Mean Reversion Macro Insights -- Starting...")
    print("="*50)
    log("Run started")

    fred_data         = fetch_fred_data()
    aaii_data         = fetch_aaii_sentiment()
    fg_data           = fetch_fear_greed()
    mkt_data          = fetch_market_indicators()
    mhs               = compute_mhs(fred_data, fg_data, mkt_data, aaii_data)

    si_tickers        = fetch_superinvestor_buys()   # dict: ticker -> buy count
    mf_tickers        = fetch_magic_formula()         # set of tickers
    am_tickers        = fetch_acquirers_multiple()    # set of tickers

    ej_text           = scrape_edward_jones()
    cnbc_text         = fetch_cnbc_email()
    yahoo_text        = fetch_yahoo_morning_brief()
    mcoscillator_text = fetch_mcoscillator_email()

    briefing, ai_failed = synthesize_with_ai(
        ej_text, cnbc_text, yahoo_text, mcoscillator_text,
        fred_data, fg_data, mkt_data, mhs,
        si_tickers, mf_tickers, am_tickers, aaii_data,
    )

    build_html(
        briefing, ai_failed, ej_text, cnbc_text, yahoo_text, mcoscillator_text,
        fred_data, fg_data, mkt_data, mhs,
        si_tickers, mf_tickers, am_tickers, aaii_data,
    )

    print("\n📧 Email disabled -- GitHub Pages dashboard is primary output")
    print("\n"+"="*50)
    print("✅ Mean Reversion Macro Insights Complete!")
    print("🌐 https://anil2040.github.io/market-pulse-ai")
    print("="*50)