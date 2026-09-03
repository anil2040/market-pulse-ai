# ============================================================
# MarketPulse AI - main.py
# Updated: September 2026
# ============================================================
# Pipeline:
#   1.  FRED macro indicators (12 series, parallel fetch)
#   2.  FRED economic calendar (upcoming high-impact releases)
#   3.  CNN Fear & Greed Index (JSON)
#   4.  Market Breadth - % S&P 500 above 200MA
#   5.  Edward Jones daily recap (web scrape)
#   6.  CNBC Morning Squawk (Yahoo IMAP)
#   7.  Yahoo Finance Morning Brief (Yahoo IMAP)
#   8.  Gemini AI synthesis (google-genai SDK, gemini-3.6-flash)
#   9.  Build HTML dashboard (index.html -> GitHub Pages)
#  10.  Email DISABLED - dashboard is primary output
# ============================================================

import os
import imaplib
import email
import re
import concurrent.futures
from datetime import datetime, timezone, timedelta, date
import requests
from bs4 import BeautifulSoup
import google.genai as genai

# --- SECRETS: injected by GitHub Actions at runtime ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
YAHOO_EMAIL    = os.environ.get("YAHOO_EMAIL")
YAHOO_PASSWORD = os.environ.get("YAHOO_APP_PASSWORD")
FRED_API_KEY   = os.environ.get("FRED_API_KEY")

# --- TIMEZONE: Boise, Idaho ---
# MDT = UTC-6 (summer), MST = UTC-7 (winter, change November)
MT = timezone(timedelta(hours=-6))

print("✅ Configuration loaded")
print(f"📧 Email: {YAHOO_EMAIL}")


# ============================================================
# STEP 1: FRED MACRO INDICATORS (12 series, parallel)
# ============================================================
# ThreadPoolExecutor fires all 12 API calls simultaneously.
# Cuts fetch time from ~30s sequential to ~4s parallel!
# INDEX series (CPI, PCE): show YoY % change, not raw index.
# RATE series: show value directly (already a percentage).
# ============================================================

FRED_SERIES = [
    {
        "label":    "Core PCE (Fed Target 2%)",
        "id":       "PCEPILFE",
        "is_index": True,
        "freq":     "Monthly (BEA)",
        "insight":  "Fed's primary target -- above 2% = rates stay elevated",
    },
    {
        "label":    "Core CPI (ex Food/Energy)",
        "id":       "CPILFESL",
        "is_index": True,
        "freq":     "Monthly (BLS)",
        "insight":  "Cleaner inflation signal -- Fed watches this closely",
    },
    {
        "label":    "CPI Inflation (Headline)",
        "id":       "CPIAUCSL",
        "is_index": True,
        "freq":     "Monthly (BLS)",
        "insight":  "Headline CPI including food & energy prices",
    },
    {
        "label":    "Fed Funds Rate",
        "id":       "FEDFUNDS",
        "is_index": False,
        "freq":     "FOMC ~8x/year",
        "insight":  "Cost of borrowing -- rising = headwind for equities",
    },
    {
        "label":    "HY Credit Spread",
        "id":       "BAMLH0A0HYM2",
        "is_index": False,
        "freq":     "Daily",
        "insight":  "Widening = credit stress = systemic risk (caution on dip buys)",
    },
    {
        "label":    "PCE Inflation (Headline)",
        "id":       "PCEPI",
        "is_index": True,
        "freq":     "Monthly (BEA)",
        "insight":  "Fed preferred inflation gauge (broader than CPI)",
    },
    {
        "label":    "Unemployment Rate",
        "id":       "UNRATE",
        "is_index": False,
        "freq":     "Monthly (BLS)",
        "insight":  "Labor market -- rising signals recession risk ahead",
    },
    {
        "label":    "U of Michigan Sentiment",
        "id":       "UMCSENT",
        "is_index": False,
        "freq":     "Monthly",
        "insight":  "Consumer confidence 0-100 -- leading spending indicator",
        "no_pct":   True,   # Score not a percentage -- show without %
    },
    {
        "label":    "WTI Crude Oil",
        "id":       "DCOILWTICO",
        "is_index": False,
        "freq":     "Daily",
        "insight":  "Energy prices -- drives inflation & energy stock moves",
        "prefix":   "$",    # Show as dollar amount
    },
    {
        "label":    "10Y Treasury Yield",
        "id":       "GS10",
        "is_index": False,
        "freq":     "Daily",
        "insight":  "Risk-free rate -- benchmark for all equity valuations",
    },
    {
        "label":    "2Y Treasury Yield",
        "id":       "GS2",
        "is_index": False,
        "freq":     "Daily",
        "insight":  "Fed expectations barometer -- rises with rate hike bets",
    },
    {
        "label":    "Yield Curve (10Y-2Y)",
        "id":       "T10Y2Y",
        "is_index": False,
        "freq":     "Daily",
        "insight":  "Negative = inverted curve = historically predicts recession",
    },
]


