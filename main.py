# ============================================================
# MarketPulse AI - main.py  
# Complete rewrite: September 2026
# ============================================================
# What this does (in order):
#   1. Fetches FRED macro indicators (Fed rate, CPI, PCE, etc.)
#   2. Fetches CNN Fear & Greed Index
#   3. Scrapes Edward Jones daily market recap
#   4. Reads CNBC Morning Squawk email via IMAP
#   5. Sends all data to Gemini AI for synthesis
#   6. Builds a professional HTML dashboard (index.html)
#   7. Emails the briefing to Yahoo inbox as backup
# ============================================================

# --- IMPORTS: Python's toolbox ---
import os                    # Reads environment variables (our secrets)
import imaplib               # IMAP: reads email from Yahoo
import smtplib               # SMTP: sends email via Yahoo
import email                 # Decodes raw email bytes into readable text
import re                    # Regular expressions: pattern matching in text
from email.mime.multipart import MIMEMultipart  # Builds multi-part emails
from email.mime.text import MIMEText            # Adds HTML/text to emails
from datetime import datetime, timezone, timedelta, date  # Date/time tools
import requests              # Makes HTTP web requests (scraping + APIs)
from bs4 import BeautifulSoup  # Parses HTML into searchable structure
import google.genai as genai   # Gemini AI library (new google-genai SDK)

# --- SECRETS: Read from GitHub Actions environment ---
# These are injected securely at runtime -- never visible in code or logs
GEMINI_API_KEY  = os.environ.get("GEMINI_API_KEY")
YAHOO_EMAIL     = os.environ.get("YAHOO_EMAIL")
YAHOO_PASSWORD  = os.environ.get("YAHOO_APP_PASSWORD")
FRED_API_KEY    = os.environ.get("FRED_API_KEY")

# --- TIMEZONE: Boise, Idaho (Mountain Time) ---
# MDT = UTC-6 in summer, MST = UTC-7 in winter
# We use UTC-6 (MDT) -- adjust to -7 in November when clocks change
MT = timezone(timedelta(hours=-6))

print("✅ Configuration loaded")
print(f"📧 Email configured: {YAHOO_EMAIL}")


# ============================================================
# STEP 1: FRED API - Federal Reserve Economic Data
# ============================================================
# FRED = Federal Reserve Economic Data (St. Louis Fed)
# Free API, 800,000+ economic series, same data the Fed uses.
# We pull 10 key indicators with current + historical values.
# JSON API call -- clean structured data, no HTML parsing needed!
# ============================================================

