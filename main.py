# ============================================================
# MarketPulse AI - main.py
# Final version: September 2026
# ============================================================
# Pipeline (in order):
#   1. Fetch FRED macro indicators (parallel for speed)
#   2. Fetch CNN Fear & Greed Index
#   3. Fetch Market Breadth (% S&P 500 above 200-day MA)
#   4. Scrape Edward Jones daily recap
#   5. Read CNBC Morning Squawk email via IMAP
#   6. Read Yahoo Finance Morning Brief email via IMAP
#   7. Synthesize all sources with Gemini AI
#   8. Build HTML dashboard (index.html)
#   9. (Email disabled -- dashboard is primary output)
# ============================================================

import os
import imaplib
import email
import re
import concurrent.futures          # Parallel API calls -- speeds up FRED fetch!
from datetime import datetime, timezone, timedelta, date
import requests
from bs4 import BeautifulSoup
import google.genai as genai        # New google-genai SDK (not google-generativeai)

# --- SECRETS from GitHub Actions environment ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
YAHOO_EMAIL    = os.environ.get("YAHOO_EMAIL")
YAHOO_PASSWORD = os.environ.get("YAHOO_APP_PASSWORD")
FRED_API_KEY   = os.environ.get("FRED_API_KEY")

# --- TIMEZONE: Boise, Idaho Mountain Time ---
# MDT = UTC-6 (summer/now), MST = UTC-7 (winter, change in November)
MT = timezone(timedelta(hours=-6))

print("✅ Configuration loaded")
print(f"📧 Email: {YAHOO_EMAIL}")


# ============================================================
# STEP 1: FRED API -- Federal Reserve Economic Data
# ============================================================
# 12 indicators pulled in PARALLEL using ThreadPoolExecutor.
# Parallel = all 12 API calls fire simultaneously instead of
# one-by-one. Cuts FRED fetch time from ~30s to ~5s!
# JSON API -- clean structured data, no scraping needed.
# ============================================================

# Series config: label, FRED ID, whether it's a price INDEX
# (needs YoY % calc) vs a RATE (show as-is), release frequency,
# and one-line investing insight for the dashboard table.
FRED_SERIES = [
    {
        "label":    "Fed Funds Rate",
        "id":       "FEDFUNDS",
        "is_index": False,
        "freq":     "FOMC ~8x/year",
        "insight":  "Cost of borrowing -- rising = headwind for stocks",
    },
    {
        "label":    "CPI Inflation",
        "id":       "CPIAUCSL",
        "is_index": True,   # Raw index ~332 -- need YoY % change
        "freq":     "Monthly (BLS)",
        "insight":  "Headline inflation including food & energy",
    },
    {
        "label":    "Core CPI (ex Food/Energy)",
        "id":       "CPILFESL",
        "is_index": True,
        "freq":     "Monthly (BLS)",
        "insight":  "Cleaner inflation signal -- Fed watches closely",
    },
    {
        "label":    "PCE Inflation",
        "id":       "PCEPI",
        "is_index": True,
        "freq":     "Monthly (BEA)",
        "insight":  "Fed's preferred inflation measure (broader than CPI)",
    },
    {
        "label":    "Core PCE (Fed's 2% Target)",
        "id":       "PCEPILFE",
        "is_index": True,
        "freq":     "Monthly (BEA)",
        "insight":  "THE number Fed targets -- above 2% = rates stay high",
    },
    {
        "label":    "Unemployment Rate",
        "id":       "UNRATE",
        "is_index": False,
        "freq":     "Monthly (BLS Jobs Report)",
        "insight":  "Labor market health -- rising = recession risk",
    },
    {
        "label":    "10Y Treasury Yield",
        "id":       "GS10",
        "is_index": False,
        "freq":     "Daily",
        "insight":  "Risk-free rate -- benchmark for all stock valuations",
    },
    {
        "label":    "2Y Treasury Yield",
        "id":       "GS2",
        "is_index": False,
        "freq":     "Daily",
        "insight":  "Fed expectations -- rises when rate hikes expected",
    },
    {
        "label":    "Yield Curve (10Y minus 2Y)",
        "id":       "T10Y2Y",
        "is_index": False,
        "freq":     "Daily",
        "insight":  "Negative = inverted = historically predicts recession",
    },
    {
        "label":    "HY Credit Spread",
        "id":       "BAMLH0A0HYM2",
        "is_index": False,
        "freq":     "Daily",
        "insight":  "Widening = credit stress = systemic risk rising (bad for dip buys)",
    },
    {
        "label":    "WTI Crude Oil",
        "id":       "DCOILWTICO",
        "is_index": False,
        "freq":     "Daily",
        "insight":  "Energy prices -- affects inflation, margins, energy stocks",
    },
    {
        "label":    "U of Michigan Sentiment",
        "id":       "UMCSENT",
        "is_index": False,  # Already a 0-100 score -- show as-is, NO % needed
        "freq":     "Monthly (U of Michigan)",
        "insight":  "Consumer confidence -- leading indicator for spending",
    },
]


