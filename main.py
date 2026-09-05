# ============================================================
# MarketPulse AI - main.py
# Updated: September 2026
# ============================================================
# Pipeline:
#   1.  FRED macro indicators (12 series, parallel, 20s)
#   2.  AAII Weekly Sentiment Survey (direct scrape)
#   3.  CNN Fear & Greed (JSON)
#   4.  VIX + S&P 500 + Russell 2000 (Yahoo Finance)
#   5.  MRI -- Mean Reversion Insights (INVERTED 0-100)
#       DEPLOY(0-33) | SELECTIVE(34-65) | OVERHEATED(66-100)
#   6.  Dataroma superinvestor quarterly buys (scrape, fixed cols)
#   7.  Magic Formula top 30 stocks (authenticated scrape)
#   8.  Acquirer's Multiple large-cap list (authenticated scrape)
#   9.  Edward Jones daily recap (web scrape)
#  10.  CNBC Morning Squawk (Yahoo IMAP)
#  11.  Yahoo Finance Morning Brief (Yahoo IMAP)
#  12.  McClellan Oscillator newsletter (Yahoo IMAP, weekly)
#  13.  Gemini AI synthesis (3.6-flash -> 1.5-flash -> fallback)
#  14.  Build HTML dashboard with run log (index.html)
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

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
YAHOO_EMAIL    = os.environ.get("YAHOO_EMAIL")
YAHOO_PASSWORD = os.environ.get("YAHOO_APP_PASSWORD")
FRED_API_KEY   = os.environ.get("FRED_API_KEY")
MFI_EMAIL      = os.environ.get("MFI_EMAIL")
MFI_PASSWORD   = os.environ.get("MFI_PASSWORD")
AM_EMAIL       = os.environ.get("AM_EMAIL")
AM_PASSWORD    = os.environ.get("AM_PASSWORD")

# Boise MDT = UTC-6 (summer), change to -7 in November
MT = timezone(timedelta(hours=-6))

# Global run log
RUN_LOG = []
RUN_START = time.time()

def log(msg, status="✅"):
    entry = f"{status} {msg}"
    RUN_LOG.append(entry)

print("✅ Configuration loaded")
print(f"📧 Email: {YAHOO_EMAIL}")


# ============================================================
# STEP 1: FRED MACRO INDICATORS
# Grouped: INFLATION | TREASURY | ECONOMIC | CREDIT
# COLOR LOGIC (fixed):
#   INFLATION: UP=red(bad) DOWN=green(good)
#   TREASURY:  UP=red(bad for stocks) DOWN=green -- EXCEPT Yield Curve
#   Yield Curve: UP=green(steepening=good) DOWN=red(flattening)
#   CREDIT/HY:  UP=red(widening=bad) DOWN=green(tightening=good)
#   UNEMPLOYMENT: UP=red(bad) DOWN=green(good)
#   OTHERS (Fed, WTI, Sentiment): UP=green DOWN=red (default)
# ============================================================

FRED_SERIES = [
    {"label":"CPI Inflation",        "id":"CPIAUCSL",     "is_index":True,  "group":"INFLATION",
     "insight":"Headline CPI including food & energy"},
    {"label":"Core CPI",             "id":"CPILFESL",     "is_index":True,  "group":"INFLATION",
     "insight":"CPI ex food/energy -- Fed watches this closely"},
    {"label":"PCE Inflation",        "id":"PCEPI",        "is_index":True,  "group":"INFLATION",
     "insight":"Fed preferred gauge -- broader than CPI"},
    {"label":"Core PCE",             "id":"PCEPILFE",     "is_index":True,  "group":"INFLATION",
     "insight":"Fed 2% target -- THE most important inflation number"},
    {"label":"10Y Treasury",         "id":"GS10",         "is_index":False, "group":"TREASURY",
     "insight":"Risk-free rate -- RISING is BAD: increases discount rate, compresses P/E multiples"},
    {"label":"2Y Treasury",          "id":"GS2",          "is_index":False, "group":"TREASURY",
     "insight":"Fed expectations -- rising = market pricing in no rate cuts"},
    {"label":"Yield Curve (10Y-2Y)", "id":"T10Y2Y",       "is_index":False, "group":"TREASURY",
     "insight":"Negative = inverted = historically predicts recession 12-18 months ahead"},
    {"label":"Fed Funds Rate",       "id":"FEDFUNDS",     "is_index":False, "group":"ECONOMIC",
     "insight":"Cost of borrowing -- cutting cycle positive for equities"},
    {"label":"Unemployment",         "id":"UNRATE",       "is_index":False, "group":"ECONOMIC",
     "insight":"Labor market -- rising signals consumer spending risk ahead"},
    {"label":"WTI Crude Oil",        "id":"DCOILWTICO",   "is_index":False, "group":"ECONOMIC",
     "prefix":"$", "insight":"Energy prices -- drives inflation & energy sector moves"},
    {"label":"Consumer Sentiment",   "id":"UMCSENT",      "is_index":False, "group":"ECONOMIC",
     "no_pct":True, "insight":"U of Michigan 0-100 score -- avg ~75, below 60 = consumer stress"},
    {"label":"HY Credit Spread",     "id":"BAMLH0A0HYM2", "is_index":False, "group":"CREDIT",
     "insight":"Extra yield junk bonds pay vs Treasuries -- TIGHT(<3%)=calm/no fear, WIDE(>6%)=credit stress/fear"},
]

GROUP_META = {
    "INFLATION":{"icon":"🔥","color":"#c81e1e","label":"Inflation"},
    "TREASURY": {"icon":"📊","color":"#1a56db","label":"Treasury Yields"},
    "ECONOMIC": {"icon":"⚙️","color":"#b45309","label":"Economic"},
    "CREDIT":   {"icon":"💳","color":"#7f1d1d","label":"Credit"},
}


def _trend_color(label, group, trend):
    """Return correct color for trend arrow based on what direction is GOOD for equities."""
    if group == "INFLATION":
        # Inflation cooling (▼) = good = green
        return "#057a55" if trend=="▼" else "#c81e1e" if trend=="▲" else "#6b7280"
    elif group == "TREASURY":
        if "Yield Curve" in label:
            # Steepening (▲) = good = green
            return "#057a55" if trend=="▲" else "#c81e1e" if trend=="▼" else "#6b7280"
        else:
            # Rising yields (▲) = BAD for stocks = red
            return "#c81e1e" if trend=="▲" else "#057a55" if trend=="▼" else "#6b7280"
    elif group == "CREDIT":
        # Widening spread (▲) = bad = red
        return "#c81e1e" if trend=="▲" else "#057a55" if trend=="▼" else "#6b7280"
    elif group == "ECONOMIC":
        if "Unemployment" in label:
            # Rising unemployment (▲) = bad = red
            return "#c81e1e" if trend=="▲" else "#057a55" if trend=="▼" else "#6b7280"
        else:
            # Default: up = good
            return "#057a55" if trend=="▲" else "#c81e1e" if trend=="▼" else "#6b7280"
    return "#6b7280"


def _signal(label, cur_str, mo3_str, trend):
    """Signal text: trend checked FIRST to prevent contradictions."""
    try:
        cur=float(re.sub(r"[%$]","",str(cur_str)))
        mo3=float(re.sub(r"[%$]","",str(mo3_str)))
    except: return ""
    if label in("Core PCE","Core CPI"):
        if cur<=2.0:                  return "✅ At Fed 2% target"
        elif cur<=2.5 and trend=="▼": return "📉 Cooling toward 2% target"
        elif cur>3.0 and trend=="▲":  return "⚠️ Rising & above target -- rates stay elevated"
        elif cur>3.0:                 return "⚠️ Above target -- rates staying elevated"
        elif trend=="▼":              return "📉 Cooling trend"
        elif trend=="▲":              return "⚠️ Rising -- hawkish Fed signal"
        else:                         return "→ Flat"
    elif "PCE" in label or "CPI" in label:
        if trend=="▼": return "📉 Cooling"
        elif trend=="▲": return "⚠️ Heating up"
        else: return "→ Stable"
    elif "Fed Funds" in label:
        if trend=="▼": return "📉 Cutting cycle -- positive for rate-sensitive sectors"
        elif trend=="▲": return "⚠️ Rising -- tightening"
        elif cur>=5.0: return "⚠️ Restrictive -- growth headwind"
        elif cur<=3.0: return "✅ Accommodative"
        else: return "→ On hold"
    elif "Unemployment" in label:
        if trend=="▲": return "⚠️ Rising -- watch consumer discretionary"
        elif trend=="▼" and cur<=4.0: return "✅ Tightening -- strong labor market"
        elif cur<=4.0: return "✅ Strong labor market"
        elif cur>=5.0: return "⚠️ Weakening -- recession risk elevated"
        else: return "✅ Stable"
    elif "HY Credit" in label:
        if trend=="▲": return "⚠️ Widening -- credit stress rising, avoid leveraged companies"
        elif trend=="▼": return "📉 Tightening -- credit calm, risk appetite recovering"
        elif cur<=3.0: return "✅ Tight -- investors NOT fearful of defaults = calm credit"
        elif cur>=6.0: return "⚠️ Wide -- fear of defaults = credit stress"
        else: return "→ Stable"
    elif "Yield Curve" in label:
        if cur<0: return "⚠️ Inverted -- recession signal (12-18mo lead)"
        elif cur<0.3: return "→ Nearly flat"
        elif trend=="▲": return "✅ Steepening -- growth expectations improving"
        else: return "✅ Positive slope"
    elif "10Y" in label:
        if trend=="▲" and cur>=5.0: return "⚠️ High & rising -- P/E compression intensifying"
        elif trend=="▲": return "⚠️ Rising -- discount rate up, headwind for all equities"
        elif trend=="▼": return "✅ Falling -- lower discount rate supports valuations"
        elif cur>=5.0: return "⚠️ High -- P/E compression risk"
        elif cur<=3.5: return "✅ Low -- supports higher valuations"
        else: return "→ Stable"
    elif "2Y" in label:
        if trend=="▲" and cur>=4.5: return "⚠️ Rising & elevated -- no rate cuts priced in"
        elif trend=="▲": return "⚠️ Rising -- markets pricing in delayed cuts"
        elif trend=="▼": return "✅ Falling -- rate cuts being priced in"
        elif cur>=5.0: return "⚠️ Elevated"
        else: return "→ Stable"
    elif "Consumer Sentiment" in label:
        if trend=="▼" and cur<=65: return "⚠️ Declining & below avg -- consumer stress"
        elif trend=="▼": return "⚠️ Declining"
        elif cur<=55: return "⚠️ Well below avg (~75) -- consumer worried"
        elif cur<=65: return "→ Below average"
        elif cur>=80: return "✅ High confidence"
        else: return "→ Near average"
    elif "WTI" in label:
        if trend=="▲" and cur>=90: return "⚠️ High & rising -- inflation pressure"
        elif trend=="▲": return "⚠️ Rising -- watch for inflation spillover"
        elif trend=="▼": return "📉 Falling -- easing energy inflation"
        elif cur>=90: return "⚠️ High -- inflationary"
        elif cur<=60: return "✅ Low -- consumer-friendly"
        else: return "→ Stable"
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
    except:
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
    ok=sum(1 for r in results if r["current"]!="N/A")
    log(f"FRED: {ok}/{len(results)} indicators", "✅" if ok==len(results) else "⚠️")
    return results