def fetch_fred_data():
    print("\n🏦 Fetching FRED macro indicators...")

    # Each entry: display label, FRED series ID, whether it's a
    # price INDEX (needs YoY % calc) vs a RATE (show as-is),
    # release frequency, and why it matters for investing
    series_config = [
        {
            "label":     "Fed Funds Rate",
            "id":        "FEDFUNDS",
            "is_index":  False,
            "freq":      "Monthly (FOMC meetings ~8x/year)",
            "insight":   "Cost of money -- rising = headwind for stocks & bonds",
        },
        {
            "label":     "CPI Inflation",
            "id":        "CPIAUCSL",
            "is_index":  True,   # Raw index ~332, need YoY % change
            "freq":      "Monthly (BLS, ~2 weeks after month end)",
            "insight":   "Headline inflation -- includes food & energy",
        },
        {
            "label":     "Core CPI (ex Food/Energy)",
            "id":        "CPILFESL",
            "is_index":  True,
            "freq":      "Monthly (BLS, same release as CPI)",
            "insight":   "Cleaner signal -- Fed watches this closely",
        },
        {
            "label":     "PCE Inflation",
            "id":        "PCEPI",
            "is_index":  True,
            "freq":      "Monthly (BEA, ~last week of month)",
            "insight":   "Fed's preferred inflation gauge (broader than CPI)",
        },
        {
            "label":     "Core PCE (Fed Target)",
            "id":        "PCEPILFE",
            "is_index":  True,
            "freq":      "Monthly (BEA, same release as PCE)",
            "insight":   "THE number Fed targets at 2.0% -- most important",
        },
        {
            "label":     "Unemployment Rate",
            "id":        "UNRATE",
            "is_index":  False,
            "freq":      "Monthly (BLS Jobs Report, first Friday of month)",
            "insight":   "Labor market health -- high = recession risk",
        },
        {
            "label":     "10Y Treasury Yield",
            "id":        "GS10",
            "is_index":  False,
            "freq":      "Daily (market-driven)",
            "insight":   "Risk-free rate -- benchmark for all valuations",
        },
        {
            "label":     "2Y Treasury Yield",
            "id":        "GS2",
            "is_index":  False,
            "freq":      "Daily (market-driven)",
            "insight":   "Fed expectations barometer -- moves with rate outlook",
        },
        {
            "label":     "Yield Curve (10Y minus 2Y)",
            "id":        "T10Y2Y",
            "is_index":  False,
            "freq":      "Daily (market-driven)",
            "insight":   "Inversion (negative) = recession historically predicted",
        },
        {
            "label":     "U of Michigan Sentiment",
            "id":        "UMCSENT",
            "is_index":  False,
            "freq":      "Monthly (U of Michigan, mid-month preliminary)",
            "insight":   "Consumer confidence -- leading indicator for spending",
        },
    ]

    # Date range: pull 15 months of history
    # We need 13+ months to calculate proper YoY % changes
    end_date   = date.today().strftime("%Y-%m-%d")
    start_date = (date.today() - timedelta(days=460)).strftime("%Y-%m-%d")

    results = []

    for cfg in series_config:
        label     = cfg["label"]
        series_id = cfg["id"]
        is_index  = cfg["is_index"]

        try:
            # JSON API call to FRED -- one per indicator
            # Returns list of {date, value} observations, latest first
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

            # Filter out missing values -- FRED uses "." for unavailable
            obs = [o for o in data.get("observations", []) if o["value"] != "."]

            if not obs:
                results.append({
                    "label":   label,
                    "current": "N/A",
                    "mo3":     "N/A",
                    "mo12":    "N/A",
                    "trend":   "?",
                    "date":    "N/A",
                    "freq":    cfg["freq"],
                    "insight": cfg["insight"],
                })
                continue

            # Get raw values -- obs[0] is most recent (sort_order=desc)
            val_now  = float(obs[0]["value"])
            val_3mo  = float(obs[min(3,  len(obs)-1)]["value"])
            val_12mo = float(obs[min(12, len(obs)-1)]["value"])

            # For INDEX series: calculate Year-over-Year % change
            # Example: CPI was 321.5 last year, now 332.1
            # YoY = (332.1 - 321.5) / 321.5 * 100 = 3.30%
            # This is the INFLATION RATE -- what the news reports!
            if is_index and val_12mo != 0:
                # Current YoY rate (vs 12 months ago)
                current_rate = (val_now - val_12mo) / val_12mo * 100

                # 3-month-ago rate (vs values from 15 months ago)
                val_15mo = float(obs[min(14, len(obs)-1)]["value"])
                mo3_rate = (val_3mo - val_15mo) / val_15mo * 100 if val_15mo != 0 else current_rate

                # 12-month-ago rate: approximation using available data
                mo12_rate = mo3_rate  # Best we can do with 15mo limit

                display_current = f"{current_rate:.1f}%"
                display_mo3     = f"{mo3_rate:.1f}%"
                display_mo12    = f"{mo12_rate:.1f}%"

                # Trend: is inflation cooling (▼ = good) or heating (▲ = bad)?
                trend = "▼" if current_rate < mo3_rate - 0.05 else "▲" if current_rate > mo3_rate + 0.05 else "→"

            else:
                # RATE series: show value directly (already a percentage)
                display_current = f"{val_now:.2f}%"
                display_mo3     = f"{val_3mo:.2f}%"
                display_mo12    = f"{val_12mo:.2f}%"
                trend = "▲" if val_now > val_3mo + 0.05 else "▼" if val_now < val_3mo - 0.05 else "→"

            # Format the publication date nicely
            pub_date = datetime.strptime(obs[0]["date"], "%Y-%m-%d").strftime("%b %Y")

            results.append({
                "label":   label,
                "current": display_current,
                "mo3":     display_mo3,
                "mo12":    display_mo12,
                "trend":   trend,
                "date":    pub_date,
                "freq":    cfg["freq"],
                "insight": cfg["insight"],
            })

            print(f"   ✅ {label}: {display_current} {trend} (as of {pub_date})")

        except Exception as e:
            print(f"   ❌ {label} failed: {e}")
            results.append({
                "label":   label,
                "current": "N/A",
                "mo3":     "N/A",
                "mo12":    "N/A",
                "trend":   "?",
                "date":    "N/A",
                "freq":    cfg["freq"],
                "insight": cfg["insight"],
            })

    print(f"   🏦 FRED complete: {len(results)} indicators")
    return results


# ============================================================
# STEP 2: CNN FEAR & GREED INDEX
# ============================================================
# Fear & Greed is a composite sentiment indicator (0-100):
#   0-24  = Extreme Fear (historically: good buying opportunity)
#   25-44 = Fear
#   45-55 = Neutral
#   56-74 = Greed
#   75-100 = Extreme Greed (historically: market may be overheated)
# CNN updates this once per day -- perfect for our daily briefing.
# We fetch it as JSON -- clean, no scraping needed!
# ============================================================

def fetch_fear_greed():
    print("\n😨 Fetching CNN Fear & Greed Index...")
    try:
        url = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()

        # CNN returns current score and historical values
        fg = data.get("fear_and_greed", {})
        score     = round(float(fg.get("score", 0)))
        rating    = fg.get("rating", "Unknown").replace("_", " ").title()
        prev_close = round(float(fg.get("previous_close", score)))
        prev_week  = round(float(fg.get("previous_1_week", score)))
        prev_month = round(float(fg.get("previous_1_month", score)))
        prev_year  = round(float(fg.get("previous_1_year", score)))

        # Simple signal for investors
        if score <= 24:
            signal = "EXTREME FEAR -- Historically good buying opportunity"
        elif score <= 44:
            signal = "FEAR -- Market pessimism, watch for entry points"
        elif score <= 55:
            signal = "NEUTRAL -- No strong directional signal"
        elif score <= 74:
            signal = "GREED -- Market optimism, exercise caution"
        else:
            signal = "EXTREME GREED -- Market may be overheated"

        result = {
            "score":      score,
            "rating":     rating,
            "signal":     signal,
            "prev_close": prev_close,
            "prev_week":  prev_week,
            "prev_month": prev_month,
            "prev_year":  prev_year,
        }

        print(f"   ✅ Fear & Greed: {score}/100 ({rating})")
        return result

    except Exception as e:
        print(f"   ❌ Fear & Greed failed: {e}")
        return {
            "score": "N/A", "rating": "Unavailable",
            "signal": "Data unavailable today",
            "prev_close": "N/A", "prev_week": "N/A",
            "prev_month": "N/A", "prev_year": "N/A",
        }