def _fetch_one_fred(cfg, start_date, end_date):
    """Fetch a single FRED series. Called in parallel via ThreadPoolExecutor."""
    label     = cfg["label"]
    series_id = cfg["id"]
    is_index  = cfg["is_index"]

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

        # Filter out missing values -- FRED uses "." for unavailable data
        obs = [o for o in data.get("observations", []) if o["value"] != "."]

        if not obs:
            return {**cfg, "current": "N/A", "mo3": "N/A", "mo12": "N/A",
                    "trend": "?", "date": "N/A"}

        # Latest, 3-month-ago, and 12-month-ago raw values
        val_now  = float(obs[0]["value"])
        val_3mo  = float(obs[min(3,  len(obs)-1)]["value"])
        val_12mo = float(obs[min(12, len(obs)-1)]["value"])

        if is_index and val_12mo != 0:
            # INDEX series: calculate Year-over-Year % change
            # e.g. CPI index was 321.5 a year ago, now 332.1
            # YoY inflation = (332.1 - 321.5) / 321.5 * 100 = 3.3%
            cur_rate  = (val_now  - val_12mo) / val_12mo * 100
            val_15mo  = float(obs[min(14, len(obs)-1)]["value"])
            mo3_rate  = (val_3mo  - val_15mo) / val_15mo * 100 if val_15mo else cur_rate
            mo12_rate = mo3_rate  # Approximation with our data window

            display_cur  = f"{cur_rate:.1f}%"
            display_mo3  = f"{mo3_rate:.1f}%"
            display_mo12 = f"{mo12_rate:.1f}%"

            # For inflation: DOWN trend (▼) = GOOD (cooling)
            trend = "▼" if cur_rate < mo3_rate - 0.05 else "▲" if cur_rate > mo3_rate + 0.05 else "→"

        else:
            # RATE series: show directly (already meaningful as-is)
            # Special case: U of Michigan is 0-100 index, show without %
            if series_id == "UMCSENT":
                display_cur  = f"{val_now:.1f}"
                display_mo3  = f"{val_3mo:.1f}"
                display_mo12 = f"{val_12mo:.1f}"
            else:
                display_cur  = f"{val_now:.2f}%"
                display_mo3  = f"{val_3mo:.2f}%"
                display_mo12 = f"{val_12mo:.2f}%"

            trend = "▲" if val_now > val_3mo + 0.05 else "▼" if val_now < val_3mo - 0.05 else "→"

        pub_date = datetime.strptime(obs[0]["date"], "%Y-%m-%d").strftime("%b %Y")

        return {
            **cfg,
            "current": display_cur,
            "mo3":     display_mo3,
            "mo12":    display_mo12,
            "trend":   trend,
            "date":    pub_date,
        }

    except Exception as e:
        return {**cfg, "current": "N/A", "mo3": "N/A", "mo12": "N/A",
                "trend": "?", "date": "N/A", "error": str(e)}


def fetch_fred_data():
    print("\n🏦 Fetching FRED macro indicators (parallel)...")

    end_date   = date.today().strftime("%Y-%m-%d")
    start_date = (date.today() - timedelta(days=460)).strftime("%Y-%m-%d")

    # ThreadPoolExecutor fires all 12 FRED calls simultaneously
    # Instead of 12 sequential waits, we get 1 combined wait!
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        futures = {
            executor.submit(_fetch_one_fred, cfg, start_date, end_date): cfg
            for cfg in FRED_SERIES
        }
        # Collect results in original order
        future_map = {f: cfg for f, cfg in futures.items()}
        result_map = {}
        for future in concurrent.futures.as_completed(futures):
            cfg = future_map[future]
            result = future.result()
            result_map[cfg["label"]] = result
            status = "✅" if result["current"] != "N/A" else "❌"
            print(f"   {status} {cfg['label']}: {result['current']} {result['trend']}")

    # Restore original order
    for cfg in FRED_SERIES:
        results.append(result_map.get(cfg["label"], {**cfg, "current": "N/A",
                                                     "mo3": "N/A", "mo12": "N/A",
                                                     "trend": "?", "date": "N/A"}))

    print(f"   🏦 FRED complete: {len(results)} indicators")
    return results


# ============================================================
# STEP 2: CNN FEAR & GREED INDEX
# ============================================================
# CNN updates this composite sentiment score once per day.
# Score 0-100: Extreme Fear / Fear / Neutral / Greed / Extreme Greed
# Fetched as JSON -- clean, fast, no HTML parsing needed!
# Warren Buffett's philosophy in one number: "be greedy when
# others are fearful" -- this tells you how fearful they are!
# ============================================================

