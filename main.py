# ============================================================
# MarketPulse AI - main.py
# Updated: September 2026
# ============================================================
# Pipeline:
#   1.  FRED macro indicators (12 series, parallel, 20s)
#   2.  CNN Fear & Greed (JSON)
#   3.  VIX + S&P 500 + Russell 2000 (Yahoo Finance)
#   4.  MRI -- Mean Reversion Insights score (computed)
#   5.  Dataroma superinvestor quarterly buys (scrape, fixed)
#   6.  Edward Jones daily recap (web scrape)
#   7.  CNBC Morning Squawk (Yahoo IMAP)
#   8.  Yahoo Finance Morning Brief (Yahoo IMAP)
#   9.  McClellan Oscillator newsletter (Yahoo IMAP, weekly)
#  10.  Gemini AI synthesis (single attempt, 90s timeout)
#       Fallback model: gemini-1.5-flash if 3.6 fails
#  11.  Build HTML dashboard (index.html -> GitHub Pages)
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
# STEP 1: FRED MACRO INDICATORS
# Grouped: INFLATION | TREASURY | ECONOMIC | CREDIT
# ============================================================

FRED_SERIES = [
    {"label":"CPI Inflation",        "id":"CPIAUCSL",     "is_index":True,  "group":"INFLATION",
     "insight":"Headline CPI including food & energy"},
    {"label":"Core CPI",             "id":"CPILFESL",     "is_index":True,  "group":"INFLATION",
     "insight":"CPI ex food/energy -- Fed watches this closely"},
    {"label":"PCE Inflation",        "id":"PCEPI",        "is_index":True,  "group":"INFLATION",
     "insight":"Fed's preferred inflation gauge (broader than CPI)"},
    {"label":"Core PCE",             "id":"PCEPILFE",     "is_index":True,  "group":"INFLATION",
     "insight":"Fed's 2% target -- most important inflation measure"},
    {"label":"10Y Treasury",         "id":"GS10",         "is_index":False, "group":"TREASURY",
     "insight":"Risk-free benchmark -- rising = headwind for high-multiple stocks"},
    {"label":"2Y Treasury",          "id":"GS2",          "is_index":False, "group":"TREASURY",
     "insight":"Fed rate expectations -- rises when markets price in no cuts"},
    {"label":"Yield Curve (10Y-2Y)", "id":"T10Y2Y",       "is_index":False, "group":"TREASURY",
     "insight":"Negative = inverted = historically predicts recession ahead"},
    {"label":"Fed Funds Rate",       "id":"FEDFUNDS",     "is_index":False, "group":"ECONOMIC",
     "insight":"Cost of borrowing -- cutting cycle = positive for equities"},
    {"label":"Unemployment",         "id":"UNRATE",       "is_index":False, "group":"ECONOMIC",
     "insight":"Labor market -- rising signals recession risk ahead"},
    {"label":"WTI Crude Oil",        "id":"DCOILWTICO",   "is_index":False, "group":"ECONOMIC",
     "prefix":"$", "insight":"Energy prices -- drives inflation & energy stocks"},
    {"label":"Consumer Sentiment",   "id":"UMCSENT",      "is_index":False, "group":"ECONOMIC",
     "no_pct":True, "insight":"U of Michigan 0-100 score (avg ~75)"},
    {"label":"HY Credit Spread",     "id":"BAMLH0A0HYM2", "is_index":False, "group":"CREDIT",
     "insight":"High Yield (junk bond) spread -- widening = credit stress"},
]

GROUP_META = {
    "INFLATION":{"icon":"🔥","color":"#c81e1e","label":"Inflation"},
    "TREASURY": {"icon":"📊","color":"#1a56db","label":"Treasury Yields"},
    "ECONOMIC": {"icon":"⚙️","color":"#b45309","label":"Economic"},
    "CREDIT":   {"icon":"💳","color":"#7f1d1d","label":"Credit"},
}


def _signal(label, cur_str, mo3_str, trend):
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
        if trend=="▲": return "⚠️ Widening -- systemic risk rising"
        elif trend=="▼": return "📉 Tightening -- credit improving"
        elif cur<=3.0: return "✅ Tight -- credit markets calm"
        elif cur>=6.0: return "⚠️ Wide -- avoid leveraged balance sheets"
        else: return "→ Stable"
    elif "Yield Curve" in label:
        if cur<0: return "⚠️ Inverted -- recession signal (12-18mo lead)"
        elif cur<0.3: return "→ Nearly flat"
        elif trend=="▲": return "✅ Steepening -- growth expectations improving"
        else: return "✅ Positive slope"
    elif "10Y" in label:
        if trend=="▲" and cur>=5.0: return "⚠️ High & rising -- P/E compression risk"
        elif trend=="▲": return "⚠️ Rising -- headwind for growth stocks"
        elif trend=="▼": return "📉 Falling -- relief for rate-sensitive stocks"
        elif cur>=5.0: return "⚠️ High -- P/E compression risk"
        elif cur<=3.5: return "✅ Low -- supports higher valuations"
        else: return "→ Stable"
    elif "2Y" in label:
        if trend=="▲" and cur>=4.5: return "⚠️ Rising & elevated -- no cuts priced in"
        elif trend=="▲": return "⚠️ Rising -- delayed cuts priced in"
        elif trend=="▼": return "✅ Falling -- rate cuts priced in"
        elif cur>=5.0: return "⚠️ Elevated"
        else: return "→ Stable"
    elif "Consumer Sentiment" in label:
        if trend=="▼" and cur<=65: return "⚠️ Declining & below avg"
        elif trend=="▼": return "⚠️ Declining"
        elif cur<=55: return "⚠️ Well below avg (~75)"
        elif cur<=65: return "→ Below average"
        elif cur>=80: return "✅ High confidence"
        else: return "→ Near average"
    elif "WTI" in label:
        if trend=="▲" and cur>=90: return "⚠️ High & rising -- inflation pressure"
        elif trend=="▲": return "⚠️ Rising"
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
    print(f"   🏦 FRED complete: {len(results)} indicators")
    return results


