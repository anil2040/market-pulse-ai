# ============================================================
# MarketPulse AI - main.py
# Updated: September 2026
# ============================================================
# Pipeline:
#   1.  FRED macro indicators (12 series, parallel, ~4s)
#   2.  FRED economic calendar (upcoming high-impact releases)
#   3.  CNN Fear & Greed Index (JSON)
#   4.  Market Breadth via stooq.com (^S5TH, no auth needed)
#   5.  Edward Jones daily recap (web scrape)
#   6.  CNBC Morning Squawk (Yahoo IMAP)
#   7.  Gemini AI synthesis (90s timeout, gemini-3.6-flash)
#   8.  Build HTML dashboard (index.html -> GitHub Pages)
# Email is DISABLED -- dashboard is primary output.
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

# --- TIMEZONE: Boise, Idaho Mountain Time ---
# MDT = UTC-6 (summer), MST = UTC-7 (Nov-Mar)
MT = timezone(timedelta(hours=-6))

print("✅ Configuration loaded")
print(f"📧 Email: {YAHOO_EMAIL}")


# ============================================================
# STEP 1: FRED MACRO INDICATORS (12 series, parallel)
# ============================================================
# ThreadPoolExecutor fires all 12 calls simultaneously.
# INDEX series (CPI, PCE): calculate YoY % change.
# RATE series: show value directly.
# Dynamic insight generated from actual data values.
# ============================================================

FRED_SERIES = [
    {"label": "Core PCE (Fed Target 2%)",     "id": "PCEPILFE",     "is_index": True,  "insight": "Fed's primary inflation target -- above 2% = rates stay high"},
    {"label": "Core CPI (ex Food/Energy)",    "id": "CPILFESL",     "is_index": True,  "insight": "Cleaner inflation signal the Fed watches closely"},
    {"label": "CPI Inflation (Headline)",     "id": "CPIAUCSL",     "is_index": True,  "insight": "Headline inflation including food & energy"},
    {"label": "Fed Funds Rate",               "id": "FEDFUNDS",     "is_index": False, "insight": "Cost of borrowing -- rising = headwind for equities"},
    {"label": "HY Credit Spread",             "id": "BAMLH0A0HYM2", "is_index": False, "insight": "Widening = credit stress, systemic risk rising"},
    {"label": "PCE Inflation (Headline)",     "id": "PCEPI",        "is_index": True,  "insight": "Fed preferred gauge (broader than CPI)"},
    {"label": "Unemployment Rate",            "id": "UNRATE",       "is_index": False, "insight": "Labor market -- rising signals recession risk"},
    {"label": "U of Michigan Sentiment",      "id": "UMCSENT",      "is_index": False, "no_pct": True,  "insight": "Consumer confidence 0-100 score"},
    {"label": "WTI Crude Oil",                "id": "DCOILWTICO",   "is_index": False, "prefix": "$",   "insight": "Energy prices -- drives inflation & energy stocks"},
    {"label": "10Y Treasury Yield",           "id": "GS10",         "is_index": False, "insight": "Risk-free benchmark for all equity valuations"},
    {"label": "2Y Treasury Yield",            "id": "GS2",          "is_index": False, "insight": "Fed expectations -- rises with rate hike bets"},
    {"label": "Yield Curve (10Y-2Y)",         "id": "T10Y2Y",       "is_index": False, "insight": "Negative = inverted = historically predicts recession"},
]


def _signal(label, cur_str, mo3_str, trend):
    """One-line investing signal from actual current value."""
    try:
        cur = float(re.sub(r"[%$]", "", str(cur_str)))
        mo3 = float(re.sub(r"[%$]", "", str(mo3_str)))
    except:
        return ""

    if "Core PCE" in label or "Core CPI" in label:
        if cur <= 2.0:   return "✅ At Fed 2% target"
        elif cur <= 2.5 and trend == "▼": return "📉 Cooling toward target"
        elif cur > 3.0:  return "⚠️ Above target -- rates stay elevated"
        elif trend == "▼": return "📉 Cooling trend"
        else:            return "⚠️ Still above target"
    elif "PCE" in label or "CPI" in label:
        if trend == "▼": return "📉 Cooling"
        elif trend == "▲": return "⚠️ Heating up"
        else:            return "→ Stable"
    elif "Fed Funds" in label:
        if cur >= 5.0:   return "⚠️ Restrictive -- headwind for growth"
        elif cur <= 3.0: return "✅ Accommodative -- supportive for equities"
        elif trend == "▼": return "📉 Cutting cycle underway"
        else:            return "→ On hold -- watching inflation"
    elif "Unemployment" in label:
        if cur <= 4.0:   return "✅ Strong labor market"
        elif cur >= 5.0: return "⚠️ Weakening -- recession risk"
        elif trend == "▲": return "⚠️ Rising -- watch consumer stocks"
        else:            return "✅ Stable"
    elif "HY Credit" in label:
        if cur <= 3.0:   return "✅ Tight -- risk appetite healthy"
        elif cur >= 6.0: return "⚠️ Wide -- credit stress, be selective"
        elif trend == "▲": return "⚠️ Widening -- systemic risk rising"
        else:            return "→ Stable"
    elif "Yield Curve" in label:
        if cur < 0:      return "⚠️ Inverted -- recession signal"
        elif cur < 0.3:  return "→ Nearly flat -- muted growth signal"
        else:            return "✅ Positive slope -- normal"
    elif "10Y" in label:
        if cur >= 5.0:   return "⚠️ High -- P/E compression risk"
        elif cur <= 3.5: return "✅ Low -- supports higher valuations"
        elif trend == "▲": return "⚠️ Rising -- headwind for growth stocks"
        else:            return "→ Stable"
    elif "2Y" in label:
        if trend == "▼": return "✅ Falling -- rate cuts priced in"
        elif cur >= 5.0: return "⚠️ High -- rates staying elevated"
        else:            return "→ Stable"
    elif "Michigan" in label:
        if cur >= 80:    return "✅ High confidence"
        elif cur <= 60:  return "⚠️ Low confidence -- spending under pressure"
        elif trend == "▼": return "⚠️ Declining -- watch consumer stocks"
        else:            return "→ Improving"
    elif "WTI" in label:
        if cur >= 90:    return "⚠️ High -- inflationary pressure"
        elif cur <= 60:  return "✅ Low -- helps consumers"
        elif trend == "▲": return "⚠️ Rising -- watch inflation impact"
        else:            return "→ Stable"
    return ""