def fetch_fear_greed():
    print("\n😨 Fetching CNN Fear & Greed Index...")
    try:
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()

        fg        = data.get("fear_and_greed", {})
        score     = round(float(fg.get("score", 50)))
        rating    = fg.get("rating", "Unknown").replace("_", " ").title()
        prev_close = round(float(fg.get("previous_close", score)))
        prev_week  = round(float(fg.get("previous_1_week",  score)))
        prev_month = round(float(fg.get("previous_1_month", score)))
        prev_year  = round(float(fg.get("previous_1_year",  score)))

        # Investing signal -- what this score means for action
        if score <= 24:
            signal = "Extreme Fear -- Historically strong buying opportunity"
            color  = "#c81e1e"
        elif score <= 44:
            signal = "Fear -- Market pessimism, watch for mean reversion entries"
            color  = "#e97316"
        elif score <= 55:
            signal = "Neutral -- No strong directional sentiment signal"
            color  = "#6b7280"
        elif score <= 74:
            signal = "Greed -- Optimism elevated, exercise caution on new buys"
            color  = "#059669"
        else:
            signal = "Extreme Greed -- Market overheated, high reversal risk"
            color  = "#1a56db"

        print(f"   ✅ Fear & Greed: {score}/100 ({rating})")
        return {
            "score": score, "rating": rating, "signal": signal, "color": color,
            "prev_close": prev_close, "prev_week": prev_week,
            "prev_month": prev_month, "prev_year": prev_year,
        }

    except Exception as e:
        print(f"   ❌ Fear & Greed failed: {e}")
        return {
            "score": "N/A", "rating": "Unavailable",
            "signal": "Data unavailable", "color": "#6b7280",
            "prev_close": "N/A", "prev_week": "N/A",
            "prev_month": "N/A", "prev_year": "N/A",
        }


# ============================================================
# STEP 3: MARKET BREADTH -- % S&P 500 Above 200-Day MA
# ============================================================
# Market breadth answers: "Is the whole market selling off,
# or just a few stocks?" For mean reversion investing:
# - Breadth under 25%: deeply oversold, strong buy signal
# - Breadth 25-40%: caution zone, selective buying
# - Breadth above 60%: healthy market, momentum favors bulls
# Fetches ^S5TH ticker via Yahoo Finance -- free, no API key!
# ============================================================

def fetch_market_breadth():
    print("\n📊 Fetching Market Breadth (% S&P 500 above 200-day MA)...")
    try:
        # Yahoo Finance API for ^S5TH (S&P 500 Bullish Percent Index)
        # This is the percentage of S&P 500 stocks above 200-day MA
        url = "https://query1.finance.yahoo.com/v8/finance/chart/%5ES5TH"
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()

        result = data["chart"]["result"][0]
        price  = result["meta"]["regularMarketPrice"]
        prev   = result["meta"]["previousClose"]
        change = price - prev

        # Interpret for mean reversion context
        if price < 25:
            breadth_signal = "DEEPLY OVERSOLD -- Strong mean reversion setup"
        elif price < 40:
            breadth_signal = "OVERSOLD -- Selective value opportunities emerging"
        elif price < 60:
            breadth_signal = "NEUTRAL -- Mixed breadth, stock-picking environment"
        elif price < 75:
            breadth_signal = "HEALTHY -- Broad participation, momentum intact"
        else:
            breadth_signal = "OVERBOUGHT -- Limited upside, reversal risk elevated"

        print(f"   ✅ Market Breadth: {price:.1f}% ({breadth_signal})")
        return {
            "value":   f"{price:.1f}%",
            "prev":    f"{prev:.1f}%",
            "change":  f"{change:+.1f}%",
            "signal":  breadth_signal,
        }

    except Exception as e:
        print(f"   ❌ Market Breadth failed: {e}")
        return {"value": "N/A", "prev": "N/A", "change": "N/A",
                "signal": "Data unavailable"}


# ============================================================
# STEP 4: SCRAPE EDWARD JONES DAILY RECAP
# ============================================================
# Web scraping: downloads the page HTML and extracts text.
# BeautifulSoup parses the HTML tree, we strip nav/footer junk.
# Headers make our request look like a real browser visit!
# Confirmed working: status 200, ~22,000 chars captured.
# ============================================================

def scrape_edward_jones():
    print("\n🔍 Scraping Edward Jones Daily Market Recap...")
    url = "https://www.edwardjones.com/us-en/market-news-insights/stock-market-news/daily-market-recap"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    try:
        resp = requests.get(url, headers=headers, timeout=15)
        print(f"   Status: {resp.status_code}")

        soup = BeautifulSoup(resp.text, "html.parser")
        # Remove junk tags -- navigation, ads, scripts, footers
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        lines      = [l.strip() for l in soup.get_text("\n", strip=True).splitlines() if l.strip()]
        clean_text = "\n".join(lines[:120])  # ~120 lines captures full article

        print(f"   ✅ Edward Jones: {len(clean_text)} chars")
        return clean_text

    except Exception as e:
        print(f"   ❌ Edward Jones failed: {e}")
        return "Edward Jones data unavailable today."


# ============================================================
# STEP 5 & 6: FETCH EMAILS VIA IMAP
# ============================================================
# IMAP = Internet Message Access Protocol
# imaplib connects to Yahoo mail server (port 993, SSL).
# We search by sender, always grab the LATEST email [-1].
# HTML newsletters are parsed with BeautifulSoup to get text.
# ============================================================