# ============================================================
# STEP 2: MRI -- MEAN REVERSION INSIGHTS SCORE (0-100)
# ============================================================
# MRI measures how favorable the macro environment is for
# deep-value mean reversion investing (Pabrai/Greenblatt style).
# Labels use hunting metaphor -- Pabrai's actual language:
#   🟢 PRIME HUNTING SEASON (80-100): Go aggressive
#   🟡 ACTIVE HUNTING (65-79):        Normal pace
#   🟠 PATIENT STALKING (50-64):      Best setups only
#   🔴 WATCH & WAIT (35-49):          Build cash
#   ⛔ HIBERNATE (0-34):              No new buys
# ============================================================

def compute_mri(fred_data, fg_data, mkt_data):
    score=0; breakdown=[]
    def get(lbl):
        r=next((x for x in fred_data if x["label"]==lbl),None)
        if not r or r["current"]=="N/A": return None,None
        try: return float(re.sub(r"[%$]","",r["current"])),r["trend"]
        except: return None,None

    # Inflation (20pts) -- cooling is good for rate-sensitive valuations
    cp,cpt=get("Core PCE")
    if cp is not None:
        if cp<=2.0:                 pts=20; note="Core PCE at target ✅"
        elif cp<=2.5 and cpt=="▼": pts=16; note="Core PCE cooling"
        elif cp<=3.0 and cpt=="▼": pts=12; note="Core PCE easing"
        elif cpt=="▼":             pts=8;  note="Core PCE trending down"
        elif cpt=="→":             pts=5;  note="Core PCE stable"
        else:                      pts=0;  note="Core PCE rising ⚠️"
        score+=pts; breakdown.append(f"Inflation +{pts}/20 ({note})")

    # Credit (15pts) -- tight spreads mean no systemic stress
    hy,_=get("HY Credit Spread")
    if hy is not None:
        if hy<=3.0:   pts=15; note=f"HY {hy:.2f}% tight ✅"
        elif hy<=4.0: pts=10; note=f"HY {hy:.2f}% normal"
        elif hy<=6.0: pts=5;  note=f"HY {hy:.2f}% elevated"
        else:         pts=0;  note=f"HY {hy:.2f}% wide ⚠️"
        score+=pts; breakdown.append(f"Credit +{pts}/15 ({note})")

    # Fed (15pts) -- cutting = supportive for cyclical recovery
    fed,fedt=get("Fed Funds Rate")
    if fed is not None:
        if fedt=="▼":               pts=15; note="Cutting ✅"
        elif fedt=="→" and fed<=3.5:pts=12; note="Hold, low rates"
        elif fedt=="→":             pts=8;  note="Hold"
        elif fedt=="▲":             pts=2;  note="Hiking ⚠️"
        else:                       pts=5;  note="Neutral"
        score+=pts; breakdown.append(f"Fed +{pts}/15 ({note})")

    # Yield curve (10pts)
    cv,_=get("Yield Curve (10Y-2Y)")
    if cv is not None:
        if cv>=0.5:    pts=10; note="Steep ✅"
        elif cv>=0.0:  pts=7;  note="Positive"
        elif cv>=-0.5: pts=3;  note="Mildly inverted"
        else:          pts=0;  note="Deeply inverted ⚠️"
        score+=pts; breakdown.append(f"Curve +{pts}/10 ({note})")

    # Labor (10pts)
    un,unt=get("Unemployment")
    if un is not None:
        if un<=4.0 and unt!="▲": pts=10; note="Strong ✅"
        elif un<=4.5:             pts=7;  note="Solid"
        elif un<=5.0:             pts=4;  note="Softening"
        else:                     pts=0;  note="Weak ⚠️"
        score+=pts; breakdown.append(f"Labor +{pts}/10 ({note})")

    # VIX (10pts) -- moderate fear = better entry prices
    try:
        vix=float(mkt_data["vix"]["value"])
        if vix<15:   pts=5;  note=f"VIX {vix:.1f} complacent (less opportunity)"
        elif vix<20: pts=7;  note=f"VIX {vix:.1f} normal"
        elif vix<30: pts=10; note=f"VIX {vix:.1f} elevated fear = opportunity"
        else:        pts=10; note=f"VIX {vix:.1f} panic = max opportunity"
        score+=pts; breakdown.append(f"VIX +{pts}/10 ({note})")
    except: pass

    # Fear & Greed (20pts) -- EXTREME FEAR = Pabrai/Buffett buying moment!
    try:
        fg=int(fg_data.get("score",50))
        if fg<=25:   pts=20; note=f"F&G {fg} EXTREME FEAR = prime entry 🎯"
        elif fg<=40: pts=16; note=f"F&G {fg} fear = good setup"
        elif fg<=55: pts=10; note=f"F&G {fg} neutral"
        elif fg<=70: pts=4;  note=f"F&G {fg} greed = caution"
        else:        pts=0;  note=f"F&G {fg} extreme greed = avoid ⚠️"
        score+=pts; breakdown.append(f"F&G +{pts}/20 ({note})")
    except: pass

    # Label with hunting metaphor (Pabrai's language)
    if   score>=80: lbl="🟢 PRIME HUNTING SEASON"; col="#057a55"; action="Go aggressive. Screener results = full position pace."
    elif score>=65: lbl="🟡 ACTIVE HUNTING";        col="#059669"; action="Normal pace. Execute your screener systematically."
    elif score>=50: lbl="🟠 PATIENT STALKING";      col="#b45309"; action="Wait for only the best setups. Left Leg Score <4, MoS >25%, 25% cash."
    elif score>=35: lbl="🔴 WATCH & WAIT";          col="#c81e1e"; action="Build cash above 25%. Buy only at F&G <20 (extreme fear)."
    else:           lbl="⛔ HIBERNATE";             col="#7f1d1d"; action="Capital preservation. No new buys. Wait for MRI >50."

    print(f"\n📊 MRI: {score}/100 ({lbl})")
    for b in breakdown: print(f"   {b}")
    return {"score":score,"label":lbl,"color":col,"breakdown":breakdown,"action":action}


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
        if   score<=24: lbl="Extreme Fear"; col="#c81e1e"; sig="Historically strong buying opportunity -- prime mean reversion entry"
        elif score<=44: lbl="Fear";         col="#e97316"; sig="Market pessimism -- watch for mean reversion entries"
        elif score<=55: lbl="Neutral";      col="#6b7280"; sig="No strong directional signal -- stay selective"
        elif score<=74: lbl="Greed";        col="#059669"; sig="Optimism elevated -- exercise caution on new buys"
        else:           lbl="Extreme Greed";col="#1a56db"; sig="Market overheated -- high reversal risk, avoid new buys"
        print(f"   ✅ Fear & Greed: {score}/100 ({lbl})")
        return {"score":score,"label":lbl,"color":col,"signal":sig,
                "prev_close":round(float(fg.get("previous_close",score))),
                "prev_week": round(float(fg.get("previous_1_week",score))),
                "prev_month":round(float(fg.get("previous_1_month",score))),
                "prev_year": round(float(fg.get("previous_1_year",score)))}
    except Exception as e:
        print(f"   ❌ Fear & Greed failed: {e}")
        return {"score":50,"label":"Unavailable","color":"#6b7280","signal":"Data unavailable",
                "prev_close":"N/A","prev_week":"N/A","prev_month":"N/A","prev_year":"N/A"}


