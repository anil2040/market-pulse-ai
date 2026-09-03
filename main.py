# ============================================================
# MarketPulse AI - main.py
# Updated: September 2026
# ============================================================
# Pipeline:
#   1.  FRED macro indicators (12 series, parallel, 20s timeout)
#   2.  CNN Fear & Greed (JSON)
#   3.  VIX + S&P 500 + Russell 2000 (Yahoo Finance)
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

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
YAHOO_EMAIL    = os.environ.get("YAHOO_EMAIL")
YAHOO_PASSWORD = os.environ.get("YAHOO_APP_PASSWORD")
FRED_API_KEY   = os.environ.get("FRED_API_KEY")

# Boise MDT = UTC-6 (summer), change to -7 in November
MT = timezone(timedelta(hours=-6))

print("✅ Configuration loaded")
print(f"📧 Email: {YAHOO_EMAIL}")


# ============================================================
# STEP 1: FRED MACRO INDICATORS (12 series, parallel, 20s)
# ============================================================

FRED_SERIES = [
    {"label":"Core PCE (Fed Target 2%)",   "id":"PCEPILFE",     "is_index":True,
     "insight":"Fed's primary inflation target -- above 2% = rates stay elevated"},
    {"label":"Core CPI (ex Food/Energy)",  "id":"CPILFESL",     "is_index":True,
     "insight":"Cleaner inflation signal the Fed watches most closely"},
    {"label":"CPI Inflation (Headline)",   "id":"CPIAUCSL",     "is_index":True,
     "insight":"Headline CPI including food & energy prices"},
    {"label":"Fed Funds Rate",             "id":"FEDFUNDS",     "is_index":False,
     "insight":"Cost of borrowing -- rising = headwind for equity valuations"},
    {"label":"HY Credit Spread",           "id":"BAMLH0A0HYM2", "is_index":False,
     "insight":"Widening = credit stress = systemic risk rising (caution on dip-buying)"},
    {"label":"PCE Inflation (Headline)",   "id":"PCEPI",        "is_index":True,
     "insight":"Fed's preferred inflation gauge (broader than CPI)"},
    {"label":"Unemployment Rate",          "id":"UNRATE",       "is_index":False,
     "insight":"Labor market health -- rising = consumer spending risk ahead"},
    {"label":"U of Michigan Sentiment",    "id":"UMCSENT",      "is_index":False,
     "no_pct":True, "insight":"Consumer confidence in economic conditions (0-100, historical avg ~75)"},
    {"label":"WTI Crude Oil",              "id":"DCOILWTICO",   "is_index":False,
     "prefix":"$", "insight":"Energy prices -- drives inflation & energy sector stock moves"},
    {"label":"10Y Treasury Yield",         "id":"GS10",         "is_index":False,
     "insight":"Risk-free benchmark -- rising = headwind for high-multiple stocks"},
    {"label":"2Y Treasury Yield",          "id":"GS2",          "is_index":False,
     "insight":"Fed rate expectations -- rising = markets pricing in rate hikes or no cuts"},
    {"label":"Yield Curve (10Y-2Y)",       "id":"T10Y2Y",       "is_index":False,
     "insight":"Negative = inverted = historically predicts recession 12-18 months ahead"},
]