# ============================================================
# STEP 2: AAII WEEKLY SENTIMENT SURVEY
# ============================================================
# Published every Thursday at aaii.com/sentimentsurvey.
# Contrarian indicator: bears > 50% = historically strong buy.
# Bull-Bear spread below -20% = extreme fear = opportunity.
# ============================================================

def fetch_aaii_sentiment():
    print("\n📊 Fetching AAII Weekly Sentiment Survey...")
    try:
        url="https://www.aaii.com/sentimentsurvey"
        hdrs={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
              "Accept":"text/html,application/xhtml+xml"}
        resp=requests.get(url,headers=hdrs,timeout=15)
        soup=BeautifulSoup(resp.text,"html.parser")
        text=soup.get_text()

        # Debug: show snippet to understand page structure
        lines=[l.strip() for l in text.splitlines() if l.strip()]
        snippet=" | ".join(lines[:30])
        print(f"   Page snippet: {snippet[:300]}")

        bullish=bearish=neutral=None

        # Try multiple regex patterns -- AAII changes their layout occasionally
        pattern_sets=[
            # Pattern A: "Bullish 38.5%"
            (r"[Bb]ullish[\s:]*(\d+\.?\d*)\s*%", r"[Bb]earish[\s:]*(\d+\.?\d*)\s*%", r"[Nn]eutral[\s:]*(\d+\.?\d*)\s*%"),
            # Pattern B: "38.5% Bullish"
            (r"(\d+\.?\d*)\s*%\s*[Bb]ullish", r"(\d+\.?\d*)\s*%\s*[Bb]earish", r"(\d+\.?\d*)\s*%\s*[Nn]eutral"),
            # Pattern C: look in table cells for % values near sentiment words
            (r"[Bb]ull[^\d]{0,20}(\d+\.?\d*)\s*%", r"[Bb]ear[^\d]{0,20}(\d+\.?\d*)\s*%", r"[Nn]eut[^\d]{0,20}(\d+\.?\d*)\s*%"),
        ]

        for pb,pbe,pn in pattern_sets:
            if bullish is None:
                m=re.search(pb,text)
                if m: bullish=float(m.group(1))
            if bearish is None:
                m=re.search(pbe,text)
                if m: bearish=float(m.group(1))
            if neutral is None:
                m=re.search(pn,text)
                if m: neutral=float(m.group(1))
            if all(v is not None for v in [bullish,bearish,neutral]):
                break

        # Also try parsing from table cells directly
        if bullish is None:
            for cell in soup.find_all(["td","span","div","p"]):
                txt=cell.get_text(strip=True)
                if "%" in txt:
                    num_m=re.search(r"(\d+\.?\d*)\s*%",txt)
                    if num_m:
                        val=float(num_m.group(1))
                        parent_text=cell.parent.get_text().lower() if cell.parent else ""
                        if "bull" in txt.lower() or "bull" in parent_text:
                            if bullish is None and 5<=val<=95: bullish=val
                        elif "bear" in txt.lower() or "bear" in parent_text:
                            if bearish is None and 5<=val<=95: bearish=val
                        elif "neut" in txt.lower() or "neut" in parent_text:
                            if neutral is None and 5<=val<=95: neutral=val

        if bullish is not None and bearish is not None:
            spread=round(bullish-bearish,1)
            if   spread<=-20: sig="⚠️ Extreme bearishness -- historically strong contrarian buy signal"; col="#c81e1e"
            elif spread<=-10: sig="⚠️ Bearish -- pessimism elevated, watch for entries"; col="#e97316"
            elif spread<=10:  sig="→ Neutral -- no extreme sentiment reading"; col="#6b7280"
            elif spread<=20:  sig="🟡 Bullish -- mild optimism, be selective"; col="#059669"
            else:             sig="⚠️ Extreme bullishness -- contrarian caution warranted"; col="#1a56db"
            print(f"   ✅ AAII: Bull {bullish}% / Bear {bearish}% / Neutral {neutral}% | Spread: {spread:+.1f}%")
            log(f"AAII: Bull {bullish}% Bear {bearish}% (spread {spread:+.1f}%)")
            return {"bullish":bullish,"bearish":bearish,"neutral":neutral,"spread":spread,"signal":sig,"color":col}
        else:
            print(f"   ⚠️ AAII: Could not parse percentages (bull={bullish} bear={bearish})")
            log("AAII: Parse failed -- site may require login or structure changed","⚠️")
            return None
    except Exception as e:
        print(f"   ❌ AAII failed: {e}")
        log(f"AAII: {str(e)[:60]}","❌")
        return None


# ============================================================
# STEP 3: CNN FEAR & GREED
# ============================================================

