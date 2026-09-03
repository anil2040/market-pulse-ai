# ============================================================
# MarketPulse AI - main.py
# Updated: September 2026
# ============================================================
# Pipeline:
#   1.  FRED macro indicators (12 series, parallel, 20s timeout)
#   2.  CNN Fear & Greed (JSON)
#   3.  VIX + S&P 500 + Russell 2000 (Yahoo Finance API)
#       -- Same data source as Chrome extension (Yahoo Markets)
#       -- Same exact classification thresholds as extension
#   4.  Edward Jones daily recap (web scrape)
#   5.  CNBC Morning Squawk (Yahoo IMAP)
#   6.  Yahoo Finance Morning Brief (Yahoo IMAP)
#   7.  McClellan Oscillator newsletter (Yahoo IMAP) [NEW]
#   8.  Gemini AI synthesis (150s timeout, gemini-3.6-flash)
#   9.  Build HTML dashboard (index.html -> GitHub Pages)
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
     "insight":"Widening = credit stress = systemic risk rising"},
    {"label":"PCE Inflation (Headline)",   "id":"PCEPI",        "is_index":True,
     "insight":"Fed's preferred inflation gauge (broader than CPI)"},
    {"label":"Unemployment Rate",          "id":"UNRATE",       "is_index":False,
     "insight":"Labor market health -- rising = consumer spending risk"},
    {"label":"U of Michigan Sentiment",    "id":"UMCSENT",      "is_index":False,
     "no_pct":True, "insight":"Consumer confidence 0-100 (historical avg ~75)"},
    {"label":"WTI Crude Oil",              "id":"DCOILWTICO",   "is_index":False,
     "prefix":"$", "insight":"Energy prices -- drives inflation & energy stocks"},
    {"label":"10Y Treasury Yield",         "id":"GS10",         "is_index":False,
     "insight":"Risk-free benchmark -- rising = headwind for high-multiple stocks"},
    {"label":"2Y Treasury Yield",          "id":"GS2",          "is_index":False,
     "insight":"Fed rate expectations -- rising = markets pricing in no cuts"},
    {"label":"Yield Curve (10Y-2Y)",       "id":"T10Y2Y",       "is_index":False,
     "insight":"Negative = inverted = historically predicts recession ahead"},
]