def _dynamic_insight(label, current_val, mo3_val, trend):
    """Generate a one-line dynamic insight based on current vs historical values."""
    try:
        cur = float(str(current_val).replace("%","").replace("$",""))
        mo3 = float(str(mo3_val).replace("%","").replace("$",""))
    except:
        return ""

    diff = cur - mo3

    if "Core PCE" in label or "Core CPI" in label or "PCE" in label or "CPI" in label:
        if cur <= 2.0:
            return "✅ At or below Fed target -- rate cuts more likely"
        elif cur <= 2.5 and trend == "▼":
            return "📉 Cooling toward target -- Fed likely patient"
        elif cur > 3.0 and trend == "▲":
            return "⚠️ Persistently high -- rates likely staying elevated"
        elif trend == "▼":
            return "📉 Cooling trend -- positive for rate-sensitive stocks"
        else:
            return "⚠️ Still above target -- watch for hawkish Fed signals"

    elif "Fed Funds" in label:
        if cur >= 5.0:
            return "⚠️ Restrictive territory -- significant headwind for growth stocks"
        elif cur <= 3.0:
            return "✅ Accommodative -- supportive environment for equities"
        elif trend == "▼":
            return "📉 Cutting cycle -- positive for bonds & rate-sensitive sectors"
        else:
            return "→ Holding steady -- market watching for pivot signals"

    elif "Unemployment" in label:
        if cur <= 4.0:
            return "✅ Strong labor market -- consumer spending likely resilient"
        elif cur >= 5.0:
            return "⚠️ Weakening labor -- recession risk elevated"
        elif trend == "▲":
            return "⚠️ Rising unemployment -- watch consumer discretionary"
        else:
            return "✅ Labor market stable -- no immediate recession signal"

    elif "HY Credit" in label:
        if cur <= 3.0:
            return "✅ Tight spreads -- credit market calm, risk appetite healthy"
        elif cur >= 6.0:
            return "⚠️ Wide spreads -- credit stress, avoid leveraged/weak balance sheets"
        elif trend == "▲":
            return "⚠️ Spreads widening -- systemic risk rising, be selective"
        else:
            return "→ Spreads stable -- no credit market alarm yet"

    elif "Yield Curve" in label:
        if cur < 0:
            return "⚠️ Inverted -- historically precedes recession by 12-18 months"
        elif cur < 0.3:
            return "→ Nearly flat -- monitor for inversion; muted growth signal"
        else:
            return "✅ Positive slope -- normal curve, growth expected"

    elif "10Y" in label:
        if cur >= 5.0:
            return "⚠️ High yields -- expensive for companies to borrow, P/E compression risk"
        elif cur <= 3.5:
            return "✅ Low yields -- supports higher equity valuations"
        elif trend == "▲":
            return "⚠️ Rising -- headwind for high-multiple growth stocks"
        else:
            return "→ Yields stable -- watch for direction change"

    elif "Michigan" in label or "Sentiment" in label:
        if cur >= 80:
            return "✅ High confidence -- consumer spending likely strong"
        elif cur <= 60:
            return "⚠️ Low confidence -- consumer spending under pressure"
        elif trend == "▼":
            return "⚠️ Declining -- watch consumer discretionary stocks"
        else:
            return "→ Sentiment improving -- cautiously positive"

    elif "WTI" in label:
        if cur >= 90:
            return "⚠️ High oil -- inflation pressure, positive for energy stocks"
        elif cur <= 60:
            return "✅ Low oil -- helps consumers, negative for energy stocks"
        elif trend == "▲":
            return "⚠️ Rising -- watch inflation impact & energy sector"
        else:
            return "→ Oil stable -- limited macro impact today"

    elif "2Y" in label:
        if cur >= 5.0:
            return "⚠️ Elevated -- market pricing in rates staying high longer"
        elif trend == "▼":
            return "✅ Falling -- market pricing in rate cuts ahead"
        else:
            return "→ Stable -- Fed rate expectations anchored"

    return ""


def _fetch_one_fred(cfg, start_date, end_date):
    """Fetch one FRED series -- called in parallel."""
    label     = cfg["label"]
    series_id = cfg["id"]
    is_index  = cfg["is_index"]
    no_pct    = cfg.get("no_pct", False)
    prefix    = cfg.get("prefix", "")

    try:
        url = (
            f"https://api.stlouisfed.org/fred/series/observations"
            f"?series_id={series_id}"
            f"&api_key={FRED_API_KEY}"
            f"&file_type=json"
            f"&observation_start={start_date}"
            f"&observation_end={end_date}"
            f"&sort_order=desc"
            f"&limit=15"
        )
        resp = requests.get(url, timeout=10)
        data = resp.json()
        obs  = [o for o in data.get("observations", []) if o["value"] != "."]

        if not obs:
            return {**cfg, "current": "N/A", "mo3": "N/A", "mo12": "N/A",
                    "trend": "?", "date": "N/A", "dyn_insight": ""}

        val_now  = float(obs[0]["value"])
        val_3mo  = float(obs[min(3,  len(obs)-1)]["value"])
        val_12mo = float(obs[min(12, len(obs)-1)]["value"])

        if is_index and val_12mo != 0:
            # YoY % change: (now - 12mo ago) / 12mo ago * 100
            cur_rate = (val_now  - val_12mo) / val_12mo * 100
            val_15mo = float(obs[min(14, len(obs)-1)]["value"])
            mo3_rate = (val_3mo  - val_15mo) / val_15mo * 100 if val_15mo else cur_rate
            display_cur  = f"{cur_rate:.1f}%"
            display_mo3  = f"{mo3_rate:.1f}%"
            display_mo12 = f"{mo3_rate:.1f}%"
            trend = "▼" if cur_rate < mo3_rate - 0.05 else "▲" if cur_rate > mo3_rate + 0.05 else "→"
            dyn   = _dynamic_insight(label, display_cur, display_mo3, trend)
        else:
            if no_pct:
                display_cur  = f"{val_now:.1f}"
                display_mo3  = f"{val_3mo:.1f}"
                display_mo12 = f"{val_12mo:.1f}"
            elif prefix:
                display_cur  = f"{prefix}{val_now:.1f}"
                display_mo3  = f"{prefix}{val_3mo:.1f}"
                display_mo12 = f"{prefix}{val_12mo:.1f}"
            else:
                display_cur  = f"{val_now:.2f}%"
                display_mo3  = f"{val_3mo:.2f}%"
                display_mo12 = f"{val_12mo:.2f}%"
            trend = "▲" if val_now > val_3mo + 0.05 else "▼" if val_now < val_3mo - 0.05 else "→"
            dyn   = _dynamic_insight(label, display_cur, display_mo3, trend)

        pub_date = datetime.strptime(obs[0]["date"], "%Y-%m-%d").strftime("%b %d %Y")

        return {
            **cfg,
            "current":     display_cur,
            "mo3":         display_mo3,
            "mo12":        display_mo12,
            "trend":       trend,
            "date":        pub_date,
            "dyn_insight": dyn,
        }

    except Exception as e:
        return {**cfg, "current": "N/A", "mo3": "N/A", "mo12": "N/A",
                "trend": "?", "date": "N/A", "dyn_insight": "", "error": str(e)}


def fetch_fred_data():
    print("\n🏦 Fetching FRED macro indicators (parallel)...")
    end_date   = date.today().strftime("%Y-%m-%d")
    start_date = (date.today() - timedelta(days=460)).strftime("%Y-%m-%d")

    result_map = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        futures = {ex.submit(_fetch_one_fred, cfg, start_date, end_date): cfg for cfg in FRED_SERIES}
        for future in concurrent.futures.as_completed(futures):
            r = future.result()
            result_map[r["label"]] = r
            status = "✅" if r["current"] != "N/A" else "❌"
            print(f"   {status} {r['label']}: {r['current']} {r['trend']}")

    # Return in original config order (not completion order)
    results = [result_map.get(cfg["label"], {**cfg, "current": "N/A", "mo3": "N/A",
               "mo12": "N/A", "trend": "?", "date": "N/A", "dyn_insight": ""})
               for cfg in FRED_SERIES]

    print(f"   🏦 FRED complete: {len(results)} indicators")
    return results