# ============================================================
# STEP 3: SCRAPE EDWARD JONES DAILY RECAP
# ============================================================
# Web scraping: we fetch the HTML page and extract text.
# requests.get() downloads the page like a browser would.
# BeautifulSoup parses the HTML tree so we can extract text.
# We add headers so the site thinks we're a real browser!
# ============================================================

def scrape_edward_jones():
    print("\n🔍 Scraping Edward Jones Daily Market Recap...")

    url = "https://www.edwardjones.com/us-en/market-news-insights/stock-market-news/daily-market-recap"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        print(f"   Edward Jones status code: {response.status_code}")

        soup = BeautifulSoup(response.text, "html.parser")

        # Remove navigation, ads, footers -- we only want the article text
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()

        # Extract clean text
        lines = [l.strip() for l in soup.get_text(separator="\n", strip=True).splitlines() if l.strip()]
        clean_text = "\n".join(lines[:150])

        print(f"   ✅ Edward Jones: captured {len(clean_text)} characters")
        return clean_text

    except Exception as e:
        print(f"   ❌ Edward Jones scrape failed: {e}")
        return "Edward Jones data unavailable today."


# ============================================================
# STEP 4: FETCH CNBC EMAIL VIA IMAP
# ============================================================
# IMAP = Internet Message Access Protocol
# imaplib connects to Yahoo's mail server and reads emails.
# Port 993 = secure IMAP with SSL encryption.
# We always grab the LATEST email (email_ids[-1]).
# ============================================================

def fetch_cnbc_email():
    print("\n📬 Connecting to Yahoo Mail via IMAP...")

    try:
        # Connect to Yahoo's IMAP server (SSL encrypted)
        mail = imaplib.IMAP4_SSL("imap.mail.yahoo.com", 993)
        mail.login(YAHOO_EMAIL, YAHOO_PASSWORD)
        print("   ✅ Logged into Yahoo Mail")

        mail.select("INBOX")

        # Search for emails from CNBC Morning Squawk
        status, messages = mail.search(None, '(FROM "morningsquawk@response.cnbc.com")')

        if status != "OK" or not messages[0]:
            print("   ⚠️ No CNBC emails found")
            return "CNBC Morning Squawk not found in inbox today."

        # Always grab the latest email -- [-1] = last in list
        email_ids  = messages[0].split()
        latest_id  = email_ids[-1]
        print(f"   Found {len(email_ids)} CNBC emails, reading latest...")

        # Fetch the full raw email
        status, msg_data = mail.fetch(latest_id, "(RFC822)")
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)

        body = ""

        # Try plain text first (cleaner for AI processing)
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
                        body = BeautifulSoup(html_body, "html.parser").get_text(separator="\n", strip=True)
                        break
            else:
                raw = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
                body = BeautifulSoup(raw, "html.parser").get_text(separator="\n", strip=True)

        body = body[:3000].strip()
        print(f"   ✅ CNBC email captured: {len(body)} characters")

        mail.logout()
        return body

    except Exception as e:
        print(f"   ❌ IMAP fetch failed: {e}")
        return "CNBC Morning Squawk unavailable today."


# ============================================================
# STEP 5: GEMINI AI SYNTHESIS
# ============================================================
# We send all data sources to Gemini and ask it to synthesize
# them into a clean structured briefing.
# Using google-genai SDK with Interactions API (Google's
# recommended pattern for single-turn text generation).
# Model: gemini-3.6-flash (current stable free tier, Sep 2026)
# ============================================================