def _fetch_email(sender_address, label):
    """Generic email fetcher -- reused for CNBC and Yahoo Morning Brief."""
    try:
        mail = imaplib.IMAP4_SSL("imap.mail.yahoo.com", 993)
        mail.login(YAHOO_EMAIL, YAHOO_PASSWORD)
        mail.select("INBOX")

        status, messages = mail.search(None, f'(FROM "{sender_address}")')

        if status != "OK" or not messages[0]:
            print(f"   ⚠️ No {label} emails found")
            mail.logout()
            return f"{label} email not found today."

        email_ids = messages[0].split()
        latest_id = email_ids[-1]
        print(f"   Found {len(email_ids)} {label} emails, reading latest...")

        status, msg_data = mail.fetch(latest_id, "(RFC822)")
        raw_email        = msg_data[0][1]
        msg              = email.message_from_bytes(raw_email)

        body = ""

        # Try plain text first (cleaner for AI)
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                    break

        # Fall back to HTML -- strip tags with BeautifulSoup
        if not body:
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/html":
                        html_body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                        body      = BeautifulSoup(html_body, "html.parser").get_text("\n", strip=True)
                        break
            else:
                raw  = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
                body = BeautifulSoup(raw, "html.parser").get_text("\n", strip=True)

        mail.logout()

        # Trim to 2500 chars -- enough context without bloating the Gemini prompt
        # This removes repetitive footers and unsubscribe text, keeps the news!
        body = body[:2500].strip()
        print(f"   ✅ {label}: {len(body)} chars")
        return body

    except Exception as e:
        print(f"   ❌ {label} IMAP failed: {e}")
        return f"{label} unavailable today."


def fetch_cnbc_email():
    print("\n📬 Fetching CNBC Morning Squawk via IMAP...")
    # CNBC Morning Squawk -- arrives ~6:41 AM MT daily
    return _fetch_email("morningsquawk@response.cnbc.com", "CNBC Morning Squawk")


def fetch_yahoo_morning_brief():
    print("\n📬 Fetching Yahoo Finance Morning Brief via IMAP...")
    # Yahoo Finance Morning Brief -- arrives ~4 AM MT daily
    # Excellent for earnings calendar and economic events!
    # Note: verify exact sender address from your inbox first
    return _fetch_email("finance-morning-brief@newsletters.yahoo.net", "Yahoo Morning Brief")


# ============================================================
# STEP 7: GEMINI AI SYNTHESIS
# ============================================================
# Sends all data to Gemini 3.6 Flash for synthesis.
# Using google-genai SDK with Interactions API (Sep 2026).
# CRITICAL: explicit bullet format instructions in prompt
# prevent the "No data available" section parsing failure!
# Prompt is trimmed to essentials -- no junk text fed to AI.
# ============================================================

def synthesize_with_gemini(ej_text, cnbc_text, yahoo_text, fred_data, fg_data, breadth_data):
    print("\n🤖 Sending to Gemini AI for synthesis...")

    try:
        # Build compact FRED summary for prompt (key numbers only)
        fred_summary = "\n".join([
            f"- {r['label']}: {r['current']} (trend: {r['trend']}) -- {r['insight']}"
            for r in fred_data if r["current"] != "N/A"
        ])

        fg_line = f"Fear & Greed: {fg_data['score']}/100 ({fg_data['rating']}) | {fg_data['signal']}"
        breadth_line = f"Market Breadth (% above 200MA): {breadth_data['value']} | {breadth_data['signal']}"

        prompt = f"""You are a sharp financial analyst writing a pre-market briefing for a 
deep-value mean reversion investor (Greenblatt/Munger style).

STRICT FORMATTING RULES -- follow exactly:
- Use ONLY these 5 section headers, exactly as written, no numbers or symbols:
  MARKET SUMMARY
  KEY MOVES
  MACRO AND NEWS
  EARNINGS AND CALENDAR
  PRE-MARKET OUTLOOK
- Under each header: 3-5 bullet points starting with a dash (-)
- Each bullet: one specific fact, max 20 words, no bold text
- No paragraphs, no sub-bullets, no markdown headers

MACRO CONTEXT:
{fred_summary}
{fg_line}
{breadth_line}

SOURCE 1 - EDWARD JONES RECAP:
{ej_text[:1200]}

SOURCE 2 - CNBC MORNING SQUAWK:
{cnbc_text[:1000]}

SOURCE 3 - YAHOO MORNING BRIEF (focus on earnings & economic calendar):
{yahoo_text[:1000]}
"""

        client      = genai.Client(api_key=GEMINI_API_KEY)
        interaction = client.interactions.create(
            model="gemini-3.6-flash",
            input=prompt,
        )
        briefing = interaction.output_text
        print(f"   ✅ Gemini synthesis: {len(briefing)} chars")
        return briefing

    except Exception as e:
        print(f"   ❌ Gemini failed: {e}")
        # Fallback briefing so dashboard still shows something useful
        return """MARKET SUMMARY
- AI synthesis unavailable -- see raw source data in sections below

KEY MOVES
- Check Edward Jones and CNBC sources for market moves today

MACRO AND NEWS
- FRED macro indicators available in the table below

EARNINGS AND CALENDAR
- Check Yahoo Morning Brief source for today's earnings calendar

PRE-MARKET OUTLOOK
- Review all sources below for pre-market context"""


# ============================================================
# STEP 8: PARSE GEMINI OUTPUT INTO SECTIONS
# ============================================================
# Gemini sometimes adds markdown headers (##), numbers (1.),
# emojis, or bold markers (**) to section names.
# This parser strips ALL of that before matching.
# Prints debug output so you can see exactly what was captured!
# ============================================================