# ============================================================
# STEP 2: FRED ECONOMIC CALENDAR
# ============================================================
# Uses FRED's releases/dates API to get upcoming release dates
# for key high-impact economic reports this week.
# Shows last 3 days + next 7 days of major releases.
# This replaces the "Earnings and Calendar" section with real
# scheduled economic events -- much more valuable!
# ============================================================

# High-impact releases we care about (FRED release IDs)
HIGH_IMPACT_RELEASES = {
    10:  {"name": "Consumer Price Index",        "abbr": "CPI",        "impact": "🔴 High"},
    51:  {"name": "Personal Income and Outlays", "abbr": "PCE/Income", "impact": "🔴 High"},
    50:  {"name": "Employment Situation",        "abbr": "Jobs/NFP",   "impact": "🔴 High"},
    17:  {"name": "FOMC Statement",              "abbr": "FOMC Rate",  "impact": "🔴 High"},
    53:  {"name": "Gross Domestic Product",      "abbr": "GDP",        "impact": "🔴 High"},
    21:  {"name": "Retail Sales",                "abbr": "Retail Sales","impact": "🟡 Med"},
    22:  {"name": "Producer Price Index",        "abbr": "PPI",        "impact": "🟡 Med"},
    23:  {"name": "Housing Starts",              "abbr": "Housing",    "impact": "🟡 Med"},
    11:  {"name": "Employment Cost Index",       "abbr": "ECI",        "impact": "🟡 Med"},
    33:  {"name": "ISM Manufacturing",           "abbr": "ISM Mfg",   "impact": "🟡 Med"},
}


def fetch_economic_calendar():
    print("\n📅 Fetching Economic Calendar from FRED...")
    try:
        today     = date.today()
        # Window: 3 days back, 7 days forward
        start     = (today - timedelta(days=3)).strftime("%Y-%m-%d")
        end       = (today + timedelta(days=7)).strftime("%Y-%m-%d")

        url = (
            f"https://api.stlouisfed.org/fred/releases/dates"
            f"?api_key={FRED_API_KEY}"
            f"&file_type=json"
            f"&realtime_start={start}"
            f"&realtime_end={end}"
            f"&limit=100"
            f"&sort_order=asc"
            f"&include_release_dates_with_no_data=true"
        )
        resp = requests.get(url, timeout=10)
        data = resp.json()

        events = []
        for item in data.get("release_dates", []):
            release_id = int(item.get("release_id", 0))
            if release_id in HIGH_IMPACT_RELEASES:
                rel_info   = HIGH_IMPACT_RELEASES[release_id]
                event_date = item.get("date", "")
                try:
                    dt = datetime.strptime(event_date, "%Y-%m-%d")
                    # Relative label
                    delta = (dt.date() - today).days
                    if delta < 0:
                        rel_label = f"{abs(delta)}d ago"
                    elif delta == 0:
                        rel_label = "TODAY"
                    elif delta == 1:
                        rel_label = "Tomorrow"
                    else:
                        rel_label = dt.strftime("%a %b %d")

                    events.append({
                        "date":      dt.strftime("%a %b %d"),
                        "rel":       rel_label,
                        "abbr":      rel_info["abbr"],
                        "name":      rel_info["name"],
                        "impact":    rel_info["impact"],
                        "is_today":  delta == 0,
                        "is_past":   delta < 0,
                        "delta":     delta,
                    })
                except:
                    continue

        # Sort by date
        events.sort(key=lambda x: x["delta"])

        print(f"   ✅ Economic Calendar: {len(events)} high-impact events found")
        return events

    except Exception as e:
        print(f"   ❌ Economic Calendar failed: {e}")
        return []


# ============================================================
# STEP 3: CNN FEAR & GREED
# ============================================================
# Score 0-100: Extreme Fear / Fear / Neutral / Greed / Extreme Greed
# Updated once daily by CNN. JSON fetch -- fast and clean.
# Buffett quote: "be greedy when others are fearful!"
# ============================================================

def fetch_fear_greed():
    print("\n😨 Fetching CNN Fear & Greed Index...")
    try:
        url     = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp    = requests.get(url, headers=headers, timeout=10)
        data    = resp.json()
        fg      = data.get("fear_and_greed", {})

        score      = round(float(fg.get("score", 50)))
        rating     = fg.get("rating", "Unknown").replace("_", " ").title()
        prev_close = round(float(fg.get("previous_close",   score)))
        prev_week  = round(float(fg.get("previous_1_week",  score)))
        prev_month = round(float(fg.get("previous_1_month", score)))
        prev_year  = round(float(fg.get("previous_1_year",  score)))

        if   score <= 24: signal = "Extreme Fear -- Historically strong buying opportunity"; color = "#c81e1e"
        elif score <= 44: signal = "Fear -- Market pessimism, watch for mean reversion entries"; color = "#e97316"
        elif score <= 55: signal = "Neutral -- No strong directional sentiment signal"; color = "#6b7280"
        elif score <= 74: signal = "Greed -- Optimism elevated, exercise caution on new buys"; color = "#059669"
        else:             signal = "Extreme Greed -- Market overheated, high reversal risk"; color = "#1a56db"

        print(f"   ✅ Fear & Greed: {score}/100 ({rating})")
        return {"score": score, "rating": rating, "signal": signal, "color": color,
                "prev_close": prev_close, "prev_week": prev_week,
                "prev_month": prev_month, "prev_year": prev_year}

    except Exception as e:
        print(f"   ❌ Fear & Greed failed: {e}")
        return {"score": 50, "rating": "Unavailable", "signal": "Data unavailable",
                "color": "#6b7280", "prev_close": "N/A", "prev_week": "N/A",
                "prev_month": "N/A", "prev_year": "N/A"}