def _fetch_one_fred(cfg, start_date, end_date):
    label    = cfg["label"]
    sid      = cfg["id"]
    is_index = cfg["is_index"]
    no_pct   = cfg.get("no_pct", False)
    prefix   = cfg.get("prefix", "")
    try:
        url  = (f"https://api.stlouisfed.org/fred/series/observations"
                f"?series_id={sid}&api_key={FRED_API_KEY}&file_type=json"
                f"&observation_start={start_date}&observation_end={end_date}"
                f"&sort_order=desc&limit=15")
        resp = requests.get(url, timeout=10)
        obs  = [o for o in resp.json().get("observations",[]) if o["value"] != "."]
        if not obs:
            return {**cfg, "current":"N/A","mo3":"N/A","mo12":"N/A","trend":"?","date":"N/A","sig":""}

        v0 = float(obs[0]["value"])
        v3 = float(obs[min(3,  len(obs)-1)]["value"])
        v12= float(obs[min(12, len(obs)-1)]["value"])

        if is_index and v12:
            cur  = (v0 - v12) / v12 * 100
            v15  = float(obs[min(14, len(obs)-1)]["value"])
            mo3v = (v3 - v15) / v15 * 100 if v15 else cur
            dc, dm3, dm12 = f"{cur:.1f}%", f"{mo3v:.1f}%", f"{mo3v:.1f}%"
            trend = "▼" if cur < mo3v-0.05 else "▲" if cur > mo3v+0.05 else "→"
        elif no_pct:
            dc, dm3, dm12 = f"{v0:.1f}", f"{v3:.1f}", f"{v12:.1f}"
            trend = "▲" if v0>v3+0.05 else "▼" if v0<v3-0.05 else "→"
        elif prefix:
            dc, dm3, dm12 = f"{prefix}{v0:.1f}", f"{prefix}{v3:.1f}", f"{prefix}{v12:.1f}"
            trend = "▲" if v0>v3+0.05 else "▼" if v0<v3-0.05 else "→"
        else:
            dc, dm3, dm12 = f"{v0:.2f}%", f"{v3:.2f}%", f"{v12:.2f}%"
            trend = "▲" if v0>v3+0.05 else "▼" if v0<v3-0.05 else "→"

        pub = datetime.strptime(obs[0]["date"],"%Y-%m-%d").strftime("%b %d %Y")
        sig = _signal(label, dc, dm3, trend)
        return {**cfg, "current":dc, "mo3":dm3, "mo12":dm12, "trend":trend, "date":pub, "sig":sig}
    except Exception as e:
        return {**cfg, "current":"N/A","mo3":"N/A","mo12":"N/A","trend":"?","date":"N/A","sig":""}


def fetch_fred_data():
    print("\n🏦 Fetching FRED macro indicators (parallel)...")
    end   = date.today().strftime("%Y-%m-%d")
    start = (date.today()-timedelta(days=460)).strftime("%Y-%m-%d")
    rmap  = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(_fetch_one_fred, cfg, start, end): cfg for cfg in FRED_SERIES}
        for f in concurrent.futures.as_completed(futs):
            r = f.result(); rmap[r["label"]] = r
            print(f"   {'✅' if r['current']!='N/A' else '❌'} {r['label']}: {r['current']} {r['trend']}")
    results = [rmap.get(c["label"],{**c,"current":"N/A","mo3":"N/A","mo12":"N/A","trend":"?","date":"N/A","sig":""}) for c in FRED_SERIES]
    print(f"   🏦 FRED complete: {len(results)} indicators")
    return results


# ============================================================
# STEP 2: FRED ECONOMIC CALENDAR
# ============================================================
# Upcoming high-impact economic releases this week.
# Window: 3 days back + 7 days forward.
# ============================================================

IMPACT_RELEASES = {
    10: {"abbr":"CPI",        "impact":"🔴"},
    51: {"abbr":"PCE/Income", "impact":"🔴"},
    50: {"abbr":"Jobs/NFP",   "impact":"🔴"},
    17: {"abbr":"FOMC Rate",  "impact":"🔴"},
    53: {"abbr":"GDP",        "impact":"🔴"},
    21: {"abbr":"Retail Sales","impact":"🟡"},
    22: {"abbr":"PPI",        "impact":"🟡"},
    23: {"abbr":"Housing",    "impact":"🟡"},
    33: {"abbr":"ISM Mfg",   "impact":"🟡"},
}

