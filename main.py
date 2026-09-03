# ============================================================
# MarketPulse AI - main.py
# Updated: September 2026
# ============================================================
# Pipeline:
#   1.  FRED macro indicators (11 series, parallel, ~4s)
#   2.  CNN Fear & Greed Index (JSON)
#   3.  VIX + Market Breadth attempt (Yahoo Finance / stooq)
#   4.  Edward Jones daily recap (web scrape)
#   5.  CNBC Morning Squawk (Yahoo IMAP)
#   6.  Yahoo Finance Morning Brief (Yahoo IMAP)
#   7.  Gemini AI synthesis (150s timeout, gemini-3.6-flash)
#   8.  Build HTML dashboard (index.html -> GitHub Pages)
# Email DISABLED -- dashboard is primary output.
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
# MDT = UTC-6 (summer), MST = UTC-7 (Nov-Mar, change manually)
MT = timezone(timedelta(hours=-6))

print("✅ Configuration loaded")
print(f"📧 Email: {YAHOO_EMAIL}")


# ============================================================
# STEP 1: FRED MACRO INDICATORS (11 series, parallel)
# ============================================================
# U of Michigan is now in FRED_SERIES but moved to Sentiment
# section visually. ThreadPoolExecutor fires all simultaneously.
# ============================================================

FRED_SERIES = [
    {"label":"Core PCE (Fed Target 2%)",   "id":"PCEPILFE",     "is_index":True,  "insight":"Fed's primary inflation target -- above 2% = rates stay elevated"},
    {"label":"Core CPI (ex Food/Energy)",  "id":"CPILFESL",     "is_index":True,  "insight":"Cleaner inflation signal the Fed watches most closely"},
    {"label":"CPI Inflation (Headline)",   "id":"CPIAUCSL",     "is_index":True,  "insight":"Headline CPI including food & energy prices"},
    {"label":"Fed Funds Rate",             "id":"FEDFUNDS",     "is_index":False, "insight":"Cost of borrowing -- rising = headwind for equity valuations"},
    {"label":"HY Credit Spread",           "id":"BAMLH0A0HYM2", "is_index":False, "insight":"Widening = credit stress = systemic risk rising (caution on dip-buying)"},
    {"label":"PCE Inflation (Headline)",   "id":"PCEPI",        "is_index":True,  "insight":"Fed's preferred inflation gauge (broader than CPI)"},
    {"label":"Unemployment Rate",          "id":"UNRATE",       "is_index":False, "insight":"Labor market health -- rising = consumer spending risk ahead"},
    {"label":"U of Michigan Sentiment",    "id":"UMCSENT",      "is_index":False, "no_pct":True, "insight":"Consumer confidence in current economic conditions (0-100 scale, avg ~75)"},
    {"label":"WTI Crude Oil",              "id":"DCOILWTICO",   "is_index":False, "prefix":"$", "insight":"Energy prices -- drives inflation & energy sector stock moves"},
    {"label":"10Y Treasury Yield",         "id":"GS10",         "is_index":False, "insight":"Risk-free benchmark rate -- rising = headwind for high-multiple stocks"},
    {"label":"2Y Treasury Yield",          "id":"GS2",          "is_index":False, "insight":"Fed expectations barometer -- rises when markets expect more rate hikes"},
    {"label":"Yield Curve (10Y-2Y)",       "id":"T10Y2Y",       "is_index":False, "insight":"Negative = inverted = historically predicts recession 12-18 months out"},
]