def parse_sections(briefing_text):
    sections = {
        "MARKET SUMMARY":      "",
        "KEY MOVES":           "",
        "MACRO AND NEWS":      "",
        "EARNINGS AND CALENDAR": "",
        "PRE-MARKET OUTLOOK":  "",
    }

    current = None
    for line in briefing_text.splitlines():
        upper   = line.upper().strip()
        # Strip: numbers (1. 1) ), markdown (## **), emojis (non-ASCII)
        cleaned = re.sub(r"^\d+[\.\)]\s*", "", upper)
        cleaned = re.sub(r"^#+\s*",         "", cleaned)
        cleaned = re.sub(r"^\*+\s*",         "", cleaned)
        cleaned = cleaned.encode("ascii", "ignore").decode().strip()

        # Flexible section matching -- handles any Gemini formatting variation
        if "MARKET SUMMARY"        in cleaned: current = "MARKET SUMMARY";      continue
        if "KEY MOVES"             in cleaned: current = "KEY MOVES";            continue
        if "MACRO AND NEWS"        in cleaned: current = "MACRO AND NEWS";       continue
        if "MACRO & NEWS"          in cleaned: current = "MACRO AND NEWS";       continue
        if "EARNINGS AND CALENDAR" in cleaned: current = "EARNINGS AND CALENDAR"; continue
        if "EARNINGS HIGHLIGHT"    in cleaned: current = "EARNINGS AND CALENDAR"; continue
        if "EARNINGS"              in cleaned and "CALENDAR" in cleaned: current = "EARNINGS AND CALENDAR"; continue
        if "PRE-MARKET OUTLOOK"    in cleaned: current = "PRE-MARKET OUTLOOK";  continue
        if "PRE MARKET OUTLOOK"    in cleaned: current = "PRE-MARKET OUTLOOK";  continue
        if "MORNING OUTLOOK"       in cleaned: current = "PRE-MARKET OUTLOOK";  continue

        if current and line.strip():
            sections[current] += line.strip() + "\n"

    # Debug output -- see exactly what each section captured
    for name, content in sections.items():
        status = f"{len(content)} chars" if content.strip() else "⚠️ EMPTY"
        print(f"   📋 {name}: {status}")

    return sections


# ============================================================
# STEP 9: FORMAT HELPERS
# ============================================================

def fmt_bullets(raw_text):
    """Convert raw bullet text to HTML list items."""
    if not raw_text or not raw_text.strip():
        return "<li>No data available</li>"
    items = ""
    for line in raw_text.strip().splitlines():
        line = re.sub(r"^[-•*]\s*", "", line.strip())
        line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
        if line:
            items += f"        <li>{line}</li>\n"
    return items or "<li>No data available</li>"


# ============================================================
# STEP 10: BUILD HTML DASHBOARD
# ============================================================
# Generates the complete index.html published by GitHub Pages.
# Key features:
# - SVG semicircle Fear & Greed gauge (like CNN's visual!)
# - Market Breadth indicator bar
# - FRED macro table with trend arrows and insights
# - Hidden #market-context div for Chrome extension
# - All times in Boise Mountain Time (MT)
# ============================================================