def _signal(label, cur_str, mo3_str, trend):
    """Signal checked: trend FIRST to prevent contradictions."""
    try:
        cur = float(re.sub(r"[%$]","",str(cur_str)))
        mo3 = float(re.sub(r"[%$]","",str(mo3_str)))
    except:
        return ""

    if "Core PCE" in label or "Core CPI" in label:
        if cur <= 2.0:                  return "✅ At Fed 2% target -- rate cuts more likely"
        elif cur <= 2.5 and trend=="▼": return "📉 Cooling toward target -- Fed likely patient"
        elif cur > 3.0 and trend=="▲":  return "⚠️ Rising & above target -- rates staying elevated longer"
        elif cur > 3.0:                 return "⚠️ Significantly above target -- rates staying elevated"
        elif trend=="▼":                return "📉 Cooling -- positive for rate-sensitive stocks"
        elif trend=="▲":                return "⚠️ Rising -- hawkish Fed signal"
        else:                           return "→ Flat -- Fed watching for sustained cooling"
    elif "PCE" in label or "CPI" in label:
        if trend=="▼":   return "📉 Cooling inflation"
        elif trend=="▲": return "⚠️ Heating up -- inflation persistence"
        else:            return "→ Stable"
    elif "Fed Funds" in label:
        if trend=="▼":   return "📉 Cutting cycle underway -- positive for rate-sensitive sectors"
        elif trend=="▲": return "⚠️ Rising -- tightening in progress"
        elif cur >= 5.0: return "⚠️ Restrictive territory -- significant growth headwind"
        elif cur <= 3.0: return "✅ Accommodative -- supportive for equities"
        else:            return "→ On hold -- Fed watching for more inflation data"
    elif "Unemployment" in label:
        if trend=="▲":                 return "⚠️ Rising -- watch consumer discretionary & retail"
        elif trend=="▼" and cur<=4.0:  return "✅ Tightening -- strong labor market"
        elif cur <= 4.0:               return "✅ Strong labor market -- consumer spending resilient"
        elif cur >= 5.0:               return "⚠️ Weakening -- recession risk elevated"
        else:                          return "✅ Stable -- no immediate recession signal"
    elif "HY Credit" in label:
        if trend=="▲":   return "⚠️ Widening -- systemic risk rising, be selective on dip-buys"
        elif trend=="▼": return "📉 Tightening -- credit improving, risk appetite recovering"
        elif cur <= 3.0: return "✅ Tight spreads -- credit markets calm"
        elif cur >= 6.0: return "⚠️ Wide spreads -- credit stress, avoid leveraged balance sheets"
        else:            return "→ Stable -- no credit market alarm"
    elif "Yield Curve" in label:
        if cur < 0:      return "⚠️ Inverted -- historically predicts recession 12-18 months out"
        elif cur < 0.3:  return "→ Nearly flat -- muted growth signal"
        elif trend=="▲": return "✅ Steepening -- growth expectations improving"
        else:            return "✅ Positive slope -- normal healthy curve"
    elif "10Y" in label:
        if trend=="▲" and cur>=5.0: return "⚠️ High & rising -- P/E compression risk intensifying"
        elif trend=="▲":            return "⚠️ Rising -- headwind for high-multiple growth stocks"
        elif trend=="▼":            return "📉 Falling -- relief for rate-sensitive stocks"
        elif cur >= 5.0:            return "⚠️ High -- expensive borrowing, P/E compression risk"
        elif cur <= 3.5:            return "✅ Low -- supports higher equity valuations"
        else:                       return "→ Stable -- watch for direction change"
    elif "2Y" in label:
        if trend=="▲" and cur>=4.5: return "⚠️ Rising & elevated -- markets pricing in no rate cuts soon"
        elif trend=="▲":            return "⚠️ Rising -- markets pricing in rate hikes or delayed cuts"
        elif trend=="▼":            return "✅ Falling -- markets pricing in rate cuts ahead"
        elif cur >= 5.0:            return "⚠️ Elevated -- rates expected to stay high"
        else:                       return "→ Stable -- Fed rate expectations anchored"
    elif "Michigan" in label:
        if trend=="▼" and cur<=65:  return "⚠️ Declining & below avg -- consumers increasingly worried"
        elif trend=="▼":            return "⚠️ Declining -- watch consumer discretionary stocks"
        elif cur <= 55:             return "⚠️ Well below avg (~75) -- consumers worried about jobs & prices"
        elif cur <= 65:             return "→ Below average -- mixed consumer economic outlook"
        elif cur >= 80:             return "✅ High confidence -- solid consumer economic outlook"
        else:                       return "→ Near average -- consumer confidence broadly stable"
    elif "WTI" in label:
        if trend=="▲" and cur>=90:  return "⚠️ High & rising -- inflation pressure & energy tailwind"
        elif trend=="▲":            return "⚠️ Rising -- watch for inflation spillover"
        elif trend=="▼":            return "📉 Falling -- easing energy inflation"
        elif cur >= 90:             return "⚠️ High -- inflationary, positive for energy stocks"
        elif cur <= 60:             return "✅ Low -- consumer-friendly, headwind for energy stocks"
        else:                       return "→ Stable -- limited macro impact today"
    return ""


def _fetch_one_fred(cfg, start_date, end_date):
    label=cfg["label"]; sid=cfg["id"]; is_index=cfg["is_index"]
    no_pct=cfg.get("no_pct",False); prefix=cfg.get("prefix","")
    try:
        url=(f"https://api.stlouisfed.org/fred/series/observations"
             f"?series_id={sid}&api_key={FRED_API_KEY}&file_type=json"
             f"&observation_start={start_date}&observation_end={end_date}"
             f"&sort_order=desc&limit=15")
        resp=requests.get(url,timeout=20)
        obs=[o for o in resp.json().get("observations",[]) if o["value"]!="."]
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
    print("\n🏦 Fetching FRED macro indicators (parallel, 20s)...")
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
        if   score<=24: signal="Historically strong buying opportunity"
        elif score<=44: signal="Market pessimism -- watch for mean reversion entries"
        elif score<=55: signal="No strong directional signal -- stay selective"
        elif score<=74: signal="Optimism elevated -- exercise caution on new buys"
        else:           signal="Market overheated -- high reversal risk"
        print(f"   ✅ Fear & Greed: {score}/100 ({label})")
        return {
            "score":score, "label":label, "color":color, "signal":signal,
            "prev_close":round(float(fg.get("previous_close",score))),
            "prev_week": round(float(fg.get("previous_1_week",score))),
            "prev_month":round(float(fg.get("previous_1_month",score))),
            "prev_year": round(float(fg.get("previous_1_year",score))),
        }
    except Exception as e:
        print(f"   ❌ Fear & Greed failed: {e}")
        return {"score":50,"label":"Unavailable","color":"#6b7280","signal":"Data unavailable",
                "prev_close":"N/A","prev_week":"N/A","prev_month":"N/A","prev_year":"N/A"}