def _signal(label, cur_str, mo3_str, trend):
    """Generate today's investing signal from actual data values and trend."""
    try:
        cur = float(re.sub(r"[%$]","",str(cur_str)))
        mo3 = float(re.sub(r"[%$]","",str(mo3_str)))
    except:
        return ""

    # IMPORTANT: Check trend FIRST before checking absolute levels
    # This prevents contradictions like "▲ trend but Stable signal"
    if "Core PCE" in label or "Core CPI" in label:
        if cur <= 2.0:                  return "✅ At Fed 2% target -- rate cuts more likely"
        elif cur <= 2.5 and trend=="▼": return "📉 Cooling toward 2% target -- Fed likely patient"
        elif cur > 3.0 and trend=="▲":  return "⚠️ Rising & above target -- rates staying elevated longer"
        elif cur > 3.0:                 return "⚠️ Significantly above target -- rates staying elevated"
        elif trend=="▼":                return "📉 Cooling trend -- positive for rate-sensitive stocks"
        elif trend=="▲":                return "⚠️ Rising -- hawkish Fed signal"
        else:                           return "→ Flat -- Fed watching for sustained cooling"
    elif "PCE" in label or "CPI" in label:
        if trend=="▼":   return "📉 Cooling inflation -- positive signal"
        elif trend=="▲": return "⚠️ Heating up -- inflation persistence risk"
        else:            return "→ Stable"
    elif "Fed Funds" in label:
        if cur >= 5.0:     return "⚠️ Restrictive territory -- significant growth headwind"
        elif cur <= 3.0:   return "✅ Accommodative -- supportive for equities"
        elif trend=="▼":   return "📉 Cutting cycle underway -- positive for bonds & rate-sensitive sectors"
        elif trend=="▲":   return "⚠️ Rising -- tightening in progress"
        else:              return "→ On hold -- Fed waiting for more inflation data"
    elif "Unemployment" in label:
        if cur <= 4.0 and trend!="▲": return "✅ Strong labor market -- consumer spending resilient"
        elif cur >= 5.0:               return "⚠️ Weakening -- recession risk elevated"
        elif trend=="▲":               return "⚠️ Rising -- watch consumer discretionary & retail"
        elif trend=="▼":               return "✅ Improving -- labor market tightening"
        else:                          return "✅ Stable -- no immediate recession signal"
    elif "HY Credit" in label:
        if cur <= 3.0:   return "✅ Tight spreads -- credit markets calm, risk appetite healthy"
        elif cur >= 6.0: return "⚠️ Wide spreads -- credit stress, avoid leveraged balance sheets"
        elif trend=="▲": return "⚠️ Widening -- systemic risk rising, be selective on dip-buys"
        elif trend=="▼": return "📉 Tightening -- credit improving, risk appetite recovering"
        else:            return "→ Stable -- no credit market alarm"
    elif "Yield Curve" in label:
        if cur < 0:      return "⚠️ Inverted -- historically precedes recession by 12-18 months"
        elif cur < 0.3:  return "→ Nearly flat -- muted growth signal"
        elif trend=="▲": return "✅ Steepening -- growth expectations improving"
        else:            return "✅ Positive slope -- normal healthy curve"
    elif "10Y" in label:
        if cur >= 5.0 and trend=="▲": return "⚠️ High & rising -- P/E compression risk intensifying"
        elif cur >= 5.0:              return "⚠️ High -- expensive borrowing, P/E compression risk"
        elif cur <= 3.5:              return "✅ Low -- supports higher equity valuations"
        elif trend=="▲":              return "⚠️ Rising -- headwind for high-multiple growth stocks"
        elif trend=="▼":              return "📉 Falling -- relief for rate-sensitive stocks"
        else:                         return "→ Stable -- watch for direction change"
    elif "2Y" in label:
        # MUST check trend first -- this was the source of the contradiction
        if trend=="▲" and cur >= 4.5: return "⚠️ Rising & elevated -- markets pricing in no rate cuts soon"
        elif trend=="▲":              return "⚠️ Rising -- markets pricing in rate hikes or delayed cuts"
        elif trend=="▼":              return "✅ Falling -- markets pricing in rate cuts ahead"
        elif cur >= 5.0:              return "⚠️ Elevated -- rates expected to stay high"
        else:                         return "→ Stable -- Fed rate expectations anchored"
    elif "Michigan" in label:
        if cur >= 80:    return "✅ High confidence -- consumers expect solid economic conditions"
        elif cur >= 66 and trend=="▲": return "✅ Improving -- consumer outlook strengthening"
        elif cur <= 55:  return f"⚠️ Well below avg (~75) -- consumers worried about jobs & inflation"
        elif cur <= 65:  return "→ Below average -- mixed consumer economic outlook"
        elif trend=="▼": return "⚠️ Declining -- watch consumer discretionary stocks"
        else:            return "→ Near average -- consumer confidence broadly stable"
    elif "WTI" in label:
        if cur >= 90 and trend=="▲": return "⚠️ High & rising -- inflation pressure & energy stock tailwind"
        elif cur >= 90:              return "⚠️ High -- inflationary, positive for energy stocks"
        elif cur <= 60:              return "✅ Low -- consumer-friendly, headwind for energy stocks"
        elif trend=="▲":             return "⚠️ Rising -- watch for inflation spillover"
        elif trend=="▼":             return "📉 Falling -- easing energy inflation"
        else:                        return "→ Stable -- limited macro impact today"
    return ""


def _fetch_one_fred(cfg, start_date, end_date):
    label=cfg["label"]; sid=cfg["id"]; is_index=cfg["is_index"]
    no_pct=cfg.get("no_pct",False); prefix=cfg.get("prefix","")
    try:
        url = (f"https://api.stlouisfed.org/fred/series/observations"
               f"?series_id={sid}&api_key={FRED_API_KEY}&file_type=json"
               f"&observation_start={start_date}&observation_end={end_date}"
               f"&sort_order=desc&limit=15")
        resp = requests.get(url, timeout=20)  # 20 second timeout
        obs  = [o for o in resp.json().get("observations",[]) if o["value"]!="."]
        if not obs:
            return {**cfg,"current":"N/A","mo3":"N/A","mo12":"N/A","trend":"?","date":"N/A","sig":""}
        v0=float(obs[0]["value"]); v3=float(obs[min(3,len(obs)-1)]["value"]); v12=float(obs[min(12,len(obs)-1)]["value"])
        if is_index and v12:
            cur=(v0-v12)/v12*100; v15=float(obs[min(14,len(obs)-1)]["value"])
            mo3v=(v3-v15)/v15*100 if v15 else cur
            dc,dm3,dm12=f"{cur:.1f}%",f"{mo3v:.1f}%",f"{mo3v:.1f}%"
            trend="▼" if cur<mo3v-0.05 else "▲" if cur>mo3v+0.05 else "→"
        elif no_pct:
            dc,dm3,dm12=f"{v0:.1f}",f"{v3:.1f}",f"{v12:.1f}"
            trend="▲" if v0>v3+0.05 else "▼" if v0<v3-0.05 else "→"
        elif prefix:
            dc,dm3,dm12=f"{prefix}{v0:.1f}",f"{prefix}{v3:.1f}",f"{prefix}{v12:.1f}"
            trend="▲" if v0>v3+0.05 else "▼" if v0<v3-0.05 else "→"
        else:
            dc,dm3,dm12=f"{v0:.2f}%",f"{v3:.2f}%",f"{v12:.2f}%"
            trend="▲" if v0>v3+0.05 else "▼" if v0<v3-0.05 else "→"
        pub=datetime.strptime(obs[0]["date"],"%Y-%m-%d").strftime("%b %d %Y")
        sig=_signal(label,dc,dm3,trend)
        return {**cfg,"current":dc,"mo3":dm3,"mo12":dm12,"trend":trend,"date":pub,"sig":sig}
    except Exception as e:
        return {**cfg,"current":"N/A","mo3":"N/A","mo12":"N/A","trend":"?","date":"N/A","sig":""}