def _signal(label, cur_str, mo3_str, trend):
    """One-line investing signal from actual data values."""
    try:
        cur = float(re.sub(r"[%$]","",str(cur_str)))
        mo3 = float(re.sub(r"[%$]","",str(mo3_str)))
    except:
        return ""

    if "Core PCE" in label or "Core CPI" in label:
        if cur <= 2.0:              return "✅ At Fed 2% target -- rate cuts more likely"
        elif cur <= 2.5 and trend=="▼": return "📉 Cooling toward target -- Fed likely patient"
        elif cur > 3.0:             return "⚠️ Significantly above target -- rates staying elevated"
        elif trend=="▼":            return "📉 Cooling trend -- positive for rate-sensitive stocks"
        else:                       return "⚠️ Stuck above target -- watch for hawkish Fed signals"
    elif "PCE" in label or "CPI" in label:
        if trend=="▼": return "📉 Cooling"
        elif trend=="▲": return "⚠️ Heating up -- inflation persistence"
        else:          return "→ Stable"
    elif "Fed Funds" in label:
        if cur >= 5.0:   return "⚠️ Restrictive territory -- growth stock headwind"
        elif cur <= 3.0: return "✅ Accommodative -- supportive environment for equities"
        elif trend=="▼": return "📉 Cutting cycle underway -- positive for bonds & rate-sensitive sectors"
        else:            return "→ On hold -- Fed watching inflation before moving"
    elif "Unemployment" in label:
        if cur <= 4.0:   return "✅ Strong labor market -- consumer spending likely resilient"
        elif cur >= 5.0: return "⚠️ Weakening labor market -- recession risk elevated"
        elif trend=="▲": return "⚠️ Rising -- watch consumer discretionary and retail stocks"
        else:            return "✅ Stable -- no immediate recession signal from labor"
    elif "HY Credit" in label:
        if cur <= 3.0:   return "✅ Tight spreads -- credit markets calm, risk appetite healthy"
        elif cur >= 6.0: return "⚠️ Wide spreads -- credit stress, avoid leveraged balance sheets"
        elif trend=="▲": return "⚠️ Widening -- systemic risk rising, be selective on dip-buys"
        else:            return "→ Stable -- no credit market alarm signal"
    elif "Yield Curve" in label:
        if cur < 0:      return "⚠️ Inverted -- historically precedes recession by 12-18 months"
        elif cur < 0.3:  return "→ Nearly flat -- muted growth signal, monitor for inversion"
        else:            return "✅ Positive slope -- normal healthy curve"
    elif "10Y" in label:
        if cur >= 5.0:   return "⚠️ High yields -- expensive borrowing, P/E compression risk"
        elif cur <= 3.5: return "✅ Low yields -- supports higher equity valuations"
        elif trend=="▲": return "⚠️ Rising -- headwind for high-multiple growth stocks"
        else:            return "→ Stable -- watch for direction change"
    elif "2Y" in label:
        if trend=="▼":   return "✅ Falling -- markets pricing in rate cuts ahead"
        elif cur >= 5.0: return "⚠️ Elevated -- markets expect rates to stay high longer"
        else:            return "→ Stable -- Fed rate expectations anchored"
    elif "Michigan" in label:
        if cur >= 80:    return "✅ High confidence -- consumers expect solid economic conditions"
        elif cur <= 55:  return "⚠️ Below average (avg ~75) -- consumers worried about jobs & prices"
        elif cur <= 65:  return "→ Moderate confidence -- mixed economic outlook among consumers"
        elif trend=="▼": return "⚠️ Declining -- watch consumer discretionary stocks"
        else:            return "→ Improving -- cautiously positive consumer outlook"
    elif "WTI" in label:
        if cur >= 90:    return "⚠️ High -- inflationary pressure, positive for energy stocks"
        elif cur <= 60:  return "✅ Low -- helps consumers, negative for energy sector stocks"
        elif trend=="▲": return "⚠️ Rising -- watch for inflation spillover & energy stock moves"
        else:            return "→ Stable -- limited macro impact today"
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
        resp = requests.get(url, timeout=12)
        obs  = [o for o in resp.json().get("observations",[]) if o["value"]!="."]
        if not obs:
            return {**cfg,"current":"N/A","mo3":"N/A","mo12":"N/A","trend":"?","date":"N/A","sig":""}
        v0  = float(obs[0]["value"])
        v3  = float(obs[min(3, len(obs)-1)]["value"])
        v12 = float(obs[min(12,len(obs)-1)]["value"])

        if is_index and v12:
            cur   = (v0-v12)/v12*100
            v15   = float(obs[min(14,len(obs)-1)]["value"])
            mo3v  = (v3-v15)/v15*100 if v15 else cur
            dc,dm3,dm12 = f"{cur:.1f}%",f"{mo3v:.1f}%",f"{mo3v:.1f}%"
            trend = "▼" if cur<mo3v-0.05 else "▲" if cur>mo3v+0.05 else "→"
        elif no_pct:
            dc,dm3,dm12 = f"{v0:.1f}",f"{v3:.1f}",f"{v12:.1f}"
            trend = "▲" if v0>v3+0.05 else "▼" if v0<v3-0.05 else "→"
        elif prefix:
            dc,dm3,dm12 = f"{prefix}{v0:.1f}",f"{prefix}{v3:.1f}",f"{prefix}{v12:.1f}"
            trend = "▲" if v0>v3+0.05 else "▼" if v0<v3-0.05 else "→"
        else:
            dc,dm3,dm12 = f"{v0:.2f}%",f"{v3:.2f}%",f"{v12:.2f}%"
            trend = "▲" if v0>v3+0.05 else "▼" if v0<v3-0.05 else "→"

        pub = datetime.strptime(obs[0]["date"],"%Y-%m-%d").strftime("%b %d %Y")
        sig = _signal(label, dc, dm3, trend)
        return {**cfg,"current":dc,"mo3":dm3,"mo12":dm12,"trend":trend,"date":pub,"sig":sig}
    except Exception as e:
        return {**cfg,"current":"N/A","mo3":"N/A","mo12":"N/A","trend":"?","date":"N/A","sig":""}


def fetch_fred_data():
    print("\n🏦 Fetching FRED macro indicators (parallel)...")
    end   = date.today().strftime("%Y-%m-%d")
    start = (date.today()-timedelta(days=460)).strftime("%Y-%m-%d")
    rmap  = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(_fetch_one_fred,cfg,start,end):cfg for cfg in FRED_SERIES}
        for f in concurrent.futures.as_completed(futs):
            r = f.result(); rmap[r["label"]] = r
            print(f"   {'✅' if r['current']!='N/A' else '❌'} {r['label']}: {r['current']} {r['trend']}")
    results = [rmap.get(c["label"],{**c,"current":"N/A","mo3":"N/A","mo12":"N/A","trend":"?","date":"N/A","sig":""}) for c in FRED_SERIES]
    print(f"   🏦 FRED complete: {len(results)} indicators")
    return results