def fetch_economic_calendar():
    print("\n📅 Fetching Economic Calendar (FRED)...")
    try:
        today = date.today()
        start = (today - timedelta(days=3)).strftime("%Y-%m-%d")
        end   = (today + timedelta(days=7)).strftime("%Y-%m-%d")
        url   = (f"https://api.stlouisfed.org/fred/releases/dates"
                 f"?api_key={FRED_API_KEY}&file_type=json"
                 f"&realtime_start={start}&realtime_end={end}"
                 f"&limit=200&sort_order=asc"
                 f"&include_release_dates_with_no_data=true")
        resp  = requests.get(url, timeout=10)
        events= []
        for item in resp.json().get("release_dates",[]):
            rid = int(item.get("release_id",0))
            if rid in IMPACT_RELEASES:
                try:
                    dt    = datetime.strptime(item["date"],"%Y-%m-%d")
                    delta = (dt.date()-today).days
                    rel   = ("TODAY" if delta==0 else "Tomorrow" if delta==1
                             else f"{abs(delta)}d ago" if delta<0
                             else dt.strftime("%a %b %d"))
                    events.append({
                        "date": dt.strftime("%a %b %d"), "rel": rel,
                        "abbr": IMPACT_RELEASES[rid]["abbr"],
                        "impact": IMPACT_RELEASES[rid]["impact"],
                        "delta": delta, "is_today": delta==0, "is_past": delta<0,
                    })
                except: continue
        events.sort(key=lambda x: x["delta"])
        # Deduplicate same abbr on same date
        seen, unique = set(), []
        for e in events:
            key = f"{e['abbr']}{e['date']}"
            if key not in seen: seen.add(key); unique.append(e)
        print(f"   ✅ Calendar: {len(unique)} events")
        return unique
    except Exception as e:
        print(f"   ❌ Calendar failed: {e}")
        return []


# ============================================================
# STEP 3: CNN FEAR & GREED
# ============================================================

def fetch_fear_greed():
    print("\n😨 Fetching CNN Fear & Greed...")
    try:
        url  = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        hdrs = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        fg   = requests.get(url, headers=hdrs, timeout=10).json().get("fear_and_greed",{})
        score = round(float(fg.get("score",50)))
        rating= fg.get("rating","Unknown").replace("_"," ").title()
        if   score<=24: label="Extreme Fear"; color="#c81e1e"
        elif score<=44: label="Fear";         color="#e97316"
        elif score<=55: label="Neutral";      color="#6b7280"
        elif score<=74: label="Greed";        color="#059669"
        else:           label="Extreme Greed";color="#1a56db"
        # Investing signal
        if   score<=24: signal="Historically strong buying opportunity (Buffett: be greedy when others fear)"
        elif score<=44: signal="Market pessimism -- watch for mean reversion entry points"
        elif score<=55: signal="No strong directional signal -- stay selective"
        elif score<=74: signal="Optimism elevated -- exercise caution on new buys"
        else:           signal="Market overheated -- high mean reversion reversal risk"
        print(f"   ✅ Fear & Greed: {score}/100 ({label})")
        return {"score":score,"label":label,"color":color,"signal":signal,
                "prev_close":round(float(fg.get("previous_close",score))),
                "prev_week": round(float(fg.get("previous_1_week",score))),
                "prev_month":round(float(fg.get("previous_1_month",score))),
                "prev_year": round(float(fg.get("previous_1_year",score)))}
    except Exception as e:
        print(f"   ❌ Fear & Greed failed: {e}")
        return {"score":50,"label":"Unavailable","color":"#6b7280",
                "signal":"Data unavailable","prev_close":"N/A",
                "prev_week":"N/A","prev_month":"N/A","prev_year":"N/A"}


# ============================================================
# STEP 4: MARKET BREADTH via stooq.com
# ============================================================
# stooq.com provides ^S5TH (% S&P 500 stocks above 200MA)
# as a free CSV download -- no API key, no auth blocks!
# This is more reliable than Yahoo Finance for index data.
# ============================================================

def fetch_market_breadth():
    print("\n📊 Fetching Market Breadth (% S&P 500 above 200MA)...")
    try:
        # stooq.com CSV endpoint for ^S5TH -- last 5 trading days
        url  = "https://stooq.com/q/d/l/?s=%5Es5th&i=d"
        hdrs = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        resp = requests.get(url, headers=hdrs, timeout=10)
        # CSV format: Date,Open,High,Low,Close,Volume
        lines = [l.strip() for l in resp.text.strip().splitlines() if l.strip()]
        # Last line = most recent trading day
        data_lines = [l for l in lines if not l.startswith("Date")]
        if not data_lines:
            raise Exception("No data rows returned")
        latest = data_lines[-1].split(",")
        prev   = data_lines[-2].split(",") if len(data_lines)>1 else latest
        price  = float(latest[4])   # Close price
        prev_p = float(prev[4])
        change = price - prev_p
        pub_date = latest[0]

        if   price<25: signal="Deeply Oversold -- Strong mean reversion setup"; color="#c81e1e"
        elif price<40: signal="Oversold -- Value opportunities emerging";        color="#e97316"
        elif price<60: signal="Neutral -- Mixed breadth, stock-pickers market";  color="#6b7280"
        elif price<75: signal="Healthy -- Broad participation, bulls in control";color="#059669"
        else:          signal="Overbought -- Be selective, reversal risk elevated";color="#1a56db"

        print(f"   ✅ Market Breadth: {price:.1f}% as of {pub_date} ({signal})")
        return {"value":f"{price:.1f}%","raw":price,"prev":f"{prev_p:.1f}%",
                "change":f"{change:+.1f}%","signal":signal,"color":color,"date":pub_date}
    except Exception as e:
        print(f"   ❌ Market Breadth failed: {e}")
        return {"value":"N/A","raw":50,"prev":"N/A","change":"N/A",
                "signal":"Temporarily unavailable","color":"#6b7280","date":"N/A"}