# ============================================================
# STEP 3: MARKET INDICATORS (VIX, S&P 500, Russell 2000)
# ============================================================
# EXACT same classification logic as Chrome extension background.js:
#   VIX: CALM(<15) NORMAL(<20) CAUTIOUS(<25) FEARFUL(<30) PANIC(>=30)
#   Index: SELLOFF(≤-1%) DOWN(-1 to -0.1%) FLAT(-0.1 to 0.1%)
#          UP(0.1 to 1%) RALLY(>1%)
# Source: Yahoo Finance v8 API (same underlying data as extension's
# Yahoo Markets page scrape)
# ============================================================

def _classify_vix(v):
    """Exact thresholds from background.js mktSignal() function."""
    if v < 15: return "CALM",    "#059669"
    if v < 20: return "NORMAL",  "#6b7280"
    if v < 25: return "CAUTIOUS","#e97316"
    if v < 30: return "FEARFUL", "#c81e1e"
    return         "PANIC",     "#7f1d1d"


def _classify_index(chg_pct):
    """Exact thresholds from background.js mktSignal() function."""
    if chg_pct >  1.0: return "RALLY",   "#059669"
    if chg_pct >  0.1: return "UP",      "#86c440"
    if chg_pct > -0.1: return "FLAT",    "#6b7280"
    if chg_pct > -1.0: return "DOWN",    "#e97316"
    return              "SELLOFF",       "#c81e1e"


def _vix_signal(v):
    if v >= 30: return "⚠️ Elevated fear -- mean reversion entries emerging across sectors"
    if v >= 25: return "⚠️ Cautious market -- watch for volatility spikes"
    if v >= 20: return "→ Slightly elevated -- no broad panic yet"
    if v >= 15: return "→ Normal volatility -- market not showing stress"
    return             "✅ Calm market -- low fear, complacent, rally likely intact"


def _yahoo_quote(ticker):
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2d"
    hdrs={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)","Accept":"application/json"}
    resp=requests.get(url,headers=hdrs,timeout=12)
    meta=resp.json()["chart"]["result"][0]["meta"]
    price=float(meta.get("regularMarketPrice",0))
    prev=float(meta.get("previousClose",price))
    chg=((price-prev)/prev*100) if prev else 0
    return price,prev,chg


def fetch_market_indicators():
    print("\n📊 Fetching Market Indicators (VIX, SPX, RUT)...")
    result={
        "vix":{"value":"N/A","label":"N/A","color":"#6b7280","signal":"","prev":"N/A"},
        "spx":{"value":"N/A","chg":"N/A","label":"N/A","color":"#6b7280","prev":"N/A"},
        "rut":{"value":"N/A","chg":"N/A","label":"N/A","color":"#6b7280","prev":"N/A"},
        "pulse":"",
    }
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            fv=ex.submit(_yahoo_quote,"%5EVIX")
            fs=ex.submit(_yahoo_quote,"%5EGSPC")
            fr=ex.submit(_yahoo_quote,"%5ERUT")
            vix_p,vix_prev,_   =fv.result(timeout=15)
            spx_p,spx_prev,spx_chg=fs.result(timeout=15)
            rut_p,rut_prev,rut_chg=fr.result(timeout=15)

        vix_lbl,vix_col=_classify_vix(vix_p)
        spx_lbl,spx_col=_classify_index(spx_chg)
        rut_lbl,rut_col=_classify_index(rut_chg)
        vix_sig=_vix_signal(vix_p)

        result["vix"]={"value":f"{vix_p:.2f}","label":vix_lbl,"color":vix_col,
                       "signal":vix_sig,"prev":f"{vix_prev:.2f}"}
        result["spx"]={"value":f"{spx_p:,.0f}","chg":f"{spx_chg:+.2f}%",
                       "label":spx_lbl,"color":spx_col,"prev":f"{spx_prev:,.0f}"}
        result["rut"]={"value":f"{rut_p:,.0f}","chg":f"{rut_chg:+.2f}%",
                       "label":rut_lbl,"color":rut_col,"prev":f"{rut_prev:,.0f}"}

        # Combined pulse sentence
        if vix_p>=30 or spx_lbl=="SELLOFF":
            pulse_tone="broad market stress -- mean reversion entries emerging"
        elif spx_lbl in("UP","RALLY") and rut_lbl in("UP","RALLY"):
            pulse_tone="broad strength -- exercise caution buying new deep-value positions"
        elif spx_lbl=="FLAT":
            pulse_tone="indecisive tape -- focus on individual stock catalysts"
        else:
            pulse_tone="mixed signals -- stay selective"
        result["pulse"]=(f"S&P 500 {spx_chg:+.2f}% ({spx_lbl}) · "
                         f"Russell {rut_chg:+.2f}% ({rut_lbl}) · "
                         f"VIX {vix_p:.1f} ({vix_lbl}) -- {pulse_tone}")

        print(f"   ✅ S&P 500: {spx_p:,.0f} {spx_chg:+.2f}% {spx_lbl}")
        print(f"   ✅ Russell 2000: {rut_p:,.0f} {rut_chg:+.2f}% {rut_lbl}")
        print(f"   ✅ VIX: {vix_p:.2f} {vix_lbl}")
    except Exception as e:
        print(f"   ❌ Market indicators failed: {e}")
        result["pulse"]="Market data unavailable."
    return result


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
# STEP 5, 6, 7: EMAIL VIA IMAP
# ============================================================
# Generic fetcher with extensive debug logging to diagnose
# Yahoo Morning Brief and McClellan Oscillator issues.
# ============================================================