# ============================================================
# STEP 4: MARKET PERFORMANCE (VIX, S&P 500, Russell 2000)
# Exact thresholds from Chrome extension background.js
# Pre-market state now detected and labeled correctly
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
    if v>=30: return "⚠️ Panic -- mean reversion entries across sectors"
    if v>=25: return "⚠️ Cautious -- watch for volatility spikes"
    if v>=20: return "→ Slightly elevated"
    if v>=15: return "→ Normal -- no market stress"
    return "✅ Calm -- low fear, rally likely intact"

def _yq(ticker):
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2d"
    hdrs={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)","Accept":"application/json"}
    resp=requests.get(url,headers=hdrs,timeout=12)
    meta=resp.json()["chart"]["result"][0]["meta"]
    p=float(meta.get("regularMarketPrice",0)); pv=float(meta.get("previousClose",p))
    chg=((p-pv)/pv*100) if pv else 0
    return p,pv,chg,meta.get("marketState","UNKNOWN")

def fetch_market_indicators():
    print("\n📊 Fetching Market Performance (VIX, SPX, RUT)...")
    res={"vix":{"value":"N/A","label":"N/A","color":"#6b7280","signal":"","prev":"N/A"},
         "spx":{"value":"N/A","chg":"N/A","label":"N/A","color":"#6b7280","prev":"N/A"},
         "rut":{"value":"N/A","chg":"N/A","label":"N/A","color":"#6b7280","prev":"N/A"},
         "market_state":"UNKNOWN","market_status_label":"","pulse":""}
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            fv=ex.submit(_yq,"%5EVIX"); fs=ex.submit(_yq,"%5EGSPC"); fr=ex.submit(_yq,"%5ERUT")
            vp,vpr,_,  vs=fv.result(timeout=15)
            sp,spr,sc, ss=fs.result(timeout=15)
            rp,rpr,rc, rs=fr.result(timeout=15)

        # Detect market state properly:
        # REGULAR = market open
        # PRE = pre-market (7:30 AM MT = 9:30 AM ET opening imminent)
        # POST = after-hours
        # CLOSED = fully closed (weekend/holiday)
        if ss == "REGULAR":
            mkt_state = "OPEN"
            status_label = ""
        elif ss == "PRE":
            mkt_state = "PRE"
            status_label = "Pre-Market"
        elif ss == "POST":
            mkt_state = "POST"
            status_label = "After-Hours"
        else:
            # Also detect closed by near-zero change
            mkt_state = "CLOSED" if abs(sc)<0.001 else "OPEN"
            status_label = "Last Close" if mkt_state == "CLOSED" else ""

        res["market_state"] = mkt_state
        res["market_status_label"] = status_label

        vl,vc=_classify_vix(vp); sl,sc2=_classify_idx(sc); rl,rc2=_classify_idx(rc)

        if mkt_state in ("CLOSED","PRE","POST"):
            scs=f"{status_label}"; rcs=f"{status_label}"
            if mkt_state != "OPEN":
                sl="CLOSED" if mkt_state=="CLOSED" else status_label.upper()
                sc2="#9ca3af"; rl=sl; rc2="#9ca3af"
        else:
            scs=f"{sc:+.2f}%"; rcs=f"{rc:+.2f}%"

        res["vix"]={"value":f"{vp:.2f}","label":vl,"color":vc,"signal":_vix_sig(vp),"prev":f"{vpr:.2f}"}
        res["spx"]={"value":f"{sp:,.0f}","chg":scs,"label":sl,"color":sc2,"prev":f"{spr:,.0f}"}
        res["rut"]={"value":f"{rp:,.0f}","chg":rcs,"label":rl,"color":rc2,"prev":f"{rpr:,.0f}"}

        if mkt_state == "OPEN":
            if vp>=30 or sl=="SELLOFF": tone="broad stress -- mean reversion entries emerging"
            elif sl in("UP","RALLY") and rl in("UP","RALLY"): tone="broad strength -- be selective on new buys"
            elif sl=="FLAT": tone="indecisive -- focus on individual catalysts"
            else: tone="mixed -- stay selective"
            res["pulse"]=f"S&P {scs} ({sl}) · Russell {rcs} ({rl}) · VIX {vp:.1f} ({vl}) -- {tone}"
        elif mkt_state == "PRE":
            res["pulse"]=f"Pre-Market -- S&P last close {sp:,.0f} · Russell {rp:,.0f} · VIX {vp:.1f} ({vl}) · Markets open 9:30 AM ET"
        else:
            res["pulse"]=f"Last close -- S&P {sp:,.0f} · Russell {rp:,.0f} · VIX {vp:.1f} ({vl})"

        print(f"   ✅ S&P 500: {sp:,.0f} ({scs} {sl})")
        print(f"   ✅ Russell: {rp:,.0f} ({rcs} {rl})")
        print(f"   ✅ VIX: {vp:.2f} ({vl}) | State: {mkt_state}")
    except Exception as e:
        print(f"   ❌ Market indicators failed: {e}"); res["pulse"]="Market data unavailable."
    return res