# ============================================================
# STEP 4: MARKET BREADTH
# ============================================================
# % of S&P 500 stocks above their 200-day moving average.
# Key mean reversion signal:
#   < 25% = deeply oversold = strong buy signal historically
#   25-45% = oversold = selective value opportunities
#   45-65% = neutral = stock-pickers market
#   > 65% = healthy/overbought = be selective
# Uses yfinance-compatible Yahoo Finance API (no key needed!).
# ============================================================

def fetch_market_breadth():
    print("\n📊 Fetching Market Breadth...")
    try:
        # Try primary ticker ^S5TH (S&P 500 % above 200MA)
        for ticker in ["%5ES5TH", "%5ESPX200R"]:
            try:
                url  = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=5d"
                hdrs = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                        "Accept": "application/json"}
                resp = requests.get(url, headers=hdrs, timeout=10)
                data = resp.json()
                meta = data["chart"]["result"][0]["meta"]

                price  = float(meta.get("regularMarketPrice", 0))
                prev   = float(meta.get("previousClose", price))
                change = price - prev

                if price > 0:
                    if   price < 25: signal = "Deeply Oversold -- Strong mean reversion setup"; bar_color = "#c81e1e"
                    elif price < 40: signal = "Oversold -- Value opportunities emerging"; bar_color = "#e97316"
                    elif price < 60: signal = "Neutral -- Mixed breadth, stock-pickers market"; bar_color = "#6b7280"
                    elif price < 75: signal = "Healthy -- Broad participation, momentum intact"; bar_color = "#059669"
                    else:            signal = "Overbought -- Limited upside, reversal risk elevated"; bar_color = "#1a56db"

                    print(f"   ✅ Market Breadth: {price:.1f}% ({signal})")
                    return {"value": f"{price:.1f}%", "raw": price, "prev": f"{prev:.1f}%",
                            "change": f"{change:+.1f}%", "signal": signal, "color": bar_color}
            except:
                continue

        raise Exception("All breadth tickers failed")

    except Exception as e:
        print(f"   ❌ Market Breadth failed: {e}")
        # Return a helpful fallback with explanation
        return {"value": "N/A", "raw": 50, "prev": "N/A", "change": "N/A",
                "signal": "Data temporarily unavailable -- Yahoo Finance API limit",
                "color": "#6b7280"}


# ============================================================
# STEP 5: EDWARD JONES SCRAPE
# ============================================================

def scrape_edward_jones():
    print("\n🔍 Scraping Edward Jones...")
    url     = "https://www.edwardjones.com/us-en/market-news-insights/stock-market-news/daily-market-recap"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        print(f"   Status: {resp.status_code}")
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script","style","nav","footer","header"]): tag.decompose()
        lines = [l.strip() for l in soup.get_text("\n", strip=True).splitlines() if l.strip()]
        text  = "\n".join(lines[:120])
        print(f"   ✅ Edward Jones: {len(text)} chars")
        return text
    except Exception as e:
        print(f"   ❌ Edward Jones failed: {e}")
        return "Edward Jones data unavailable today."


# ============================================================
# STEP 6 & 7: FETCH EMAILS VIA IMAP
# ============================================================

def _fetch_email(sender, label):
    """Generic IMAP email fetcher -- reused for all email sources."""
    try:
        mail = imaplib.IMAP4_SSL("imap.mail.yahoo.com", 993)
        mail.login(YAHOO_EMAIL, YAHOO_PASSWORD)
        mail.select("INBOX")
        status, messages = mail.search(None, f'(FROM "{sender}")')

        if status != "OK" or not messages[0]:
            print(f"   ⚠️ No {label} emails found")
            mail.logout()
            return f"{label} email not found today."

        email_ids = messages[0].split()
        latest_id = email_ids[-1]
        print(f"   Found {len(email_ids)} {label} emails, reading latest...")

        status, msg_data = mail.fetch(latest_id, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])

        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                    break
        if not body:
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/html":
                        html = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                        body = BeautifulSoup(html, "html.parser").get_text("\n", strip=True)
                        break
            else:
                raw  = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
                body = BeautifulSoup(raw, "html.parser").get_text("\n", strip=True)

        mail.logout()
        # Trim to 2000 chars -- removes unsubscribe footers, keeps the news
        body = body[:2000].strip()
        print(f"   ✅ {label}: {len(body)} chars")
        return body
    except Exception as e:
        print(f"   ❌ {label} IMAP failed: {e}")
        return f"{label} unavailable today."


def fetch_cnbc_email():
    print("\n📬 Fetching CNBC Morning Squawk...")
    return _fetch_email("morningsquawk@response.cnbc.com", "CNBC Morning Squawk")


def fetch_yahoo_morning_brief():
    print("\n📬 Fetching Yahoo Finance Morning Brief...")
    # Check your Yahoo inbox for exact sender -- update if needed!
    return _fetch_email("morningbrief@yahoo-inc.com", "Yahoo Morning Brief")


# ============================================================
# STEP 8: GEMINI AI SYNTHESIS
# ============================================================
# Model: gemini-3.6-flash (stable free tier, Sep 2026)
# Uses google-genai SDK Interactions API.
# Prompt explicitly requests bullet format to prevent
# section parsing failures!
# Also generates one daily AI fun fact for the dashboard.
# ============================================================