def _fetch_email(sender, label, char_limit=2500):
    """Generic IMAP fetcher with debug logging."""
    print(f"\n📬 Fetching {label}...")
    print(f"   Sender: {sender}")
    try:
        mail=imaplib.IMAP4_SSL("imap.mail.yahoo.com",993)
        mail.login(YAHOO_EMAIL,YAHOO_PASSWORD)
        print(f"   ✅ Logged in")
        mail.select("INBOX")

        # Search by sender
        status,messages=mail.search(None,f'(FROM "{sender}")')
        print(f"   Search status: {status}")

        if status!="OK" or not messages[0]:
            # Try broader search -- maybe sender format differs
            print(f"   ⚠️ Exact FROM search found nothing, trying partial...")
            # Extract domain from sender for broader search
            domain=sender.split("@")[-1] if "@" in sender else sender
            status2,messages2=mail.search(None,f'(FROM "{domain}")')
            print(f"   Broad search status: {status2}, results: {messages2[0][:100] if messages2[0] else 'empty'}")
            if status2=="OK" and messages2[0]:
                messages=messages2
                print(f"   ✅ Found emails with broad search")
            else:
                print(f"   ❌ No emails found for {label} (tried both exact and broad search)")
                mail.logout()
                return f"{label} email not found today. (sender: {sender})"

        ids=messages[0].split()
        print(f"   Found {len(ids)} emails matching {label}")
        latest=ids[-1]

        # Peek at headers to confirm sender before fetching full email
        status,hdr_data=mail.fetch(latest,"(BODY[HEADER.FIELDS (FROM SUBJECT DATE)])")
        if hdr_data and hdr_data[0]:
            hdr_text=hdr_data[0][1].decode("utf-8",errors="ignore") if isinstance(hdr_data[0][1],bytes) else str(hdr_data[0][1])
            print(f"   Latest email headers:")
            for line in hdr_text.strip().splitlines()[:5]:
                print(f"     {line}")

        # Fetch full email
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
        print(f"   ✅ {label}: {len(body)} chars captured")
        return body
    except Exception as e:
        print(f"   ❌ {label} IMAP failed: {e}")
        return f"{label} unavailable today."


def fetch_cnbc_email():
    return _fetch_email("morningsquawk@response.cnbc.com","CNBC Morning Squawk")


def fetch_yahoo_morning_brief():
    # Confirmed sender: finance-morning-brief@newsletters.yahoo.net
    return _fetch_email("finance-morning-brief@newsletters.yahoo.net","Yahoo Morning Brief",char_limit=2000)


def fetch_mcoscillator_email():
    # McClellan Oscillator newsletter: admin@mcoscillator.com
    # Contains market breadth signal and mean reversion context
    return _fetch_email("admin@mcoscillator.com","McClellan Oscillator",char_limit=1500)


# ============================================================
# STEP 8: GEMINI AI SYNTHESIS (150s timeout)
# ============================================================

def _call_gemini(prompt):
    client=genai.Client(api_key=GEMINI_API_KEY)
    return client.interactions.create(model="gemini-3.6-flash",input=prompt).output_text