# ============================================================
# STEP 5: DATAROMA SUPERINVESTOR QUARTERLY BUYS
# Fixed: now correctly parses ticker + company + number of
# superinvestors who bought, shown as a readable watchlist
# ============================================================

def fetch_superinvestor_buys():
    print("\n👑 Fetching Dataroma superinvestor quarterly buys...")
    try:
        url="https://www.dataroma.com/m/g/portfolio_b.php?q=q"
        hdrs={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
              "Accept":"text/html,application/xhtml+xml",
              "Referer":"https://www.dataroma.com/"}
        resp=requests.get(url,headers=hdrs,timeout=15)
        print(f"   Status: {resp.status_code}")

        if resp.status_code!=200:
            raise Exception(f"HTTP {resp.status_code}")

        soup=BeautifulSoup(resp.text,"html.parser")
        buys=[]

        # Find table -- Dataroma uses a specific grid table
        table=soup.find("table",{"id":"grid"})
        if not table:
            table=soup.find("table",class_=lambda c: c and "grid" in c.lower())
        if not table:
            # Try any table with multiple rows
            for t in soup.find_all("table"):
                rows=t.find_all("tr")
                if len(rows)>5:
                    table=t; break

        if table:
            rows=table.find_all("tr")
            # Print header to understand column structure
            if rows:
                headers=[th.get_text(strip=True) for th in rows[0].find_all(["th","td"])]
                print(f"   Columns: {headers[:6]}")

            for row in rows[1:26]:  # Up to 25 stocks
                cells=row.find_all("td")
                if len(cells)>=2:
                    # Column 0: ticker (with link usually)
                    ticker_cell=cells[0]
                    ticker=ticker_cell.get_text(strip=True)
                    # Remove any non-ticker characters
                    ticker=re.sub(r"[^A-Z.]","",ticker.upper())[:6]

                    if not ticker or len(ticker)<1: continue

                    # Column 1 or 2: company name
                    company=""
                    for ci in [1,2]:
                        if ci<len(cells):
                            txt=cells[ci].get_text(strip=True)
                            if txt and not txt.replace(".","").replace(",","").replace("%","").replace("$","").isnumeric():
                                company=txt[:40]; break

                    # Find the count of superinvestors -- look for integer columns
                    count=""
                    for ci in [2,3,4,5]:
                        if ci<len(cells):
                            txt=cells[ci].get_text(strip=True).replace(",","")
                            try:
                                n=int(float(txt))
                                if 1<=n<=83:  # Valid range: 1-83 superinvestors
                                    count=str(n); break
                            except: pass

                    if ticker and len(ticker)>=1:
                        if count:
                            buys.append({"ticker":ticker,"company":company,"count":count})
                        elif company:
                            buys.append({"ticker":ticker,"company":company,"count":"?"})

        if buys:
            print(f"   ✅ Dataroma: {len(buys)} stocks found")
            # Show a few for debug
            for b in buys[:3]: print(f"   Example: {b}")
        else:
            print("   ⚠️ Dataroma: no data extracted -- table structure may have changed")

        return buys

    except Exception as e:
        print(f"   ❌ Dataroma failed: {e}")
        return []


# ============================================================
# STEP 6: EDWARD JONES SCRAPE
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
# STEPS 7-9: EMAIL VIA IMAP
# ============================================================

def _fetch_email(sender, label, char_limit=2500):
    print(f"\n📬 Fetching {label} (sender: {sender})...")
    try:
        mail=imaplib.IMAP4_SSL("imap.mail.yahoo.com",993)
        mail.login(YAHOO_EMAIL,YAHOO_PASSWORD)
        print(f"   ✅ Logged in")
        mail.select("INBOX")
        status,messages=mail.search(None,f'(FROM "{sender}")')
        count=len(messages[0].split()) if messages[0] else 0
        print(f"   Found: {count} emails")
        if status!="OK" or not messages[0]:
            domain=sender.split("@")[-1] if "@" in sender else sender
            status,messages=mail.search(None,f'(FROM "{domain}")')
            count=len(messages[0].split()) if messages[0] else 0
            print(f"   Domain fallback: {count} emails")
        if status!="OK" or not messages[0]:
            print(f"   ❌ No {label} emails found"); mail.logout()
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
        return body
    except Exception as e:
        print(f"   ❌ {label} IMAP failed: {e}")
        return f"{label} unavailable today."

def fetch_cnbc_email():
    return _fetch_email("morningsquawk@response.cnbc.com","CNBC Morning Squawk")

def fetch_yahoo_morning_brief():
    return _fetch_email("finance-morning-brief@newsletters.yahoo.net","Yahoo Morning Brief",char_limit=2000)