def fetch_fred_data():
    print("\n🏦 Fetching FRED macro indicators (parallel, 20s timeout)...")
    end=date.today().strftime("%Y-%m-%d")
    start=(date.today()-timedelta(days=460)).strftime("%Y-%m-%d")
    rmap={}
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as ex:
        futs={ex.submit(_fetch_one_fred,cfg,start,end):cfg for cfg in FRED_SERIES}
        for f in concurrent.futures.as_completed(futs):
            r=f.result(); rmap[r["label"]]=r
            print(f"   {'✅' if r['current']!='N/A' else '❌'} {r['label']}: {r['current']} {r['trend']}")
    results=[rmap.get(c["label"],{**c,"current":"N/A","mo3":"N/A","mo12":"N/A","trend":"?","date":"N/A","sig":""}) for c in FRED_SERIES]
    print(f"   🏦 FRED complete: {len(results)} indicators")
    return results


# ============================================================
# STEP 2: CNN FEAR & GREED
# ============================================================

def fetch_fear_greed():
    print("\n😨 Fetching CNN Fear & Greed...")
    try:
        url="https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        hdrs={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        fg=requests.get(url,headers=hdrs,timeout=10).json().get("fear_and_greed",{})
        score=round(float(fg.get("score",50)))
        rating=fg.get("rating","Unknown").replace("_"," ").title()
        if   score<=24: label="Extreme Fear"; color="#c81e1e"
        elif score<=44: label="Fear";         color="#e97316"
        elif score<=55: label="Neutral";      color="#6b7280"
        elif score<=74: label="Greed";        color="#059669"
        else:           label="Extreme Greed";color="#1a56db"
        if   score<=24: signal="Historically strong buying opportunity -- Buffett: be greedy when others fear"
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
        return {"score":50,"label":"Unavailable","color":"#6b7280","signal":"Data unavailable",
                "prev_close":"N/A","prev_week":"N/A","prev_month":"N/A","prev_year":"N/A"}


# ============================================================
# STEP 3: MARKET INDICATORS (VIX, S&P 500, Russell 2000)
# ============================================================
# Matching your Chrome extension's categories exactly:
# S&P 500 / Russell 2000: SELLOFF / DOWN / FLAT / UP / RALLY
# VIX: PANIC / FEARFUL / CAUTIOUS / NORMAL / CALM
# Source: Yahoo Finance (same as your extension uses)
# 
# Market Breadth (% above 200MA) is valuable but NOT available
# via free real-time APIs without computing from 500 stocks.
# Best free source to check manually: StockCharts $SPXA200R
# We show VIX as the primary real-time volatility proxy instead.
# ============================================================

def _yahoo_quote(ticker):
    """Fetch a single Yahoo Finance quote. Returns (price, prev_close, change_pct)."""
    url  = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2d"
    hdrs = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)","Accept":"application/json"}
    resp = requests.get(url, headers=hdrs, timeout=12)
    data = resp.json()
    meta = data["chart"]["result"][0]["meta"]
    price = float(meta.get("regularMarketPrice",0))
    prev  = float(meta.get("previousClose", price))
    chg_pct = ((price-prev)/prev*100) if prev else 0
    return price, prev, chg_pct


def _classify_index(chg_pct):
    """Classify S&P/Russell change into SELLOFF/DOWN/FLAT/UP/RALLY labels."""
    if   chg_pct <= -2.0: return "SELLOFF", "#c81e1e"
    elif chg_pct <= -0.5: return "DOWN",    "#e97316"
    elif chg_pct <   0.5: return "FLAT",    "#6b7280"
    elif chg_pct <   2.0: return "UP",      "#059669"
    else:                 return "RALLY",   "#1a56db"


def _classify_vix(vix):
    """Classify VIX into PANIC/FEARFUL/CAUTIOUS/NORMAL/CALM labels."""
    if   vix >= 40: return "PANIC",    "#7f1d1d"
    elif vix >= 30: return "FEARFUL",  "#c81e1e"
    elif vix >= 20: return "CAUTIOUS", "#e97316"
    elif vix >= 15: return "NORMAL",   "#6b7280"
    else:           return "CALM",     "#059669"