def synthesize_with_gemini(ej_text, cnbc_text, yahoo_text,
                            fred_data, fg_data, breadth_data, calendar_events):
    print("\n🤖 Sending to Gemini AI for synthesis...")
    try:
        fred_summary = "\n".join([
            f"- {r['label']}: {r['current']} (trend: {r['trend']})"
            for r in fred_data if r["current"] != "N/A"
        ])
        fg_line      = f"Fear & Greed: {fg_data['score']}/100 ({fg_data['rating']}) -- {fg_data['signal']}"
        breadth_line = f"Market Breadth (% above 200MA): {breadth_data['value']} -- {breadth_data['signal']}"

        cal_lines = "\n".join([
            f"- {e['rel']}: {e['abbr']} ({e['impact']})"
            for e in (calendar_events or [])
        ]) or "No high-impact releases in window"

        prompt = f"""You are a sharp financial analyst writing a pre-market briefing for a 
deep-value mean reversion investor (Greenblatt/Munger style).

STRICT FORMATTING RULES:
- Use ONLY these 5 section headers, exactly as written:
  MARKET SUMMARY
  KEY MOVES
  MACRO AND NEWS
  EARNINGS AND CALENDAR
  PRE-MARKET OUTLOOK
- Under each: 3-5 bullet points starting with a dash (-)
- Each bullet: one specific fact, max 20 words
- No paragraphs, no bold, no markdown headers, no numbers before headers

MACRO CONTEXT:
{fred_summary}
{fg_line}
{breadth_line}

UPCOMING ECONOMIC RELEASES:
{cal_lines}

SOURCE 1 - EDWARD JONES:
{ej_text[:1000]}

SOURCE 2 - CNBC MORNING SQUAWK:
{cnbc_text[:900]}

SOURCE 3 - YAHOO MORNING BRIEF:
{yahoo_text[:900]}

After the 5 sections, add one more section:
AI FUN FACT
- One fascinating fact about AI, financial markets, or investing history. Make it surprising and memorable. Max 30 words.
"""

        client      = genai.Client(api_key=GEMINI_API_KEY)
        interaction = client.interactions.create(
            model="gemini-3.6-flash",
            input=prompt,
        )
        briefing = interaction.output_text
        print(f"   ✅ Gemini: {len(briefing)} chars")
        return briefing

    except Exception as e:
        print(f"   ❌ Gemini failed: {e}")
        return """MARKET SUMMARY
- AI synthesis unavailable -- check source data below

KEY MOVES
- See Edward Jones and CNBC sources for market data

MACRO AND NEWS
- FRED macro indicators available in the table below

EARNINGS AND CALENDAR
- Check economic calendar section for upcoming releases

PRE-MARKET OUTLOOK
- Review FRED data and sentiment indicators for context

AI FUN FACT
- The first stock exchange was founded in Amsterdam in 1602 for trading Dutch East India Company shares."""


# ============================================================
# STEP 9: PARSE SECTIONS
# ============================================================

def parse_sections(briefing_text):
    sections = {
        "MARKET SUMMARY":        "",
        "KEY MOVES":             "",
        "MACRO AND NEWS":        "",
        "EARNINGS AND CALENDAR": "",
        "PRE-MARKET OUTLOOK":    "",
        "AI FUN FACT":           "",
    }
    current = None
    for line in briefing_text.splitlines():
        upper   = line.upper().strip()
        cleaned = re.sub(r"^\d+[\.\)]\s*", "", upper)
        cleaned = re.sub(r"^#+\s*",         "", cleaned)
        cleaned = re.sub(r"^\*+\s*",         "", cleaned)
        cleaned = cleaned.encode("ascii", "ignore").decode().strip()

        if "MARKET SUMMARY"        in cleaned: current = "MARKET SUMMARY";        continue
        if "KEY MOVES"             in cleaned: current = "KEY MOVES";              continue
        if "MACRO AND NEWS"        in cleaned: current = "MACRO AND NEWS";         continue
        if "MACRO & NEWS"          in cleaned: current = "MACRO AND NEWS";         continue
        if "EARNINGS AND CALENDAR" in cleaned: current = "EARNINGS AND CALENDAR";  continue
        if "EARNINGS HIGHLIGHT"    in cleaned: current = "EARNINGS AND CALENDAR";  continue
        if "PRE-MARKET OUTLOOK"    in cleaned: current = "PRE-MARKET OUTLOOK";     continue
        if "PRE MARKET OUTLOOK"    in cleaned: current = "PRE-MARKET OUTLOOK";     continue
        if "MORNING OUTLOOK"       in cleaned: current = "PRE-MARKET OUTLOOK";     continue
        if "AI FUN FACT"           in cleaned: current = "AI FUN FACT";            continue
        if "FUN FACT"              in cleaned: current = "AI FUN FACT";            continue

        if current and line.strip():
            sections[current] += line.strip() + "\n"

    for name, content in sections.items():
        status = f"{len(content)} chars" if content.strip() else "⚠️ EMPTY"
        print(f"   📋 {name}: {status}")

    return sections


# ============================================================
# STEP 10: BUILD HTML DASHBOARD
# ============================================================

def fmt_bullets(raw_text):
    """Convert raw bullet text to clean HTML list items."""
    if not raw_text or not raw_text.strip():
        return "<li>No data available</li>"
    items = ""
    for line in raw_text.strip().splitlines():
        line = re.sub(r"^[-•*]\s*", "", line.strip())
        line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
        if line:
            items += f"        <li>{line}</li>\n"
    return items or "<li>No data available</li>"