# ============================================================
# STEP 2: CNN FEAR & GREED
# ============================================================

def fetch_fear_greed():
    print("\n😨 Fetching CNN Fear & Greed...")
    try:
        url  = "https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        hdrs = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        fg   = requests.get(url,headers=hdrs,timeout=10).json().get("fear_and_greed",{})
        score = round(float(fg.get("score",50)))
        rating= fg.get("rating","Unknown").replace("_"," ").title()
        if   score<=24: label="Extreme Fear"; color="#c81e1e"; signal="Historically strong buying opportunity -- be greedy when others fear"
        elif score<=44: label="Fear";         color="#e97316"; signal="Market pessimism -- watch for mean reversion entry points"
        elif score<=55: label="Neutral";      color="#6b7280"; signal="No strong directional signal -- stay selective"
        elif score<=74: label="Greed";        color="#059669"; signal="Optimism elevated -- exercise caution on new buys"
        else:           label="Extreme Greed";color="#1a56db"; signal="Market overheated -- high mean reversion reversal risk"
        print(f"   ✅ Fear & Greed: {score}/100 ({label})")
        return {"score":score,"label":label,"color":color,"signal":signal,
                "prev_close":round(float(fg.get("previous_close",score))),
                "prev_week": round(float(fg.get("previous_1_week",score))),
                "prev_month":round(float(fg.get("previous_1_month",score))),
                "prev_year": round(float(fg.get("previous_1_year",score)))}
    except Exception as e:
        print(f"   ❌ Fear & Greed failed: {e}")
        return {"score":50,"label":"Unavailable","color":"#6b7280","signal":"Data unavailable",
                "prev_close":"N/A","prev_week":"N/A","prev_month":"N/A","prev_year":"N/A"}


# ============================================================
# STEP 3: VIX + MARKET BREADTH
# ============================================================
# VIX = CBOE Volatility Index (the "fear gauge")
# Fetched from Yahoo Finance -- universally available, reliable.
# Market Breadth (^S5TH) attempted as secondary indicator.
# Both are sentiment/risk indicators for mean reversion context.
# VIX interpretation:
#   < 15 = complacent market, low volatility
#   15-20 = normal
#   20-30 = elevated anxiety
#   > 30 = fear/panic = historically good mean reversion entry
#   > 40 = extreme panic = historically excellent buy signal
# ============================================================