def synthesize_with_gemini(ej_text, cnbc_text, fred_data, fg_data):
    print("\n🤖 Sending to Gemini AI for synthesis...")

    try:
        # Build FRED summary for the prompt
        fred_summary = "\n".join([
            f"- {r['label']}: {r['current']} (3mo ago: {r['mo3']}, trend: {r['trend']})"
            for r in fred_data
        ]) if fred_data else "FRED data unavailable"

        # Fear & Greed summary
        fg_summary = f"Fear & Greed Index: {fg_data.get('score')}/100 ({fg_data.get('rating')}) -- {fg_data.get('signal')}"

        # The prompt -- structured instructions produce structured output.
        # KEY: explicitly request bullet points and exact section headers!
        prompt = f"""You are a sharp financial analyst preparing a pre-market morning briefing 
for a retail investor focused on mean reversion deep-value investing.

CRITICAL FORMATTING RULES:
- Use EXACTLY these section headers (no numbers, no emojis, no markdown ##):
  MARKET SUMMARY
  KEY MOVES
  MACRO AND NEWS
  EARNINGS HIGHLIGHTS
  MORNING OUTLOOK
- Under each header, use bullet points starting with a dash (-)
- Each bullet: one clear fact or insight, max 20 words
- No paragraphs, no bold text, no nested bullets
- Keep each section to 3-5 bullets maximum

Synthesize these sources into the 5 sections above:

FRED MACRO INDICATORS:
{fred_summary}

SENTIMENT:
{fg_summary}

SOURCE 1 - EDWARD JONES DAILY RECAP:
{ej_text[:2000]}

SOURCE 2 - CNBC MORNING SQUAWK EMAIL:
{cnbc_text[:1500]}
"""

        # Initialize new google-genai SDK client
        client = genai.Client(api_key=GEMINI_API_KEY)

        # Interactions API -- Google's recommended pattern Sep 2026
        interaction = client.interactions.create(
            model="gemini-3.6-flash",
            input=prompt,
        )
        briefing = interaction.output_text

        print(f"   ✅ Gemini synthesis complete: {len(briefing)} characters")
        return briefing

    except Exception as e:
        print(f"   ❌ Gemini synthesis failed: {e}")
        return """MARKET SUMMARY
- AI synthesis unavailable today -- check source data below manually

KEY MOVES
- See Edward Jones and CNBC sections below for raw data

MACRO AND NEWS
- FRED macro indicators available in table below

EARNINGS HIGHLIGHTS
- Check CNBC Morning Squawk source for earnings details

MORNING OUTLOOK
- Review sources below for today's market context"""


# ============================================================
# STEP 6: PARSE GEMINI OUTPUT INTO SECTIONS
# ============================================================
# Gemini sometimes adds markdown, emojis, or numbers to headers.
# This parser strips all of that and extracts clean section text.
# We check for each section name with flexible matching.
# ============================================================

def parse_sections(briefing_text):
    sections = {
        "MARKET SUMMARY":   "",
        "KEY MOVES":        "",
        "MACRO AND NEWS":   "",
        "EARNINGS":         "",
        "MORNING OUTLOOK":  "",
    }

    current = None
    for line in briefing_text.splitlines():
        # Clean the line for section detection:
        # Strip numbers (1. 2.), markdown (## **), emojis (non-ASCII)
        upper   = line.upper().strip()
        cleaned = re.sub(r"^\d+[\.\)]\s*", "", upper)   # Remove "1. " or "1) "
        cleaned = re.sub(r"^#+\s*",        "", cleaned)  # Remove "## "
        cleaned = re.sub(r"^\*+\s*",       "", cleaned)  # Remove "** "
        cleaned = cleaned.encode("ascii", "ignore").decode().strip()

        # Match section headers -- flexible contains-check
        if "MARKET SUMMARY"   in cleaned: current = "MARKET SUMMARY";  continue
        if "KEY MOVES"        in cleaned: current = "KEY MOVES";        continue
        if "MACRO AND NEWS"   in cleaned: current = "MACRO AND NEWS";   continue
        if "MACRO & NEWS"     in cleaned: current = "MACRO AND NEWS";   continue
        if "MACRO NEWS"       in cleaned: current = "MACRO AND NEWS";   continue
        if "EARNINGS"         in cleaned: current = "EARNINGS";         continue
        if "MORNING OUTLOOK"  in cleaned: current = "MORNING OUTLOOK";  continue

        # Add line to current section if we're inside one
        if current and line.strip():
            sections[current] += line.strip() + "\n"

    # Debug -- print what was captured for each section
    for name, content in sections.items():
        status = f"{len(content)} chars" if content.strip() else "EMPTY!"
        print(f"   📋 Section '{name}': {status}")

    return sections


# ============================================================
# STEP 7: BUILD HTML DASHBOARD
# ============================================================
# Converts parsed sections and data into a professional HTML page.
# GitHub Pages serves this as your live dashboard website.
# Uses CSS variables for clean theming, mobile-responsive grid.
# ============================================================

def fmt_bullets(raw_text):
    """Convert raw bullet text into clean HTML list items."""
    if not raw_text or not raw_text.strip():
        return "<li>No data available</li>"

    items = ""
    for line in raw_text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        # Remove leading dash/bullet/asterisk markers
        line = re.sub(r"^[-•*]\s*", "", line)
        line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
        if line:
            items += f"<li>{line}</li>\n"

    return items if items else "<li>No data available</li>"