# ============================================================
# STEP 5: EDWARD JONES SCRAPE
# ============================================================

def scrape_edward_jones():
    print("\n🔍 Scraping Edward Jones...")
    url  = "https://www.edwardjones.com/us-en/market-news-insights/stock-market-news/daily-market-recap"
    hdrs = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.get(url, headers=hdrs, timeout=15)
        print(f"   Status: {resp.status_code}")
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script","style","nav","footer","header"]): tag.decompose()
        lines = [l.strip() for l in soup.get_text("\n",strip=True).splitlines() if l.strip()]
        text  = "\n".join(lines[:120])
        print(f"   ✅ Edward Jones: {len(text)} chars")
        return text
    except Exception as e:
        print(f"   ❌ Edward Jones failed: {e}")
        return "Edward Jones data unavailable today."


# ============================================================
# STEP 6: CNBC MORNING SQUAWK (IMAP)
# ============================================================

def fetch_cnbc_email():
    print("\n📬 Fetching CNBC Morning Squawk via IMAP...")
    try:
        mail = imaplib.IMAP4_SSL("imap.mail.yahoo.com", 993)
        mail.login(YAHOO_EMAIL, YAHOO_PASSWORD)
        mail.select("INBOX")
        status, messages = mail.search(None,'(FROM "morningsquawk@response.cnbc.com")')
        if status!="OK" or not messages[0]:
            print("   ⚠️ No CNBC emails found"); mail.logout()
            return "CNBC Morning Squawk not found today."
        ids    = messages[0].split()
        latest = ids[-1]
        print(f"   Found {len(ids)} CNBC emails, reading latest...")
        status, msg_data = mail.fetch(latest,"(RFC822)")
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
                        body=BeautifulSoup(part.get_payload(decode=True).decode("utf-8",errors="ignore"),"html.parser").get_text("\n",strip=True); break
            else:
                body=BeautifulSoup(msg.get_payload(decode=True).decode("utf-8",errors="ignore"),"html.parser").get_text("\n",strip=True)
        mail.logout()
        body = body[:2500].strip()
        print(f"   ✅ CNBC: {len(body)} chars")
        return body
    except Exception as e:
        print(f"   ❌ CNBC IMAP failed: {e}")
        return "CNBC Morning Squawk unavailable today."


# ============================================================
# STEP 7: GEMINI AI SYNTHESIS (90-second timeout)
# ============================================================
# Wrapped in ThreadPoolExecutor with 90s timeout.
# If Gemini hangs, we use a structured fallback -- dashboard
# still builds and shows FRED/sentiment data!
# ============================================================

def _call_gemini(prompt):
    """Inner function -- called with timeout wrapper."""
    client = genai.Client(api_key=GEMINI_API_KEY)
    interaction = client.interactions.create(
        model="gemini-3.6-flash",
        input=prompt,
    )
    return interaction.output_text


def synthesize_with_gemini(ej_text, cnbc_text, fred_data, fg_data, breadth_data, cal_events):
    print("\n🤖 Sending to Gemini (90s timeout)...")
    try:
        fred_summary = "\n".join([
            f"- {r['label']}: {r['current']} (trend:{r['trend']}) {r.get('sig','')}"
            for r in fred_data if r["current"]!="N/A"
        ])
        cal_lines = "\n".join([
            f"- {e['rel']}: {e['abbr']} ({e['impact']})"
            for e in (cal_events or [])
        ]) or "No high-impact releases this week"

        prompt = f"""You are a sharp financial analyst writing a pre-market market briefing for a 
deep-value mean reversion investor (Greenblatt/Munger style).

STRICT RULES:
- Output EXACTLY these 4 section headers (no numbers, no markdown, no emojis):
  MARKET AND KEY MOVES
  MACRO AND NEWS
  EARNINGS AND EVENTS
  WHAT TO WATCH
- Under each: 3-4 bullet points starting with dash (-)
- Each bullet: one specific fact or insight, max 20 words
- No paragraphs, no bold, no sub-bullets

After the 4 sections, add:
AI FUN FACT
- One surprising fact about AI, markets, or investing history. Max 25 words.

DATA:
Fear & Greed: {fg_data['score']}/100 ({fg_data['label']}) -- {fg_data['signal']}
Market Breadth (% above 200MA): {breadth_data['value']} -- {breadth_data['signal']}

FRED INDICATORS:
{fred_summary}

UPCOMING RELEASES:
{cal_lines}

EDWARD JONES RECAP:
{ej_text[:1200]}

CNBC MORNING SQUAWK:
{cnbc_text[:1000]}
"""
        # 90-second timeout via ThreadPoolExecutor
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future  = ex.submit(_call_gemini, prompt)
            briefing= future.result(timeout=90)   # Raises TimeoutError if >90s

        print(f"   ✅ Gemini: {len(briefing)} chars")
        return briefing

    except concurrent.futures.TimeoutError:
        print("   ⚠️ Gemini timed out (>90s) -- using structured fallback")
    except Exception as e:
        print(f"   ❌ Gemini failed: {e}")

    # Structured fallback -- dashboard still useful!
    return """MARKET AND KEY MOVES
- AI synthesis timed out -- see FRED indicators and sentiment data below
- Edward Jones and CNBC source data available in logs

MACRO AND NEWS
- Check FRED macro table for current economic indicators
- Fear & Greed and Market Breadth shown in sentiment section

EARNINGS AND EVENTS
- See economic calendar for upcoming data releases

WHAT TO WATCH
- Review all data sections below for today's market context

AI FUN FACT
- The first stock ticker tape machine was invented by Thomas Edison in 1869."""