def fetch_mcoscillator_email():
    return _fetch_email("admin@mcoscillator.com","McClellan Oscillator",char_limit=1500)


# ============================================================
# STEP 10: GEMINI AI SYNTHESIS
# Single attempt -- fail fast strategy.
# Tries gemini-3.6-flash first, falls back to gemini-1.5-flash.
# Why single attempt: quota is 20 RPD on free tier.
# Multiple retries waste quota AND time for no benefit
# when the real issue is daily quota exhaustion.
# Exponential backoff explained: waiting progressively longer
# gives overloaded servers time to recover. But when quota is
# exhausted (not just overloaded), retries don't help -- the
# quota resets at midnight UTC, not in minutes.
# ============================================================

def _call_gemini_model(prompt, model_name):
    """Call a specific Gemini model."""
    client=genai.Client(api_key=GEMINI_API_KEY)
    return client.interactions.create(model=model_name,input=prompt).output_text

def synthesize_with_gemini(ej_text, cnbc_text, yahoo_text, mcoscillator_text,
                            fred_data, fg_data, mkt_data, mri, superinvestor_buys):
    print("\n🤖 Sending to Gemini (single attempt, 90s timeout)...")

    fred_summary="\n".join([
        f"- {r['label']}: {r['current']} (trend:{r['trend']}) {r.get('sig','')}"
        for r in fred_data if r["current"]!="N/A"
    ])

    si_text=""
    if superinvestor_buys:
        si_lines=[f"- {b['ticker']} ({b['company']}) -- bought by {b['count']} superinvestors"
                  for b in superinvestor_buys[:8]]
        si_text="SUPERINVESTOR QUARTERLY BUYS (Dataroma 13F):\n"+"\n".join(si_lines)

    prompt=f"""You are a sharp financial analyst writing a morning briefing for a 
deep-value mean reversion investor (Greenblatt/Munger/Pabrai style).

STRICT RULES:
- Output EXACTLY these 3 section headers (no numbers, no markdown):
  MARKET AND MACRO
  EARNINGS AND EVENTS
  WHAT TO WATCH
- MARKET AND MACRO: 4-5 bullets -- market moves + macro news
- EARNINGS AND EVENTS: 3-4 bullets -- specific earnings dates/releases with dates if mentioned
- WHAT TO WATCH: 3-4 bullets -- mean reversion opportunities, mention superinvestor buys if relevant
- Do NOT mention F&G score, VIX number, S&P/Russell % -- shown in tables
- Max 20 words per bullet, dash (-) prefix, no paragraphs, no bold

After the 3 sections add:
AI FUN FACT
- One genuinely surprising fact about AI, markets, or investing. Max 25 words.

AI LEARNING
- One AI concept relevant to finance/investing, plain English. Max 30 words.

MRI: {mri['score']}/100 -- {mri['label']}
MARKET: {mkt_data['pulse']}
FRED: {fred_summary}
{si_text}
EDWARD JONES: {ej_text[:900]}
CNBC SQUAWK: {cnbc_text[:700]}
YAHOO BRIEF: {yahoo_text[:700]}
McCLELLAN (breadth signal): {mcoscillator_text[:500]}
"""

    # Try primary model, fall back to older model if quota hit
    for model_name in ["gemini-3.6-flash","gemini-1.5-flash"]:
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                fut=ex.submit(_call_gemini_model,prompt,model_name)
                briefing=fut.result(timeout=90)
            print(f"   ✅ Gemini ({model_name}): {len(briefing)} chars")
            return briefing, False
        except concurrent.futures.TimeoutError:
            print(f"   ⚠️ {model_name} timed out (>90s) -- trying fallback model")
        except Exception as e:
            err=str(e)
            if "quota" in err.lower() or "429" in err:
                print(f"   ⚠️ {model_name} quota exceeded -- trying fallback model")
            elif "500" in err:
                print(f"   ⚠️ {model_name} server error -- trying fallback model")
            else:
                print(f"   ⚠️ {model_name} failed: {err[:100]}")

    print("   ❌ All Gemini models failed -- using structured fallback")
    fallback="""MARKET AND MACRO
- AI synthesis unavailable today -- all data sections below are complete and current

EARNINGS AND EVENTS
- Check Yahoo Morning Brief and CNBC for earnings calendar details

WHAT TO WATCH
- Review MRI score and FRED signals -- data complete even without AI narrative

AI FUN FACT
- Mohnish Pabrai paid $650,100 with Guy Spier to lunch with Buffett in 2007 -- his best investment ever.

AI LEARNING
- RAG (Retrieval Augmented Generation): AI fetches relevant context before answering -- exactly how this dashboard enriches your stock analysis."""
    return fallback, True


# ============================================================
# STEP 11: PARSE SECTIONS
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
# STEP 12: BUILD HTML DASHBOARD
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
       "CLOSED":"CLOSED","PRE-MARKET":"PRE-MKT","AFTER-HOURS":"AFTER-HRS","Unavailable":"N/A"}
    c={"BULLISH":"#057a55","NEUTRAL":"#6b7280","CAUTIOUS":"#b45309","BEARISH":"#c81e1e",
       "CLOSED":"#9ca3af","PRE-MKT":"#6366f1","AFTER-HRS":"#8b5cf6","N/A":"#9ca3af"}
    std=m.get(raw_lbl,raw_lbl); col=c.get(std,raw_col)
    return f'<span style="background:{col};color:white;padding:2px 9px;border-radius:4px;font-size:.68rem;font-weight:700;">{std}</span>'