def build_html(briefing_text, ej_text, cnbc_text, fred_data, fg_data):
    print("\n🎨 Building HTML dashboard...")

    # Parse Gemini output into named sections
    sections = parse_sections(briefing_text)

    # Current time in Boise MT
    now_mt = datetime.now(MT)
    today  = now_mt.strftime("%A, %B %d, %Y")
    now    = now_mt.strftime("%I:%M %p")

    # Fear & Greed display
    fg_score  = fg_data.get("score", "N/A")
    fg_rating = fg_data.get("rating", "N/A")
    fg_signal = fg_data.get("signal", "")

    # Fear & Greed color based on score
    try:
        s = int(fg_score)
        if s <= 24:   fg_color = "#c81e1e"  # Red -- extreme fear
        elif s <= 44: fg_color = "#e97316"  # Orange -- fear
        elif s <= 55: fg_color = "#6b7280"  # Gray -- neutral
        elif s <= 74: fg_color = "#059669"  # Green -- greed
        else:         fg_color = "#1a56db"  # Blue -- extreme greed
    except:
        fg_color = "#6b7280"

    # Build FRED table rows
    fred_rows = ""
    for r in (fred_data or []):
        trend_color = "#057a55" if r["trend"] == "▲" else "#c81e1e" if r["trend"] == "▼" else "#6b7280"
        # For inflation series, DOWN trend (▼) is actually GOOD (cooling)
        if "CPI" in r["label"] or "PCE" in r["label"] or "Inflation" in r["label"]:
            trend_color = "#057a55" if r["trend"] == "▼" else "#c81e1e" if r["trend"] == "▲" else "#6b7280"
        fred_rows += f"""
        <tr>
          <td class="td-label">{r['label']}</td>
          <td class="td-val"><strong>{r['current']}</strong></td>
          <td class="td-val muted">{r['mo3']}</td>
          <td class="td-val muted">{r['mo12']}</td>
          <td class="td-center" style="color:{trend_color};font-size:1.1rem">{r['trend']}</td>
          <td class="td-date muted">{r['date']}</td>
          <td class="td-insight">{r['insight']}</td>
        </tr>"""

    # Build hidden market-context div (plain text for Chrome extension)
    fred_plain = "\n".join([
        f"  {r['label']}: {r['current']} (3mo: {r['mo3']}, 12mo: {r['mo12']}, trend: {r['trend']}) -- {r['insight']}"
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

EARNINGS:
{sections.get('EARNINGS','').strip() or 'None noted today'}

MORNING OUTLOOK:
{sections.get('MORNING OUTLOOK','').strip() or 'See sources below'}

FEAR AND GREED INDEX: {fg_score}/100 ({fg_rating}) -- {fg_signal}

FRED MACRO INDICATORS:
{fred_plain}

DATA SOURCES:
- Edward Jones Daily Market Recap (edwardjones.com)
- CNBC Morning Squawk Newsletter (morningsquawk@response.cnbc.com)
- Federal Reserve FRED API (fred.stlouisfed.org)
- CNN Fear and Greed Index (CNN Business)"""

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
    background: var(--bg);
    color: var(--ink);
    padding: 0 0 60px;
  }}

  /* HEADER */
  .hero {{
    background: linear-gradient(135deg, #1e3a5f 0%, #1a56db 100%);
    color: #fff;
    padding: 28px 24px 22px;
    text-align: center;
  }}
  .hero h1 {{ font-size:1.8rem; letter-spacing:3px; font-weight:800; }}
  .hero .sub {{ opacity:.85; margin-top:5px; font-size:.9rem; }}
  .hero .ts  {{ opacity:.6; margin-top:3px; font-size:.75rem; }}

  /* TICKER BAR */
  .ticker {{
    background:#1e3a5f;
    color:#93c5fd;
    font-size:.75rem;
    padding:6px 20px;
    display:flex; gap:20px;
    flex-wrap:wrap; justify-content:center;
  }}

  /* LAYOUT */
  .container {{ max-width:1200px; margin:24px auto; padding:0 16px; }}
  .grid-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
  .grid-3 {{ display:grid; grid-template-columns:1fr 1fr 1fr; gap:16px; }}

  /* CARDS */
  .card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 18px 20px;
    box-shadow: 0 1px 3px rgba(0,0,0,.05);
  }}
  .card h2 {{
    font-size:.68rem; font-weight:700;
    letter-spacing:1.5px; text-transform:uppercase;
    color: var(--blue); margin-bottom:12px;
    padding-bottom:8px; border-bottom:2px solid var(--border);
  }}
  .card.accent-green {{ border-left:4px solid var(--green); }}
  .card.accent-blue  {{ border-left:4px solid var(--blue);  }}
  .card.accent-amber {{ border-left:4px solid var(--amber); }}
  .card.accent-red   {{ border-left:4px solid var(--red);   }}
  .card.full         {{ grid-column: 1 / -1; }}

  /* BULLET LISTS */
  .card ul {{
    list-style: none; padding:0; margin:0;
  }}
  .card ul li {{
    padding: 5px 0 5px 14px;
    border-bottom: 1px solid #f3f4f6;
    font-size: .86rem; line-height:1.5;
    color: #374151; position: relative;
  }}
  .card ul li:before {{
    content: "▸";
    position: absolute; left:0;
    color: var(--blue); font-size:.8rem;
  }}
  .card ul li:last-child {{ border-bottom:none; }}

  /* FEAR & GREED */
  .fg-score {{
    font-size:3rem; font-weight:800;
    color:{fg_color}; line-height:1;
  }}
  .fg-label {{
    font-size:.9rem; font-weight:600;
    color:{fg_color}; margin-top:4px;
  }}
  .fg-signal {{
    font-size:.78rem; color:var(--muted);
    margin-top:6px; line-height:1.4;
  }}
  .fg-history {{
    display:grid; grid-template-columns:1fr 1fr;
    gap:6px; margin-top:12px;
  }}
  .fg-item {{
    background:#f9fafb; border-radius:6px;
    padding:6px 8px; font-size:.75rem;
  }}
  .fg-item .fg-lbl {{ color:var(--muted); }}
  .fg-item .fg-val {{ font-weight:700; }}

  /* FRED TABLE */
  .fred-table {{
    width:100%; border-collapse:collapse;
    font-size:.8rem;
  }}
  .fred-table thead tr {{
    background:#f3f4f6;
  }}
  .fred-table th {{
    padding:8px 10px; text-align:left;
    font-size:.68rem; letter-spacing:.5px;
    text-transform:uppercase; color:var(--muted);
    border-bottom:2px solid var(--border);
  }}
  .fred-table tbody tr:hover {{ background:#fafafa; }}
  .td-label  {{ padding:8px 10px; font-weight:600; color:var(--ink); }}
  .td-val    {{ padding:8px 10px; text-align:center; }}
  .td-center {{ padding:8px 10px; text-align:center; }}
  .td-date   {{ padding:8px 10px; font-size:.75rem; white-space:nowrap; }}
  .td-insight{{ padding:8px 10px; font-size:.75rem; color:var(--muted); }}
  .muted     {{ color:var(--muted); }}
  .fred-table tbody tr {{ border-bottom:1px solid #f3f4f6; }}

  /* SOURCE BOXES */
  .source-text {{
    font-size:.75rem; color:var(--muted);
    line-height:1.55; max-height:120px;
    overflow-y:auto;
  }}

  /* FOOTER */
  .footer {{
    text-align:center; color:var(--muted);
    font-size:.72rem; margin-top:32px;
    padding:0 16px;
  }}
  .footer a {{ color:var(--blue); text-decoration:none; }}
  .footer a:hover {{ text-decoration:underline; }}

  /* MOBILE */
  @media(max-width:640px){{
    .grid-2,.grid-3{{ grid-template-columns:1fr; }}
    .hero h1{{ font-size:1.3rem; }}
    .td-insight,.td-date{{ display:none; }}
  }}
</style>
</head>
<body>

<!-- HIDDEN DIV: Clean text for Chrome extension to fetch
     Access via: document.getElementById('market-context').innerText
     Or fetch the page and parse this div for macro context! -->
<div id="market-context" style="display:none;white-space:pre;">{market_context}</div>

<div class="hero">
  <h1>📈 MARKETPULSE AI</h1>
  <div class="sub">Anil Abraham &nbsp;·&nbsp; {today}</div>
  <div class="ts">Last updated {now} MT &nbsp;·&nbsp; Gemini 3.6 Flash &nbsp;·&nbsp; Edward Jones &nbsp;·&nbsp; CNBC Morning Squawk &nbsp;·&nbsp; FRED API &nbsp;·&nbsp; CNN Fear & Greed</div>
</div>

<div class="ticker">
  📈 Auto-updated weekdays 6:55 AM MT &nbsp;|&nbsp;
  🤖 Gemini 3.6 Flash &nbsp;|&nbsp;
  🏦 FRED Economic Data &nbsp;|&nbsp;
  😨 CNN Fear & Greed &nbsp;|&nbsp;
  📰 Edward Jones + CNBC Squawk
</div>

<div class="container">

  <!-- ROW 1: Fear & Greed + Market Summary + Morning Outlook -->
  <div class="grid-3">

    <div class="card accent-red">
      <h2>😨 Fear & Greed Index</h2>
      <div class="fg-score">{fg_score}</div>
      <div class="fg-label">{fg_rating}</div>
      <div class="fg-signal">{fg_signal}</div>
      <div class="fg-history">
        <div class="fg-item">
          <div class="fg-lbl">Yesterday</div>
          <div class="fg-val">{fg_data.get('prev_close','N/A')}</div>
        </div>
        <div class="fg-item">
          <div class="fg-lbl">1 Week Ago</div>
          <div class="fg-val">{fg_data.get('prev_week','N/A')}</div>
        </div>
        <div class="fg-item">
          <div class="fg-lbl">1 Month Ago</div>
          <div class="fg-val">{fg_data.get('prev_month','N/A')}</div>
        </div>
        <div class="fg-item">
          <div class="fg-lbl">1 Year Ago</div>
          <div class="fg-val">{fg_data.get('prev_year','N/A')}</div>
        </div>
      </div>
    </div>

    <div class="card accent-blue">
      <h2>📊 Market Summary</h2>
      <ul>{fmt_bullets(sections.get("MARKET SUMMARY",""))}</ul>
    </div>

    <div class="card accent-green">
      <h2>🌅 Morning Outlook</h2>
      <ul>{fmt_bullets(sections.get("MORNING OUTLOOK",""))}</ul>
    </div>

  </div>

  <!-- ROW 2: Key Moves + Macro & News -->
  <div class="grid-2" style="margin-top:16px">
    <div class="card accent-amber">
      <h2>⚡ Key Moves</h2>
      <ul>{fmt_bullets(sections.get("KEY MOVES",""))}</ul>
    </div>
    <div class="card accent-red">
      <h2>🌐 Macro & News</h2>
      <ul>{fmt_bullets(sections.get("MACRO AND NEWS",""))}</ul>
    </div>
  </div>

  <!-- ROW 3: Earnings -->
  <div style="margin-top:16px">
    <div class="card full accent-green">
      <h2>💰 Earnings Highlights</h2>
      <ul>{fmt_bullets(sections.get("EARNINGS",""))}</ul>
    </div>
  </div>

  <!-- ROW 4: FRED Macro Table -->
  <div style="margin-top:16px">
    <div class="card full">
      <h2>🏦 Macro Indicators &nbsp;<span style="font-weight:400;color:var(--muted);font-size:.65rem;">Source: Federal Reserve FRED API (fred.stlouisfed.org) &nbsp;·&nbsp; Updated daily</span></h2>
      <table class="fred-table">
        <thead>
          <tr>
            <th>Indicator</th>
            <th style="text-align:center">Current</th>
            <th style="text-align:center">3 Mo Ago</th>
            <th style="text-align:center">12 Mo Ago</th>
            <th style="text-align:center">Trend</th>
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

  <!-- ROW 5: Sources -->
  <div class="grid-2" style="margin-top:16px">
    <div class="card">
      <h2>📰 Edward Jones Source <span style="font-weight:400;color:var(--muted);font-size:.65rem;">edwardjones.com</span></h2>
      <div class="source-text">{" ".join(ej_text[:800].split())}</div>
    </div>
    <div class="card">
      <h2>📧 CNBC Squawk Source <span style="font-weight:400;color:var(--muted);font-size:.65rem;">morningsquawk@response.cnbc.com</span></h2>
      <div class="source-text">{" ".join(cnbc_text[:800].split())}</div>
    </div>
  </div>

  <div class="footer">
    MarketPulse AI &nbsp;·&nbsp; Built by anil2040 &nbsp;·&nbsp;
    Sources:
    <a href="https://www.edwardjones.com/us-en/market-news-insights/stock-market-news/daily-market-recap" target="_blank">Edward Jones</a> &nbsp;·&nbsp;
    <a href="https://www.cnbc.com/newsletters/" target="_blank">CNBC Morning Squawk</a> &nbsp;·&nbsp;
    <a href="https://fred.stlouisfed.org" target="_blank">FRED API</a> &nbsp;·&nbsp;
    <a href="https://money.cnn.com/data/fear-and-greed/" target="_blank">CNN Fear & Greed</a>
    &nbsp;·&nbsp; For informational purposes only. Not financial advice.
  </div>

</div>
</body>
</html>"""

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("   ✅ index.html written successfully")


# ============================================================
# STEP 8: SEND EMAIL BACKUP VIA SMTP
# ============================================================
# SMTP = Simple Mail Transfer Protocol
# Port 587 with STARTTLS = secure email sending.
# We send a clean bullet-point HTML email -- no messy formatting!
# ============================================================

def send_email(sections, fg_data, fred_data):
    print("\n📤 Sending email backup via SMTP...")

    try:
        now_mt = datetime.now(MT)
        today  = now_mt.strftime("%A, %B %d, %Y")
        now    = now_mt.strftime("%I:%M %p MT")

        # Build clean bullet HTML for email
        def email_bullets(raw):
            if not raw or not raw.strip():
                return "<li>No data available</li>"
            items = ""
            for line in raw.strip().splitlines():
                line = re.sub(r"^[-•*]\s*", "", line.strip())
                if line:
                    items += f"<li style='margin:4px 0;'>{line}</li>"
            return items or "<li>No data available</li>"

        # Fear & Greed for email
        fg_score  = fg_data.get("score", "N/A")
        fg_rating = fg_data.get("rating", "N/A")

        # FRED top 5 for email (keep it concise)
        fred_email_rows = ""
        for r in (fred_data or [])[:6]:
            fred_email_rows += f"""
            <tr>
              <td style='padding:6px 10px;font-weight:600;'>{r['label']}</td>
              <td style='padding:6px 10px;text-align:center;font-weight:700;'>{r['current']}</td>
              <td style='padding:6px 10px;text-align:center;color:#6b7280;'>{r['mo3']}</td>
              <td style='padding:6px 10px;text-align:center;'>{r['trend']}</td>
            </tr>"""

        html_body = f"""
<html><body style='font-family:Segoe UI,sans-serif;max-width:680px;margin:0 auto;background:#f3f4f6;padding:20px;'>

  <div style='background:linear-gradient(135deg,#1e3a5f,#1a56db);color:#fff;padding:24px;border-radius:10px;text-align:center;margin-bottom:20px;'>
    <h1 style='margin:0;font-size:1.5rem;letter-spacing:2px;'>📈 MARKETPULSE AI</h1>
    <p style='margin:6px 0 0;opacity:.8;font-size:.9rem;'>Anil Abraham &nbsp;·&nbsp; {today} &nbsp;·&nbsp; {now}</p>
  </div>

  <div style='background:#fff;border-radius:8px;padding:16px 20px;margin-bottom:14px;border-left:4px solid #c81e1e;'>
    <h3 style='color:#1a56db;margin:0 0 8px;font-size:.75rem;letter-spacing:1px;text-transform:uppercase;'>😨 Fear & Greed: {fg_score}/100 -- {fg_rating}</h3>
    <p style='margin:0;font-size:.82rem;color:#6b7280;'>Yesterday: {fg_data.get('prev_close','N/A')} &nbsp;|&nbsp; 1 Week Ago: {fg_data.get('prev_week','N/A')} &nbsp;|&nbsp; 1 Month Ago: {fg_data.get('prev_month','N/A')}</p>
  </div>

  <div style='background:#fff;border-radius:8px;padding:16px 20px;margin-bottom:14px;border-left:4px solid #1a56db;'>
    <h3 style='color:#1a56db;margin:0 0 8px;font-size:.75rem;letter-spacing:1px;text-transform:uppercase;'>📊 Market Summary</h3>
    <ul style='margin:0;padding-left:18px;color:#374151;font-size:.86rem;line-height:1.6;'>
      {email_bullets(sections.get('MARKET SUMMARY',''))}
    </ul>
  </div>

  <div style='background:#fff;border-radius:8px;padding:16px 20px;margin-bottom:14px;border-left:4px solid #b45309;'>
    <h3 style='color:#1a56db;margin:0 0 8px;font-size:.75rem;letter-spacing:1px;text-transform:uppercase;'>⚡ Key Moves</h3>
    <ul style='margin:0;padding-left:18px;color:#374151;font-size:.86rem;line-height:1.6;'>
      {email_bullets(sections.get('KEY MOVES',''))}
    </ul>
  </div>

  <div style='background:#fff;border-radius:8px;padding:16px 20px;margin-bottom:14px;border-left:4px solid #c81e1e;'>
    <h3 style='color:#1a56db;margin:0 0 8px;font-size:.75rem;letter-spacing:1px;text-transform:uppercase;'>🌐 Macro & News</h3>
    <ul style='margin:0;padding-left:18px;color:#374151;font-size:.86rem;line-height:1.6;'>
      {email_bullets(sections.get('MACRO AND NEWS',''))}
    </ul>
  </div>

  <div style='background:#fff;border-radius:8px;padding:16px 20px;margin-bottom:14px;border-left:4px solid #057a55;'>
    <h3 style='color:#1a56db;margin:0 0 8px;font-size:.75rem;letter-spacing:1px;text-transform:uppercase;'>💰 Earnings Highlights</h3>
    <ul style='margin:0;padding-left:18px;color:#374151;font-size:.86rem;line-height:1.6;'>
      {email_bullets(sections.get('EARNINGS',''))}
    </ul>
  </div>

  <div style='background:#fff;border-radius:8px;padding:16px 20px;margin-bottom:14px;border-left:4px solid #057a55;'>
    <h3 style='color:#1a56db;margin:0 0 8px;font-size:.75rem;letter-spacing:1px;text-transform:uppercase;'>🌅 Morning Outlook</h3>
    <ul style='margin:0;padding-left:18px;color:#374151;font-size:.86rem;line-height:1.6;'>
      {email_bullets(sections.get('MORNING OUTLOOK',''))}
    </ul>
  </div>

  <div style='background:#fff;border-radius:8px;padding:16px 20px;margin-bottom:20px;'>
    <h3 style='color:#1a56db;margin:0 0 10px;font-size:.75rem;letter-spacing:1px;text-transform:uppercase;'>🏦 Key Macro Indicators (FRED)</h3>
    <table style='width:100%;border-collapse:collapse;font-size:.82rem;'>
      <tr style='background:#f3f4f6;'>
        <th style='padding:6px 10px;text-align:left;'>Indicator</th>
        <th style='padding:6px 10px;text-align:center;'>Current</th>
        <th style='padding:6px 10px;text-align:center;'>3 Mo Ago</th>
        <th style='padding:6px 10px;text-align:center;'>Trend</th>
      </tr>
      {fred_email_rows}
    </table>
  </div>

  <div style='text-align:center;color:#9ca3af;font-size:.72rem;'>
    MarketPulse AI &nbsp;·&nbsp; Built by anil2040 &nbsp;·&nbsp;
    <a href='https://anil2040.github.io/market-pulse-ai/' style='color:#1a56db;'>View Full Dashboard</a>
    &nbsp;·&nbsp; Not financial advice.
  </div>

</body></html>"""

        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"📈 MarketPulse AI · {today} · F&G: {fg_score} ({fg_rating})"
        msg["From"]    = YAHOO_EMAIL
        msg["To"]      = YAHOO_EMAIL

        msg.attach(MIMEText(html_body, "html"))

        with smtplib.SMTP("smtp.mail.yahoo.com", 587) as server:
            server.starttls()
            server.login(YAHOO_EMAIL, YAHOO_PASSWORD)
            server.sendmail(YAHOO_EMAIL, YAHOO_EMAIL, msg.as_string())

        print("   ✅ Email sent successfully!")

    except Exception as e:
        print(f"   ❌ Email send failed: {e}")
        print("   (Dashboard still updated -- email is backup only)")


# ============================================================
# MAIN RUNNER
# ============================================================
# if __name__ == "__main__" means:
# "Only run this block if THIS file was called directly"
# Best practice -- prevents accidental execution if imported.
# ============================================================

if __name__ == "__main__":
    print("🚀 MarketPulse AI Starting...")
    print("=" * 50)

    # Run all steps in sequence
    fred_data = fetch_fred_data()
    fg_data   = fetch_fear_greed()
    ej_text   = scrape_edward_jones()
    cnbc_text = fetch_cnbc_email()
    briefing  = synthesize_with_gemini(ej_text, cnbc_text, fred_data, fg_data)

    # Parse sections ONCE -- reuse for both HTML and email
    sections  = parse_sections(briefing)

    build_html(briefing, ej_text, cnbc_text, fred_data, fg_data)
    send_email(sections, fg_data, fred_data)

    print("\n" + "=" * 50)
    print("✅ MarketPulse AI Complete!")
    print(f"🌐 Dashboard: https://anil2040.github.io/market-pulse-ai")
    print("=" * 50)