# ============================================================
# STEP 8: PARSE SECTIONS
# ============================================================

def parse_sections(text):
    secs = {
        "MARKET AND KEY MOVES": "",
        "MACRO AND NEWS":       "",
        "EARNINGS AND EVENTS":  "",
        "WHAT TO WATCH":        "",
        "AI FUN FACT":          "",
    }
    current = None
    for line in text.splitlines():
        up  = line.upper().strip()
        cln = re.sub(r"^\d+[\.\)]\s*","",up)
        cln = re.sub(r"^#+\s*","",cln)
        cln = re.sub(r"^\*+\s*","",cln)
        cln = cln.encode("ascii","ignore").decode().strip()

        if "MARKET AND KEY MOVES" in cln or ("MARKET" in cln and "KEY" in cln): current="MARKET AND KEY MOVES"; continue
        if "KEY MOVES" in cln and "MARKET" not in cln: current="MARKET AND KEY MOVES"; continue
        if "MARKET SUMMARY" in cln: current="MARKET AND KEY MOVES"; continue
        if "MACRO AND NEWS" in cln or "MACRO & NEWS" in cln: current="MACRO AND NEWS"; continue
        if "EARNINGS AND EVENTS" in cln or "EARNINGS AND CALENDAR" in cln: current="EARNINGS AND EVENTS"; continue
        if "EARNINGS HIGHLIGHT" in cln: current="EARNINGS AND EVENTS"; continue
        if "WHAT TO WATCH" in cln or "PRE-MARKET" in cln or "MORNING OUTLOOK" in cln: current="WHAT TO WATCH"; continue
        if "AI FUN FACT" in cln or ("FUN FACT" in cln): current="AI FUN FACT"; continue

        if current and line.strip():
            secs[current] += line.strip()+"\n"

    for name,content in secs.items():
        print(f"   📋 {name}: {len(content)} chars" if content.strip() else f"   ⚠️ {name}: EMPTY")
    return secs


# ============================================================
# STEP 9: BUILD HTML DASHBOARD
# ============================================================

def fmt_bullets(raw):
    if not raw or not raw.strip(): return "<li>No data available</li>"
    items=""
    for line in raw.strip().splitlines():
        line = re.sub(r"^[-•*]\s*","",line.strip())
        line = re.sub(r"\*\*(.+?)\*\*",r"<strong>\1</strong>",line)
        if line: items+=f"        <li>{line}</li>\n"
    return items or "<li>No data available</li>"