def build_html(briefing, ai_failed, ej_text, cnbc_text, yahoo_text, mcoscillator_text,
               fred_data, fg_data, mkt_data, mri, superinvestor_buys):
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
    status_label=mkt_data.get("market_status_label","")

    fg_score=fg_data.get("score",50); fg_lbl=fg_data.get("label","N/A")
    fg_col=fg_data.get("color","#6b7280"); fg_sig=fg_data.get("signal","")

    umich=next((r for r in fred_data if r["label"]=="Consumer Sentiment"),None)
    umich_val=umich["current"] if umich else "N/A"; umich_mo3=umich["mo3"] if umich else "N/A"
    umich_mo12=umich["mo12"] if umich else "N/A"; umich_sig=umich.get("sig","") if umich else ""
    try: umich_num=float(str(umich_val))
    except: umich_num=55
    ucol="#c81e1e" if umich_num<60 else "#6b7280" if umich_num<75 else "#057a55"
    umich_raw_lbl="LOW" if umich_num<60 else "MID" if umich_num<75 else "HIGH"

    mri_score=mri["score"]; mri_lbl=mri["label"]; mri_col=mri["color"]
    mri_action=mri["action"]; mri_pct=min(100,max(0,mri_score))
    mri_breakdown="".join([f'<span style="font-size:.63rem;color:#6b7280;margin-right:10px;">{b}</span>' for b in mri["breakdown"]])

    # ---- AI alert ------------------------------------------
    ai_alert=""
    if ai_failed:
        ai_alert="""<div style="background:#fef2f2;border:2px solid #fca5a5;border-radius:8px;padding:10px 16px;
            margin-bottom:12px;display:flex;align-items:center;gap:10px;">
          <span style="font-size:1.3rem;">⚠️</span>
          <div>
            <div style="font-weight:700;font-size:.82rem;color:#c81e1e;">AI Synthesis Unavailable</div>
            <div style="font-size:.73rem;color:#6b7280;margin-top:2px;">
              Gemini quota exceeded (free tier: 20 requests/day) or temporary outage.
              All data sections are complete. Run manually after midnight UTC to retry,
              or upgrade to Gemini paid tier ($4.99/mo) for higher limits.
            </div>
          </div>
        </div>"""

    # ---- Market status banner ---------------------------------
    mkt_banner=""
    if mkt_state == "PRE":
        mkt_banner='<div style="background:#eef2ff;border:1px solid #c7d2fe;border-radius:5px;padding:4px 8px;margin-bottom:7px;font-size:.72rem;color:#3730a3;">🌅 Pre-Market · Markets open 9:30 AM ET (7:30 AM MT) · Last close shown</div>'
    elif mkt_state in ("CLOSED",):
        mkt_banner='<div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:5px;padding:4px 8px;margin-bottom:7px;font-size:.72rem;color:#6b7280;">🔒 Markets closed · Last close shown</div>'
    elif mkt_state == "POST":
        mkt_banner='<div style="background:#faf5ff;border:1px solid #e9d5ff;border-radius:5px;padding:4px 8px;margin-bottom:7px;font-size:.72rem;color:#6d28d9;">🌙 After-Hours · Last regular session shown</div>'

    # ---- Market performance rows -----------------------------
    try: vix_num=float(vix_val)
    except: vix_num=20
    vix_badge_lbl="CALM" if vix_num<15 else "NORMAL" if vix_num<20 else "CAUTIOUS" if vix_num<25 else "FEARFUL" if vix_num<30 else "PANIC"

    def pr(name,val,chg,prev,rl,rc,note=""):
        nh=f'<div style="font-size:.6rem;color:#9ca3af;">{note}</div>' if note else ""
        return f'<tr style="border-bottom:1px solid #f3f4f6;"><td style="padding:7px 10px;"><div style="font-weight:600;font-size:.82rem;">{name}</div>{nh}</td><td style="padding:7px 10px;font-weight:700;font-size:.9rem;">{val}</td><td style="padding:7px 10px;font-size:.78rem;color:#6b7280;">{chg}</td><td style="padding:7px 10px;font-size:.75rem;color:#9ca3af;">prev {prev}</td><td style="padding:7px 10px;">{_badge(rl,rc)}</td></tr>'

    def sr(name,val,hist,rl,rc,sig,note=""):
        nh=f'<div style="font-size:.6rem;color:#9ca3af;">{note}</div>' if note else ""
        return f'<tr style="border-bottom:1px solid #f3f4f6;"><td style="padding:7px 10px;"><div style="font-weight:600;font-size:.82rem;">{name}</div>{nh}</td><td style="padding:7px 10px;font-weight:700;font-size:.9rem;">{val}</td><td style="padding:7px 10px;font-size:.75rem;color:#6b7280;">{hist}</td><td style="padding:7px 10px;">{_badge(rl,rc)}</td><td style="padding:7px 10px;font-size:.72rem;color:#374151;">{sig}</td></tr>'

    perf_rows=(
        pr("S&P 500 (Large Cap)",spx_val,spx_chg,spx_prev,spx_lbl,spx_col,"Yahoo Finance · large cap benchmark")
        +pr("Russell 2000 (Small Cap)",rut_val,rut_chg,rut_prev,rut_lbl,rut_col,"Yahoo Finance · small cap / risk appetite proxy")
        +pr("VIX (Volatility Index)",vix_val,f"prev {vix_prev}","",vix_badge_lbl,vix_col,"CBOE · CALM<15 NORMAL<20 CAUTIOUS<25 FEARFUL<30 PANIC≥30")
    )

    sent_rows=(
        sr("Fear & Greed Index",f"{fg_score}/100",
           f"1wk:{fg_data.get('prev_week','N/A')} 1mo:{fg_data.get('prev_month','N/A')} 1yr:{fg_data.get('prev_year','N/A')}",
           fg_lbl,fg_col,fg_sig,"CNN Business · daily composite sentiment")
        +sr("Consumer Sentiment",f"{umich_val}/100",f"3mo:{umich_mo3} 12mo:{umich_mo12}",
            umich_raw_lbl,ucol,umich_sig,"U of Michigan · avg ~75 · monthly")
    )

    # ---- FRED table (grouped) --------------------------------
    group_order=["INFLATION","TREASURY","ECONOMIC","CREDIT"]
    fred_rows=""; rn=1
    for g in group_order:
        gm=GROUP_META[g]; items=[r for r in fred_data if r.get("group")==g]
        if not items: continue
        fred_rows+=f'<tr style="background:#f9fafb;"><td colspan="8" style="padding:6px 10px;font-size:.64rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:{gm["color"]};border-bottom:1px solid #e5e7eb;">{gm["icon"]} {gm["label"]}</td></tr>'
        for r in items:
            tc="#057a55" if (g=="INFLATION" and r["trend"]=="▼") or (g!="INFLATION" and r["trend"]=="▲") else "#c81e1e" if (g=="INFLATION" and r["trend"]=="▲") or (g!="INFLATION" and r["trend"]=="▼") else "#6b7280"
            fred_rows+=f'<tr style="border-bottom:1px solid #f3f4f6;"><td style="padding:7px 8px;text-align:center;font-size:.7rem;color:#9ca3af;">{rn}</td><td style="padding:7px 10px;"><div style="font-weight:600;font-size:.8rem;">{r["label"]}</div><div style="font-size:.62rem;color:#9ca3af;">[{r["insight"]}]</div></td><td style="padding:7px 10px;text-align:center;font-weight:700;font-size:.88rem;">{r["current"]}</td><td style="padding:7px 10px;text-align:center;font-size:.78rem;color:#6b7280;">{r["mo3"]}</td><td style="padding:7px 10px;text-align:center;font-size:.78rem;color:#6b7280;">{r["mo12"]}</td><td style="padding:7px 10px;text-align:center;font-size:1rem;color:{tc};">{r["trend"]}</td><td style="padding:7px 8px;font-size:.67rem;color:#9ca3af;white-space:nowrap;">{r["date"]}</td><td style="padding:7px 10px;font-size:.72rem;color:#1e3a5f;">{r.get("sig","")}</td></tr>'; rn+=1

    # ---- Superinvestor section (improved: show ticker watchlist) ----
    si_html=""
    if superinvestor_buys:
        # Compact ticker grid -- shows ticker prominently, company + count in smaller text
        si_items=""
        for b in superinvestor_buys[:25]:
            count_txt=f"{b['count']} investors" if b['count']!="?" else "recently bought"
            si_items+=f"""<div style="background:#f0f9ff;border:1px solid #bae6fd;border-radius:7px;padding:8px 10px;min-width:120px;">
              <div style="font-weight:800;font-size:.95rem;color:#0c4a6e;">{b['ticker']}</div>
              <div style="font-size:.68rem;color:#0369a1;margin-top:1px;">{b['company'][:25]}</div>
              <div style="font-size:.62rem;color:#6b7280;margin-top:2px;">👑 {count_txt}</div>
            </div>"""

        si_html=f"""<div class="card ab" style="margin-top:12px;">
      <h2>👑 Superinvestor Quarterly Buys
        <span style="font-weight:400;color:var(--muted);font-size:.55rem;">&nbsp; Dataroma · 13F SEC filings · ~45 day lag · {len(superinvestor_buys)} stocks</span>
      </h2>
      <div style="display:flex;flex-wrap:wrap;gap:8px;margin-bottom:10px;">
        {si_items}
      </div>
      <div style="font-size:.68rem;color:#6b7280;background:#f0f9ff;border-radius:5px;padding:6px 10px;line-height:1.5;">
        <strong>Who are superinvestors?</strong> Legendary value investors tracked by Dataroma:
        Warren Buffett (Berkshire), Mohnish Pabrai, Seth Klarman (Baupost), Bill Ackman (Pershing Square),
        David Tepper (Appaloosa), Joel Greenblatt, and ~75 others with exceptional long-term track records.
        These are stocks they BOUGHT (not just held) in the most recent quarter.
        <strong>How to use:</strong> Run any of these through your mean reversion framework as a second-opinion confirmation.
        If a stock appears here AND shows up in your Finviz screener AND Left Leg Score is low, that's a strong alignment signal.
      </div>
    </div>"""

    # ---- AI blocks -------------------------------------------
    fun_raw=secs.get("AI FUN FACT","").strip(); learn_raw=secs.get("AI LEARNING","").strip()
    if fun_raw:  fun_raw=re.sub(r"^[-•*]\s*","",fun_raw.splitlines()[0].strip())
    else:        fun_raw="Mohnish Pabrai paid $650,100 with Guy Spier to lunch with Buffett in 2007 -- his best investment ever."
    if learn_raw: learn_raw=re.sub(r"^[-•*]\s*","",learn_raw.splitlines()[0].strip())
    else:         learn_raw="Exponential backoff: when a server is busy, wait progressively longer between retries (5s, 10s, 20s). Prevents hammering overloaded systems -- used by every major tech company."

    # ---- Hidden market-context div (Chrome extension) --------
    fred_plain="\n".join([f"  {r['label']}: {r['current']} (3mo:{r['mo3']} 12mo:{r['mo12']} trend:{r['trend']}) -- {r['insight']}" for r in fred_data])
    si_tickers=" | ".join([f"{b['ticker']}({b['count']}SI)" for b in (superinvestor_buys or [])[:20]])
    mctx=f"""MARKETPULSE AI MACRO CONTEXT - {today} {now} MT
=== MRI (MEAN REVERSION INSIGHTS): {mri_score}/100 -- {mri_lbl} ===
Action: {mri_action}

=== MARKET PERFORMANCE ===
               Change        Price        Signal
S&P 500        {spx_chg:<14}{spx_val:<13}{spx_lbl}
Russell 2000   {rut_chg:<14}{rut_val:<13}{rut_lbl}
VIX            {'--':<14}{vix_val:<13}{vix_badge_lbl}
Market State: {mkt_state}

=== SENTIMENT ===
Fear & Greed: {fg_score}/100 ({fg_lbl}) -- {fg_sig}
  History: 1wk={fg_data.get('prev_week','N/A')} 1mo={fg_data.get('prev_month','N/A')} 1yr={fg_data.get('prev_year','N/A')}
Consumer Sentiment (U of Michigan): {umich_val}/100 -- {umich_sig}
  History: 3mo={umich_mo3} 12mo={umich_mo12}

=== BRIEFING ===
MARKET AND MACRO:
{secs.get('MARKET AND MACRO','').strip()}

EARNINGS AND EVENTS:
{secs.get('EARNINGS AND EVENTS','').strip()}

WHAT TO WATCH:
{secs.get('WHAT TO WATCH','').strip()}

=== FRED MACRO INDICATORS ===
{fred_plain}

=== SUPERINVESTOR BUYS (13F ~45 day lag) ===
{si_tickers if si_tickers else 'Unavailable'}"""

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
<div id="market-context" style="display:none;white-space:pre;">{mctx}</div>