def build_html(briefing_text, ej_text, cnbc_text, yahoo_text,
               fred_data, fg_data, breadth_data, calendar_events):
    print("\n🎨 Building HTML dashboard...")

    sections = parse_sections(briefing_text)

    now_mt = datetime.now(MT)
    today  = now_mt.strftime("%A, %B %d, %Y")
    now    = now_mt.strftime("%I:%M %p")

    fg_score  = fg_data.get("score",  50)
    fg_rating = fg_data.get("rating", "N/A")
    fg_signal = fg_data.get("signal", "")
    fg_color  = fg_data.get("color",  "#6b7280")

    # ---- CSS-based Fear & Greed Gauge (bulletproof) ----------
    # Uses a simple CSS half-circle with a rotating needle.
    # No SVG arc math -- just CSS transform: rotate()
    # Score 0 = needle points left (-90deg)
    # Score 100 = needle points right (+90deg)
    try:
        score_num    = int(fg_score)
        needle_deg   = -90 + (score_num * 1.8)  # -90 to +90 degrees
    except:
        score_num  = 50
        needle_deg = 0

    fg_gauge = f"""
<div style="text-align:center;padding:8px 0;">
  <!-- Gauge container -->
  <div style="position:relative;width:200px;height:105px;margin:0 auto;overflow:hidden;">
    <!-- Colored arc background (conic-gradient half circle) -->
    <div style="
      position:absolute;bottom:0;left:50%;transform:translateX(-50%);
      width:200px;height:100px;
      background:conic-gradient(
        from 270deg,
        #c81e1e 0deg 36deg,
        #e97316 36deg 72deg,
        #d4d400 72deg 108deg,
        #86c440 108deg 144deg,
        #059669 144deg 180deg
      );
      border-radius:100px 100px 0 0;
    "></div>
    <!-- White inner circle (creates donut shape) -->
    <div style="
      position:absolute;bottom:0;left:50%;transform:translateX(-50%);
      width:130px;height:65px;
      background:white;border-radius:65px 65px 0 0;
    "></div>
    <!-- Needle -->
    <div style="
      position:absolute;bottom:5px;left:50%;
      width:3px;height:80px;
      background:#1e3a5f;border-radius:3px 3px 0 0;
      transform-origin:bottom center;
      transform:translateX(-50%) rotate({needle_deg}deg);
    "></div>
    <!-- Center dot -->
    <div style="
      position:absolute;bottom:0px;left:50%;transform:translateX(-50%);
      width:14px;height:14px;background:#1e3a5f;border-radius:50%;
      margin-bottom:-2px;
    "></div>
  </div>
  <!-- Labels -->
  <div style="display:flex;justify-content:space-between;width:200px;margin:2px auto 0;font-size:.65rem;color:#9ca3af;">
    <span>Fear</span><span>Neutral</span><span>Greed</span>
  </div>
  <!-- Score + Rating -->
  <div style="font-size:2.2rem;font-weight:800;color:{fg_color};line-height:1;margin-top:8px;">{fg_score}</div>
  <div style="font-size:.85rem;font-weight:700;color:{fg_color};">{fg_rating.upper()}</div>
  <div style="font-size:.72rem;color:#6b7280;margin-top:4px;line-height:1.4;">{fg_signal}</div>
</div>
<!-- History grid -->
<div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;margin-top:10px;">
  <div style="background:#f9fafb;border-radius:6px;padding:5px 7px;font-size:.72rem;">
    <div style="color:#9ca3af;">Yesterday</div>
    <div style="font-weight:700;">{fg_data.get('prev_close','N/A')}</div>
  </div>
  <div style="background:#f9fafb;border-radius:6px;padding:5px 7px;font-size:.72rem;">
    <div style="color:#9ca3af;">1 Week Ago</div>
    <div style="font-weight:700;">{fg_data.get('prev_week','N/A')}</div>
  </div>
  <div style="background:#f9fafb;border-radius:6px;padding:5px 7px;font-size:.72rem;">
    <div style="color:#9ca3af;">1 Month Ago</div>
    <div style="font-weight:700;">{fg_data.get('prev_month','N/A')}</div>
  </div>
  <div style="background:#f9fafb;border-radius:6px;padding:5px 7px;font-size:.72rem;">
    <div style="color:#9ca3af;">1 Year Ago</div>
    <div style="font-weight:700;">{fg_data.get('prev_year','N/A')}</div>
  </div>
</div>"""

    # ---- Market Breadth bar -----------------------------------
    try:
        bval      = float(str(breadth_data.get("raw", 50)))
        bar_color = breadth_data.get("color", "#6b7280")
    except:
        bval      = 50
        bar_color = "#6b7280"

    breadth_bar = f"""
<div style="margin-top:12px;">
  <div style="font-size:.65rem;font-weight:700;letter-spacing:1px;
              text-transform:uppercase;color:#1a56db;margin-bottom:6px;">
    📊 Market Breadth (% S&P 500 above 200-Day MA)
  </div>
  <div style="display:flex;justify-content:space-between;font-size:.62rem;color:#9ca3af;margin-bottom:3px;">
    <span>0% Oversold</span><span>50%</span><span>100% Overbought</span>
  </div>
  <div style="background:#e5e7eb;border-radius:99px;height:12px;overflow:hidden;">
    <div style="width:{bval}%;background:{bar_color};height:100%;border-radius:99px;"></div>
  </div>
  <div style="font-size:.75rem;font-weight:700;color:{bar_color};margin-top:4px;">
    {breadth_data.get('value','N/A')} &nbsp;·&nbsp; {breadth_data.get('signal','N/A')}
  </div>
  <div style="font-size:.68rem;color:#9ca3af;margin-top:2px;">
    vs Yesterday: {breadth_data.get('prev','N/A')} ({breadth_data.get('change','N/A')})
  </div>
  <div style="font-size:.68rem;color:#6b7280;margin-top:6px;line-height:1.4;
              background:#f9fafb;border-radius:6px;padding:5px 7px;">
    💡 Below 25% = deeply oversold market (mean reversion buy signal).
    Above 75% = overbought (be selective on new positions).
  </div>
</div>"""

    # ---- Economic Calendar rows ------------------------------
    cal_rows = ""
    for ev in (calendar_events or []):
        row_bg    = "#fff8f0" if ev["is_today"] else "#f9fafb" if ev["is_past"] else "white"
        date_bold = "font-weight:800;color:#1a56db;" if ev["is_today"] else "color:#6b7280;" if ev["is_past"] else ""
        cal_rows += f"""
        <tr style="background:{row_bg};border-bottom:1px solid #f3f4f6;">
          <td style="padding:7px 10px;font-size:.78rem;{date_bold}white-space:nowrap;">{ev['rel']}</td>
          <td style="padding:7px 10px;font-size:.78rem;">{ev['impact']}</td>
          <td style="padding:7px 10px;font-size:.82rem;font-weight:600;">{ev['abbr']}</td>
          <td style="padding:7px 10px;font-size:.75rem;color:#6b7280;">{ev['name']}</td>
        </tr>"""

    if not cal_rows:
        cal_rows = '<tr><td colspan="4" style="padding:10px;color:#9ca3af;font-size:.8rem;">No high-impact releases in window</td></tr>'

    # ---- FRED table rows (sorted alphabetically) -------------
    sorted_fred = sorted([r for r in (fred_data or [])], key=lambda x: x["label"])
    fred_rows   = ""
    for r in sorted_fred:
        # Inflation: DOWN = good (green), UP = bad (red)
        if any(x in r["label"] for x in ["CPI","PCE","Inflation"]):
            tc = "#057a55" if r["trend"] == "▼" else "#c81e1e" if r["trend"] == "▲" else "#6b7280"
        else:
            tc = "#057a55" if r["trend"] == "▲" else "#c81e1e" if r["trend"] == "▼" else "#6b7280"

        dyn = r.get("dyn_insight","")
        fred_rows += f"""
        <tr style="border-bottom:1px solid #f3f4f6;">
          <td class="td-label">{r['label']}</td>
          <td class="td-val"><strong>{r['current']}</strong></td>
          <td class="td-val muted">{r['mo3']}</td>
          <td class="td-val muted">{r['mo12']}</td>
          <td class="td-center" style="color:{tc};font-size:1.05rem;">{r['trend']}</td>
          <td class="td-date muted">{r['date']}</td>
          <td class="td-insight muted">{r['insight']}</td>
          <td class="td-insight" style="color:#1e3a5f;">{dyn}</td>
        </tr>"""

    # ---- AI Fun Fact block -----------------------------------
    fun_fact_text = sections.get("AI FUN FACT","").strip()
    if fun_fact_text:
        fun_fact_text = re.sub(r"^[-•*]\s*", "", fun_fact_text.splitlines()[0].strip())
    else:
        fun_fact_text = "The first algorithmic trading program ran in 1976 on the New York Stock Exchange, decades before AI made it mainstream."

    fun_fact_html = f"""
<div style="
  background:linear-gradient(135deg,#1e3a5f,#1a56db);
  color:white;border-radius:10px;padding:14px 20px;
  margin-bottom:16px;display:flex;align-items:center;gap:14px;
">
  <div style="font-size:2rem;flex-shrink:0;">🤖</div>
  <div>
    <div style="font-size:.62rem;font-weight:700;letter-spacing:1.5px;
                text-transform:uppercase;opacity:.7;margin-bottom:4px;">
      AI Fun Fact of the Day
    </div>
    <div style="font-size:.88rem;line-height:1.55;opacity:.95;">
      {fun_fact_text}
    </div>
  </div>
</div>"""

    # ---- Hidden market-context div (Chrome extension) --------
    fred_plain = "\n".join([
        f"  {r['label']}: {r['current']} (3mo: {r['mo3']}, trend: {r['trend']}) -- {r['insight']}"
        for r in (fred_data or [])
    ])
    cal_plain = "\n".join([
        f"  {e['rel']}: {e['abbr']} ({e['impact']})"
        for e in (calendar_events or [])
    ])

    market_context = f"""MARKETPULSE AI MACRO CONTEXT
Generated: {today} at {now} MT

MARKET SUMMARY:
{sections.get('MARKET SUMMARY','').strip() or 'See sources below'}

KEY MOVES:
{sections.get('KEY MOVES','').strip() or 'See sources below'}

MACRO AND NEWS:
{sections.get('MACRO AND NEWS','').strip() or 'See sources below'}

EARNINGS AND CALENDAR:
{sections.get('EARNINGS AND CALENDAR','').strip() or 'None noted today'}

PRE-MARKET OUTLOOK:
{sections.get('PRE-MARKET OUTLOOK','').strip() or 'See sources below'}

FEAR AND GREED: {fg_score}/100 ({fg_rating}) -- {fg_signal}
MARKET BREADTH: {breadth_data.get('value','N/A')} -- {breadth_data.get('signal','N/A')}

ECONOMIC CALENDAR (next 7 days):
{cal_plain or 'No high-impact releases scheduled'}

FRED MACRO INDICATORS:
{fred_plain}

SOURCES: Edward Jones, CNBC Morning Squawk, Yahoo Finance, FRED API, CNN Fear & Greed"""

    # ---- Full HTML -------------------------------------------
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>MarketPulse AI · {today}</title>
<!-- Favicon: simple chart emoji rendered as SVG -->
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>📈</text></svg>">
<style>
  :root {{
    --blue:   #1a56db;
    --green:  #057a55;
    --red:    #c81e1e;
    --amber:  #b45309;
    --ink:    #111928;
    --muted:  #6b7280;
    --border: #e5e7eb;
    --bg:     #f3f4f6;
    --card:   #ffffff;
  }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:'Segoe UI',system-ui,sans-serif; background:var(--bg); color:var(--ink); padding-bottom:60px; }}
  .hero {{ background:linear-gradient(135deg,#1e3a5f,#1a56db); color:#fff; padding:24px 20px 18px; text-align:center; }}
  .hero h1 {{ font-size:1.7rem; letter-spacing:3px; font-weight:800; }}
  .hero .sub {{ opacity:.8; margin-top:4px; font-size:.85rem; }}
  .hero .ts  {{ opacity:.55; margin-top:3px; font-size:.7rem; }}
  .container {{ max-width:1200px; margin:18px auto; padding:0 14px; }}
  .grid-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
  .grid-3 {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:14px; }}
  .card {{ background:var(--card); border:1px solid var(--border); border-radius:10px; padding:16px 18px; box-shadow:0 1px 3px rgba(0,0,0,.05); }}
  .card h2 {{ font-size:.63rem; font-weight:700; letter-spacing:1.5px; text-transform:uppercase; color:var(--blue); margin-bottom:10px; padding-bottom:7px; border-bottom:2px solid var(--border); }}
  .card.accent-green {{ border-left:4px solid var(--green); }}
  .card.accent-blue  {{ border-left:4px solid var(--blue);  }}
  .card.accent-amber {{ border-left:4px solid var(--amber); }}
  .card.accent-red   {{ border-left:4px solid var(--red);   }}
  .card ul {{ list-style:none; padding:0; margin:0; }}
  .card ul li {{ padding:5px 0 5px 14px; border-bottom:1px solid #f3f4f6; font-size:.83rem; line-height:1.5; color:#374151; position:relative; }}
  .card ul li:before {{ content:"▸"; position:absolute; left:0; color:var(--blue); font-size:.75rem; }}
  .card ul li:last-child {{ border-bottom:none; }}
  .fred-table {{ width:100%; border-collapse:collapse; font-size:.76rem; }}
  .fred-table thead tr {{ background:#f3f4f6; }}
  .fred-table th {{ padding:7px 9px; text-align:left; font-size:.62rem; letter-spacing:.5px; text-transform:uppercase; color:var(--muted); border-bottom:2px solid var(--border); }}
  .fred-table tbody tr:hover {{ background:#fafafa; }}
  .td-label   {{ padding:7px 9px; font-weight:600; color:var(--ink); min-width:160px; }}
  .td-val     {{ padding:7px 9px; text-align:center; }}
  .td-center  {{ padding:7px 9px; text-align:center; }}
  .td-date    {{ padding:7px 9px; font-size:.68rem; white-space:nowrap; }}
  .td-insight {{ padding:7px 9px; font-size:.7rem; }}
  .muted      {{ color:var(--muted); }}
  .cal-table  {{ width:100%; border-collapse:collapse; font-size:.8rem; }}
  .footer     {{ text-align:center; color:var(--muted); font-size:.7rem; margin-top:28px; }}
  .footer a   {{ color:var(--blue); text-decoration:none; }}
  @media(max-width:640px){{
    .grid-2,.grid-3{{ grid-template-columns:1fr; }}
    .hero h1{{ font-size:1.3rem; }}
    .td-insight{{ display:none; }}
  }}
</style>
</head>
<body>

<!-- HIDDEN: Chrome Extension macro context
     Usage: fetch page, parse div#market-context innerText -->
<div id="market-context" style="display:none;white-space:pre;">{market_context}</div>

<!-- HEADER: clean, no repeated credits -->
<div class="hero">
  <h1>📈 MARKETPULSE AI</h1>
  <div class="sub">Anil Abraham &nbsp;·&nbsp; {today}</div>
  <div class="ts">Last updated {now} MT</div>
</div>

<div class="container">

  <!-- AI FUN FACT (top of page) -->
  {fun_fact_html}

  <!-- ROW 1: Sentiment + Market Summary + Pre-Market Outlook -->
  <div class="grid-3">

    <div class="card accent-red">
      <h2>😨 Sentiment Indicators</h2>
      {fg_gauge}
      {breadth_bar}
    </div>

    <div class="card accent-blue">
      <h2>📊 Market Summary</h2>
      <ul>{fmt_bullets(sections.get("MARKET SUMMARY",""))}</ul>
    </div>

    <div class="card accent-green">
      <h2>🌅 Pre-Market Outlook</h2>
      <ul>{fmt_bullets(sections.get("PRE-MARKET OUTLOOK",""))}</ul>
    </div>

  </div>

  <!-- ROW 2: Key Moves + Macro & News -->
  <div class="grid-2" style="margin-top:14px;">
    <div class="card accent-amber">
      <h2>⚡ Key Moves</h2>
      <ul>{fmt_bullets(sections.get("KEY MOVES",""))}</ul>
    </div>
    <div class="card accent-red">
      <h2>🌐 Macro & News</h2>
      <ul>{fmt_bullets(sections.get("MACRO AND NEWS",""))}</ul>
    </div>
  </div>

  <!-- ROW 3: AI Briefing + Economic Calendar side by side -->
  <div class="grid-2" style="margin-top:14px;">

    <div class="card accent-green">
      <h2>💰 Earnings & AI Highlights</h2>
      <ul>{fmt_bullets(sections.get("EARNINGS AND CALENDAR",""))}</ul>
    </div>

    <div class="card accent-blue">
      <h2>📅 Economic Calendar
        <span style="font-weight:400;color:var(--muted);font-size:.58rem;">
          &nbsp; Last 3 days + Next 7 days · High-impact only · Source: FRED
        </span>
      </h2>
      <table class="cal-table">
        <thead>
          <tr style="background:#f3f4f6;">
            <th style="padding:6px 10px;font-size:.62rem;text-transform:uppercase;color:var(--muted);">When</th>
            <th style="padding:6px 10px;font-size:.62rem;text-transform:uppercase;color:var(--muted);">Impact</th>
            <th style="padding:6px 10px;font-size:.62rem;text-transform:uppercase;color:var(--muted);">Release</th>
            <th style="padding:6px 10px;font-size:.62rem;text-transform:uppercase;color:var(--muted);">Full Name</th>
          </tr>
        </thead>
        <tbody>
          {cal_rows}
        </tbody>
      </table>
    </div>

  </div>

  <!-- ROW 4: FRED Macro Table (alphabetical, with dynamic insights) -->
  <div style="margin-top:14px;">
    <div class="card">
      <h2>🏦 Macro Indicators
        <span style="font-weight:400;color:var(--muted);font-size:.58rem;">
          &nbsp; Source: Federal Reserve FRED API · Sorted alphabetically · As-of dates shown
        </span>
      </h2>
      <div style="overflow-x:auto;">
        <table class="fred-table">
          <thead>
            <tr>
              <th>Indicator</th>
              <th style="text-align:center;">Current</th>
              <th style="text-align:center;">3 Mo Ago</th>
              <th style="text-align:center;">12 Mo Ago</th>
              <th style="text-align:center;">Trend</th>
              <th>As Of</th>
              <th>What It Measures</th>
              <th>Today's Signal</th>
            </tr>
          </thead>
          <tbody>
            {fred_rows}
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- FOOTER: single clean credits line -->
  <div class="footer" style="margin-top:24px;">
    Built by <strong>Anil Abraham</strong> &nbsp;·&nbsp;
    <a href="https://www.edwardjones.com/us-en/market-news-insights/stock-market-news/daily-market-recap" target="_blank">Edward Jones</a> &nbsp;·&nbsp;
    <a href="https://www.cnbc.com/newsletters/" target="_blank">CNBC Squawk</a> &nbsp;·&nbsp;
    <a href="https://finance.yahoo.com" target="_blank">Yahoo Finance</a> &nbsp;·&nbsp;
    <a href="https://fred.stlouisfed.org" target="_blank">FRED API</a> &nbsp;·&nbsp;
    <a href="https://www.cnn.com/markets/fear-and-greed" target="_blank">CNN Fear &amp; Greed</a> &nbsp;·&nbsp;
    Gemini 3.6 Flash &nbsp;·&nbsp; GitHub Actions &nbsp;·&nbsp; Not financial advice.
  </div>

</div>
</body>
</html>"""

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("   ✅ index.html written successfully")


# ============================================================
# MAIN RUNNER
# ============================================================

if __name__ == "__main__":
    print("🚀 MarketPulse AI Starting...")
    print("=" * 50)

    fred_data      = fetch_fred_data()
    cal_events     = fetch_economic_calendar()
    fg_data        = fetch_fear_greed()
    breadth_data   = fetch_market_breadth()
    ej_text        = scrape_edward_jones()
    cnbc_text      = fetch_cnbc_email()
    yahoo_text     = fetch_yahoo_morning_brief()

    briefing = synthesize_with_gemini(
        ej_text, cnbc_text, yahoo_text,
        fred_data, fg_data, breadth_data, cal_events
    )

    build_html(
        briefing, ej_text, cnbc_text, yahoo_text,
        fred_data, fg_data, breadth_data, cal_events
    )

    print("\n📧 Email disabled -- dashboard is primary output")
    print("\n" + "=" * 50)
    print("✅ MarketPulse AI Complete!")
    print(f"🌐 https://anil2040.github.io/market-pulse-ai")
    print("=" * 50)