def fetch_market_indicators():
    """Fetch VIX, S&P 500, and Russell 2000 from Yahoo Finance."""
    print("\n📊 Fetching Market Indicators (VIX, SPX, RUT)...")
    result = {
        "vix":{"value":"N/A","label":"N/A","color":"#6b7280","signal":""},
        "spx":{"value":"N/A","chg":"N/A","label":"N/A","color":"#6b7280"},
        "rut":{"value":"N/A","chg":"N/A","label":"N/A","color":"#6b7280"},
        "combined_signal":"",
    }
    try:
        # Fetch all three in parallel for speed
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            f_vix = ex.submit(_yahoo_quote, "%5EVIX")
            f_spx = ex.submit(_yahoo_quote, "%5EGSPC")
            f_rut = ex.submit(_yahoo_quote, "%5ERUT")
            vix_p, _, _   = f_vix.result(timeout=15)
            spx_p, _, spx_chg = f_spx.result(timeout=15)
            rut_p, _, rut_chg = f_rut.result(timeout=15)

        vix_label, vix_color = _classify_vix(vix_p)
        spx_label, spx_color = _classify_index(spx_chg)
        rut_label, rut_color = _classify_index(rut_chg)

        # VIX signal text
        if   vix_p >= 40: vix_sig="🚨 Extreme panic -- historically excellent mean reversion entry"
        elif vix_p >= 30: vix_sig="⚠️ High fear -- mean reversion entries emerging across sectors"
        elif vix_p >= 20: vix_sig="⚠️ Elevated anxiety -- watch for volatility spikes"
        elif vix_p >= 15: vix_sig="→ Normal volatility -- no broad market panic signal"
        else:             vix_sig="✅ Calm market -- low fear, rally likely intact"

        result["vix"] = {"value":f"{vix_p:.2f}","label":vix_label,"color":vix_color,"signal":vix_sig}
        result["spx"] = {"value":f"{spx_p:,.0f}","chg":f"{spx_chg:+.2f}%","label":spx_label,"color":spx_color}
        result["rut"] = {"value":f"{rut_p:,.0f}","chg":f"{rut_chg:+.2f}%","label":rut_label,"color":rut_color}

        # Combined market pulse sentence (used as first bullet in Market section)
        result["combined_signal"] = _make_pulse(vix_p, vix_label, spx_chg, spx_label, rut_chg, rut_label)

        print(f"   ✅ S&P 500: {spx_p:,.0f} ({spx_chg:+.2f}% {spx_label})")
        print(f"   ✅ Russell 2000: {rut_p:,.0f} ({rut_chg:+.2f}% {rut_label})")
        print(f"   ✅ VIX: {vix_p:.2f} ({vix_label})")

    except Exception as e:
        print(f"   ❌ Market indicators failed: {e}")
        result["combined_signal"] = "Market data unavailable -- check sources below."

    return result


def _make_pulse(vix, vix_lbl, spx_chg, spx_lbl, rut_chg, rut_lbl):
    """Generate a combined market pulse sentence from all indicators."""
    # Tone assessment
    if vix >= 30 or spx_lbl == "SELLOFF":
        tone = "broad market stress"
        action = "mean reversion entries emerging -- elevated fear historically precedes recoveries"
    elif spx_lbl in ("UP","RALLY") and rut_lbl in ("UP","RALLY"):
        tone = "broad market strength"
        action = "breadth confirming rally -- exercise caution on new deep-value buys at these levels"
    elif spx_lbl == "FLAT" or spx_lbl == "DOWN":
        tone = "mixed/cautious tape"
        action = "selective environment -- focus on individual stock catalysts over macro tailwinds"
    else:
        tone = "mixed signals"
        action = "stay selective, let individual setups lead positioning decisions"

    vix_note = f"VIX at {vix:.1f} ({vix_lbl.lower()})"
    spx_note = f"S&P 500 {spx_chg} ({spx_lbl})"
    rut_note = f"Russell {rut_chg} ({rut_lbl})"
    return f"Market Pulse: {spx_note}, {rut_note}, {vix_note} -- {tone}. {action}."


# ============================================================
# STEP 4: EDWARD JONES SCRAPE
# ============================================================