def build_html(briefing, ej_text, cnbc_text, fred_data, fg_data,
               breadth_data, cal_events):
    print("\n🎨 Building HTML dashboard...")

    secs   = parse_sections(briefing)
    now_mt = datetime.now(MT)
    today  = now_mt.strftime("%A, %B %d, %Y")
    now    = now_mt.strftime("%I:%M %p")

    fg_score = fg_data.get("score", 50)
    fg_label = fg_data.get("label","N/A")
    fg_color = fg_data.get("color","#6b7280")
    fg_sig   = fg_data.get("signal","")

    # Get U of Michigan from FRED data for sentiment section
    umich = next((r for r in fred_data if "Michigan" in r["label"]), None)
    umich_val   = umich["current"] if umich else "N/A"
    umich_trend = umich["trend"]   if umich else "?"
    umich_sig   = umich.get("sig","") if umich else ""

    # ---- SENTIMENT SECTION (3 horizontal bars) ---------------
    # Fear & Greed bar
    try:
        fg_num = int(fg_score)
        fg_pct = fg_num  # Already 0-100
    except: fg_num=50; fg_pct=50

    def sentiment_bar(value_pct, color, label_left, label_mid, label_right, zones=None):
        """Render a horizontal gradient bar with marker needle."""
        # Default 5-zone gradient (red -> orange -> yellow -> lime -> green)
        grad = zones or "linear-gradient(to right,#c81e1e 0%,#e97316 25%,#d4d400 45%,#86c440 65%,#059669 100%)"
        return f"""
<div style="margin-bottom:14px;">
  <div style="display:flex;justify-content:space-between;font-size:.62rem;color:#9ca3af;margin-bottom:2px;">
    <span>{label_left}</span><span>{label_mid}</span><span>{label_right}</span>
  </div>
  <div style="position:relative;background:{grad};border-radius:99px;height:16px;">
    <!-- Marker line at position -->
    <div style="position:absolute;top:-3px;bottom:-3px;width:3px;border-radius:3px;
                background:#1e3a5f;left:calc({value_pct}% - 1.5px);"></div>
  </div>
</div>"""

    # Fear & Greed: 5 zones labeled Extreme Fear, Fear, Neutral, Greed, Extreme Greed
    fg_bar = f"""
<div style="margin-bottom:4px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
    <span style="font-size:.72rem;font-weight:700;color:{fg_color};">😨 Fear & Greed: {fg_score}/100 ({fg_label})</span>
    <span style="font-size:.68rem;color:#9ca3af;">CNN · updated daily</span>
  </div>
  <div style="position:relative;height:18px;border-radius:99px;overflow:hidden;
              background:linear-gradient(to right,#c81e1e 0%,#e97316 22%,#9ca3af 44%,#86c440 66%,#059669 100%);">
    <div style="position:absolute;top:0;bottom:0;width:4px;background:#1e3a5f;border-radius:2px;
                left:calc({fg_pct}% - 2px);"></div>
  </div>
  <div style="display:flex;justify-content:space-between;font-size:.58rem;color:#9ca3af;margin-top:1px;">
    <span>Extreme Fear</span><span>Fear</span><span>Neutral</span><span>Greed</span><span>Extreme Greed</span>
  </div>
  <div style="font-size:.72rem;color:{fg_color};margin-top:4px;">{fg_sig}</div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:3px;margin-top:6px;">
    <div style="background:#f9fafb;border-radius:5px;padding:4px 7px;font-size:.68rem;">
      <span style="color:#9ca3af;">Yesterday </span><strong>{fg_data.get('prev_close','N/A')}</strong>
    </div>
    <div style="background:#f9fafb;border-radius:5px;padding:4px 7px;font-size:.68rem;">
      <span style="color:#9ca3af;">1 Week Ago </span><strong>{fg_data.get('prev_week','N/A')}</strong>
    </div>
    <div style="background:#f9fafb;border-radius:5px;padding:4px 7px;font-size:.68rem;">
      <span style="color:#9ca3af;">1 Month Ago </span><strong>{fg_data.get('prev_month','N/A')}</strong>
    </div>
    <div style="background:#f9fafb;border-radius:5px;padding:4px 7px;font-size:.68rem;">
      <span style="color:#9ca3af;">1 Year Ago </span><strong>{fg_data.get('prev_year','N/A')}</strong>
    </div>
  </div>
</div>"""

    # Market Breadth bar
    try: braw=float(str(breadth_data.get("raw",50))); bcol=breadth_data.get("color","#6b7280")
    except: braw=50; bcol="#6b7280"
    breadth_bar = f"""
<div style="margin-bottom:14px;border-top:1px solid #f3f4f6;padding-top:12px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
    <span style="font-size:.72rem;font-weight:700;color:{bcol};">📊 Market Breadth: {breadth_data.get('value','N/A')} vs 200MA</span>
    <span style="font-size:.68rem;color:#9ca3af;">{breadth_data.get('date','')}</span>
  </div>
  <div style="position:relative;height:18px;border-radius:99px;overflow:hidden;
              background:linear-gradient(to right,#c81e1e 0%,#e97316 25%,#9ca3af 45%,#86c440 65%,#059669 100%);">
    <div style="position:absolute;top:0;bottom:0;width:4px;background:#1e3a5f;border-radius:2px;
                left:calc({braw}% - 2px);"></div>
  </div>
  <div style="display:flex;justify-content:space-between;font-size:.58rem;color:#9ca3af;margin-top:1px;">
    <span>0% Oversold</span><span>50% Neutral</span><span>100% Overbought</span>
  </div>
  <div style="font-size:.72rem;color:{bcol};margin-top:4px;">{breadth_data.get('signal','N/A')}</div>
  <div style="font-size:.65rem;color:#6b7280;background:#f9fafb;border-radius:5px;padding:4px 7px;margin-top:5px;">
    💡 Below 25% = deeply oversold (mean reversion buy signal) · Above 75% = be selective
  </div>
</div>"""

    # U of Michigan bar (0-100 score)
    try:
        umich_num = float(str(umich_val).replace("%",""))
        if   umich_num>=80: ucol="#059669"
        elif umich_num>=60: ucol="#6b7280"
        else:               ucol="#c81e1e"
    except: umich_num=55; ucol="#6b7280"
    umich_bar = f"""
<div style="border-top:1px solid #f3f4f6;padding-top:12px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
    <span style="font-size:.72rem;font-weight:700;color:{ucol};">🎓 U of Michigan Sentiment: {umich_val}</span>
    <span style="font-size:.68rem;color:#9ca3af;">monthly · {umich.get('date','') if umich else ''}</span>
  </div>
  <div style="position:relative;height:18px;border-radius:99px;overflow:hidden;
              background:linear-gradient(to right,#c81e1e 0%,#e97316 30%,#9ca3af 55%,#059669 100%);">
    <div style="position:absolute;top:0;bottom:0;width:4px;background:#1e3a5f;border-radius:2px;
                left:calc({umich_num}% - 2px);"></div>
  </div>
  <div style="display:flex;justify-content:space-between;font-size:.58rem;color:#9ca3af;margin-top:1px;">
    <span>0 Low</span><span>50 Neutral</span><span>100 High</span>
  </div>
  <div style="font-size:.72rem;color:{ucol};margin-top:4px;">{umich_sig}</div>
</div>"""

    # ---- FRED table (sorted alpha, insight below label) ------
    sorted_fred = sorted([r for r in fred_data if "Michigan" not in r["label"]],
                         key=lambda x: x["label"])
    fred_rows = ""
    for r in sorted_fred:
        if any(x in r["label"] for x in ["CPI","PCE","Inflation"]):
            tc = "#057a55" if r["trend"]=="▼" else "#c81e1e" if r["trend"]=="▲" else "#6b7280"
        else:
            tc = "#057a55" if r["trend"]=="▲" else "#c81e1e" if r["trend"]=="▼" else "#6b7280"
        sig_html = f'<div style="font-size:.68rem;color:#6b7280;margin-top:2px;">{r.get("sig","")}</div>' if r.get("sig") else ""
        fred_rows += f"""
        <tr style="border-bottom:1px solid #f3f4f6;">
          <td style="padding:8px 10px;">
            <div style="font-weight:600;font-size:.8rem;">{r['label']}</div>
            <div style="font-size:.68rem;color:#9ca3af;margin-top:1px;">[{r['insight']}]</div>
            {sig_html}
          </td>
          <td style="padding:8px 10px;text-align:center;font-weight:700;font-size:.88rem;">{r['current']}</td>
          <td style="padding:8px 10px;text-align:center;font-size:.8rem;color:#6b7280;">{r['mo3']}</td>
          <td style="padding:8px 10px;text-align:center;font-size:.8rem;color:#6b7280;">{r['mo12']}</td>
          <td style="padding:8px 10px;text-align:center;font-size:1.1rem;color:{tc};">{r['trend']}</td>
          <td style="padding:8px 10px;font-size:.7rem;color:#9ca3af;white-space:nowrap;">{r['date']}</td>
        </tr>"""

    # ---- Economic Calendar -----------------------------------
    cal_rows=""
    for ev in (cal_events or []):
        bg  = "#fff3cd" if ev["is_today"] else "#f9fafb" if ev["is_past"] else "white"
        wt  = "800" if ev["is_today"] else "400"
        cal_rows += f"""
        <tr style="background:{bg};border-bottom:1px solid #f3f4f6;">
          <td style="padding:7px 10px;font-size:.78rem;font-weight:{wt};white-space:nowrap;">{ev['rel']}</td>
          <td style="padding:7px 10px;font-size:.82rem;">{ev['impact']}</td>
          <td style="padding:7px 10px;font-size:.82rem;font-weight:600;">{ev['abbr']}</td>
        </tr>"""
    if not cal_rows:
        cal_rows='<tr><td colspan="3" style="padding:10px;color:#9ca3af;font-size:.78rem;">No high-impact releases in window</td></tr>'

    # ---- AI Fun Fact -----------------------------------------
    fun_raw = secs.get("AI FUN FACT","").strip()
    if fun_raw:
        fun_raw = re.sub(r"^[-•*]\s*","",fun_raw.splitlines()[0].strip())
    else:
        fun_raw = "The first algorithmic trading program ran in 1976 on NYSE, decades before modern AI."

    # ---- Hidden market-context div ---------------------------
    fred_plain = "\n".join([f"  {r['label']}: {r['current']} trend:{r['trend']} -- {r['insight']}" for r in fred_data])
    cal_plain  = "\n".join([f"  {e['rel']}: {e['abbr']}" for e in (cal_events or [])])
    mctx = f"""MARKETPULSE AI MACRO CONTEXT - {today} {now} MT
MARKET AND KEY MOVES:
{secs.get('MARKET AND KEY MOVES','').strip()}
MACRO AND NEWS:
{secs.get('MACRO AND NEWS','').strip()}
EARNINGS AND EVENTS:
{secs.get('EARNINGS AND EVENTS','').strip()}
WHAT TO WATCH:
{secs.get('WHAT TO WATCH','').strip()}
FEAR AND GREED: {fg_score}/100 ({fg_label}) -- {fg_sig}
MARKET BREADTH: {breadth_data.get('value','N/A')} -- {breadth_data.get('signal','N/A')}
U OF MICHIGAN: {umich_val} {umich_trend}
ECONOMIC CALENDAR:
{cal_plain}
FRED INDICATORS:
{fred_plain}"""

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>MarketPulse AI · {today}</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>📈</text></svg>">
<style>
  :root{{--blue:#1a56db;--green:#057a55;--red:#c81e1e;--amber:#b45309;--ink:#111928;--muted:#6b7280;--border:#e5e7eb;--bg:#f3f4f6;--card:#ffffff;}}
  *{{box-sizing:border-box;margin:0;padding:0;}}
  body{{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--ink);padding-bottom:60px;}}
  .hero{{background:linear-gradient(135deg,#1e3a5f,#1a56db);color:#fff;padding:22px 20px 16px;text-align:center;}}
  .hero h1{{font-size:1.6rem;letter-spacing:3px;font-weight:800;}}
  .hero .sub{{opacity:.8;margin-top:4px;font-size:.82rem;}}
  .hero .ts{{opacity:.5;margin-top:2px;font-size:.68rem;}}
  .container{{max-width:1200px;margin:16px auto;padding:0 14px;}}
  .grid-2{{display:grid;grid-template-columns:1fr 1fr;gap:14px;}}
  .grid-3{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;}}
  .card{{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px 16px;box-shadow:0 1px 3px rgba(0,0,0,.05);}}
  .card h2{{font-size:.62rem;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:var(--blue);margin-bottom:9px;padding-bottom:7px;border-bottom:2px solid var(--border);}}
  .card.ag{{border-left:4px solid var(--green);}}
  .card.ab{{border-left:4px solid var(--blue);}}
  .card.aa{{border-left:4px solid var(--amber);}}
  .card.ar{{border-left:4px solid var(--red);}}
  .card ul{{list-style:none;padding:0;margin:0;}}
  .card ul li{{padding:5px 0 5px 14px;border-bottom:1px solid #f3f4f6;font-size:.82rem;line-height:1.5;color:#374151;position:relative;}}
  .card ul li:before{{content:"▸";position:absolute;left:0;color:var(--blue);font-size:.75rem;}}
  .card ul li:last-child{{border-bottom:none;}}
  .footer{{text-align:center;color:var(--muted);font-size:.68rem;margin-top:24px;}}
  .footer a{{color:var(--blue);text-decoration:none;}}
  @media(max-width:640px){{.grid-2,.grid-3{{grid-template-columns:1fr;}}.hero h1{{font-size:1.2rem;}}}}
</style>
</head>
<body>
<div id="market-context" style="display:none;white-space:pre;">{mctx}</div>

<div class="hero">
  <h1>📈 MARKETPULSE AI</h1>
  <div class="sub">Anil Abraham &nbsp;·&nbsp; {today}</div>
  <div class="ts">Last updated {now} MT</div>
</div>

<div class="container">

<!-- AI FUN FACT -->
<div style="background:linear-gradient(135deg,#1e3a5f,#1a56db);color:white;border-radius:10px;padding:12px 18px;margin-bottom:14px;display:flex;align-items:center;gap:12px;">
  <div style="font-size:1.8rem;flex-shrink:0;">🤖</div>
  <div>
    <div style="font-size:.58rem;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;opacity:.65;margin-bottom:3px;">AI Fun Fact of the Day</div>
    <div style="font-size:.85rem;line-height:1.5;opacity:.92;">{fun_raw}</div>
  </div>
</div>

<!-- ROW 1: Sentiment + Market & Key Moves + Macro & News -->
<div class="grid-3">

  <div class="card ar">
    <h2>🌡️ Sentiment</h2>
    {fg_bar}
    {breadth_bar}
    {umich_bar}
  </div>

  <div class="card ab">
    <h2>📊 Market & Key Moves</h2>
    <ul>{fmt_bullets(secs.get("MARKET AND KEY MOVES",""))}</ul>
  </div>

  <div class="card aa">
    <h2>🌐 Macro & News</h2>
    <ul>{fmt_bullets(secs.get("MACRO AND NEWS",""))}</ul>
  </div>

</div>

<!-- ROW 2: Earnings & Events + Economic Calendar + What to Watch -->
<div class="grid-3" style="margin-top:14px;">

  <div class="card ag">
    <h2>💰 Earnings & Events</h2>
    <ul>{fmt_bullets(secs.get("EARNINGS AND EVENTS",""))}</ul>
  </div>

  <div class="card ab">
    <h2>📅 Economic Calendar
      <span style="font-weight:400;color:var(--muted);font-size:.56rem;">&nbsp;High-impact · ±7 days · FRED</span>
    </h2>
    <table style="width:100%;border-collapse:collapse;">
      <tbody>{cal_rows}</tbody>
    </table>
  </div>

  <div class="card ag">
    <h2>🔭 What to Watch</h2>
    <ul>{fmt_bullets(secs.get("WHAT TO WATCH",""))}</ul>
  </div>

</div>

<!-- ROW 3: FRED Macro Indicators -->
<div style="margin-top:14px;">
  <div class="card">
    <h2>🏦 Macro Indicators
      <span style="font-weight:400;color:var(--muted);font-size:.56rem;">&nbsp;Federal Reserve FRED API · sorted alphabetically · insight shown in grey</span>
    </h2>
    <div style="overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:.78rem;">
        <thead>
          <tr style="background:#f3f4f6;">
            <th style="padding:7px 10px;text-align:left;font-size:.62rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">Indicator</th>
            <th style="padding:7px 10px;text-align:center;font-size:.62rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">Current</th>
            <th style="padding:7px 10px;text-align:center;font-size:.62rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">3 Mo Ago</th>
            <th style="padding:7px 10px;text-align:center;font-size:.62rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">12 Mo Ago</th>
            <th style="padding:7px 10px;text-align:center;font-size:.62rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">Trend</th>
            <th style="padding:7px 10px;font-size:.62rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">As Of</th>
          </tr>
        </thead>
        <tbody>{fred_rows}</tbody>
      </table>
    </div>
  </div>
</div>

<div class="footer">
  Built by <strong>Anil Abraham</strong> &nbsp;·&nbsp;
  <a href="https://www.edwardjones.com/us-en/market-news-insights/stock-market-news/daily-market-recap" target="_blank">Edward Jones</a> &nbsp;·&nbsp;
  <a href="https://www.cnbc.com/newsletters/" target="_blank">CNBC Squawk</a> &nbsp;·&nbsp;
  <a href="https://fred.stlouisfed.org" target="_blank">FRED API</a> &nbsp;·&nbsp;
  <a href="https://www.cnn.com/markets/fear-and-greed" target="_blank">CNN Fear &amp; Greed</a> &nbsp;·&nbsp;
  <a href="https://stooq.com" target="_blank">stooq.com</a> &nbsp;·&nbsp;
  Gemini 3.6 Flash &nbsp;·&nbsp; Not financial advice.
</div>

</div>
</body>
</html>"""

    with open("index.html","w",encoding="utf-8") as f: f.write(html)
    print("   ✅ index.html written")


# ============================================================
# MAIN RUNNER
# ============================================================

if __name__ == "__main__":
    print("🚀 MarketPulse AI Starting...")
    print("="*50)

    fred_data    = fetch_fred_data()
    cal_events   = fetch_economic_calendar()
    fg_data      = fetch_fear_greed()
    breadth_data = fetch_market_breadth()
    ej_text      = scrape_edward_jones()
    cnbc_text    = fetch_cnbc_email()

    briefing = synthesize_with_gemini(
        ej_text, cnbc_text, fred_data, fg_data, breadth_data, cal_events
    )

    build_html(
        briefing, ej_text, cnbc_text, fred_data,
        fg_data, breadth_data, cal_events
    )

    print("\n📧 Email disabled -- dashboard is primary output")
    print("\n"+"="*50)
    print("✅ MarketPulse AI Complete!")
    print("🌐 https://anil2040.github.io/market-pulse-ai")
    print("="*50)