def synthesize_with_gemini(ej_text, cnbc_text, yahoo_text, mcoscillator_text,
                            fred_data, fg_data, mkt_data):
    print("\n🤖 Sending to Gemini (150s timeout)...")
    try:
        fred_summary="\n".join([
            f"- {r['label']}: {r['current']} (trend:{r['trend']}) {r.get('sig','')}"
            for r in fred_data if r["current"]!="N/A"
        ])
        prompt=f"""You are a sharp financial analyst writing a morning briefing for a 
deep-value mean reversion investor (Greenblatt/Munger style).

STRICT RULES:
- Output EXACTLY these 4 section headers (no numbers, no markdown):
  MARKET AND KEY MOVES
  MACRO AND NEWS
  EARNINGS AND EVENTS
  WHAT TO WATCH
- Under each: 3-4 bullet points starting with dash (-)
- Max 20 words per bullet, one specific fact per bullet
- Do NOT mention Fear & Greed score, VIX number, or S&P/Russell % -- shown visually
- Include any economic calendar events, earnings dates, or upcoming releases in EARNINGS AND EVENTS
- No paragraphs, no bold, no nested bullets

Then add:
AI FUN FACT
- One fascinating AI or investing history fact. Max 25 words.

MARKET CONTEXT (do not repeat these numbers in bullets):
{mkt_data['pulse']}

FRED INDICATORS:
{fred_summary}

EDWARD JONES RECAP:
{ej_text[:1000]}

CNBC MORNING SQUAWK:
{cnbc_text[:800]}

YAHOO MORNING BRIEF (focus on earnings calendar & economic events -- include specific dates):
{yahoo_text[:800]}

McCLELLAN OSCILLATOR NEWSLETTER (market breadth signal):
{mcoscillator_text[:600]}
"""
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut=ex.submit(_call_gemini,prompt)
            briefing=fut.result(timeout=150)
        print(f"   ✅ Gemini: {len(briefing)} chars")
        return briefing
    except concurrent.futures.TimeoutError:
        print("   ⚠️ Gemini timed out (>150s) -- using fallback")
    except Exception as e:
        print(f"   ❌ Gemini failed: {e}")
    return """MARKET AND KEY MOVES
- AI synthesis unavailable -- see FRED indicators and sentiment table below

MACRO AND NEWS
- Check FRED macro table for current economic indicators

EARNINGS AND EVENTS
- See Yahoo Morning Brief source for earnings calendar

WHAT TO WATCH
- Review sentiment table and FRED data for context

AI FUN FACT
- The first algorithmic trading program ran in 1976 on NYSE, decades before modern AI."""


# ============================================================
# STEP 9: PARSE SECTIONS
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
# STEP 10: BUILD HTML DASHBOARD
# ============================================================
# Layout (2-column then 3-column):
#
#  [Market Sentiment TABLE] | [Market & Key Moves + Macro & News]
#  [Earnings & Events]      | [What to Watch]
#  [FRED Macro Indicators - full width]
#
# Sentiment section: table format matching Chrome extension style
# -- readable, historical context, Chrome extension friendly
# ============================================================

def fmt_bullets(raw):
    if not raw or not raw.strip(): return "<li>No data available</li>"
    items=""
    for line in raw.strip().splitlines():
        line=re.sub(r"^[-•*]\s*","",line.strip())
        line=re.sub(r"\*\*(.+?)\*\*",r"<strong>\1</strong>",line)
        if line: items+=f"        <li>{line}</li>\n"
    return items or "<li>No data available</li>"