<div class="hero">
  <h1>📈 MARKETPULSE AI</h1>
  <div class="sub">Anil Abraham &nbsp;·&nbsp; {today}</div>
  <div class="ts">Last updated {now} MT</div>
</div>

<div class="container">

{ai_alert}

<!-- AI BLOCKS -->
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
      <div style="font-size:.88rem;font-weight:700;color:{mri_col};">{mri_lbl}</div>
      <div style="margin-top:5px;background:#e5e7eb;border-radius:99px;height:7px;width:220px;overflow:hidden;">
        <div style="width:{mri_pct}%;background:{mri_col};height:100%;border-radius:99px;"></div>
      </div>
      <div style="font-size:.7rem;color:#374151;margin-top:5px;">📋 {mri_action}</div>
    </div>
    <div style="font-size:.64rem;color:var(--muted);flex:1;min-width:200px;line-height:1.8;">
      {mri_breakdown}
    </div>
  </div>
  <div style="margin-top:8px;font-size:.67rem;color:#374151;background:#f9fafb;border-radius:5px;padding:6px 10px;line-height:1.6;">
    <strong>Hunting Guide:</strong>
    🟢 PRIME HUNTING (80+): Aggressive · 
    🟡 ACTIVE (65-79): Normal pace · 
    🟠 PATIENT STALKING (50-64): Best setups only -- Left Leg &lt;4, MoS &gt;25% · 
    🔴 WATCH & WAIT (35-49): Build cash · 
    ⛔ HIBERNATE (0-34): No new buys.
    <br>Mixed signals today? Consumer bearish + F&G cautious + VIX calm = people worried but NOT panic-selling = classic mean reversion setup. No forced selling yet.
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
      <h2>🔭 What to Watch
        <span style="font-weight:400;color:var(--muted);font-size:.55rem;">&nbsp; Mean reversion · Pabrai/Greenblatt/Munger</span>
      </h2>
      <ul>{fmt_bullets(secs.get("WHAT TO WATCH",""))}</ul>
    </div>
  </div>