def fetch_vix_and_breadth():
    print("\n📊 Fetching VIX and Market Breadth...")
    result = {"vix":"N/A","vix_prev":"N/A","vix_signal":"","vix_color":"#6b7280",
              "breadth":"N/A","breadth_raw":50,"breadth_prev":"N/A",
              "breadth_signal":"Data unavailable","breadth_color":"#6b7280","breadth_date":"N/A"}

    # --- VIX from Yahoo Finance (very reliable) ---------------
    try:
        url  = "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX?interval=1d&range=5d"
        hdrs = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
                "Accept":"application/json"}
        resp = requests.get(url,headers=hdrs,timeout=10)
        data = resp.json()
        meta = data["chart"]["result"][0]["meta"]
        vix  = float(meta.get("regularMarketPrice",20))
        prev = float(meta.get("previousClose",vix))

        if   vix < 15:  vsig="✅ Complacent market -- low fear, rally likely intact";   vcol="#059669"
        elif vix < 20:  vsig="→ Normal volatility -- no panic signal";                  vcol="#6b7280"
        elif vix < 30:  vsig="⚠️ Elevated anxiety -- watch for volatility spikes";      vcol="#e97316"
        elif vix < 40:  vsig="⚠️ Fear/panic zone -- mean reversion entries emerging";   vcol="#c81e1e"
        else:           vsig="🚨 Extreme panic -- historically excellent buy signal";    vcol="#7f1d1d"

        result["vix"]       = f"{vix:.1f}"
        result["vix_prev"]  = f"{prev:.1f}"
        result["vix_signal"]= vsig
        result["vix_color"] = vcol
        print(f"   ✅ VIX: {vix:.1f} ({vsig})")
    except Exception as e:
        print(f"   ❌ VIX failed: {e}")

    # --- Market Breadth (% S&P 500 above 200MA) ---------------
    # Try multiple sources -- stooq CSV, then Yahoo Finance API
    breadth_fetched = False
    for attempt, (url, parser_fn) in enumerate([
        # Attempt 1: stooq.com CSV
        ("https://stooq.com/q/d/l/?s=%5Es5th&i=d",
         lambda text: _parse_stooq_csv(text)),
        # Attempt 2: Yahoo Finance v8 API
        ("https://query1.finance.yahoo.com/v8/finance/chart/%5ES5TH?interval=1d&range=5d",
         lambda text: _parse_yahoo_json(text)),
    ]):
        try:
            hdrs = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)","Accept":"*/*"}
            resp = requests.get(url,headers=hdrs,timeout=10)
            val, prev_val, dt = parser_fn(resp.text)
            if val and val > 0:
                change = val - prev_val
                if   val<25:  bsig="Deeply Oversold -- Strong mean reversion setup";  bcol="#c81e1e"
                elif val<40:  bsig="Oversold -- Value opportunities emerging";          bcol="#e97316"
                elif val<60:  bsig="Neutral -- Mixed breadth, stock-pickers market";   bcol="#6b7280"
                elif val<75:  bsig="Healthy -- Broad participation, bulls in control"; bcol="#059669"
                else:         bsig="Overbought -- Be selective, reversal risk elevated";bcol="#1a56db"

                result["breadth"]       = f"{val:.1f}%"
                result["breadth_raw"]   = val
                result["breadth_prev"]  = f"{prev_val:.1f}%"
                result["breadth_signal"]= bsig
                result["breadth_color"] = bcol
                result["breadth_date"]  = dt
                print(f"   ✅ Market Breadth: {val:.1f}% as of {dt} (source {attempt+1})")
                breadth_fetched = True
                break
        except Exception as e:
            print(f"   ⚠️ Breadth source {attempt+1} failed: {e}")

    if not breadth_fetched:
        print("   ℹ️ Market Breadth unavailable -- using VIX as primary volatility signal")

    return result


def _parse_stooq_csv(text):
    """Parse stooq.com CSV response for ^S5TH."""
    lines = [l.strip() for l in text.strip().splitlines() if l.strip() and not l.startswith("Date")]
    if len(lines) < 1: raise ValueError("No data rows")
    latest = lines[-1].split(",")
    prev   = lines[-2].split(",") if len(lines)>1 else latest
    return float(latest[4]), float(prev[4]), latest[0]


def _parse_yahoo_json(text):
    """Parse Yahoo Finance v8 API JSON for index data."""
    import json
    data = json.loads(text)
    meta = data["chart"]["result"][0]["meta"]
    closes = data["chart"]["result"][0]["indicators"]["quote"][0]["close"]
    closes = [c for c in closes if c is not None]
    if len(closes) < 1: raise ValueError("No close prices")
    val  = closes[-1]
    prev = closes[-2] if len(closes)>1 else val
    ts   = data["chart"]["result"][0]["timestamp"][-1]
    dt   = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    return val, prev, dt


# ============================================================
# STEP 4: EDWARD JONES SCRAPE
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
        return text
    except Exception as e:
        print(f"   ❌ Edward Jones failed: {e}")
        return "Edward Jones data unavailable today."


# ============================================================
# STEP 5 & 6: EMAIL VIA IMAP (CNBC + Yahoo Finance)
# ============================================================
# Generic IMAP fetcher reused for both email sources.
# CNBC Morning Squawk: morningsquawk@response.cnbc.com
# Yahoo Finance Morning Brief: finance-morning-brief@newsletters.yahoo.net
# ============================================================

def _fetch_email(sender, label, char_limit=2500):
    """Generic IMAP email fetcher."""
    try:
        mail = imaplib.IMAP4_SSL("imap.mail.yahoo.com", 993)
        mail.login(YAHOO_EMAIL, YAHOO_PASSWORD)
        mail.select("INBOX")
        status, messages = mail.search(None, f'(FROM "{sender}")')
        if status!="OK" or not messages[0]:
            print(f"   ⚠️ No {label} emails found (sender: {sender})")
            mail.logout()
            return f"{label} email not found today."
        ids    = messages[0].split()
        latest = ids[-1]
        print(f"   Found {len(ids)} {label} emails, reading latest...")
        status, msg_data = mail.fetch(latest,"(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])
        body = ""
        # Try plain text first
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type()=="text/plain":
                    body=part.get_payload(decode=True).decode("utf-8",errors="ignore"); break
        # Fall back to HTML
        if not body:
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type()=="text/html":
                        body=BeautifulSoup(part.get_payload(decode=True).decode("utf-8",errors="ignore"),"html.parser").get_text("\n",strip=True); break
            else:
                body=BeautifulSoup(msg.get_payload(decode=True).decode("utf-8",errors="ignore"),"html.parser").get_text("\n",strip=True)
        mail.logout()
        body = body[:char_limit].strip()
        print(f"   ✅ {label}: {len(body)} chars")
        return body
    except Exception as e:
        print(f"   ❌ {label} IMAP failed: {e}")
        return f"{label} unavailable today."


def fetch_cnbc_email():
    print("\n📬 Fetching CNBC Morning Squawk via IMAP...")
    return _fetch_email("morningsquawk@response.cnbc.com","CNBC Morning Squawk")


def fetch_yahoo_morning_brief():
    print("\n📬 Fetching Yahoo Finance Morning Brief via IMAP...")
    # Confirmed sender: finance-morning-brief@newsletters.yahoo.net
    # Arrives ~4 AM MT daily -- contains earnings calendar & economic events
    return _fetch_email("finance-morning-brief@newsletters.yahoo.net","Yahoo Morning Brief",char_limit=2000)


# ============================================================
# STEP 7: GEMINI AI SYNTHESIS (150s timeout = 2.5 minutes)
# ============================================================
# 150s is generous for our use case -- current pipeline runs
# in ~60-90s total. Leaves headroom as we add data.
# GitHub Actions free = 2,000 min/month. At 3 min/run x 22
# weekdays = 66 min = just 3.3% of monthly quota.
# Monitor: github.com > Settings > Billing > Usage.
# ============================================================

def _call_gemini(prompt):
    client = genai.Client(api_key=GEMINI_API_KEY)
    return client.interactions.create(model="gemini-3.6-flash", input=prompt).output_text


def synthesize_with_gemini(ej_text, cnbc_text, yahoo_text,
                            fred_data, fg_data, vix_data):
    print("\n🤖 Sending to Gemini (150s timeout)...")
    try:
        fred_summary = "\n".join([
            f"- {r['label']}: {r['current']} (trend:{r['trend']}) {r.get('sig','')}"
            for r in fred_data if r["current"]!="N/A"
        ])
        vix_line = f"VIX (Volatility Index): {vix_data['vix']} (prev: {vix_data['vix_prev']}) -- {vix_data['vix_signal']}"
        breadth_line = f"Market Breadth (% S&P 500 above 200MA): {vix_data['breadth']} -- {vix_data['breadth_signal']}"

        prompt = f"""You are a sharp financial analyst writing a morning briefing for a 
deep-value mean reversion investor (Greenblatt/Munger style, buys oversold value stocks).

STRICT FORMATTING RULES -- follow exactly:
- Use ONLY these 4 section headers, exactly as written (no numbers, no markdown):
  MARKET AND KEY MOVES
  MACRO AND NEWS
  EARNINGS AND EVENTS
  WHAT TO WATCH
- Under each: 3-4 bullet points starting with dash (-)
- Each bullet: one specific fact or actionable insight, max 20 words
- IMPORTANT: Do NOT mention Fear & Greed Index or its score in ANY section
  (it has its own dedicated visual card on the dashboard)
- No paragraphs, no bold text, no nested bullets

After the 4 sections, add:
AI FUN FACT
- One surprising fact about AI, financial markets, or investing history. Max 25 words. Make it fascinating.

MARKET DATA:
VIX: {vix_data['vix']} -- {vix_data['vix_signal']}
Market Breadth: {vix_data['breadth']} -- {vix_data['breadth_signal']}

FRED INDICATORS:
{fred_summary}

EDWARD JONES RECAP:
{ej_text[:1000]}

CNBC MORNING SQUAWK:
{cnbc_text[:900]}

YAHOO FINANCE MORNING BRIEF (focus on earnings calendar & upcoming events):
{yahoo_text[:900]}
"""
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(_call_gemini, prompt)
            briefing = fut.result(timeout=150)  # 2.5 minute timeout

        print(f"   ✅ Gemini: {len(briefing)} chars")
        return briefing

    except concurrent.futures.TimeoutError:
        print("   ⚠️ Gemini timed out (>150s) -- using structured fallback")
    except Exception as e:
        print(f"   ❌ Gemini failed: {e}")

    return """MARKET AND KEY MOVES
- AI synthesis unavailable -- review FRED indicators and sentiment data below

MACRO AND NEWS
- Check FRED macro table for current economic indicators and trends

EARNINGS AND EVENTS
- See economic calendar in Yahoo Morning Brief source for upcoming releases

WHAT TO WATCH
- Review VIX level and market breadth in sentiment section for context

AI FUN FACT
- The first algorithmic trading program ran in 1976 on NYSE, decades before AI made it mainstream."""


# ============================================================
# STEP 8: PARSE SECTIONS
# ============================================================

def parse_sections(text):
    secs = {
        "MARKET AND KEY MOVES":"",
        "MACRO AND NEWS":"",
        "EARNINGS AND EVENTS":"",
        "WHAT TO WATCH":"",
        "AI FUN FACT":"",
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
        if "MARKET SUMMARY" in cln:  current="MARKET AND KEY MOVES"; continue
        if "MACRO AND NEWS" in cln or "MACRO & NEWS" in cln: current="MACRO AND NEWS"; continue
        if "EARNINGS AND EVENTS" in cln or "EARNINGS AND CALENDAR" in cln: current="EARNINGS AND EVENTS"; continue
        if "EARNINGS HIGHLIGHT" in cln: current="EARNINGS AND EVENTS"; continue
        if "WHAT TO WATCH" in cln or "PRE-MARKET" in cln or "MORNING OUTLOOK" in cln: current="WHAT TO WATCH"; continue
        if "AI FUN FACT" in cln or "FUN FACT" in cln: current="AI FUN FACT"; continue

        if current and line.strip():
            secs[current] += line.strip()+"\n"

    for name,content in secs.items():
        print(f"   {'📋' if content.strip() else '⚠️'} {name}: {len(content)} chars" if content.strip() else f"   ⚠️ {name}: EMPTY")
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


def build_html(briefing, ej_text, cnbc_text, yahoo_text,
               fred_data, fg_data, vix_data):
    print("\n🎨 Building HTML dashboard...")

    secs   = parse_sections(briefing)
    now_mt = datetime.now(MT)
    today  = now_mt.strftime("%A, %B %d, %Y")
    now    = now_mt.strftime("%I:%M %p")

    fg_score = fg_data.get("score",50)
    fg_label = fg_data.get("label","N/A")
    fg_color = fg_data.get("color","#6b7280")
    fg_sig   = fg_data.get("signal","")

    # Get U of Michigan from FRED for sentiment bar
    umich = next((r for r in fred_data if "Michigan" in r["label"]),None)
    umich_val = umich["current"] if umich else "N/A"
    umich_sig = umich.get("sig","") if umich else ""
    try: umich_num=float(str(umich_val).replace("%","")); ucol="#c81e1e" if umich_num<60 else "#6b7280" if umich_num<75 else "#059669"
    except: umich_num=55; ucol="#6b7280"

    vix_val  = vix_data.get("vix","N/A")
    vix_prev = vix_data.get("vix_prev","N/A")
    vix_sig  = vix_data.get("vix_signal","")
    vix_col  = vix_data.get("vix_color","#6b7280")
    try: vix_num=float(str(vix_val)); vix_pct=min(100,max(0,(vix_num/50)*100))
    except: vix_num=20; vix_pct=40

    bval     = vix_data.get("breadth","N/A")
    braw     = vix_data.get("breadth_raw",50)
    bsig     = vix_data.get("breadth_signal","Unavailable")
    bcol     = vix_data.get("breadth_color","#6b7280")
    bdate    = vix_data.get("breadth_date","N/A")

    # ---- Sentiment Bars (horizontal gradient with needle) ----
    def hbar(pct, grad, left_label, right_label, extra_labels=None):
        """Render a horizontal gradient bar with a position needle."""
        safe_pct = min(99, max(1, float(pct)))  # Keep needle visible
        midlabels = ""
        if extra_labels:
            positions = ["0%","22%","44%","66%","100%"]
            midlabels = "".join([f'<span style="position:absolute;left:{pos};transform:translateX(-50%);font-size:.56rem;color:#9ca3af;">{lbl}</span>'
                                  for pos,lbl in zip(positions,extra_labels)])
        return f"""
<div style="position:relative;height:16px;border-radius:99px;overflow:hidden;background:{grad};">
  <div style="position:absolute;top:0;bottom:0;width:4px;background:#1e3a5f;border-radius:2px;left:calc({safe_pct}% - 2px);"></div>
</div>
<div style="position:relative;height:12px;">
  {midlabels}
  <span style="position:absolute;left:0;font-size:.58rem;color:#9ca3af;">{left_label}</span>
  <span style="position:absolute;right:0;font-size:.58rem;color:#9ca3af;">{right_label}</span>
</div>"""

    # Fear & Greed (0-100, 5 zones)
    fg_bar = f"""
<div style="margin-bottom:12px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
    <span style="font-size:.72rem;font-weight:700;color:{fg_color};">😨 Fear & Greed: {fg_score}/100 &nbsp; {fg_label}</span>
    <span style="font-size:.62rem;color:#9ca3af;">CNN · daily</span>
  </div>
  {hbar(fg_score,"linear-gradient(to right,#c81e1e 0%,#e97316 22%,#9ca3af 44%,#86c440 66%,#059669 100%)","Extreme Fear","Extreme Greed",["Ext Fear","Fear","Neutral","Greed","Ext Greed"])}
  <div style="font-size:.7rem;color:{fg_color};margin-top:3px;">{fg_sig}</div>
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:3px;margin-top:6px;">
    {"".join([f'<div style="background:#f9fafb;border-radius:4px;padding:3px 6px;font-size:.65rem;"><span style="color:#9ca3af;">{lbl} </span><strong>{val}</strong></div>' for lbl,val in [("Yest",fg_data.get("prev_close","N/A")),("1Wk",fg_data.get("prev_week","N/A")),("1Mo",fg_data.get("prev_month","N/A")),("1Yr",fg_data.get("prev_year","N/A"))]])}
  </div>
</div>"""

    # VIX (0-50+ scale, capped at 50 for display)
    vix_bar = f"""
<div style="margin-bottom:12px;border-top:1px solid #f3f4f6;padding-top:10px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
    <span style="font-size:.72rem;font-weight:700;color:{vix_col};">📉 VIX (Volatility): {vix_val} <span style="font-weight:400;color:#9ca3af;font-size:.65rem;">prev {vix_prev}</span></span>
    <span style="font-size:.62rem;color:#9ca3af;">CBOE · daily</span>
  </div>
  {hbar(vix_pct,"linear-gradient(to right,#059669 0%,#86c440 25%,#9ca3af 45%,#e97316 65%,#c81e1e 100%)","Low (calm)","High (panic)")}
  <div style="font-size:.7rem;color:{vix_col};margin-top:3px;">{vix_sig}</div>
</div>"""

    # Market Breadth (0-100%)
    breadth_bar = f"""
<div style="margin-bottom:12px;border-top:1px solid #f3f4f6;padding-top:10px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
    <span style="font-size:.72rem;font-weight:700;color:{bcol};">📊 Breadth (% above 200MA): {bval}</span>
    <span style="font-size:.62rem;color:#9ca3af;">{bdate}</span>
  </div>
  {hbar(braw,"linear-gradient(to right,#c81e1e 0%,#e97316 25%,#9ca3af 45%,#86c440 65%,#059669 100%)","0% Oversold","100% Overbought")}
  <div style="font-size:.7rem;color:{bcol};margin-top:3px;">{bsig}</div>
  <div style="font-size:.65rem;color:#6b7280;background:#f9fafb;border-radius:4px;padding:3px 7px;margin-top:4px;">
    💡 Below 25% = deeply oversold (mean reversion buy signal) · Above 75% = be selective
  </div>
</div>"""

    # U of Michigan (0-100 score)
    umich_bar = f"""
<div style="border-top:1px solid #f3f4f6;padding-top:10px;">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;">
    <span style="font-size:.72rem;font-weight:700;color:{ucol};">🎓 Consumer Sentiment: {umich_val}/100</span>
    <span style="font-size:.62rem;color:#9ca3af;">{umich.get('date','') if umich else ''} · monthly</span>
  </div>
  {hbar(umich_num,"linear-gradient(to right,#c81e1e 0%,#e97316 30%,#9ca3af 55%,#059669 100%)","0 Low","100 High")}
  <div style="font-size:.7rem;color:{ucol};margin-top:3px;">{umich_sig}</div>
  <div style="font-size:.65rem;color:#6b7280;background:#f9fafb;border-radius:4px;padding:3px 7px;margin-top:4px;">
    💡 Historical average ~75 · Below 60 = consumers worried about jobs & inflation
  </div>
</div>"""

    # ---- FRED table (alpha sorted, U of Michigan excluded --  in Sentiment) ---
    sorted_fred = sorted([r for r in fred_data if "Michigan" not in r["label"]],
                         key=lambda x: x["label"])
    fred_rows = ""
    for r in sorted_fred:
        if any(x in r["label"] for x in ["CPI","PCE","Inflation"]):
            tc="#057a55" if r["trend"]=="▼" else "#c81e1e" if r["trend"]=="▲" else "#6b7280"
        else:
            tc="#057a55" if r["trend"]=="▲" else "#c81e1e" if r["trend"]=="▼" else "#6b7280"
        sig_cell = f'<td style="padding:7px 10px;font-size:.72rem;color:#1e3a5f;">{r.get("sig","")}</td>'
        fred_rows += f"""
        <tr style="border-bottom:1px solid #f3f4f6;">
          <td style="padding:7px 10px;">
            <div style="font-weight:600;font-size:.8rem;">{r['label']}</div>
            <div style="font-size:.65rem;color:#9ca3af;margin-top:1px;">[{r['insight']}]</div>
          </td>
          <td style="padding:7px 10px;text-align:center;font-weight:700;font-size:.88rem;">{r['current']}</td>
          <td style="padding:7px 10px;text-align:center;font-size:.78rem;color:#6b7280;">{r['mo3']}</td>
          <td style="padding:7px 10px;text-align:center;font-size:.78rem;color:#6b7280;">{r['mo12']}</td>
          <td style="padding:7px 10px;text-align:center;font-size:1.05rem;color:{tc};">{r['trend']}</td>
          <td style="padding:7px 10px;font-size:.68rem;color:#9ca3af;white-space:nowrap;">{r['date']}</td>
          {sig_cell}
        </tr>"""

    # ---- AI Fun Fact ------------------------------------------
    fun_raw = secs.get("AI FUN FACT","").strip()
    if fun_raw:
        fun_raw = re.sub(r"^[-•*]\s*","",fun_raw.splitlines()[0].strip())
    else:
        fun_raw = "The first algorithmic trading program ran in 1976 on NYSE, decades before modern AI made it mainstream."

    # ---- Hidden market-context div (Chrome extension) --------
    fred_plain = "\n".join([f"  {r['label']}: {r['current']} trend:{r['trend']} -- {r['insight']}" for r in fred_data])
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
VIX: {vix_val} -- {vix_sig}
MARKET BREADTH: {bval} -- {bsig}
U OF MICHIGAN: {umich_val} -- {umich_sig}
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
  :root{{--blue:#1a56db;--green:#057a55;--red:#c81e1e;--amber:#b45309;--ink:#111928;--muted:#6b7280;--border:#e5e7eb;--bg:#f3f4f6;--card:#fff;}}
  *{{box-sizing:border-box;margin:0;padding:0;}}
  body{{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--ink);padding-bottom:60px;}}
  .hero{{background:linear-gradient(135deg,#1e3a5f,#1a56db);color:#fff;padding:20px 20px 14px;text-align:center;}}
  .hero h1{{font-size:1.6rem;letter-spacing:3px;font-weight:800;}}
  .hero .sub{{opacity:.8;margin-top:3px;font-size:.82rem;}}
  .hero .ts{{opacity:.5;margin-top:2px;font-size:.68rem;}}
  .container{{max-width:1200px;margin:14px auto;padding:0 14px;}}
  .grid-2{{display:grid;grid-template-columns:1fr 1fr;gap:12px;}}
  .grid-3{{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;}}
  .card{{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px 16px;box-shadow:0 1px 3px rgba(0,0,0,.04);}}
  .card h2{{font-size:.62rem;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:var(--blue);margin-bottom:9px;padding-bottom:7px;border-bottom:2px solid var(--border);}}
  .card.ag{{border-left:4px solid var(--green);}}
  .card.ab{{border-left:4px solid var(--blue);}}
  .card.aa{{border-left:4px solid var(--amber);}}
  .card.ar{{border-left:4px solid var(--red);}}
  .card ul{{list-style:none;padding:0;margin:0;}}
  .card ul li{{padding:5px 0 5px 13px;border-bottom:1px solid #f3f4f6;font-size:.82rem;line-height:1.5;color:#374151;position:relative;}}
  .card ul li:before{{content:"▸";position:absolute;left:0;color:var(--blue);font-size:.72rem;}}
  .card ul li:last-child{{border-bottom:none;}}
  .footer{{text-align:center;color:var(--muted);font-size:.68rem;margin-top:22px;padding:0 14px;}}
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
<div style="background:linear-gradient(135deg,#1e3a5f,#1a56db);color:white;border-radius:10px;padding:11px 16px;margin-bottom:12px;display:flex;align-items:center;gap:12px;">
  <div style="font-size:1.6rem;flex-shrink:0;">🤖</div>
  <div>
    <div style="font-size:.57rem;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;opacity:.6;margin-bottom:2px;">AI Fun Fact of the Day</div>
    <div style="font-size:.84rem;line-height:1.5;opacity:.92;">{fun_raw}</div>
  </div>
</div>

<!-- ROW 1: Sentiment + Market & Key Moves + Macro & News -->
<div class="grid-3">
  <div class="card ar">
    <h2>🌡️ Sentiment</h2>
    {fg_bar}
    {vix_bar}
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

<!-- ROW 2: Earnings & Events + What to Watch -->
<div class="grid-2" style="margin-top:12px;">
  <div class="card ag">
    <h2>💰 Earnings & Events</h2>
    <ul>{fmt_bullets(secs.get("EARNINGS AND EVENTS",""))}</ul>
  </div>
  <div class="card ag">
    <h2>🔭 What to Watch</h2>
    <ul>{fmt_bullets(secs.get("WHAT TO WATCH",""))}</ul>
  </div>
</div>

<!-- ROW 3: FRED Macro Table -->
<div style="margin-top:12px;">
  <div class="card">
    <h2>🏦 Macro Indicators
      <span style="font-weight:400;color:var(--muted);font-size:.56rem;">
        &nbsp;Federal Reserve FRED API · sorted alphabetically · insight greyed below label · today's signal at right
      </span>
    </h2>
    <div style="overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:.78rem;">
        <thead>
          <tr style="background:#f3f4f6;">
            <th style="padding:7px 10px;text-align:left;font-size:.6rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);min-width:180px;">Indicator</th>
            <th style="padding:7px 10px;text-align:center;font-size:.6rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">Current</th>
            <th style="padding:7px 10px;text-align:center;font-size:.6rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">3 Mo Ago</th>
            <th style="padding:7px 10px;text-align:center;font-size:.6rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">12 Mo Ago</th>
            <th style="padding:7px 10px;text-align:center;font-size:.6rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">Trend</th>
            <th style="padding:7px 10px;font-size:.6rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">As Of</th>
            <th style="padding:7px 10px;font-size:.6rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);min-width:200px;">Today's Signal</th>
          </tr>
        </thead>
        <tbody>{fred_rows}</tbody>
      </table>
    </div>
  </div>
</div>

<!-- FOOTER -->
<div class="footer">
  Built by <strong>Anil Abraham</strong> &nbsp;·&nbsp;
  <a href="https://www.edwardjones.com/us-en/market-news-insights/stock-market-news/daily-market-recap" target="_blank">Edward Jones</a> &nbsp;·&nbsp;
  <a href="https://www.cnbc.com/newsletters/" target="_blank">CNBC Squawk</a> &nbsp;·&nbsp;
  <a href="https://finance.yahoo.com" target="_blank">Yahoo Finance</a> &nbsp;·&nbsp;
  <a href="https://fred.stlouisfed.org" target="_blank">FRED API</a> &nbsp;·&nbsp;
  <a href="https://www.cnn.com/markets/fear-and-greed" target="_blank">CNN Fear &amp; Greed</a> &nbsp;·&nbsp;
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
    fg_data      = fetch_fear_greed()
    vix_data     = fetch_vix_and_breadth()
    ej_text      = scrape_edward_jones()
    cnbc_text    = fetch_cnbc_email()
    yahoo_text   = fetch_yahoo_morning_brief()

    briefing = synthesize_with_gemini(
        ej_text, cnbc_text, yahoo_text,
        fred_data, fg_data, vix_data
    )

    build_html(
        briefing, ej_text, cnbc_text, yahoo_text,
        fred_data, fg_data, vix_data
    )

    print("\n📧 Email disabled -- dashboard is primary output")
    print("\n"+"="*50)
    print("✅ MarketPulse AI Complete!")
    print("🌐 https://anil2040.github.io/market-pulse-ai")
    print("="*50)