def build_html(briefing, ej_text, cnbc_text, yahoo_text, mcoscillator_text,
               fred_data, fg_data, mkt_data):
    print("\n🎨 Building HTML dashboard...")

    secs=parse_sections(briefing)
    now_mt=datetime.now(MT)
    today=now_mt.strftime("%A, %B %d, %Y")
    now=now_mt.strftime("%I:%M %p")

    # Market indicator values
    vix_val  =mkt_data["vix"]["value"]
    vix_prev =mkt_data["vix"]["prev"]
    vix_lbl  =mkt_data["vix"]["label"]
    vix_col  =mkt_data["vix"]["color"]
    vix_sig  =mkt_data["vix"]["signal"]
    spx_val  =mkt_data["spx"]["value"]
    spx_chg  =mkt_data["spx"]["chg"]
    spx_prev =mkt_data["spx"]["prev"]
    spx_lbl  =mkt_data["spx"]["label"]
    spx_col  =mkt_data["spx"]["color"]
    rut_val  =mkt_data["rut"]["value"]
    rut_chg  =mkt_data["rut"]["chg"]
    rut_prev =mkt_data["rut"]["prev"]
    rut_lbl  =mkt_data["rut"]["label"]
    rut_col  =mkt_data["rut"]["color"]
    pulse    =mkt_data["pulse"]

    fg_score =fg_data.get("score",50)
    fg_lbl   =fg_data.get("label","N/A")
    fg_col   =fg_data.get("color","#6b7280")
    fg_sig   =fg_data.get("signal","")

    # U of Michigan from FRED
    umich=next((r for r in fred_data if "Michigan" in r["label"]),None)
    umich_val=umich["current"] if umich else "N/A"
    umich_mo3=umich["mo3"]     if umich else "N/A"
    umich_mo12=umich["mo12"]   if umich else "N/A"
    umich_sig=umich.get("sig","") if umich else ""
    try: umich_num=float(str(umich_val)); ucol="#c81e1e" if umich_num<60 else "#6b7280" if umich_num<75 else "#059669"
    except: ucol="#6b7280"

    # ---- Sentiment TABLE (matching extension style) -----------
    # Each row: Indicator | Current | vs Prev | Signal | Historical
    def sig_badge(label, color):
        return f'<span style="background:{color};color:white;padding:2px 8px;border-radius:4px;font-size:.7rem;font-weight:700;">{label}</span>'

    def row(indicator, current, prev_or_chg, label, color, signal, mo3="", mo12="", note=""):
        hist=""
        if mo3 and mo12:
            hist=f'<div style="font-size:.62rem;color:#9ca3af;margin-top:2px;">3mo: {mo3} &nbsp; 12mo: {mo12}</div>'
        elif mo3:
            hist=f'<div style="font-size:.62rem;color:#9ca3af;margin-top:2px;">Prev close: {mo3}</div>'
        note_html=f'<div style="font-size:.65rem;color:#6b7280;margin-top:1px;">{note}</div>' if note else ""
        return f"""
        <tr style="border-bottom:1px solid #f3f4f6;">
          <td style="padding:8px 10px;">
            <div style="font-weight:600;font-size:.82rem;">{indicator}</div>
            {hist}
          </td>
          <td style="padding:8px 10px;font-weight:700;font-size:.9rem;color:{color};">{current}</td>
          <td style="padding:8px 10px;font-size:.78rem;color:#6b7280;">{prev_or_chg}</td>
          <td style="padding:8px 10px;">{sig_badge(label,color)}</td>
          <td style="padding:8px 10px;font-size:.72rem;color:#374151;">{signal}{note_html}</td>
        </tr>"""

    sentiment_rows=(
        row("S&P 500", spx_val, spx_chg, spx_lbl, spx_col,
            "Large-cap US equities", mo3=f"prev {spx_prev}")
        + row("Russell 2000", rut_val, rut_chg, rut_lbl, rut_col,
              "Small-cap US equities", mo3=f"prev {rut_prev}")
        + row("VIX (Volatility)", vix_val, f"prev {vix_prev}", vix_lbl, vix_col,
              vix_sig)
        + row("Fear & Greed", f"{fg_score}/100", f"1wk: {fg_data.get('prev_week','N/A')}  1mo: {fg_data.get('prev_month','N/A')}  1yr: {fg_data.get('prev_year','N/A')}", fg_lbl, fg_col,
              fg_sig)
        + row("Consumer Sentiment", f"{umich_val}/100", f"3mo: {umich_mo3}  12mo: {umich_mo12}", 
              "HIGH" if umich_num>=75 else "LOW" if umich_num<60 else "MID",
              ucol, umich_sig,
              note="U of Michigan · historical avg ~75")
    )

    # ---- FRED table rows (numbered, alpha, U of Mich excluded) ---
    sorted_fred=sorted([r for r in fred_data if "Michigan" not in r["label"]],key=lambda x:x["label"])
    fred_rows=""
    for i,r in enumerate(sorted_fred,1):
        if any(x in r["label"] for x in ["CPI","PCE","Inflation"]):
            tc="#057a55" if r["trend"]=="▼" else "#c81e1e" if r["trend"]=="▲" else "#6b7280"
        else:
            tc="#057a55" if r["trend"]=="▲" else "#c81e1e" if r["trend"]=="▼" else "#6b7280"
        fred_rows+=f"""
        <tr style="border-bottom:1px solid #f3f4f6;">
          <td style="padding:7px 8px;text-align:center;font-size:.7rem;color:#9ca3af;font-weight:600;">{i}</td>
          <td style="padding:7px 10px;">
            <div style="font-weight:600;font-size:.8rem;">{r['label']}</div>
            <div style="font-size:.63rem;color:#9ca3af;margin-top:1px;">[{r['insight']}]</div>
          </td>
          <td style="padding:7px 10px;text-align:center;font-weight:700;font-size:.88rem;">{r['current']}</td>
          <td style="padding:7px 10px;text-align:center;font-size:.78rem;color:#6b7280;">{r['mo3']}</td>
          <td style="padding:7px 10px;text-align:center;font-size:.78rem;color:#6b7280;">{r['mo12']}</td>
          <td style="padding:7px 10px;text-align:center;font-size:1rem;color:{tc};">{r['trend']}</td>
          <td style="padding:7px 8px;font-size:.67rem;color:#9ca3af;white-space:nowrap;">{r['date']}</td>
          <td style="padding:7px 10px;font-size:.72rem;color:#1e3a5f;">{r.get('sig','')}</td>
        </tr>"""

    # ---- AI Fun Fact ------------------------------------------
    fun_raw=secs.get("AI FUN FACT","").strip()
    if fun_raw:
        fun_raw=re.sub(r"^[-•*]\s*","",fun_raw.splitlines()[0].strip())
    else:
        fun_raw="In 1987, early quantitative program trading models triggered automated sell cascades, significantly accelerating the Black Monday crash."

    # ---- Hidden market-context div (Chrome extension) --------
    fred_plain="\n".join([f"  {r['label']}: {r['current']} trend:{r['trend']} -- {r['insight']}" for r in fred_data])
    mctx=f"""MARKETPULSE AI MACRO CONTEXT - {today} {now} MT
=== MARKET CONTEXT ===
               1D           Price        Signal
S&P 500        {spx_chg:<12} {spx_val:<12} {spx_lbl}
Russell 2000   {rut_chg:<12} {rut_val:<12} {rut_lbl}
VIX            {mkt_data['vix']['value']:<12} {mkt_data['vix']['value']:<12} {vix_lbl}

Fear & Greed: {fg_score}/100 ({fg_lbl}) -- {fg_sig}
Consumer Sentiment (U of Michigan): {umich_val}/100 -- {umich_sig}

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
  .card{{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px 16px;box-shadow:0 1px 3px rgba(0,0,0,.04);}}
  .card h2{{font-size:.62rem;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;color:var(--blue);margin-bottom:9px;padding-bottom:7px;border-bottom:2px solid var(--border);}}
  .card.ag{{border-left:4px solid var(--green);}} .card.ab{{border-left:4px solid var(--blue);}}
  .card.aa{{border-left:4px solid var(--amber);}} .card.ar{{border-left:4px solid var(--red);}}
  .card ul{{list-style:none;padding:0;margin:0;}}
  .card ul li{{padding:5px 0 5px 13px;border-bottom:1px solid #f3f4f6;font-size:.82rem;line-height:1.5;color:#374151;position:relative;}}
  .card ul li:before{{content:"▸";position:absolute;left:0;color:var(--blue);font-size:.72rem;}}
  .card ul li:last-child{{border-bottom:none;}}
  .pulse-note{{background:#fffbeb;border:1px solid #fde68a;border-radius:6px;padding:7px 11px;margin-bottom:10px;font-size:.78rem;color:#78350f;line-height:1.4;}}
  .sent-table{{width:100%;border-collapse:collapse;font-size:.8rem;}}
  .sent-table thead tr{{background:#f3f4f6;}}
  .sent-table th{{padding:6px 10px;text-align:left;font-size:.6rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);}}
  .footer{{text-align:center;color:var(--muted);font-size:.68rem;margin-top:22px;}}
  .footer a{{color:var(--blue);text-decoration:none;}}
  @media(max-width:680px){{.grid-2{{grid-template-columns:1fr;}}.hero h1{{font-size:1.2rem;}}}}
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

<!-- ROW 1: Sentiment Table | Market Analysis -->
<div class="grid-2">

  <!-- LEFT: Market Sentiment Table -->
  <div class="card ar">
    <h2>🌡️ Market Sentiment</h2>
    <table class="sent-table">
      <thead>
        <tr>
          <th>Indicator</th>
          <th>Current</th>
          <th>vs Prior</th>
          <th>Signal</th>
          <th>What it means</th>
        </tr>
      </thead>
      <tbody>
        {sentiment_rows}
      </tbody>
    </table>
    <div style="margin-top:8px;font-size:.62rem;color:#9ca3af;">
      Sources: Yahoo Finance (SPX, RUT, VIX) · CNN Fear &amp; Greed · U of Michigan (FRED)
    </div>
  </div>

  <!-- RIGHT: Market Analysis (2 sections stacked) -->
  <div style="display:flex;flex-direction:column;gap:12px;">

    <div class="card ab">
      <h2>📊 Market & Key Moves</h2>
      <div class="pulse-note">⚡ {pulse}</div>
      <ul>{fmt_bullets(secs.get("MARKET AND KEY MOVES",""))}</ul>
    </div>

    <div class="card aa">
      <h2>🌐 Macro & News</h2>
      <ul>{fmt_bullets(secs.get("MACRO AND NEWS",""))}</ul>
    </div>

  </div>

</div>

<!-- ROW 2: Earnings & Events | What to Watch -->
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
        Federal Reserve FRED API · sorted alphabetically · numbered · Today's Signal at right
      </span>
    </h2>
    <div style="overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:.78rem;">
        <thead>
          <tr style="background:#f3f4f6;">
            <th style="padding:6px 8px;text-align:center;font-size:.58rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">#</th>
            <th style="padding:6px 10px;text-align:left;font-size:.58rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);min-width:170px;">Indicator</th>
            <th style="padding:6px 10px;text-align:center;font-size:.58rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">Current</th>
            <th style="padding:6px 10px;text-align:center;font-size:.58rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">3 Mo Ago</th>
            <th style="padding:6px 10px;text-align:center;font-size:.58rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">12 Mo Ago</th>
            <th style="padding:6px 10px;text-align:center;font-size:.58rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">Trend</th>
            <th style="padding:6px 8px;font-size:.58rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">As Of</th>
            <th style="padding:6px 10px;font-size:.58rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);min-width:190px;">Today's Signal</th>
          </tr>
        </thead>
        <tbody>{fred_rows}</tbody>
      </table>
    </div>
    <div style="margin-top:8px;font-size:.63rem;color:#9ca3af;">
      📊 Market Breadth (% S&P 500 above 200MA): not available via free API.
      Check <a href="https://stockcharts.com/h-sc/ui?s=%24SPXA200R" target="_blank" style="color:#1a56db;">StockCharts $SPXA200R</a> · Below 25% = deeply oversold (mean reversion signal) · Above 75% = be selective.
    </div>
  </div>
</div>

<div class="footer" style="margin-top:22px;">
  Built by <strong>Anil Abraham</strong> &nbsp;·&nbsp;
  <a href="https://www.edwardjones.com/us-en/market-news-insights/stock-market-news/daily-market-recap" target="_blank">Edward Jones</a> &nbsp;·&nbsp;
  <a href="https://www.cnbc.com/newsletters/" target="_blank">CNBC Squawk</a> &nbsp;·&nbsp;
  <a href="https://finance.yahoo.com" target="_blank">Yahoo Finance</a> &nbsp;·&nbsp;
  <a href="https://fred.stlouisfed.org" target="_blank">FRED API</a> &nbsp;·&nbsp;
  <a href="https://www.cnn.com/markets/fear-and-greed" target="_blank">CNN Fear &amp; Greed</a> &nbsp;·&nbsp;
  <a href="https://www.mcoscillator.com" target="_blank">McClellan Oscillator</a> &nbsp;·&nbsp;
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

    fred_data       = fetch_fred_data()
    fg_data         = fetch_fear_greed()
    mkt_data        = fetch_market_indicators()
    ej_text         = scrape_edward_jones()
    cnbc_text       = fetch_cnbc_email()
    yahoo_text      = fetch_yahoo_morning_brief()
    mcoscillator_text = fetch_mcoscillator_email()

    briefing = synthesize_with_gemini(
        ej_text, cnbc_text, yahoo_text, mcoscillator_text,
        fred_data, fg_data, mkt_data
    )

    build_html(
        briefing, ej_text, cnbc_text, yahoo_text, mcoscillator_text,
        fred_data, fg_data, mkt_data
    )

    print("\n📧 Email disabled -- dashboard is primary output")
    print("\n"+"="*50)
    print("✅ MarketPulse AI Complete!")
    print("🌐 https://anil2040.github.io/market-pulse-ai")
    print("="*50)