def scrape_edward_jones():
    print("\n🔍 Scraping Edward Jones...")
    url="https://www.edwardjones.com/us-en/market-news-insights/stock-market-news/daily-market-recap"
    hdrs={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp=requests.get(url,headers=hdrs,timeout=15)
        print(f"   Status: {resp.status_code}")
        soup=BeautifulSoup(resp.text,"html.parser")
        for tag in soup(["script","style","nav","footer","header"]): tag.decompose()
        lines=[l.strip() for l in soup.get_text("\n",strip=True).splitlines() if l.strip()]
        text="\n".join(lines[:120])
        print(f"   ✅ Edward Jones: {len(text)} chars")
        return text
    except Exception as e:
        print(f"   ❌ Edward Jones failed: {e}")
        return "Edward Jones data unavailable today."


# ============================================================
# STEP 5 & 6: EMAIL VIA IMAP
# ============================================================

def _fetch_email(sender, label, char_limit=2500):
    try:
        mail=imaplib.IMAP4_SSL("imap.mail.yahoo.com",993)
        mail.login(YAHOO_EMAIL,YAHOO_PASSWORD)
        mail.select("INBOX")
        status,messages=mail.search(None,f'(FROM "{sender}")')
        if status!="OK" or not messages[0]:
            print(f"   ⚠️ No {label} emails found (sender: {sender})")
            mail.logout(); return f"{label} not found today."
        ids=messages[0].split(); latest=ids[-1]
        print(f"   Found {len(ids)} {label} emails, reading latest...")
        status,msg_data=mail.fetch(latest,"(RFC822)")
        msg=email.message_from_bytes(msg_data[0][1])
        body=""
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
        body=body[:char_limit].strip()
        print(f"   ✅ {label}: {len(body)} chars")
        return body
    except Exception as e:
        print(f"   ❌ {label} IMAP failed: {e}")
        return f"{label} unavailable today."


def fetch_cnbc_email():
    print("\n📬 Fetching CNBC Morning Squawk...")
    return _fetch_email("morningsquawk@response.cnbc.com","CNBC Morning Squawk")


def fetch_yahoo_morning_brief():
    print("\n📬 Fetching Yahoo Finance Morning Brief...")
    # Confirmed sender: finance-morning-brief@newsletters.yahoo.net
    return _fetch_email("finance-morning-brief@newsletters.yahoo.net","Yahoo Morning Brief",char_limit=2000)


# ============================================================
# STEP 7: GEMINI AI SYNTHESIS (150s timeout)
# ============================================================

def _call_gemini(prompt):
    client=genai.Client(api_key=GEMINI_API_KEY)
    return client.interactions.create(model="gemini-3.6-flash",input=prompt).output_text


def synthesize_with_gemini(ej_text, cnbc_text, yahoo_text,
                            fred_data, fg_data, mkt_data):
    print("\n🤖 Sending to Gemini (150s timeout)...")
    try:
        fred_summary="\n".join([
            f"- {r['label']}: {r['current']} (trend:{r['trend']}) {r.get('sig','')}"
            for r in fred_data if r["current"]!="N/A"
        ])
        prompt=f"""You are a sharp financial analyst writing a morning briefing for a 
deep-value mean reversion investor (Greenblatt/Munger style).

STRICT FORMATTING RULES:
- Output EXACTLY these 4 section headers (no numbers, no markdown):
  MARKET AND KEY MOVES
  MACRO AND NEWS
  EARNINGS AND EVENTS
  WHAT TO WATCH
- Under each: 3-4 bullet points starting with dash (-)
- Each bullet: one specific fact or insight, max 20 words
- Do NOT mention Fear & Greed score/index -- it has its own visual card
- Do NOT mention VIX number -- it has its own visual card
- Do NOT mention S&P 500 or Russell 2000 percentage changes -- shown in sentiment section
- No paragraphs, no bold text, no nested bullets

After the 4 sections add:
AI FUN FACT
- One fascinating fact about AI, financial markets, or investing history. Max 25 words. Be surprising.

MARKET CONTEXT:
S&P 500: {mkt_data['spx']['value']} ({mkt_data['spx']['chg']}, {mkt_data['spx']['label']})
Russell 2000: {mkt_data['rut']['value']} ({mkt_data['rut']['chg']}, {mkt_data['rut']['label']})
VIX: {mkt_data['vix']['value']} ({mkt_data['vix']['label']})

FRED INDICATORS:
{fred_summary}

EDWARD JONES RECAP:
{ej_text[:1000]}

CNBC MORNING SQUAWK:
{cnbc_text[:900]}

YAHOO FINANCE MORNING BRIEF (extract earnings calendar & upcoming economic events):
{yahoo_text[:900]}
"""
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut=ex.submit(_call_gemini,prompt)
            briefing=fut.result(timeout=150)
        print(f"   ✅ Gemini: {len(briefing)} chars")
        return briefing
    except concurrent.futures.TimeoutError:
        print("   ⚠️ Gemini timed out (>150s) -- using structured fallback")
    except Exception as e:
        print(f"   ❌ Gemini failed: {e}")
    return """MARKET AND KEY MOVES
- AI synthesis unavailable -- review FRED indicators and sentiment data below

MACRO AND NEWS
- Check FRED macro table for current economic indicators and signals

EARNINGS AND EVENTS
- See Yahoo Morning Brief source for earnings calendar and upcoming events

WHAT TO WATCH
- Review sentiment section for VIX and market context

AI FUN FACT
- The first algorithmic trading program ran in 1976 on NYSE, decades before modern AI."""


# ============================================================
# STEP 8: PARSE SECTIONS
# ============================================================

def parse_sections(text):
    secs={"MARKET AND KEY MOVES":"","MACRO AND NEWS":"","EARNINGS AND EVENTS":"","WHAT TO WATCH":"","AI FUN FACT":""}
    current=None
    for line in text.splitlines():
        up=line.upper().strip()
        cln=re.sub(r"^\d+[\.\)]\s*","",up)
        cln=re.sub(r"^#+\s*","",cln)
        cln=re.sub(r"^\*+\s*","",cln)
        cln=cln.encode("ascii","ignore").decode().strip()
        if "MARKET AND KEY MOVES" in cln or ("MARKET" in cln and "KEY" in cln): current="MARKET AND KEY MOVES"; continue
        if "KEY MOVES" in cln and "MARKET" not in cln: current="MARKET AND KEY MOVES"; continue
        if "MARKET SUMMARY" in cln: current="MARKET AND KEY MOVES"; continue
        if "MACRO AND NEWS" in cln or "MACRO & NEWS" in cln: current="MACRO AND NEWS"; continue
        if "EARNINGS AND EVENTS" in cln or "EARNINGS AND CALENDAR" in cln: current="EARNINGS AND EVENTS"; continue
        if "EARNINGS HIGHLIGHT" in cln: current="EARNINGS AND EVENTS"; continue
        if "WHAT TO WATCH" in cln or "PRE-MARKET" in cln or "MORNING OUTLOOK" in cln: current="WHAT TO WATCH"; continue
        if "AI FUN FACT" in cln or "FUN FACT" in cln: current="AI FUN FACT"; continue
        if current and line.strip(): secs[current]+=line.strip()+"\n"
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
        line=re.sub(r"^[-•*]\s*","",line.strip())
        line=re.sub(r"\*\*(.+?)\*\*",r"<strong>\1</strong>",line)
        if line: items+=f"        <li>{line}</li>\n"
    return items or "<li>No data available</li>"


def _hbar(pct, grad, left_lbl, right_lbl, zone_labels=None):
    """Horizontal gradient bar with position needle."""
    safe=min(99,max(1,float(pct) if pct else 50))
    zones=""
    if zone_labels:
        # 5 evenly spaced labels
        positions=["0%","25%","50%","75%","100%"]
        zones="".join([f'<span style="position:absolute;left:{pos};transform:translateX(-50%);font-size:.55rem;color:#9ca3af;white-space:nowrap;">{lbl}</span>'
                       for pos,lbl in zip(positions,zone_labels)])
    return f"""
<div style="position:relative;height:14px;border-radius:99px;overflow:hidden;background:{grad};">
  <div style="position:absolute;top:0;bottom:0;width:4px;background:#1e3a5f;border-radius:2px;left:calc({safe}% - 2px);"></div>
</div>
<div style="position:relative;height:14px;margin-top:1px;">
  {zones}
  <span style="position:absolute;left:0;font-size:.56rem;color:#9ca3af;">{left_lbl}</span>
  <span style="position:absolute;right:0;font-size:.56rem;color:#9ca3af;">{right_lbl}</span>
</div>"""


def _index_bar(chg_pct_str, label, color):
    """Bar for S&P 500 / Russell 2000 using SELLOFF/DOWN/FLAT/UP/RALLY zones."""
    # Map the 5 categories to fixed positions: SELLOFF=10%, DOWN=28%, FLAT=50%, UP=72%, RALLY=90%
    pos_map={"SELLOFF":10,"DOWN":28,"FLAT":50,"UP":72,"RALLY":90}
    pct=pos_map.get(label,50)
    grad="linear-gradient(to right,#c81e1e 0%,#e97316 22%,#9ca3af 44%,#86c440 66%,#059669 100%)"
    return _hbar(pct,grad,"SELLOFF","RALLY",["SELLOFF","DOWN","FLAT","UP","RALLY"])


def build_html(briefing, ej_text, cnbc_text, yahoo_text,
               fred_data, fg_data, mkt_data):
    print("\n🎨 Building HTML dashboard...")

    secs=parse_sections(briefing)
    now_mt=datetime.now(MT)
    today=now_mt.strftime("%A, %B %d, %Y")
    now=now_mt.strftime("%I:%M %p")

    fg_score=fg_data.get("score",50)
    fg_label=fg_data.get("label","N/A")
    fg_color=fg_data.get("color","#6b7280")
    fg_sig=fg_data.get("signal","")

    vix_val  = mkt_data["vix"]["value"]
    vix_label= mkt_data["vix"]["label"]
    vix_color= mkt_data["vix"]["color"]
    vix_sig  = mkt_data["vix"]["signal"]
    spx_val  = mkt_data["spx"]["value"]
    spx_chg  = mkt_data["spx"]["chg"]
    spx_label= mkt_data["spx"]["label"]
    spx_color= mkt_data["spx"]["color"]
    rut_val  = mkt_data["rut"]["value"]
    rut_chg  = mkt_data["rut"]["chg"]
    rut_label= mkt_data["rut"]["label"]
    rut_color= mkt_data["rut"]["color"]
    combined = mkt_data.get("combined_signal","")

    # U of Michigan for sentiment bar
    umich=next((r for r in fred_data if "Michigan" in r["label"]),None)
    umich_val=umich["current"] if umich else "N/A"
    umich_sig=umich.get("sig","") if umich else ""
    try: umich_num=float(str(umich_val).replace("%","")); ucol="#c81e1e" if umich_num<60 else "#6b7280" if umich_num<75 else "#059669"
    except: umich_num=55; ucol="#6b7280"

    try: fg_num=int(fg_score)
    except: fg_num=50
    try: vix_num=float(str(vix_val)); vix_pct=min(99,max(1,(vix_num/50)*100))
    except: vix_num=20; vix_pct=40

    grad_rg  ="linear-gradient(to right,#c81e1e 0%,#e97316 22%,#9ca3af 44%,#86c440 66%,#059669 100%)"
    grad_gyr  ="linear-gradient(to right,#059669 0%,#86c440 30%,#9ca3af 50%,#e97316 70%,#c81e1e 100%)"

    # ---- Sentiment section HTML ---------------------------------
    # S&P 500 bar
    spx_pct_map={"SELLOFF":10,"DOWN":28,"FLAT":50,"UP":72,"RALLY":90}
    spx_pct=spx_pct_map.get(spx_label,50)
    spx_bar=f"""
<div style="margin-bottom:10px;">
  <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:3px;">
    <span style="font-size:.72rem;font-weight:700;color:{spx_color};">S&amp;P 500 &nbsp; {spx_val} &nbsp; <span style="font-weight:400;">{spx_chg}</span></span>
    <span style="font-size:.7rem;font-weight:700;color:{spx_color};">{spx_label}</span>
  </div>
  {_hbar(spx_pct,grad_rg,"SELLOFF","RALLY",["SELLOFF","DOWN","FLAT","UP","RALLY"])}
</div>"""

    # Russell 2000 bar
    rut_pct_map={"SELLOFF":10,"DOWN":28,"FLAT":50,"UP":72,"RALLY":90}
    rut_pct=rut_pct_map.get(rut_label,50)
    rut_bar=f"""
<div style="margin-bottom:10px;border-top:1px solid #f3f4f6;padding-top:8px;">
  <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:3px;">
    <span style="font-size:.72rem;font-weight:700;color:{rut_color};">Russell 2000 &nbsp; {rut_val} &nbsp; <span style="font-weight:400;">{rut_chg}</span></span>
    <span style="font-size:.7rem;font-weight:700;color:{rut_color};">{rut_label}</span>
  </div>
  {_hbar(rut_pct,grad_rg,"SELLOFF","RALLY",["SELLOFF","DOWN","FLAT","UP","RALLY"])}
</div>"""

    # VIX bar (inverted: calm=left=green, panic=right=red)
    vix_pct_map={"CALM":10,"NORMAL":30,"CAUTIOUS":55,"FEARFUL":75,"PANIC":92}
    vix_bar_pct=vix_pct_map.get(vix_label,50)
    vix_bar=f"""
<div style="margin-bottom:10px;border-top:1px solid #f3f4f6;padding-top:8px;">
  <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:3px;">
    <span style="font-size:.72rem;font-weight:700;color:{vix_color};">VIX &nbsp; {vix_val}</span>
    <span style="font-size:.7rem;font-weight:700;color:{vix_color};">{vix_label}</span>
  </div>
  {_hbar(vix_bar_pct,grad_gyr,"CALM","PANIC",["CALM","NORMAL","CAUTIOUS","FEARFUL","PANIC"])}
  <div style="font-size:.68rem;color:{vix_color};margin-top:3px;">{vix_sig}</div>
</div>"""

    # Fear & Greed bar
    fg_bar=f"""
<div style="margin-bottom:10px;border-top:1px solid #f3f4f6;padding-top:8px;">
  <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:3px;">
    <span style="font-size:.72rem;font-weight:700;color:{fg_color};">Fear &amp; Greed &nbsp; {fg_score}/100</span>
    <span style="font-size:.7rem;font-weight:700;color:{fg_color};">{fg_label}</span>
  </div>
  {_hbar(fg_num,grad_rg,"Extreme Fear","Extreme Greed",["Ext Fear","Fear","Neutral","Greed","Ext Greed"])}
  <div style="font-size:.68rem;color:{fg_color};margin-top:3px;">{fg_sig}</div>
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:3px;margin-top:5px;">
    {"".join([f'<div style="background:#f9fafb;border-radius:4px;padding:3px 5px;font-size:.62rem;"><span style="color:#9ca3af;">{l} </span><strong>{v}</strong></div>' for l,v in [("Yest",fg_data.get("prev_close","N/A")),("1Wk",fg_data.get("prev_week","N/A")),("1Mo",fg_data.get("prev_month","N/A")),("1Yr",fg_data.get("prev_year","N/A"))]])}
  </div>
</div>"""

    # U of Michigan bar
    umich_bar=f"""
<div style="border-top:1px solid #f3f4f6;padding-top:8px;">
  <div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:3px;">
    <span style="font-size:.72rem;font-weight:700;color:{ucol};">Consumer Sentiment &nbsp; {umich_val}/100</span>
    <span style="font-size:.62rem;color:#9ca3af;">{umich.get('date','') if umich else ''} · monthly</span>
  </div>
  {_hbar(umich_num,grad_rg,"0 Low","100 High")}
  <div style="font-size:.68rem;color:{ucol};margin-top:3px;">{umich_sig}</div>
  <div style="font-size:.62rem;color:#9ca3af;margin-top:2px;">Historical avg ~75 · Below 60 = consumers worried</div>
</div>"""

    # ---- FRED table (numbered, alpha sorted, U of Mich excluded) ---
    sorted_fred=sorted([r for r in fred_data if "Michigan" not in r["label"]],key=lambda x:x["label"])
    fred_rows=""
    for i,r in enumerate(sorted_fred,1):
        if any(x in r["label"] for x in ["CPI","PCE","Inflation"]):
            tc="#057a55" if r["trend"]=="▼" else "#c81e1e" if r["trend"]=="▲" else "#6b7280"
        else:
            tc="#057a55" if r["trend"]=="▲" else "#c81e1e" if r["trend"]=="▼" else "#6b7280"
        fred_rows+=f"""
        <tr style="border-bottom:1px solid #f3f4f6;">
          <td style="padding:7px 8px;text-align:center;font-size:.72rem;color:#9ca3af;font-weight:600;">{i}</td>
          <td style="padding:7px 10px;">
            <div style="font-weight:600;font-size:.8rem;">{r['label']}</div>
            <div style="font-size:.64rem;color:#9ca3af;margin-top:1px;">[{r['insight']}]</div>
          </td>
          <td style="padding:7px 10px;text-align:center;font-weight:700;font-size:.88rem;">{r['current']}</td>
          <td style="padding:7px 10px;text-align:center;font-size:.78rem;color:#6b7280;">{r['mo3']}</td>
          <td style="padding:7px 10px;text-align:center;font-size:.78rem;color:#6b7280;">{r['mo12']}</td>
          <td style="padding:7px 10px;text-align:center;font-size:1rem;color:{tc};">{r['trend']}</td>
          <td style="padding:7px 8px;font-size:.68rem;color:#9ca3af;white-space:nowrap;">{r['date']}</td>
          <td style="padding:7px 10px;font-size:.72rem;color:#1e3a5f;">{r.get('sig','')}</td>
        </tr>"""

    # ---- AI Fun Fact ------------------------------------------
    fun_raw=secs.get("AI FUN FACT","").strip()
    if fun_raw:
        fun_raw=re.sub(r"^[-•*]\s*","",fun_raw.splitlines()[0].strip())
    else:
        fun_raw="The first algorithmic trading program ran in 1976 on NYSE, decades before modern AI made it mainstream."

    # ---- Hidden market-context div (Chrome extension) --------
    fred_plain="\n".join([f"  {r['label']}: {r['current']} trend:{r['trend']} -- {r['insight']}" for r in fred_data])
    mctx=f"""MARKETPULSE AI MACRO CONTEXT - {today} {now} MT
MARKET PULSE: {combined}
S&P 500: {spx_val} ({spx_chg}, {spx_label})
Russell 2000: {rut_val} ({rut_chg}, {rut_label})
VIX: {vix_val} ({vix_label}) -- {vix_sig}
FEAR AND GREED: {fg_score}/100 ({fg_label}) -- {fg_sig}
U OF MICHIGAN: {umich_val} -- {umich_sig}
MARKET AND KEY MOVES:
{secs.get('MARKET AND KEY MOVES','').strip()}
MACRO AND NEWS:
{secs.get('MACRO AND NEWS','').strip()}
EARNINGS AND EVENTS:
{secs.get('EARNINGS AND EVENTS','').strip()}
WHAT TO WATCH:
{secs.get('WHAT TO WATCH','').strip()}
FRED INDICATORS:
{fred_plain}"""

    html=f"""<!DOCTYPE html>
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
  .card.ag{{border-left:4px solid var(--green);}} .card.ab{{border-left:4px solid var(--blue);}}
  .card.aa{{border-left:4px solid var(--amber);}} .card.ar{{border-left:4px solid var(--red);}}
  .card ul{{list-style:none;padding:0;margin:0;}}
  .card ul li{{padding:5px 0 5px 13px;border-bottom:1px solid #f3f4f6;font-size:.82rem;line-height:1.5;color:#374151;position:relative;}}
  .card ul li:before{{content:"▸";position:absolute;left:0;color:var(--blue);font-size:.72rem;}}
  .card ul li:last-child{{border-bottom:none;}}
  .pulse-bar{{background:#fff3cd;border:1px solid #ffc107;border-radius:7px;padding:8px 12px;margin-bottom:10px;font-size:.8rem;color:#7f5a00;line-height:1.45;}}
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

<!-- ROW 1: Market Sentiment + Market & Key Moves + Macro & News -->
<div class="grid-3">

  <div class="card ar">
    <h2>🌡️ Market Sentiment</h2>
    {spx_bar}
    {rut_bar}
    {vix_bar}
    {fg_bar}
    {umich_bar}
  </div>

  <div class="card ab">
    <h2>📊 Market & Key Moves</h2>
    <!-- Combined Market Pulse (data-driven, always accurate) -->
    <div class="pulse-bar">⚡ {combined}</div>
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

<!-- ROW 3: FRED Macro Indicators -->
<div style="margin-top:12px;">
  <div class="card">
    <h2>🏦 Macro Indicators
      <span style="font-weight:400;color:var(--muted);font-size:.56rem;">
        &nbsp; Federal Reserve FRED API · sorted alphabetically · numbered · Today's Signal at right
      </span>
    </h2>
    <div style="overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:.78rem;">
        <thead>
          <tr style="background:#f3f4f6;">
            <th style="padding:6px 8px;text-align:center;font-size:.58rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">#</th>
            <th style="padding:6px 10px;text-align:left;font-size:.58rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);min-width:180px;">Indicator</th>
            <th style="padding:6px 10px;text-align:center;font-size:.58rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">Current</th>
            <th style="padding:6px 10px;text-align:center;font-size:.58rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">3 Mo Ago</th>
            <th style="padding:6px 10px;text-align:center;font-size:.58rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">12 Mo Ago</th>
            <th style="padding:6px 10px;text-align:center;font-size:.58rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">Trend</th>
            <th style="padding:6px 8px;font-size:.58rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">As Of</th>
            <th style="padding:6px 10px;font-size:.58rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);min-width:200px;">Today's Signal</th>
          </tr>
        </thead>
        <tbody>{fred_rows}</tbody>
      </table>
    </div>
    <div style="margin-top:8px;font-size:.65rem;color:#9ca3af;">
      📊 Market Breadth (% S&P 500 above 200-day MA) not available via free real-time API.
      Check <a href="https://stockcharts.com/h-sc/ui?s=%24SPXA200R" target="_blank" style="color:#1a56db;">StockCharts $SPXA200R</a> manually for breadth readings.
      Below 25% = deeply oversold (strong mean reversion signal). Above 75% = be selective.
    </div>
  </div>
</div>

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
    mkt_data     = fetch_market_indicators()
    ej_text      = scrape_edward_jones()
    cnbc_text    = fetch_cnbc_email()
    yahoo_text   = fetch_yahoo_morning_brief()

    briefing = synthesize_with_gemini(
        ej_text, cnbc_text, yahoo_text,
        fred_data, fg_data, mkt_data
    )

    build_html(
        briefing, ej_text, cnbc_text, yahoo_text,
        fred_data, fg_data, mkt_data
    )

    print("\n📧 Email disabled -- dashboard is primary output")
    print("\n"+"="*50)
    print("✅ MarketPulse AI Complete!")
    print("🌐 https://anil2040.github.io/market-pulse-ai")
    print("="*50)