def build_html(briefing_text, ej_text, cnbc_text, yahoo_text,
               fred_data, fg_data, breadth_data):
    print("\n🎨 Building HTML dashboard...")

    sections = parse_sections(briefing_text)

    now_mt = datetime.now(MT)
    today  = now_mt.strftime("%A, %B %d, %Y")
    now    = now_mt.strftime("%I:%M %p")

    fg_score  = fg_data.get("score",  "N/A")
    fg_rating = fg_data.get("rating", "N/A")
    fg_signal = fg_data.get("signal", "")
    fg_color  = fg_data.get("color",  "#6b7280")

    # ---- SVG Fear & Greed Gauge (semicircle needle) --------
    # Classic CNN-style half-circle gauge with animated needle.
    # Score 0 = far left (red), 100 = far right (blue/green).
    # Needle angle: 0 score = -180deg, 100 score = 0deg
    try:
        score_num   = int(fg_score)
        needle_angle = -180 + (score_num * 1.8)  # Maps 0-100 to -180 to 0 degrees
    except:
        score_num    = 50
        needle_angle = -90

    fg_gauge_svg = f"""
    <svg viewBox="0 0 200 110" xmlns="http://www.w3.org/2000/svg" style="width:100%;max-width:280px;display:block;margin:0 auto;">
      <!-- Gauge arc segments: red=fear, orange, gray=neutral, green, blue=greed -->
      <!-- Each segment is a thick arc drawn with stroke-dasharray trick -->
      <path d="M 20 100 A 80 80 0 0 1 52 27" fill="none" stroke="#c81e1e" stroke-width="18" stroke-linecap="butt"/>
      <path d="M 52 27 A 80 80 0 0 1 100 20" fill="none" stroke="#e97316" stroke-width="18" stroke-linecap="butt"/>
      <path d="M 100 20 A 80 80 0 0 1 148 27" fill="none" stroke="#9ca3af" stroke-width="18" stroke-linecap="butt"/>
      <path d="M 148 27 A 80 80 0 0 1 180 100" fill="none" stroke="#059669" stroke-width="18" stroke-linecap="butt"/>
      <!-- Labels -->
      <text x="12" y="112" font-size="7" fill="#c81e1e" text-anchor="middle">Fear</text>
      <text x="188" y="112" font-size="7" fill="#059669" text-anchor="middle">Greed</text>
      <text x="100" y="15" font-size="7" fill="#6b7280" text-anchor="middle">Neutral</text>
      <!-- Needle: rotates from center of arc base -->
      <g transform="translate(100,100) rotate({needle_angle})">
        <line x1="0" y1="0" x2="0" y2="-72" stroke="#1e3a5f" stroke-width="3" stroke-linecap="round"/>
        <circle cx="0" cy="0" r="6" fill="#1e3a5f"/>
      </g>
      <!-- Score text -->
      <text x="100" y="92" font-size="22" font-weight="bold" fill="{fg_color}" text-anchor="middle">{fg_score}</text>
      <text x="100" y="105" font-size="8" fill="{fg_color}" text-anchor="middle">{fg_rating.upper()}</text>
    </svg>"""

    # ---- Market Breadth bar -----------------------------------
    try:
        breadth_val = float(breadth_data["value"].replace("%",""))
        bar_color   = "#c81e1e" if breadth_val < 30 else "#e97316" if breadth_val < 45 else "#6b7280" if breadth_val < 60 else "#059669"
    except:
        breadth_val = 50
        bar_color   = "#6b7280"

    breadth_bar = f"""
    <div style="margin-top:8px;">
      <div style="display:flex;justify-content:space-between;font-size:.72rem;color:#6b7280;margin-bottom:3px;">
        <span>0% Oversold</span><span>50% Neutral</span><span>100% Overbought</span>
      </div>
      <div style="background:#e5e7eb;border-radius:99px;height:14px;overflow:hidden;">
        <div style="width:{breadth_val}%;background:{bar_color};height:100%;border-radius:99px;transition:width .5s;"></div>
      </div>
      <div style="font-size:.78rem;color:{bar_color};font-weight:700;margin-top:4px;">
        {breadth_data['value']} &nbsp;·&nbsp; {breadth_data['signal']}
      </div>
      <div style="font-size:.72rem;color:#9ca3af;margin-top:2px;">
        vs Yesterday: {breadth_data['prev']} ({breadth_data['change']})
      </div>
    </div>"""

    # ---- FRED table rows -------------------------------------
    fred_rows = ""
    for r in (fred_data or []):
        # For inflation series: ▼ is GOOD (cooling) so color green
        if any(x in r["label"] for x in ["CPI", "PCE", "Inflation"]):
            tc = "#057a55" if r["trend"] == "▼" else "#c81e1e" if r["trend"] == "▲" else "#6b7280"
        else:
            tc = "#057a55" if r["trend"] == "▲" else "#c81e1e" if r["trend"] == "▼" else "#6b7280"

        fred_rows += f"""
        <tr>
          <td class="td-label">{r['label']}</td>
          <td class="td-val"><strong>{r['current']}</strong></td>
          <td class="td-val muted">{r['mo3']}</td>
          <td class="td-val muted">{r['mo12']}</td>
          <td class="td-center" style="color:{tc};font-size:1.1rem;">{r['trend']}</td>
          <td class="td-date muted">{r['date']}</td>
          <td class="td-insight muted">{r['insight']}</td>
        </tr>"""

    # ---- Hidden market-context div (for Chrome extension) ----
    fred_plain = "\n".join([
        f"  {r['label']}: {r['current']} (3mo: {r['mo3']}, trend: {r['trend']}) -- {r['insight']}"
        for r in (fred_data or [])
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
MARKET BREADTH: {breadth_data['value']} -- {breadth_data['signal']}

FRED MACRO INDICATORS:
{fred_plain}

SOURCES:
- Edward Jones Daily Market Recap (edwardjones.com)
- CNBC Morning Squawk (morningsquawk@response.cnbc.com)
- Yahoo Finance Morning Brief
- Federal Reserve FRED API (fred.stlouisfed.org)
- CNN Fear and Greed Index"""

    # ---- Full HTML page --------------------------------------
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>MarketPulse AI · {today}</title>
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
  body {{
    font-family: 'Segoe UI', system-ui, sans-serif;
    background: var(--bg); color: var(--ink);
    padding-bottom: 60px;
  }}
  .hero {{
    background: linear-gradient(135deg, #1e3a5f 0%, #1a56db 100%);
    color:#fff; padding:26px 24px 20px; text-align:center;
  }}
  .hero h1 {{ font-size:1.8rem; letter-spacing:3px; font-weight:800; }}
  .hero .sub {{ opacity:.85; margin-top:5px; font-size:.88rem; }}
  .hero .ts  {{ opacity:.6;  margin-top:3px; font-size:.72rem; }}
  .ticker {{
    background:#1e3a5f; color:#93c5fd; font-size:.72rem;
    padding:5px 16px; display:flex; gap:16px;
    flex-wrap:wrap; justify-content:center;
  }}
  .container {{ max-width:1200px; margin:20px auto; padding:0 14px; }}
  .grid-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:14px; }}
  .grid-3 {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:14px; }}
  .card {{
    background:var(--card); border:1px solid var(--border);
    border-radius:10px; padding:16px 18px;
    box-shadow:0 1px 3px rgba(0,0,0,.05);
  }}
  .card h2 {{
    font-size:.65rem; font-weight:700; letter-spacing:1.5px;
    text-transform:uppercase; color:var(--blue);
    margin-bottom:10px; padding-bottom:8px;
    border-bottom:2px solid var(--border);
  }}
  .card.accent-green {{ border-left:4px solid var(--green); }}
  .card.accent-blue  {{ border-left:4px solid var(--blue);  }}
  .card.accent-amber {{ border-left:4px solid var(--amber); }}
  .card.accent-red   {{ border-left:4px solid var(--red);   }}
  .card ul {{ list-style:none; padding:0; margin:0; }}
  .card ul li {{
    padding:5px 0 5px 14px; border-bottom:1px solid #f3f4f6;
    font-size:.84rem; line-height:1.5; color:#374151; position:relative;
  }}
  .card ul li:before {{
    content:"▸"; position:absolute; left:0;
    color:var(--blue); font-size:.78rem;
  }}
  .card ul li:last-child {{ border-bottom:none; }}
  .fred-table {{ width:100%; border-collapse:collapse; font-size:.78rem; }}
  .fred-table thead tr {{ background:#f3f4f6; }}
  .fred-table th {{
    padding:7px 10px; text-align:left; font-size:.65rem;
    letter-spacing:.5px; text-transform:uppercase;
    color:var(--muted); border-bottom:2px solid var(--border);
  }}
  .fred-table tbody tr {{ border-bottom:1px solid #f3f4f6; }}
  .fred-table tbody tr:hover {{ background:#fafafa; }}
  .td-label   {{ padding:7px 10px; font-weight:600; color:var(--ink); min-width:180px; }}
  .td-val     {{ padding:7px 10px; text-align:center; }}
  .td-center  {{ padding:7px 10px; text-align:center; }}
  .td-date    {{ padding:7px 10px; font-size:.72rem; white-space:nowrap; }}
  .td-insight {{ padding:7px 10px; font-size:.72rem; }}
  .muted      {{ color:var(--muted); }}
  .source-text {{
    font-size:.73rem; color:var(--muted); line-height:1.55;
    max-height:110px; overflow-y:auto;
  }}
  .footer {{
    text-align:center; color:var(--muted);
    font-size:.7rem; margin-top:28px; padding:0 14px;
  }}
  .footer a {{ color:var(--blue); text-decoration:none; }}
  @media(max-width:640px){{
    .grid-2,.grid-3{{ grid-template-columns:1fr; }}
    .hero h1{{ font-size:1.3rem; }}
    .td-insight,.td-date{{ display:none; }}
  }}
</style>
</head>
<body>

<!--
  HIDDEN MARKET CONTEXT DIV
  For Chrome Extension use:
    fetch('https://anil2040.github.io/market-pulse-ai/')
      .then(r => r.text())
      .then(html => {{
        const doc = new DOMParser().parseFromString(html,'text/html');
        const ctx = doc.getElementById('market-context').innerText;
        // Append ctx to your Finviz stock analysis!
      }});
-->
<div id="market-context" style="display:none;white-space:pre;">{market_context}</div>

<div class="hero">
  <h1>📈 MARKETPULSE AI</h1>
  <div class="sub">Anil Abraham &nbsp;·&nbsp; {today}</div>
  <div class="ts">
    Last updated {now} MT &nbsp;·&nbsp;
    Gemini 3.6 Flash &nbsp;·&nbsp; FRED API &nbsp;·&nbsp;
    CNN Fear &amp; Greed &nbsp;·&nbsp; Edward Jones &nbsp;·&nbsp; CNBC Squawk &nbsp;·&nbsp; Yahoo Finance
  </div>
</div>

<div class="ticker">
  ⏱ Auto-updated 6:55 AM MT weekdays &nbsp;|&nbsp;
  🤖 Gemini 3.6 Flash &nbsp;|&nbsp;
  🏦 FRED &nbsp;|&nbsp; 😨 CNN Fear &amp; Greed &nbsp;|&nbsp;
  📰 Edward Jones &nbsp;|&nbsp; 📧 CNBC + Yahoo Finance
</div>

<div class="container">

  <!-- ROW 1: Sentiment gauges + Market Summary + Pre-Market Outlook -->
  <div class="grid-3">

    <!-- FEAR & GREED + MARKET BREADTH combined card -->
    <div class="card accent-red">
      <h2>😨 Sentiment Indicators</h2>
      {fg_gauge_svg}
      <div style="font-size:.75rem;color:{fg_color};text-align:center;margin-top:4px;line-height:1.4;">{fg_signal}</div>
      <div style="margin-top:6px;font-size:.7rem;color:var(--muted);display:grid;grid-template-columns:1fr 1fr;gap:4px;">
        <div style="background:#f9fafb;border-radius:6px;padding:5px 7px;">
          <div style="color:var(--muted);">Yesterday</div>
          <div style="font-weight:700;">{fg_data.get('prev_close','N/A')}</div>
        </div>
        <div style="background:#f9fafb;border-radius:6px;padding:5px 7px;">
          <div style="color:var(--muted);">1 Week Ago</div>
          <div style="font-weight:700;">{fg_data.get('prev_week','N/A')}</div>
        </div>
        <div style="background:#f9fafb;border-radius:6px;padding:5px 7px;">
          <div style="color:var(--muted);">1 Month Ago</div>
          <div style="font-weight:700;">{fg_data.get('prev_month','N/A')}</div>
        </div>
        <div style="background:#f9fafb;border-radius:6px;padding:5px 7px;">
          <div style="color:var(--muted);">1 Year Ago</div>
          <div style="font-weight:700;">{fg_data.get('prev_year','N/A')}</div>
        </div>
      </div>
      <div style="margin-top:12px;">
        <div style="font-size:.65rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--blue);margin-bottom:6px;">
          📊 Market Breadth (% above 200MA)
        </div>
        {breadth_bar}
      </div>
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

  <!-- ROW 3: Earnings & Calendar (full width) -->
  <div style="margin-top:14px;">
    <div class="card accent-green">
      <h2>💰 Earnings & Economic Calendar</h2>
      <ul>{fmt_bullets(sections.get("EARNINGS AND CALENDAR",""))}</ul>
    </div>
  </div>

  <!-- ROW 4: FRED Macro Table -->
  <div style="margin-top:14px;">
    <div class="card">
      <h2>
        🏦 Macro Indicators
        <span style="font-weight:400;color:var(--muted);font-size:.6rem;">
          &nbsp; Federal Reserve FRED API (fred.stlouisfed.org) · Updated daily
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
              <th>Why It Matters</th>
            </tr>
          </thead>
          <tbody>
            {fred_rows}
          </tbody>
        </table>
      </div>
    </div>
  </div>

  <!-- ROW 5: Raw Sources -->
  <div class="grid-3" style="margin-top:14px;">
    <div class="card">
      <h2>📰 Edward Jones <span style="font-weight:400;font-size:.6rem;color:var(--muted);">edwardjones.com</span></h2>
      <div class="source-text">{" ".join(ej_text[:700].split())}</div>
    </div>
    <div class="card">
      <h2>📧 CNBC Squawk <span style="font-weight:400;font-size:.6rem;color:var(--muted);">morningsquawk@response.cnbc.com</span></h2>
      <div class="source-text">{" ".join(cnbc_text[:700].split())}</div>
    </div>
    <div class="card">
      <h2>📧 Yahoo Morning Brief <span style="font-weight:400;font-size:.6rem;color:var(--muted);">Yahoo Finance</span></h2>
      <div class="source-text">{" ".join(yahoo_text[:700].split())}</div>
    </div>
  </div>

  <div class="footer">
    MarketPulse AI &nbsp;·&nbsp; Built by anil2040 &nbsp;·&nbsp;
    <a href="https://www.edwardjones.com/us-en/market-news-insights/stock-market-news/daily-market-recap" target="_blank">Edward Jones</a> &nbsp;·&nbsp;
    <a href="https://www.cnbc.com/newsletters/" target="_blank">CNBC Squawk</a> &nbsp;·&nbsp;
    <a href="https://finance.yahoo.com/newsletters/" target="_blank">Yahoo Finance</a> &nbsp;·&nbsp;
    <a href="https://fred.stlouisfed.org" target="_blank">FRED API</a> &nbsp;·&nbsp;
    <a href="https://www.cnn.com/markets/fear-and-greed" target="_blank">CNN Fear &amp; Greed</a>
    &nbsp;·&nbsp; For informational purposes only. Not financial advice.
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
# if __name__ == "__main__" = only run when called directly.
# Calls each step in sequence, passes data between them.
# Email is DISABLED -- dashboard is the primary output!
# ============================================================

if __name__ == "__main__":
    print("🚀 MarketPulse AI Starting...")
    print("=" * 50)

    # Step 1: Fetch all data sources
    fred_data    = fetch_fred_data()       # 12 FRED indicators, parallel
    fg_data      = fetch_fear_greed()      # CNN Fear & Greed
    breadth_data = fetch_market_breadth()  # % S&P 500 above 200MA
    ej_text      = scrape_edward_jones()   # Edward Jones web scrape
    cnbc_text    = fetch_cnbc_email()      # CNBC Morning Squawk IMAP
    yahoo_text   = fetch_yahoo_morning_brief()  # Yahoo Finance IMAP

    # Step 2: AI synthesis
    briefing = synthesize_with_gemini(
        ej_text, cnbc_text, yahoo_text,
        fred_data, fg_data, breadth_data
    )

    # Step 3: Build dashboard
    build_html(
        briefing, ej_text, cnbc_text, yahoo_text,
        fred_data, fg_data, breadth_data
    )

    # Email DISABLED -- dashboard at GitHub Pages is primary output
    # To re-enable: uncomment send_email() call and restore function
    print("\n📧 Email disabled -- dashboard is primary output")

    print("\n" + "=" * 50)
    print("✅ MarketPulse AI Complete!")
    print(f"🌐 https://anil2040.github.io/market-pulse-ai")
    print("=" * 50)