def fetch_fear_greed():
    print("\n😨 Fetching CNN Fear & Greed...")
    try:
        url="https://production.dataviz.cnn.io/index/fearandgreed/graphdata"
        hdrs={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        fg=requests.get(url,headers=hdrs,timeout=10).json().get("fear_and_greed",{})
        score=round(float(fg.get("score",50)))
        if   score<=24: lbl="Extreme Fear"; col="#c81e1e"; sig="Historically strong buying opportunity"
        elif score<=44: lbl="Fear";         col="#e97316"; sig="Pessimism -- watch for mean reversion entries"
        elif score<=55: lbl="Neutral";      col="#6b7280"; sig="No strong directional signal"
        elif score<=74: lbl="Greed";        col="#059669"; sig="Optimism elevated -- exercise caution"
        else:           lbl="Extreme Greed";col="#1a56db"; sig="Overheated -- high reversal risk"
        print(f"   ✅ Fear & Greed: {score}/100 ({lbl})")
        log(f"Fear & Greed: {score}/100 ({lbl})")
        return {"score":score,"label":lbl,"color":col,"signal":sig,
                "prev_close":round(float(fg.get("previous_close",score))),
                "prev_week": round(float(fg.get("previous_1_week",score))),
                "prev_month":round(float(fg.get("previous_1_month",score))),
                "prev_year": round(float(fg.get("previous_1_year",score)))}
    except Exception as e:
        print(f"   ❌ Fear & Greed failed: {e}")
        log(f"Fear & Greed: {str(e)[:60]}","❌")
        return {"score":50,"label":"Unavailable","color":"#6b7280","signal":"Data unavailable",
                "prev_close":"N/A","prev_week":"N/A","prev_month":"N/A","prev_year":"N/A"}


# ============================================================
# STEP 4: MARKET PERFORMANCE (S&P 500, Russell 2000, VIX)
# Exact thresholds from Chrome extension background.js:
#   VIX: CALM(<15) NORMAL(<20) CAUTIOUS(<25) FEARFUL(<30) PANIC(>=30)
#   Index: SELLOFF(≤-1%) DOWN(-1 to -0.1%) FLAT(-0.1 to 0.1%)
#          UP(0.1 to 1%) RALLY(>1%)
# VIX moved to Sentiment section -- it measures fear, not performance.
# Pre-market (PRE), after-hours (POST), closed (CLOSED) all labeled correctly.
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
    if v>=25: return "⚠️ Cautious -- elevated fear, watch for entry points"
    if v>=20: return "→ Slightly elevated -- no broad panic signal"
    if v>=15: return "→ Normal -- market calm, no stress signal"
    return "✅ Calm -- low fear (note: complacency = less opportunity for value investors)"

def _yq(ticker):
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2d"
    hdrs={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)","Accept":"application/json"}
    resp=requests.get(url,headers=hdrs,timeout=12)
    meta=resp.json()["chart"]["result"][0]["meta"]
    p=float(meta.get("regularMarketPrice",0)); pv=float(meta.get("previousClose",p))
    chg=((p-pv)/pv*100) if pv else 0
    return p,pv,chg,meta.get("marketState","UNKNOWN")

def fetch_market_indicators():
    print("\n📊 Fetching Market Performance (SPX, RUT, VIX)...")
    res={"vix":{"value":"N/A","label":"N/A","color":"#6b7280","signal":"","prev":"N/A"},
         "spx":{"value":"N/A","chg":"N/A","label":"N/A","color":"#6b7280","prev":"N/A"},
         "rut":{"value":"N/A","chg":"N/A","label":"N/A","color":"#6b7280","prev":"N/A"},
         "market_state":"UNKNOWN","market_status_label":"","pulse":""}
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            fv=ex.submit(_yq,"%5EVIX"); fs=ex.submit(_yq,"%5EGSPC"); fr=ex.submit(_yq,"%5ERUT")
            vp,vpr,_,vs  =fv.result(timeout=15)
            sp,spr,sc,ss =fs.result(timeout=15)
            rp,rpr,rc,rs =fr.result(timeout=15)

        # Proper market state detection using Yahoo's marketState field
        state_map={"REGULAR":"OPEN","PRE":"PRE","POST":"POST","CLOSED":"CLOSED"}
        mkt_state=state_map.get(ss,"OPEN" if abs(sc)>0.005 else "CLOSED")
        status_labels={"OPEN":"","PRE":"Pre-Market","POST":"After-Hours","CLOSED":"Last Close"}
        status_label=status_labels.get(mkt_state,"")

        res["market_state"]=mkt_state; res["market_status_label"]=status_label
        vl,vc=_classify_vix(vp); sl,sc2=_classify_idx(sc); rl,rc2=_classify_idx(rc)

        if mkt_state=="PRE":
            scs="Pre-Market"; rcs="Pre-Market"
            sl="PRE-MKT"; sc2="#6366f1"; rl="PRE-MKT"; rc2="#6366f1"
        elif mkt_state in("POST","CLOSED"):
            scs="Last Close"; rcs="Last Close"
            sl="CLOSED"; sc2="#9ca3af"; rl="CLOSED"; rc2="#9ca3af"
        else:
            scs=f"{sc:+.2f}%"; rcs=f"{rc:+.2f}%"

        res["vix"]={"value":f"{vp:.2f}","label":vl,"color":vc,"signal":_vix_sig(vp),"prev":f"{vpr:.2f}"}
        res["spx"]={"value":f"{sp:,.0f}","chg":scs,"label":sl,"color":sc2,"prev":f"{spr:,.0f}"}
        res["rut"]={"value":f"{rp:,.0f}","chg":rcs,"label":rl,"color":rc2,"prev":f"{rpr:,.0f}"}

        if mkt_state=="OPEN":
            if vp>=30 or sl=="SELLOFF": tone="broad stress -- mean reversion entries emerging"
            elif sl in("UP","RALLY") and rl in("UP","RALLY"): tone="broad strength -- be selective on new positions"
            elif sl=="FLAT": tone="indecisive -- focus on individual stock catalysts"
            else: tone="mixed -- stay selective"
            res["pulse"]=f"S&P {scs} ({sl}) · Russell {rcs} ({rl}) · VIX {vp:.1f} ({vl}) -- {tone}"
        elif mkt_state=="PRE":
            res["pulse"]=f"Pre-Market · S&P last close {sp:,.0f} · Russell {rp:,.0f} · VIX {vp:.1f} ({vl}) · Opens 9:30 AM ET (7:30 AM MT)"
        else:
            res["pulse"]=f"Last close · S&P {sp:,.0f} · Russell {rp:,.0f} · VIX {vp:.1f} ({vl})"

        print(f"   ✅ S&P 500: {sp:,.0f} ({scs} {sl})")
        print(f"   ✅ Russell: {rp:,.0f} ({rcs} {rl})")
        print(f"   ✅ VIX: {vp:.2f} ({vl}) | State: {mkt_state}")
        log(f"Market: SPX {sp:,.0f} ({scs}) RUT {rp:,.0f} VIX {vp:.1f} | {mkt_state}")
    except Exception as e:
        print(f"   ❌ Market indicators failed: {e}")
        log(f"Market indicators: {str(e)[:60]}","❌")
        res["pulse"]="Market data unavailable."
    return res


# ============================================================
# STEP 5: MRI -- MEAN REVERSION INSIGHTS (INVERTED SCALE)
# ============================================================
# INVERTED 0-100: LOWER = better mean reversion opportunity.
# Fear, panic, dislocation LOWERS the score (toward DEPLOY).
# Complacency, greed, expensive conditions RAISES the score (toward OVERHEATED).
#
# Bands aligned to your verdict system:
#   0-33:   🟢 DEPLOY     -- Panic. Dislocation. Macro confirms STRONG BUY signals.
#   34-65:  🟠 SELECTIVE  -- Some opportunity. Best setups only. Left Leg <4, MoS >25%.
#   66-100: ⛔ OVERHEATED -- Expensive & complacent. Build cash. Trim winners.
# ============================================================

def compute_mri(fred_data, fg_data, mkt_data, aaii_data):
    raw=50  # Start neutral, adjustments move it up (overheated) or down (deploy)
    breakdown=[]

    def get(lbl):
        r=next((x for x in fred_data if x["label"]==lbl),None)
        if not r or r["current"]=="N/A": return None,None
        try: return float(re.sub(r"[%$]","",r["current"])),r["trend"]
        except: return None,None

    # INFLATION -- rising inflation raises score (overheated signal)
    cp,cpt=get("Core PCE")
    if cp is not None:
        if cp>3.5:   adj=+15; note="Core PCE well above target"
        elif cp>3.0: adj=+10; note="Core PCE above target"
        elif cp>2.5: adj=+5;  note="Core PCE mildly elevated"
        elif cp>2.0: adj=+2;  note="Core PCE near target"
        else:        adj=-5;  note="Core PCE at/below target"
        if cpt=="▲": adj+=5;  note+=" & rising"
        elif cpt=="▼": adj-=5; note+=" & cooling"
        raw+=adj; breakdown.append(f"Inflation {adj:+d} ({note})")

    # VIX -- high VIX lowers score (panic = opportunity)
    try:
        vix=float(mkt_data["vix"]["value"])
        if vix>=40:   adj=-20; note=f"VIX {vix:.1f} panic"
        elif vix>=30: adj=-15; note=f"VIX {vix:.1f} fear"
        elif vix>=25: adj=-8;  note=f"VIX {vix:.1f} cautious"
        elif vix>=20: adj=-3;  note=f"VIX {vix:.1f} elevated"
        elif vix>=15: adj=+5;  note=f"VIX {vix:.1f} normal/calm"
        else:         adj=+10; note=f"VIX {vix:.1f} complacent"
        raw+=adj; breakdown.append(f"VIX {adj:+d} ({note})")
    except: pass

    # FEAR & GREED -- low score lowers MRI (fear = opportunity)
    try:
        fg=int(fg_data.get("score",50))
        if fg<=20:   adj=-20; note=f"F&G {fg} extreme fear"
        elif fg<=35: adj=-12; note=f"F&G {fg} fear"
        elif fg<=50: adj=-4;  note=f"F&G {fg} mild fear"
        elif fg<=65: adj=+4;  note=f"F&G {fg} neutral/mild greed"
        elif fg<=80: adj=+12; note=f"F&G {fg} greed"
        else:        adj=+20; note=f"F&G {fg} extreme greed"
        raw+=adj; breakdown.append(f"Fear&Greed {adj:+d} ({note})")
    except: pass

    # AAII -- bearish reading lowers MRI (contrarian signal)
    if aaii_data:
        spread=aaii_data.get("spread",0)
        if spread<=-25:  adj=-12; note=f"AAII spread {spread:+.1f}% extreme bearish"
        elif spread<=-15:adj=-8;  note=f"AAII spread {spread:+.1f}% bearish"
        elif spread<=-5: adj=-3;  note=f"AAII spread {spread:+.1f}% mildly bearish"
        elif spread<=10: adj=0;   note=f"AAII spread {spread:+.1f}% neutral"
        elif spread<=20: adj=+6;  note=f"AAII spread {spread:+.1f}% bullish"
        else:            adj=+12; note=f"AAII spread {spread:+.1f}% extreme bullish"
        raw+=adj; breakdown.append(f"AAII {adj:+d} ({note})")

    # HY CREDIT SPREAD -- wide spread lowers MRI (dislocation)
    hy,_=get("HY Credit Spread")
    if hy is not None:
        if hy>=8.0:   adj=-15; note=f"HY {hy:.2f}% very wide"
        elif hy>=6.0: adj=-10; note=f"HY {hy:.2f}% wide"
        elif hy>=4.5: adj=-4;  note=f"HY {hy:.2f}% elevated"
        elif hy<=2.5: adj=+12; note=f"HY {hy:.2f}% very tight"
        elif hy<=3.5: adj=+6;  note=f"HY {hy:.2f}% tight"
        else:         adj=+2;  note=f"HY {hy:.2f}% normal"
        raw+=adj; breakdown.append(f"Credit {adj:+d} ({note})")

    # YIELD CURVE
    cv,_=get("Yield Curve (10Y-2Y)")
    if cv is not None:
        if cv<-0.5:  adj=-8; note="Deeply inverted"
        elif cv<0:   adj=-4; note="Inverted"
        elif cv<0.3: adj=+2; note="Nearly flat"
        elif cv>=0.5:adj=+4; note="Steep"
        else:        adj=+2; note="Positive"
        raw+=adj; breakdown.append(f"Yield Curve {adj:+d} ({note})")

    # FED POSTURE
    fed,fedt=get("Fed Funds Rate")
    if fed is not None:
        if fedt=="▼":    adj=-6; note="Fed cutting"
        elif fedt=="▲":  adj=+8; note="Fed hiking"
        elif fed>=5.0:   adj=+6; note="Fed restrictive"
        elif fed<=3.0:   adj=-4; note="Fed accommodative"
        else:            adj=+2; note="Fed on hold"
        raw+=adj; breakdown.append(f"Fed {adj:+d} ({note})")

    score=max(0,min(100,round(raw)))

    if   score<=33: lbl="🟢 DEPLOY";     col="#057a55"; action="Aggressive deployment. Macro confirms STRONG BUY signals. Full position pace."
    elif score<=65: lbl="🟠 SELECTIVE";  col="#b45309"; action="Best setups only. Left Leg <4, MoS >25%. Measured pace. Keep 25% cash."
    else:           lbl="⛔ OVERHEATED"; col="#c81e1e"; action="Build cash. Trim winners. Avoid new positions unless extraordinary setup."

    print(f"\n📊 MRI: {score}/100 ({lbl})")
    for b in breakdown: print(f"   {b}")
    log(f"MRI: {score}/100 ({lbl})")
    return {"score":score,"label":lbl,"color":col,"breakdown":breakdown,"action":action}


# ============================================================
# STEP 6: DATAROMA SUPERINVESTOR QUARTERLY BUYS
# Confirmed columns from live run: Symbol, Stock, %▼, Buys, Hold Price*, CurrentPrice
# "Buys" column = number of superinvestors who bought this quarter
# ============================================================

def fetch_superinvestor_buys():
    print("\n👑 Fetching Dataroma superinvestor quarterly buys...")
    try:
        url="https://www.dataroma.com/m/g/portfolio_b.php?q=q"
        hdrs={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
              "Accept":"text/html,application/xhtml+xml","Referer":"https://www.dataroma.com/"}
        resp=requests.get(url,headers=hdrs,timeout=15)
        print(f"   Status: {resp.status_code}")
        if resp.status_code!=200: raise Exception(f"HTTP {resp.status_code}")

        soup=BeautifulSoup(resp.text,"html.parser")
        buys={}  # ticker -> count

        table=soup.find("table",{"id":"grid"})
        if not table:
            for t in soup.find_all("table"):
                if len(t.find_all("tr"))>5: table=t; break

        if table:
            rows=table.find_all("tr")
            headers=[th.get_text(strip=True) for th in rows[0].find_all(["th","td"])]
            print(f"   Columns: {headers}")

            # Find correct column indices by header name
            sym_idx=next((i for i,h in enumerate(headers)
                          if any(k in h for k in ["Symbol","Ticker","symbol","ticker"])),0)
            buy_idx=next((i for i,h in enumerate(headers)
                          if any(k in h for k in ["Buy","buy","Count","count"])),3)
            print(f"   Using: Symbol col={sym_idx}, Buys col={buy_idx}")

            for row in rows[1:]:
                cells=row.find_all("td")
                if len(cells)>max(sym_idx,buy_idx):
                    ticker=re.sub(r"[^A-Z.]","",cells[sym_idx].get_text(strip=True).upper())[:6]
                    if not ticker or len(ticker)<1: continue
                    try:
                        count=int(cells[buy_idx].get_text(strip=True).replace(",",""))
                    except:
                        count=1
                    if ticker: buys[ticker]=count

        print(f"   ✅ Dataroma: {len(buys)} stocks")
        if buys:
            top3=sorted(buys.items(),key=lambda x:-x[1])[:3]
            print(f"   Top: {top3}")
        log(f"Dataroma 13F: {len(buys)} stocks")
        return buys
    except Exception as e:
        print(f"   ❌ Dataroma failed: {e}")
        log(f"Dataroma: {str(e)[:60]}","❌")
        return {}


# ============================================================
# STEP 7: MAGIC FORMULA INVESTING -- AUTHENTICATED SCRAPE
# ============================================================
# Greenblatt Magic Formula: ranks stocks by:
#   Earnings Yield (EBIT/Enterprise Value) = cheapness
#   Return on Capital = quality/efficiency
# Top stocks combine high earnings yield + high ROC.
#
# ASP.NET login flow (anti-forgery token required):
# 1. GET login page -> extract __RequestVerificationToken
# 2. POST credentials + token -> session established
# 3. GET screener page -> extract NEW token
# 4. POST screener form + token -> results HTML
# requests.Session() carries cookies automatically between steps.
# ============================================================

def fetch_magic_formula():
    print("\n🔮 Fetching Magic Formula top 30 stocks...")
    try:
        sess=requests.Session()
        sess.headers.update({
            "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

        # Step 1: GET login page, extract anti-forgery token
        login_url="https://www.magicformulainvesting.com/Account/LogOn"
        resp=sess.get(login_url,timeout=15)
        soup=BeautifulSoup(resp.text,"html.parser")
        token_input=soup.find("input",{"name":"__RequestVerificationToken"})
        if not token_input:
            raise Exception("Login token not found")
        token=token_input.get("value","")
        print(f"   Got anti-forgery token: {token[:20]}...")

        # Step 2: POST login
        login_data={"Email":MFI_EMAIL,"Password":MFI_PASSWORD,"__RequestVerificationToken":token}
        resp=sess.post(login_url,data=login_data,timeout=15)
        if "Welcome" in resp.text or "LogOff" in resp.text or "Log Off" in resp.text or "Screening" in resp.url:
            print(f"   ✅ Logged into Magic Formula")
        elif "invalid" in resp.text.lower() or "incorrect" in resp.text.lower():
            raise Exception("Login failed -- check MFI_EMAIL and MFI_PASSWORD")
        else:
            print(f"   Login submitted (status {resp.status_code})")

        # Step 3: GET screener page, extract its anti-forgery token
        screener_url="https://www.magicformulainvesting.com/Screening/StockScreening"
        resp=sess.get(screener_url,timeout=15)
        soup=BeautifulSoup(resp.text,"html.parser")
        screen_token_input=soup.find("input",{"name":"__RequestVerificationToken"})
        if not screen_token_input:
            raise Exception("Screener token not found")
        screen_token=screen_token_input.get("value","")

        # Step 4: POST screener form (MinMarketCap=2000, 30 stocks)
        screen_data={
            "MinimumMarketCap":"2000",
            "NumberOfStocks":"30",
            "__RequestVerificationToken":screen_token,
        }
        resp=sess.post(screener_url,data=screen_data,timeout=20)
        soup=BeautifulSoup(resp.text,"html.parser")

        # Debug: show what tables exist on the results page
        tables=soup.find_all("table")
        print(f"   Tables found: {len(tables)}")

        tickers=[]
        ticker_col=None

        # Find the results table
        for t in tables:
            rows=t.find_all("tr")
            if len(rows)<3: continue
            # Check headers
            hdrs=[th.get_text(strip=True) for th in rows[0].find_all(["th","td"])]
            print(f"   Table headers: {hdrs}")
            # Look for ticker column
            for ci,h in enumerate(hdrs):
                if any(k in h.lower() for k in ["ticker","symbol"]):
                    ticker_col=ci
                    print(f"   Ticker column at index {ci}: '{h}'")
                    break
            if ticker_col is None:
                # Auto-detect: check first data row for short uppercase value
                if len(rows)>1:
                    sample=rows[1].find_all("td")
                    for ci,cell in enumerate(sample):
                        txt=cell.get_text(strip=True).upper()
                        if re.match(r"^[A-Z]{1,5}$",txt):
                            ticker_col=ci
                            print(f"   Ticker auto-detected at col {ci}: '{txt}'")
                            break
            # Extract tickers from this table
            if ticker_col is not None:
                for row in rows[1:]:
                    cells=row.find_all("td")
                    if ticker_col<len(cells):
                        txt=cells[ticker_col].get_text(strip=True).upper()
                        clean=re.sub(r"[^A-Z.]","",txt)
                        if re.match(r"^[A-Z]{1,5}$",clean) and clean:
                            tickers.append(clean)
                break  # Found the right table

        tickers=list(dict.fromkeys(tickers))  # Deduplicate, preserve order
        print(f"   ✅ Magic Formula: {len(tickers)} tickers")
        if tickers: print(f"   Sample: {tickers[:8]}")
        log(f"Magic Formula: {len(tickers)} stocks")
        return set(tickers)
    except Exception as e:
        print(f"   ❌ Magic Formula failed: {e}")
        log(f"Magic Formula: {str(e)[:60]}","❌")
        return set()


# ============================================================
# STEP 8: ACQUIRER'S MULTIPLE -- AUTHENTICATED SCRAPE
# ============================================================
# Carlisle Acquirer's Multiple = EV / Operating Earnings.
# Lower = cheaper on earnings vs enterprise value.
# Sorted ascending = cheapest stocks first.
#
# WordPress login flow (simpler than ASP.NET):
# 1. GET login page (sets initial cookies)
# 2. POST to /wp-login.php with credentials
#    'log' = username/email (WordPress field name)
#    'testcookie' = 1 (confirms cookies work)
# 3. GET screener -- session cookie carried automatically
# ============================================================

def fetch_acquirers_multiple():
    print("\n📐 Fetching Acquirer's Multiple large-cap stocks...")
    try:
        sess=requests.Session()
        sess.headers.update({
            "User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept":"text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

        # Step 1: GET login page (establishes initial cookies)
        login_page_url="https://acquirersmultiple.com/login/"
        resp=sess.get(login_page_url,timeout=15)
        print(f"   Got initial cookies: {len(sess.cookies)} cookies")

        # Step 2: POST to WordPress login endpoint
        wp_login_url="https://acquirersmultiple.com/wp-login.php"
        login_data={
            "log":        AM_EMAIL,
            "pwd":        AM_PASSWORD,
            "wp-submit":  "Log In",
            "testcookie": "1",
            "redirect_to":"https://acquirersmultiple.com/screener/large-cap/",
        }
        resp=sess.post(wp_login_url,data=login_data,timeout=15,allow_redirects=True)
        print(f"   Login status: {resp.status_code}, URL: {resp.url}")

        if "logout" in resp.text.lower() or "log-out" in resp.text.lower() or "log out" in resp.text.lower():
            print(f"   ✅ Logged into Acquirer's Multiple")
        else:
            print(f"   Login submitted -- checking screener access...")

        # Step 3: GET the large-cap screener
        screener_url="https://acquirersmultiple.com/screener/large-cap/"
        resp=sess.get(screener_url,timeout=20)
        print(f"   Screener status: {resp.status_code}")

        soup=BeautifulSoup(resp.text,"html.parser")
        tickers=[]
        tables=soup.find_all("table")
        print(f"   Tables found: {len(tables)}")

        for i,t in enumerate(tables[:6]):
            rows=t.find_all("tr")
            if not rows: continue
            hdrs=[c.get_text(strip=True)[:20] for c in rows[0].find_all(["th","td"])]
            if rows and len(rows)>3:
                print(f"   Table {i}: {len(rows)} rows, headers: {hdrs[:5]}")

        # Find table where first data column contains ticker-like values
        target_table=None
        for t in tables:
            rows=t.find_all("tr")
            if len(rows)<5: continue
            if len(rows)>1:
                first_row_cells=rows[1].find_all("td")
                if first_row_cells:
                    candidate=first_row_cells[0].get_text(strip=True).upper()
                    candidate=re.sub(r"[^A-Z.]","",candidate)
                    if re.match(r"^[A-Z]{1,5}$",candidate) and len(candidate)>=1:
                        target_table=t
                        print(f"   Found target table (first ticker: {candidate})")
                        break

        if target_table:
            rows=target_table.find_all("tr")
            hdrs=[c.get_text(strip=True) for c in rows[0].find_all(["th","td"])]
            print(f"   AM columns: {hdrs[:6]}")
            for row in rows[1:]:
                cells=row.find_all("td")
                if cells:
                    ticker=cells[0].get_text(strip=True).upper()
                    ticker=re.sub(r"[^A-Z.]","",ticker)
                    if ticker and re.match(r"^[A-Z]{1,5}$",ticker):
                        tickers.append(ticker)
        else:
            # Fallback: scan all text for ticker-like patterns near prices
            print("   Target table not found -- trying text scan fallback...")
            all_text=soup.get_text()
            # Look for lines that start with a ticker pattern
            for line in all_text.splitlines():
                line=line.strip()
                if re.match(r"^[A-Z]{1,5}\s",line):
                    ticker=line.split()[0]
                    if re.match(r"^[A-Z]{1,5}$",ticker):
                        tickers.append(ticker)
                        if len(tickers)>=50: break

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
# STEP 9: EDWARD JONES SCRAPE
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
        log(f"Edward Jones: {len(text)} chars")
        return text
    except Exception as e:
        print(f"   ❌ Edward Jones failed: {e}")
        log(f"Edward Jones: {str(e)[:60]}","❌")
        return "Edward Jones data unavailable today."


# ============================================================
# STEPS 10-12: EMAIL VIA IMAP
# ============================================================

def _fetch_email(sender, label, char_limit=2500):
    print(f"\n📬 Fetching {label}...")
    try:
        mail=imaplib.IMAP4_SSL("imap.mail.yahoo.com",993)
        mail.login(YAHOO_EMAIL,YAHOO_PASSWORD)
        mail.select("INBOX")
        status,messages=mail.search(None,f'(FROM "{sender}")')
        count=len(messages[0].split()) if messages[0] else 0
        if status!="OK" or not messages[0]:
            domain=sender.split("@")[-1] if "@" in sender else sender
            status,messages=mail.search(None,f'(FROM "{domain}")')
            count=len(messages[0].split()) if messages[0] else 0
        if status!="OK" or not messages[0]:
            print(f"   ❌ No {label} emails found"); mail.logout()
            log(f"{label}: no emails found","❌")
            return f"{label} not found today."
        ids=messages[0].split(); latest=ids[-1]
        _,hdr=mail.fetch(latest,"(BODY[HEADER.FIELDS (FROM SUBJECT DATE)])")
        if hdr and hdr[0] and hdr[0][1]:
            for line in hdr[0][1].decode("utf-8",errors="ignore").strip().splitlines()[:4]:
                if line.strip(): print(f"   {line.strip()}")
        _,msg_data=mail.fetch(latest,"(RFC822)")
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
        log(f"{label}: {len(body)} chars")
        return body
    except Exception as e:
        print(f"   ❌ {label} IMAP failed: {e}")
        log(f"{label}: {str(e)[:60]}","❌")
        return f"{label} unavailable today."

def fetch_cnbc_email():
    return _fetch_email("morningsquawk@response.cnbc.com","CNBC Morning Squawk")

def fetch_yahoo_morning_brief():
    # Confirmed sender: finance-morning-brief@newsletters.yahoo.net
    return _fetch_email("finance-morning-brief@newsletters.yahoo.net","Yahoo Morning Brief",char_limit=2000)

def fetch_mcoscillator_email():
    # Tom McClellan weekly newsletter
    return _fetch_email("admin@mcoscillator.com","McClellan Oscillator",char_limit=1500)


# ============================================================
# STEP 13: GEMINI AI SYNTHESIS
# Fallback chain: gemini-3.6-flash -> gemini-1.5-flash -> text
# Single attempt per model -- fail fast, no wasted quota.
# ============================================================

def _call_gemini(prompt, model):
    client=genai.Client(api_key=GEMINI_API_KEY)
    return client.interactions.create(model=model,input=prompt).output_text

def synthesize_with_gemini(ej_text, cnbc_text, yahoo_text, mcoscillator_text,
                            fred_data, fg_data, mkt_data, mri,
                            si_tickers, mf_tickers, am_tickers, aaii_data):
    print("\n🤖 Sending to Gemini...")

    fred_summary="\n".join([
        f"- {r['label']}: {r['current']} (trend:{r['trend']}) {r.get('sig','')}"
        for r in fred_data if r["current"]!="N/A"
    ])

    # High-conviction tickers: appear in 2+ screens
    overlap=[]
    all_tickers=sorted(set(si_tickers.keys())|mf_tickers|am_tickers)
    for t in all_tickers:
        tags=[]
        if si_tickers.get(t,0)>0: tags.append(f"{si_tickers[t]}SI")
        if t in mf_tickers: tags.append("MF")
        if t in am_tickers: tags.append("AM")
        if len(tags)>=2: overlap.append(f"{t}({','.join(tags)})")

    aaii_str=""
    if aaii_data:
        aaii_str=f"AAII Survey: Bull {aaii_data['bullish']}% Bear {aaii_data['bearish']}% Spread {aaii_data['spread']:+.1f}%"

    prompt=f"""You are a sharp financial analyst writing a morning briefing for a 
deep-value mean reversion investor. Style: Greenblatt magic formula, Tobias Carlisle 
acquirer's multiple, Howard Marks cycles, Terry Smith quality, Michael Burry contrarian.

STRICT RULES:
- Output EXACTLY these 3 section headers (no numbers, no markdown):
  MARKET AND MACRO
  EARNINGS AND EVENTS
  WHAT TO WATCH
- MARKET AND MACRO: 4-5 bullets -- key market moves + macro news
- EARNINGS AND EVENTS: 3-4 bullets -- specific dates/releases from any source
- WHAT TO WATCH: 3-4 bullets -- cyclical vs structural calls, mean reversion setups,
  mention high-conviction tickers (in 2+ screens) where relevant
- Do NOT mention F&G score, VIX number, S&P/Russell % -- shown in tables
- Max 20 words per bullet, dash (-) prefix, no paragraphs, no bold

After the 3 sections add:
AI FUN FACT
- One genuinely surprising fact about AI, markets, or investing history. Max 25 words.

AI LEARNING
- One AI concept relevant to finance/investing. Plain English. Max 30 words.

MRI: {mri['score']}/100 -- {mri['label']} | Action: {mri['action']}
MARKET: {mkt_data['pulse']}
{aaii_str}
FRED: {fred_summary}
HIGH CONVICTION (2+ screens): {', '.join(overlap[:15]) if overlap else 'None today'}
EDWARD JONES: {ej_text[:800]}
CNBC SQUAWK: {cnbc_text[:600]}
YAHOO BRIEF: {yahoo_text[:600]}
McCLELLAN (breadth): {mcoscillator_text[:400]}
"""

    for model in ["gemini-3.6-flash","gemini-1.5-flash"]:
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                fut=ex.submit(_call_gemini,prompt,model)
                briefing=fut.result(timeout=90)
            print(f"   ✅ Gemini ({model}): {len(briefing)} chars")
            log(f"Gemini ({model}): {len(briefing)} chars")
            return briefing, False
        except concurrent.futures.TimeoutError:
            print(f"   ⚠️ {model} timed out (>90s)")
            log(f"Gemini {model}: timeout","⚠️")
        except Exception as e:
            print(f"   ⚠️ {model} failed: {str(e)[:100]}")
            log(f"Gemini {model}: {str(e)[:60]}","⚠️")

    print("   ❌ All Gemini models failed -- using structured fallback")
    log("Gemini: all models failed -- using fallback","❌")
    fallback="""MARKET AND MACRO
- AI synthesis unavailable today -- all data sections below are complete and current

EARNINGS AND EVENTS
- Check Yahoo Morning Brief and CNBC for earnings calendar details

WHAT TO WATCH
- Review MRI score and FRED signals -- data complete even without AI narrative

AI FUN FACT
- Joel Greenblatt tested his Magic Formula from 1988-2004 and found it returned 23.8% annually vs 12.3% for the S&P 500.

AI LEARNING
- Transformer architecture: the neural network design behind all modern LLMs -- uses attention to weigh relationships between all words simultaneously."""
    return fallback, True


# ============================================================
# STEP 14: PARSE SECTIONS
# ============================================================

def parse_sections(text):
    secs={"MARKET AND MACRO":"","EARNINGS AND EVENTS":"","WHAT TO WATCH":"","AI FUN FACT":"","AI LEARNING":""}
    current=None
    for line in text.splitlines():
        up=line.upper().strip()
        cln=re.sub(r"^\d+[\.\)]\s*","",up); cln=re.sub(r"^#+\s*","",cln); cln=re.sub(r"^\*+\s*","",cln)
        cln=cln.encode("ascii","ignore").decode().strip()
        if "MARKET AND MACRO" in cln or ("MARKET AND KEY" in cln): current="MARKET AND MACRO"; continue
        if "MARKET SUMMARY" in cln or ("KEY MOVES" in cln and "MACRO" not in cln): current="MARKET AND MACRO"; continue
        if "MACRO AND NEWS" in cln or "MACRO & NEWS" in cln: current="MARKET AND MACRO"; continue
        if "EARNINGS AND EVENTS" in cln or "EARNINGS AND CALENDAR" in cln: current="EARNINGS AND EVENTS"; continue
        if "WHAT TO WATCH" in cln or "PRE-MARKET" in cln: current="WHAT TO WATCH"; continue
        if "AI FUN FACT" in cln: current="AI FUN FACT"; continue
        if "AI LEARNING" in cln or ("AI" in cln and "LEARN" in cln): current="AI LEARNING"; continue
        if "FUN FACT" in cln and "AI" not in cln: current="AI FUN FACT"; continue
        if current and line.strip(): secs[current]+=line.strip()+"\n"
    for n,c in secs.items():
        print(f"   {'📋' if c.strip() else '⚠️'} {n}: {len(c)} chars" if c.strip() else f"   ⚠️ {n}: EMPTY")
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

def _ticker_tag(t, si_tickers, mf_tickers, am_tickers):
    """Build compact ticker label. Returns None if not in any list."""
    tags=[]
    if si_tickers.get(t,0)>0: tags.append(f"{si_tickers[t]}SI")
    if t in mf_tickers: tags.append("MF")
    if t in am_tickers: tags.append("AM")
    if not tags: return None
    return f"{t}({','.join(tags)})"


def build_html(briefing, ai_failed, ej_text, cnbc_text, yahoo_text, mcoscillator_text,
               fred_data, fg_data, mkt_data, mri,
               si_tickers, mf_tickers, am_tickers, aaii_data):
    print("\n🎨 Building HTML dashboard...")

    secs=parse_sections(briefing)
    now_mt=datetime.now(MT)
    today=now_mt.strftime("%A, %B %d, %Y")
    now=now_mt.strftime("%I:%M %p")

    vix_val=mkt_data["vix"]["value"]; vix_prev=mkt_data["vix"]["prev"]
    vix_lbl=mkt_data["vix"]["label"]; vix_col=mkt_data["vix"]["color"]; vix_sig=mkt_data["vix"]["signal"]
    spx_val=mkt_data["spx"]["value"]; spx_chg=mkt_data["spx"]["chg"]
    spx_lbl=mkt_data["spx"]["label"]; spx_col=mkt_data["spx"]["color"]; spx_prev=mkt_data["spx"]["prev"]
    rut_val=mkt_data["rut"]["value"]; rut_chg=mkt_data["rut"]["chg"]
    rut_lbl=mkt_data["rut"]["label"]; rut_col=mkt_data["rut"]["color"]; rut_prev=mkt_data["rut"]["prev"]
    pulse=mkt_data["pulse"]
    mkt_state=mkt_data.get("market_state","UNKNOWN")

    fg_score=fg_data.get("score",50); fg_lbl=fg_data.get("label","N/A")
    fg_col=fg_data.get("color","#6b7280"); fg_sig=fg_data.get("signal","")

    umich=next((r for r in fred_data if r["label"]=="Consumer Sentiment"),None)
    umich_val=umich["current"] if umich else "N/A"
    umich_mo3=umich["mo3"] if umich else "N/A"; umich_mo12=umich["mo12"] if umich else "N/A"
    umich_sig=umich.get("sig","") if umich else ""
    try: umich_num=float(str(umich_val))
    except: umich_num=55
    ucol="#c81e1e" if umich_num<60 else "#6b7280" if umich_num<75 else "#057a55"
    umich_raw_lbl="LOW" if umich_num<60 else "MID" if umich_num<75 else "HIGH"

    mri_score=mri["score"]; mri_lbl=mri["label"]; mri_col=mri["color"]
    mri_action=mri["action"]
    mri_breakdown="".join([f'<span style="font-size:.63rem;color:#6b7280;margin-right:10px;">{b}</span>' for b in mri["breakdown"]])

    # ---- Market status banner --------------------------------
    mkt_banner=""
    if mkt_state=="PRE":
        mkt_banner='<div style="background:#eef2ff;border:1px solid #c7d2fe;border-radius:5px;padding:4px 8px;margin-bottom:7px;font-size:.72rem;color:#3730a3;">🌅 Pre-Market · Opens 9:30 AM ET (7:30 AM MT)</div>'
    elif mkt_state=="POST":
        mkt_banner='<div style="background:#faf5ff;border:1px solid #e9d5ff;border-radius:5px;padding:4px 8px;margin-bottom:7px;font-size:.72rem;color:#6d28d9;">🌙 After-Hours</div>'
    elif mkt_state=="CLOSED":
        mkt_banner='<div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:5px;padding:4px 8px;margin-bottom:7px;font-size:.72rem;color:#6b7280;">🔒 Markets closed · last close shown</div>'

    # ---- AI failure alert ------------------------------------
    ai_alert=""
    if ai_failed:
        ai_alert="""<div style="background:#fef2f2;border:2px solid #fca5a5;border-radius:8px;padding:10px 16px;
            margin-bottom:12px;display:flex;align-items:center;gap:10px;">
          <span style="font-size:1.3rem;">⚠️</span>
          <div>
            <div style="font-weight:700;font-size:.82rem;color:#c81e1e;">AI Synthesis Unavailable</div>
            <div style="font-size:.73rem;color:#6b7280;margin-top:2px;">
              Gemini API quota exceeded or temporary outage. All data sections are complete.
              Quota resets at midnight UTC. Run manually after midnight to retry.
            </div>
          </div>
        </div>"""

    # ---- Market performance rows (S&P + Russell only) --------
    def pr(name,val,chg,prev,rl,rc,note=""):
        nh=f'<div style="font-size:.6rem;color:#9ca3af;">{note}</div>' if note else ""
        return f'<tr style="border-bottom:1px solid #f3f4f6;"><td style="padding:7px 10px;"><div style="font-weight:600;font-size:.82rem;">{name}</div>{nh}</td><td style="padding:7px 10px;font-weight:700;font-size:.9rem;">{val}</td><td style="padding:7px 10px;font-size:.78rem;color:#6b7280;">{chg}</td><td style="padding:7px 10px;font-size:.75rem;color:#9ca3af;">prev {prev}</td><td style="padding:7px 10px;">{_badge(rl,rc)}</td></tr>'

    perf_rows=(
        pr("S&P 500 (Large Cap)",spx_val,spx_chg,spx_prev,spx_lbl,spx_col,"Yahoo Finance · large cap benchmark")
        +pr("Russell 2000 (Small Cap)",rut_val,rut_chg,rut_prev,rut_lbl,rut_col,"Yahoo Finance · small cap / risk appetite proxy")
    )

    # ---- Sentiment rows (VIX here now, not in Market table) --
    try: vix_num=float(vix_val)
    except: vix_num=20
    vix_badge_lbl="CALM" if vix_num<15 else "NORMAL" if vix_num<20 else "CAUTIOUS" if vix_num<25 else "FEARFUL" if vix_num<30 else "PANIC"

    def sr(name,val,hist,rl,rc,sig,note=""):
        nh=f'<div style="font-size:.6rem;color:#9ca3af;">{note}</div>' if note else ""
        return f'<tr style="border-bottom:1px solid #f3f4f6;"><td style="padding:7px 10px;"><div style="font-weight:600;font-size:.82rem;">{name}</div>{nh}</td><td style="padding:7px 10px;font-weight:700;font-size:.9rem;">{val}</td><td style="padding:7px 10px;font-size:.75rem;color:#6b7280;">{hist}</td><td style="padding:7px 10px;">{_badge(rl,rc)}</td><td style="padding:7px 10px;font-size:.72rem;color:#374151;">{sig}</td></tr>'

    sent_rows=(
        sr("VIX (Volatility Index)",vix_val,f"prev {vix_prev}",vix_badge_lbl,vix_col,vix_sig,
           "CBOE · CALM<15 NORMAL<20 CAUTIOUS<25 FEARFUL<30 PANIC≥30")
        +sr("Fear & Greed Index",f"{fg_score}/100",
            f"1wk:{fg_data.get('prev_week','N/A')} 1mo:{fg_data.get('prev_month','N/A')} 1yr:{fg_data.get('prev_year','N/A')}",
            fg_lbl,fg_col,fg_sig,"CNN Business · daily composite sentiment")
        +sr("Consumer Sentiment",f"{umich_val}/100",f"3mo:{umich_mo3} 12mo:{umich_mo12}",
            umich_raw_lbl,ucol,umich_sig,"U of Michigan · avg ~75 · monthly")
    )

    # AAII row if available
    if aaii_data:
        spread=aaii_data.get("spread",0)
        aaii_sig=aaii_data.get("signal","")
        aaii_col=aaii_data.get("color","#6b7280")
        aaii_lbl="BEARISH" if spread<=-10 else "BULLISH" if spread>=10 else "NEUTRAL"
        sent_rows+=sr("AAII Sentiment",
                      f"Bull {aaii_data['bullish']}% / Bear {aaii_data['bearish']}%",
                      f"Spread: {spread:+.1f}%",
                      aaii_lbl,aaii_col,aaii_sig,
                      "AAII · 160K retail investors · weekly Thursday · contrarian indicator")

    # ---- FRED table (grouped, correct colors) ----------------
    group_order=["INFLATION","TREASURY","ECONOMIC","CREDIT"]
    fred_rows=""; rn=1
    for g in group_order:
        gm=GROUP_META[g]; items=[r for r in fred_data if r.get("group")==g]
        if not items: continue
        fred_rows+=f'<tr style="background:#f9fafb;"><td colspan="8" style="padding:6px 10px;font-size:.64rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:{gm["color"]};border-bottom:1px solid #e5e7eb;">{gm["icon"]} {gm["label"]}</td></tr>'
        for r in items:
            tc=_trend_color(r["label"],g,r["trend"])
            fred_rows+=f'<tr style="border-bottom:1px solid #f3f4f6;"><td style="padding:7px 8px;text-align:center;font-size:.7rem;color:#9ca3af;">{rn}</td><td style="padding:7px 10px;"><div style="font-weight:600;font-size:.8rem;">{r["label"]}</div><div style="font-size:.62rem;color:#9ca3af;">[{r["insight"]}]</div></td><td style="padding:7px 10px;text-align:center;font-weight:700;font-size:.88rem;">{r["current"]}</td><td style="padding:7px 10px;text-align:center;font-size:.78rem;color:#6b7280;">{r["mo3"]}</td><td style="padding:7px 10px;text-align:center;font-size:.78rem;color:#6b7280;">{r["mo12"]}</td><td style="padding:7px 10px;text-align:center;font-size:1rem;color:{tc};">{r["trend"]}</td><td style="padding:7px 8px;font-size:.67rem;color:#9ca3af;white-space:nowrap;">{r["date"]}</td><td style="padding:7px 10px;font-size:.72rem;color:#1e3a5f;">{r.get("sig","")}</td></tr>'
            rn+=1

    # ---- Value Screens ticker section (alphabetical, color coded) ----
    all_tickers_set=sorted(set(si_tickers.keys())|mf_tickers|am_tickers)
    ticker_cards=""
    for t in all_tickers_set:
        tags=[]
        count=si_tickers.get(t,0)
        if count>0: tags.append(f"{count}SI")
        if t in mf_tickers: tags.append("MF")
        if t in am_tickers: tags.append("AM")
        if not tags: continue
        tag_str=", ".join(tags)
        lists_count=(1 if count>0 else 0)+(1 if t in mf_tickers else 0)+(1 if t in am_tickers else 0)
        if lists_count>=3:  card_col="#eff6ff"; border_col="#1a56db"; txt_col="#0c4a6e"
        elif lists_count==2: card_col="#f0fdf4"; border_col="#057a55"; txt_col="#064e3b"
        else:                card_col="#f9fafb"; border_col="#e5e7eb"; txt_col="#374151"
        ticker_cards+=f'<div style="background:{card_col};border:1px solid {border_col};border-radius:6px;padding:5px 8px;white-space:nowrap;"><span style="font-weight:800;font-size:.82rem;color:{txt_col};">{t}</span><span style="color:#6b7280;font-size:.68rem;margin-left:3px;">({tag_str})</span></div>'

    # ---- AI blocks -------------------------------------------
    fun_raw=secs.get("AI FUN FACT","").strip(); learn_raw=secs.get("AI LEARNING","").strip()
    if fun_raw:  fun_raw=re.sub(r"^[-•*]\s*","",fun_raw.splitlines()[0].strip())
    else:        fun_raw="Joel Greenblatt tested his Magic Formula from 1988-2004: 23.8% annually vs 12.3% for the S&P 500."
    if learn_raw: learn_raw=re.sub(r"^[-•*]\s*","",learn_raw.splitlines()[0].strip())
    else:         learn_raw="Transformer architecture: the neural network design behind all modern LLMs -- uses attention to weigh relationships between all words simultaneously."

    # ---- Hidden market-context div (ultra-compact for Chrome extension) ----
    # Designed for minimum token usage when fed into mean reversion LLM analysis
    fred_compact="\n".join([f"{r['label']}: {r['current']} ({r['trend']})" for r in fred_data if r["current"]!="N/A"])
    aaii_compact=""
    if aaii_data: aaii_compact=f"\nAAII: Bull {aaii_data['bullish']}% Bear {aaii_data['bearish']}% Spread {aaii_data['spread']:+.1f}%"

    # Ticker compact: alphabetical, all tags, pipe-separated
    ticker_compact=" | ".join([
        tag for t in all_tickers_set
        if (tag:=_ticker_tag(t,si_tickers,mf_tickers,am_tickers)) is not None
    ])

    mctx=f"""MARKETPULSE AI - {today} {now} MT
MRI: {mri_score}/100 {mri_lbl} | {mri_action}
SPX: {spx_chg} ({spx_lbl}) | RUT: {rut_chg} ({rut_lbl}) | VIX: {vix_val} ({vix_lbl}) | {mkt_state}
F&G: {fg_score}/100 ({fg_lbl}) | Consumer: {umich_val}/100{aaii_compact}
MACRO:
{fred_compact}
BRIEFING:
{secs.get('MARKET AND MACRO','').strip()}
WHAT TO WATCH:
{secs.get('WHAT TO WATCH','').strip()}
SCREENS (13F+MF+AM):
{ticker_compact}"""

    # ---- Run log HTML (collapsed by default) -----------------
    elapsed=round(time.time()-RUN_START)
    run_log_items="".join([
        f'<div style="font-size:.72rem;padding:2px 0;border-bottom:1px solid #f3f4f6;font-family:monospace;">{entry}</div>'
        for entry in RUN_LOG
    ])
    run_log_html=f"""
<div style="margin-top:12px;">
  <button onclick="var d=this.nextElementSibling;d.style.display=d.style.display==='none'?'block':'none';"
          style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;padding:6px 14px;
                 font-size:.72rem;color:#6b7280;cursor:pointer;width:100%;text-align:left;">
    📋 View Run Log &nbsp;·&nbsp; Total time: {elapsed}s &nbsp;·&nbsp; {len(RUN_LOG)} steps completed
  </button>
  <div style="display:none;background:#f9fafb;border:1px solid #e5e7eb;border-top:none;border-radius:0 0 6px 6px;
              padding:10px 14px;max-height:400px;overflow-y:auto;">
    {run_log_items}
    <div style="font-size:.7rem;color:#9ca3af;margin-top:4px;padding-top:4px;border-top:1px solid #e5e7eb;">
      Total runtime: {elapsed} seconds · {today} {now} MT
    </div>
  </div>
</div>"""

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
  .pulse-note{{background:#fffbeb;border:1px solid #fde68a;border-radius:6px;padding:6px 10px;margin-bottom:9px;font-size:.76rem;color:#78350f;}}
  .tbl{{width:100%;border-collapse:collapse;font-size:.8rem;}}
  .tbl th{{padding:6px 10px;text-align:left;font-size:.58rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);background:#f9fafb;}}
  .footer{{text-align:center;color:var(--muted);font-size:.68rem;margin-top:22px;}}
  .footer a{{color:var(--blue);text-decoration:none;}}
  @media(max-width:680px){{.grid-2{{grid-template-columns:1fr;}}.hero h1{{font-size:1.2rem;}}}}
</style>
</head>
<body>
<!-- Chrome Extension: fetch this page, read #market-context innerText for macro context -->
<div id="market-context" style="display:none;white-space:pre;">{mctx}</div>

<div class="hero">
  <h1>📈 MARKETPULSE AI</h1>
  <div class="sub">Anil Abraham &nbsp;·&nbsp; {today}</div>
  <div class="ts">Last updated {now} MT</div>
</div>

<div class="container">

{ai_alert}

<!-- AI BLOCKS: Fun Fact + AI Learning -->
<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px;">
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

<!-- MRI: MEAN REVERSION INSIGHTS SCORE -->
<div class="card" style="margin-bottom:12px;border-left:4px solid {mri_col};">
  <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;">
    <div style="flex-shrink:0;">
      <div style="font-size:.58rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--muted);margin-bottom:3px;">MRI · Mean Reversion Insights</div>
      <div style="font-size:2rem;font-weight:800;color:{mri_col};line-height:1;">{mri_score}<span style="font-size:.85rem;color:var(--muted);">/100</span></div>
    </div>
    <div>
      <div style="font-size:.9rem;font-weight:700;color:{mri_col};">{mri_lbl}</div>
      <div style="margin-top:5px;background:#e5e7eb;border-radius:99px;height:7px;width:220px;overflow:hidden;">
        <div style="width:{mri_score}%;background:{mri_col};height:100%;border-radius:99px;"></div>
      </div>
      <div style="font-size:.7rem;color:#374151;margin-top:5px;">📋 {mri_action}</div>
    </div>
    <div style="font-size:.63rem;color:var(--muted);flex:1;min-width:200px;line-height:1.8;">
      {mri_breakdown}
    </div>
  </div>
  <div style="margin-top:8px;font-size:.67rem;color:#374151;background:#f9fafb;border-radius:5px;padding:6px 10px;line-height:1.6;">
    <strong>Scale (LOWER = better opportunity):</strong>
    🟢 DEPLOY (0-33): Panic, dislocation -- aggressive deployment, macro confirms STRONG BUY ·
    🟠 SELECTIVE (34-65): Some opportunity -- best setups only, Left Leg &lt;4 &amp; MoS &gt;25% ·
    ⛔ OVERHEATED (66-100): Expensive, complacent -- build cash, trim winners.
    Connects directly to your verdict system as a macro overlay on individual stock decisions.
  </div>
</div>

<!-- ROW 1: Market Performance + Sentiment | Analysis sections -->
<div class="grid-2">

  <div style="display:flex;flex-direction:column;gap:12px;">
    <div class="card ar">
      <h2>📈 Market Performance</h2>
      {mkt_banner}
      <table class="tbl">
        <thead><tr><th>Index</th><th>Price</th><th>Change</th><th>Prev</th><th>Signal</th></tr></thead>
        <tbody>{perf_rows}</tbody>
      </table>
    </div>
    <div class="card aa">
      <h2>🌡️ Market Sentiment</h2>
      <table class="tbl">
        <thead><tr><th>Indicator</th><th>Current</th><th>History</th><th>Signal</th><th>What it means</th></tr></thead>
        <tbody>{sent_rows}</tbody>
      </table>
    </div>
  </div>

  <div style="display:flex;flex-direction:column;gap:12px;">
    <div class="card ab">
      <h2>📊 Market & Macro</h2>
      <div class="pulse-note">⚡ {pulse}</div>
      <ul>{fmt_bullets(secs.get("MARKET AND MACRO",""))}</ul>
    </div>
    <div class="card ag">
      <h2>💰 Earnings & Events</h2>
      <ul>{fmt_bullets(secs.get("EARNINGS AND EVENTS",""))}</ul>
    </div>
    <div class="card ag">
      <h2>🔭 What to Watch</h2>
      <ul>{fmt_bullets(secs.get("WHAT TO WATCH",""))}</ul>
    </div>
  </div>

</div>

<!-- VALUE SCREENS: 13F + Magic Formula + Acquirer's Multiple -->
<div style="margin-top:12px;">
  <div class="card ab">
    <h2>📋 Value Screens
      <span style="font-weight:400;color:var(--muted);font-size:.55rem;">
        &nbsp; Alphabetical ·
        <span style="background:#1a56db;color:white;padding:1px 5px;border-radius:3px;font-size:.55rem;">Blue</span> = all 3 screens ·
        <span style="background:#057a55;color:white;padding:1px 5px;border-radius:3px;font-size:.55rem;">Green</span> = 2 screens ·
        SI=Superinvestors(13F) · MF=Magic Formula · AM=Acquirer's Multiple
      </span>
    </h2>
    {'<div style="color:#9ca3af;font-size:.8rem;padding:8px 0;">No screen data available today -- check run log for details.</div>' if not ticker_cards else f'<div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px;">{ticker_cards}</div>'}
    <div style="font-size:.67rem;color:#6b7280;background:#f0f9ff;border-radius:5px;padding:6px 10px;line-height:1.5;">
      <strong>How to read:</strong> MSFT (18SI, MF, AM) = 18 superinvestors bought it this quarter (13F SEC filing) + Greenblatt Magic Formula top 30 + Carlisle Acquirer's Multiple large-cap list.
      Blue = highest conviction (all 3). Green = 2 screens. Use these as starting candidates for your mean reversion framework -- if a ticker also appears in your Finviz screener AND Left Leg Score &lt;4, that's strong convergence.
      <em>13F data: ~45 day lag. MF &amp; AM: daily.</em>
    </div>
  </div>
</div>

<!-- FRED MACRO INDICATORS -->
<div style="margin-top:12px;">
  <div class="card">
    <h2>🏦 Macro Indicators
      <span style="font-weight:400;color:var(--muted);font-size:.55rem;">&nbsp; FRED API · grouped · ▲▼ colors: green=good for equities, red=bad · Today's Signal at right</span>
    </h2>
    <div style="overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:.78rem;">
        <thead><tr style="background:#f9fafb;">
          <th style="padding:6px 8px;text-align:center;font-size:.57rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">#</th>
          <th style="padding:6px 10px;text-align:left;font-size:.57rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);min-width:140px;">Indicator</th>
          <th style="padding:6px 10px;text-align:center;font-size:.57rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">Current</th>
          <th style="padding:6px 10px;text-align:center;font-size:.57rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">3 Mo</th>
          <th style="padding:6px 10px;text-align:center;font-size:.57rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">12 Mo</th>
          <th style="padding:6px 10px;text-align:center;font-size:.57rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">Trend</th>
          <th style="padding:6px 8px;font-size:.57rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">As Of</th>
          <th style="padding:6px 10px;font-size:.57rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);min-width:180px;">Today's Signal</th>
        </tr></thead>
        <tbody>{fred_rows}</tbody>
      </table>
    </div>
    <div style="margin-top:8px;font-size:.62rem;color:#9ca3af;border-top:1px solid #f3f4f6;padding-top:6px;">
      📊 Market Breadth ($SPXA200R) not available via free API.
      <a href="https://stockcharts.com/h-sc/ui?s=%24SPXA200R" target="_blank" style="color:#1a56db;">Check StockCharts</a> ·
      Below 25% = deeply oversold (mean reversion signal) · Above 75% = be selective.
    </div>
  </div>
</div>

{run_log_html}

<div class="footer" style="margin-top:20px;">
  Built by <strong>Anil Abraham</strong> &nbsp;·&nbsp;
  <a href="https://www.edwardjones.com/us-en/market-news-insights/stock-market-news/daily-market-recap" target="_blank">Edward Jones</a> &nbsp;·&nbsp;
  <a href="https://www.cnbc.com/newsletters/" target="_blank">CNBC Squawk</a> &nbsp;·&nbsp;
  <a href="https://finance.yahoo.com" target="_blank">Yahoo Finance</a> &nbsp;·&nbsp;
  <a href="https://fred.stlouisfed.org" target="_blank">FRED API</a> &nbsp;·&nbsp;
  <a href="https://www.cnn.com/markets/fear-and-greed" target="_blank">CNN Fear &amp; Greed</a> &nbsp;·&nbsp;
  <a href="https://www.aaii.com/sentimentsurvey" target="_blank">AAII</a> &nbsp;·&nbsp;
  <a href="https://www.mcoscillator.com" target="_blank">McClellan</a> &nbsp;·&nbsp;
  <a href="https://www.dataroma.com" target="_blank">Dataroma 13F</a> &nbsp;·&nbsp;
  <a href="https://www.magicformulainvesting.com" target="_blank">Magic Formula</a> &nbsp;·&nbsp;
  <a href="https://acquirersmultiple.com" target="_blank">Acquirer's Multiple</a> &nbsp;·&nbsp;
  Gemini 3.6/1.5 Flash &nbsp;·&nbsp; Not financial advice.
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
    print("🚀 MarketPulse AI Starting...")
    print("="*50)
    log("MarketPulse AI started")

    fred_data         = fetch_fred_data()
    aaii_data         = fetch_aaii_sentiment()
    fg_data           = fetch_fear_greed()
    mkt_data          = fetch_market_indicators()
    mri               = compute_mri(fred_data, fg_data, mkt_data, aaii_data)
    si_tickers        = fetch_superinvestor_buys()   # dict: ticker -> count
    mf_tickers        = fetch_magic_formula()         # set of tickers
    am_tickers        = fetch_acquirers_multiple()    # set of tickers
    ej_text           = scrape_edward_jones()
    cnbc_text         = fetch_cnbc_email()
    yahoo_text        = fetch_yahoo_morning_brief()
    mcoscillator_text = fetch_mcoscillator_email()

    briefing, ai_failed = synthesize_with_gemini(
        ej_text, cnbc_text, yahoo_text, mcoscillator_text,
        fred_data, fg_data, mkt_data, mri,
        si_tickers, mf_tickers, am_tickers, aaii_data
    )

    build_html(
        briefing, ai_failed, ej_text, cnbc_text, yahoo_text, mcoscillator_text,
        fred_data, fg_data, mkt_data, mri,
        si_tickers, mf_tickers, am_tickers, aaii_data
    )

    print("\n📧 Email disabled -- dashboard is primary output")
    print("\n"+"="*50)
    print("✅ MarketPulse AI Complete!")
    print("🌐 https://anil2040.github.io/market-pulse-ai")
    print("="*50)