</div>

<!-- Superinvestor Buys -->
{si_html}

<!-- FRED Macro Indicators -->
<div style="margin-top:12px;">
  <div class="card">
    <h2>🏦 Macro Indicators
      <span style="font-weight:400;color:var(--muted);font-size:.55rem;">&nbsp; FRED API · grouped by category · Today's Signal at right</span>
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

<div class="footer" style="margin-top:20px;">
  Built by <strong>Anil Abraham</strong> &nbsp;·&nbsp;
  <a href="https://www.edwardjones.com/us-en/market-news-insights/stock-market-news/daily-market-recap" target="_blank">Edward Jones</a> &nbsp;·&nbsp;
  <a href="https://www.cnbc.com/newsletters/" target="_blank">CNBC Squawk</a> &nbsp;·&nbsp;
  <a href="https://finance.yahoo.com" target="_blank">Yahoo Finance</a> &nbsp;·&nbsp;
  <a href="https://fred.stlouisfed.org" target="_blank">FRED API</a> &nbsp;·&nbsp;
  <a href="https://www.cnn.com/markets/fear-and-greed" target="_blank">CNN Fear &amp; Greed</a> &nbsp;·&nbsp;
  <a href="https://www.mcoscillator.com" target="_blank">McClellan</a> &nbsp;·&nbsp;
  <a href="https://www.dataroma.com" target="_blank">Dataroma 13F</a> &nbsp;·&nbsp;
  Gemini 3.6 Flash / 1.5 Flash &nbsp;·&nbsp; Not financial advice.
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

    fred_data         = fetch_fred_data()
    fg_data           = fetch_fear_greed()
    mkt_data          = fetch_market_indicators()
    mri               = compute_mri(fred_data, fg_data, mkt_data)
    superinvestor_buys= fetch_superinvestor_buys()
    ej_text           = scrape_edward_jones()
    cnbc_text         = fetch_cnbc_email()
    yahoo_text        = fetch_yahoo_morning_brief()
    mcoscillator_text = fetch_mcoscillator_email()

    briefing, ai_failed = synthesize_with_gemini(
        ej_text, cnbc_text, yahoo_text, mcoscillator_text,
        fred_data, fg_data, mkt_data, mri, superinvestor_buys
    )

    build_html(
        briefing, ai_failed, ej_text, cnbc_text, yahoo_text, mcoscillator_text,
        fred_data, fg_data, mkt_data, mri, superinvestor_buys
    )

    print("\n📧 Email disabled -- dashboard is primary output")
    print("\n"+"="*50)
    print("✅ MarketPulse AI Complete!")
    print("🌐 https://anil2040.github.io/market-pulse-ai")
    print("="*50)