# ============================================================
# MarketPulse AI - main.py
# Updated: September 2026
# ============================================================
# Pipeline:
#   1.  FRED macro indicators (12 series, parallel, 20s)
#   2.  CNN Fear & Greed (JSON)
#   3.  VIX + S&P 500 + Russell 2000 (Yahoo Finance)
#   4.  Macro Regime Score / MRS (computed from data)
#   5.  Dataroma superinvestor quarterly buys (scrape)
#   6.  Edward Jones daily recap (web scrape)
#   7.  CNBC Morning Squawk (Yahoo IMAP)
#   8.  Yahoo Finance Morning Brief (Yahoo IMAP)
#   9.  McClellan Oscillator newsletter (Yahoo IMAP, weekly)
#  10.  Gemini AI synthesis with retry (150s + 3 attempts)
#  11.  Build HTML dashboard (index.html -> GitHub Pages)
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
     "insight":"High Yield spread -- widening = credit stress (HY = junk bonds)"},
]

GROUP_META = {
    "INFLATION":{"icon":"🔥","color":"#c81e1e","label":"Inflation"},
    "TREASURY": {"icon":"📊","color":"#1a56db","label":"Treasury Yields"},
    "ECONOMIC": {"icon":"⚙️","color":"#b45309","label":"Economic"},
    "CREDIT":   {"icon":"💳","color":"#7f1d1d","label":"Credit"},
}


def _signal(label, cur_str, mo3_str, trend):
    """Signal: trend checked FIRST to prevent contradictions."""
    try:
        cur=float(re.sub(r"[%$]","",str(cur_str)))
        mo3=float(re.sub(r"[%$]","",str(mo3_str)))
    except: return ""
    if label in("Core PCE","Core CPI"):
        if cur<=2.0:                  return "✅ At Fed 2% target"
        elif cur<=2.5 and trend=="▼": return "📉 Cooling toward 2% target"
        elif cur>3.0 and trend=="▲":  return "⚠️ Rising & above target -- rates stay elevated longer"
        elif cur>3.0:                 return "⚠️ Above target -- rates staying elevated"
        elif trend=="▼":              return "📉 Cooling trend"
        elif trend=="▲":              return "⚠️ Rising -- hawkish Fed signal"
        else:                         return "→ Flat -- watching for sustained cooling"
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
    print(f"   🏦 FRED complete: {len(results)} indicators")
    return results


# ============================================================
# STEP 2: MACRO REGIME SCORE (MRS)
# ============================================================
# 0-100 score reflecting macro favorability for deep-value
# mean reversion investing. Key insight: extreme fear gets
# BONUS points because that's the Pabrai/Buffett buying moment.
# How to use MRS with your mean reversion framework:
#   80-100: Aggressive -- go full pace on high-conviction buys
#   65-79:  Normal pace -- execute your screener results
#   50-64:  Selective -- only best setups (Left Leg <4, MoS >25%)
#   35-49:  Cautious -- build cash, wait for better setups
#   0-34:   Hostile -- capital preservation, no new buys
# ============================================================

def compute_mrs(fred_data, fg_data, mkt_data):
    score=0; breakdown=[]
    def get(lbl):
        r=next((x for x in fred_data if x["label"]==lbl),None)
        if not r or r["current"]=="N/A": return None,None
        try: return float(re.sub(r"[%$]","",r["current"])),r["trend"]
        except: return None,None

    # Inflation (20pts) -- cooling is good
    cp,cpt=get("Core PCE")
    if cp is not None:
        if cp<=2.0:                   pts=20; note="Core PCE at target"
        elif cp<=2.5 and cpt=="▼":   pts=16; note="Core PCE cooling"
        elif cp<=3.0 and cpt=="▼":   pts=12; note="Core PCE easing"
        elif cpt=="▼":               pts=8;  note="Core PCE trending down"
        elif cpt=="→":               pts=5;  note="Core PCE stable"
        else:                        pts=0;  note="Core PCE rising"
        score+=pts; breakdown.append(f"Inflation +{pts}/20 ({note})")

    # Credit (15pts)
    hy,_=get("HY Credit Spread")
    if hy is not None:
        if hy<=3.0:   pts=15; note=f"HY {hy:.2f}% tight"
        elif hy<=4.0: pts=10; note=f"HY {hy:.2f}% normal"
        elif hy<=6.0: pts=5;  note=f"HY {hy:.2f}% elevated"
        else:         pts=0;  note=f"HY {hy:.2f}% wide"
        score+=pts; breakdown.append(f"Credit +{pts}/15 ({note})")

    # Fed (15pts)
    fed,fedt=get("Fed Funds Rate")
    if fed is not None:
        if fedt=="▼":              pts=15; note="Cutting"
        elif fedt=="→" and fed<=3.5: pts=12; note="Hold, low rates"
        elif fedt=="→":            pts=8;  note="Hold"
        elif fedt=="▲":            pts=2;  note="Hiking"
        else:                      pts=5;  note="Neutral"
        score+=pts; breakdown.append(f"Fed +{pts}/15 ({note})")

    # Yield curve (10pts)
    cv,_=get("Yield Curve (10Y-2Y)")
    if cv is not None:
        if cv>=0.5:   pts=10; note="Steep"
        elif cv>=0.0: pts=7;  note="Positive"
        elif cv>=-0.5:pts=3;  note="Mildly inverted"
        else:         pts=0;  note="Deeply inverted"
        score+=pts; breakdown.append(f"Curve +{pts}/10 ({note})")

    # Labor (10pts)
    un,unt=get("Unemployment")
    if un is not None:
        if un<=4.0 and unt!="▲": pts=10; note="Strong labor"
        elif un<=4.5:             pts=7;  note="Solid labor"
        elif un<=5.0:             pts=4;  note="Softening"
        else:                     pts=0;  note="Weak labor"
        score+=pts; breakdown.append(f"Labor +{pts}/10 ({note})")

    # VIX (10pts) -- some fear is good for mean reversion buyers
    try:
        vix=float(mkt_data["vix"]["value"])
        if vix<15:   pts=5;  note=f"VIX {vix:.1f} complacent"
        elif vix<20: pts=7;  note=f"VIX {vix:.1f} normal"
        elif vix<30: pts=10; note=f"VIX {vix:.1f} elevated fear"
        else:        pts=10; note=f"VIX {vix:.1f} high fear"
        score+=pts; breakdown.append(f"VIX +{pts}/10 ({note})")
    except: pass

    # Fear & Greed (20pts) -- extreme fear = Pabrai buying moment!
    try:
        fg=int(fg_data.get("score",50))
        if fg<=25:   pts=20; note=f"F&G {fg} EXTREME FEAR -- Pabrai zone"
        elif fg<=40: pts=16; note=f"F&G {fg} fear -- good setup"
        elif fg<=55: pts=10; note=f"F&G {fg} neutral"
        elif fg<=70: pts=4;  note=f"F&G {fg} greed"
        else:        pts=0;  note=f"F&G {fg} extreme greed"
        score+=pts; breakdown.append(f"Fear&Greed +{pts}/20 ({note})")
    except: pass

    if   score>=80: lbl="🟢 STRONG BUY ENVIRONMENT"; col="#057a55"; action="Go aggressive on high-conviction mean reversion buys. Full position pace."
    elif score>=65: lbl="🟡 FAVORABLE";              col="#059669"; action="Good environment. Normal position sizing on screener results."
    elif score>=50: lbl="🟠 NEUTRAL -- SELECTIVE";   col="#b45309"; action="Only best setups: Left Leg Score <4 AND Margin of Safety >25%. Maintain 25% cash."
    elif score>=35: lbl="🔴 CAUTIOUS";               col="#c81e1e"; action="Build cash above 25%. Only buy at extreme Fear & Greed (<20)."
    else:           lbl="⛔ HOSTILE -- WAIT";        col="#7f1d1d"; action="Capital preservation. No new buys. Wait for MRS >50."

    print(f"\n📊 MRS: {score}/100 ({lbl})")
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
        if   score<=24: lbl="Extreme Fear"; col="#c81e1e"; sig="Historically strong buying opportunity"
        elif score<=44: lbl="Fear";         col="#e97316"; sig="Pessimism -- watch for mean reversion entries"
        elif score<=55: lbl="Neutral";      col="#6b7280"; sig="No strong directional signal"
        elif score<=74: lbl="Greed";        col="#059669"; sig="Optimism elevated -- exercise caution"
        else:           lbl="Extreme Greed";col="#1a56db"; sig="Overheated -- high reversal risk"
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
    if v>=30: return "⚠️ Fear/panic -- mean reversion entries emerging"
    if v>=25: return "⚠️ Cautious -- watch for volatility spikes"
    if v>=20: return "→ Slightly elevated"
    if v>=15: return "→ Normal -- no market stress"
    return "✅ Calm -- low fear, rally intact"

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
         "market_state":"UNKNOWN","pulse":""}
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            fv=ex.submit(_yq,"%5EVIX"); fs=ex.submit(_yq,"%5EGSPC"); fr=ex.submit(_yq,"%5ERUT")
            vp,vpr,_,vs  =fv.result(timeout=15)
            sp,spr,sc,ss =fs.result(timeout=15)
            rp,rpr,rc,rs =fr.result(timeout=15)
        closed=ss in("CLOSED","POST","PRE") or abs(sc)<0.001
        res["market_state"]="CLOSED" if closed else "OPEN"
        vl,vc=_classify_vix(vp); sl,sc2=_classify_idx(sc); rl,rc2=_classify_idx(rc)
        if closed: sl="CLOSED"; sc2="#9ca3af"; rl="CLOSED"; rc2="#9ca3af"; scs="last close"; rcs="last close"
        else:      scs=f"{sc:+.2f}%"; rcs=f"{rc:+.2f}%"
        res["vix"]={"value":f"{vp:.2f}","label":vl,"color":vc,"signal":_vix_sig(vp),"prev":f"{vpr:.2f}"}
        res["spx"]={"value":f"{sp:,.0f}","chg":scs,"label":sl,"color":sc2,"prev":f"{spr:,.0f}"}
        res["rut"]={"value":f"{rp:,.0f}","chg":rcs,"label":rl,"color":rc2,"prev":f"{rpr:,.0f}"}
        if closed: res["pulse"]=f"Last close -- S&P {sp:,.0f} · Russell {rp:,.0f} · VIX {vp:.1f} ({vl})"
        else:
            if vp>=30 or sl=="SELLOFF": tone="broad stress -- mean reversion entries emerging"
            elif sl in("UP","RALLY") and rl in("UP","RALLY"): tone="broad strength -- be selective on new buys"
            elif sl=="FLAT": tone="indecisive -- focus on individual catalysts"
            else: tone="mixed -- stay selective"
            res["pulse"]=f"S&P {scs} ({sl}) · Russell {rcs} ({rl}) · VIX {vp:.1f} ({vl}) -- {tone}"
        print(f"   ✅ S&P 500: {sp:,.0f} ({scs} {sl})")
        print(f"   ✅ Russell: {rp:,.0f} ({rcs} {rl})")
        print(f"   ✅ VIX: {vp:.2f} ({vl}) | State: {res['market_state']}")
    except Exception as e:
        print(f"   ❌ Market indicators failed: {e}"); res["pulse"]="Market data unavailable."
    return res


# ============================================================
# STEP 5: DATAROMA SUPERINVESTOR QUARTERLY BUYS
# ============================================================
# Scrapes Dataroma's quarterly activity page showing which
# stocks superinvestors BOUGHT this quarter.
# Public website, no API key needed.
# Shows top buys across all tracked superinvestors.
# 13F data is 45 days old but valuable for idea confirmation.
# ============================================================

def fetch_superinvestor_buys():
    print("\n👑 Fetching Dataroma superinvestor quarterly buys...")
    try:
        # Quarterly buys page -- stocks bought by superinvestors this quarter
        url="https://www.dataroma.com/m/g/portfolio_b.php?q=q"
        hdrs={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
              "Accept":"text/html,application/xhtml+xml",
              "Referer":"https://www.dataroma.com/"}
        resp=requests.get(url,headers=hdrs,timeout=15)
        print(f"   Status: {resp.status_code}")

        if resp.status_code!=200:
            raise Exception(f"HTTP {resp.status_code}")

        soup=BeautifulSoup(resp.text,"html.parser")

        # Find the main data table
        buys=[]
        table=soup.find("table",{"id":"grid"}) or soup.find("table",class_="grid")
        if not table:
            # Try any table with stock data
            tables=soup.find_all("table")
            for t in tables:
                if t.find("td") and len(t.find_all("tr"))>3:
                    table=t; break

        if table:
            rows=table.find_all("tr")[1:]  # Skip header
            for row in rows[:15]:  # Top 15 buys
                cells=row.find_all("td")
                if len(cells)>=3:
                    ticker=cells[0].get_text(strip=True) if cells[0] else ""
                    company=cells[1].get_text(strip=True) if cells[1] else ""
                    owners=cells[2].get_text(strip=True) if cells[2] else ""
                    if ticker and len(ticker)<=6:
                        buys.append(f"{ticker} -- {company} (owned by {owners} superinvestors)")

        if buys:
            print(f"   ✅ Dataroma: {len(buys)} quarterly buys found")
            return buys
        else:
            print("   ⚠️ Dataroma: table structure changed, no data extracted")
            return []

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
    # Confirmed sender: finance-morning-brief@newsletters.yahoo.net
    return _fetch_email("finance-morning-brief@newsletters.yahoo.net","Yahoo Morning Brief",char_limit=2000)

def fetch_mcoscillator_email():
    # Tom McClellan weekly -- admin@mcoscillator.com
    return _fetch_email("admin@mcoscillator.com","McClellan Oscillator",char_limit=1500)


# ============================================================
# STEP 10: GEMINI AI SYNTHESIS
# Retry with exponential backoff -- 3 attempts
# Attempt 1: immediate
# Attempt 2: wait 15 seconds
# Attempt 3: wait 30 seconds
# If all fail: structured fallback (still useful dashboard!)
# ============================================================

def _call_gemini(prompt):
    client=genai.Client(api_key=GEMINI_API_KEY)
    return client.interactions.create(model="gemini-3.6-flash",input=prompt).output_text

def synthesize_with_gemini(ej_text, cnbc_text, yahoo_text, mcoscillator_text,
                            fred_data, fg_data, mkt_data, mrs, superinvestor_buys):
    print("\n🤖 Sending to Gemini (3 attempts, 150s timeout each)...")

    fred_summary="\n".join([
        f"- {r['label']}: {r['current']} (trend:{r['trend']}) {r.get('sig','')}"
        for r in fred_data if r["current"]!="N/A"
    ])

    si_text=""
    if superinvestor_buys:
        si_text="SUPERINVESTOR QUARTERLY BUYS (Dataroma 13F data):\n"+"\n".join([f"- {b}" for b in superinvestor_buys[:8]])

    prompt=f"""You are a sharp financial analyst writing a morning briefing for a 
deep-value mean reversion investor (Greenblatt/Munger/Pabrai style).

STRICT RULES:
- Output EXACTLY these 3 section headers (no numbers, no markdown):
  MARKET AND MACRO
  EARNINGS AND EVENTS
  WHAT TO WATCH
- MARKET AND MACRO: 4-5 bullets covering key market moves + macro news
- EARNINGS AND EVENTS: 3-4 bullets -- include any specific earnings dates,
  economic data releases from any source. Include dates if mentioned.
- WHAT TO WATCH: 3-4 bullets -- mean reversion lens, specific sector/stock
  opportunities for deep-value investors, reference superinvestor activity if relevant
- Do NOT repeat VIX number, S&P/Russell %, Fear & Greed score -- shown in table
- Max 20 words per bullet, dash (-) prefix, no paragraphs, no bold

After the 3 sections add:
AI FUN FACT
- One genuinely surprising fact about AI, markets, or investing history. Max 25 words.

AI LEARNING
- One specific AI concept relevant to investing/finance. Plain English. Max 30 words.

MRS: {mrs['score']}/100 -- {mrs['label']}
MARKET: {mkt_data['pulse']}
FRED: {fred_summary}
{si_text}
EDWARD JONES: {ej_text[:900]}
CNBC SQUAWK: {cnbc_text[:700]}
YAHOO BRIEF: {yahoo_text[:700]}
McCLELLAN (breadth): {mcoscillator_text[:500]}
"""

    # Retry with exponential backoff
    delays=[0, 15, 30]  # Seconds to wait before each attempt
    for attempt, delay in enumerate(delays, 1):
        if delay>0:
            print(f"   Waiting {delay}s before attempt {attempt}...")
            time.sleep(delay)
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                fut=ex.submit(_call_gemini,prompt)
                briefing=fut.result(timeout=150)
            print(f"   ✅ Gemini succeeded on attempt {attempt}: {len(briefing)} chars")
            return briefing, False  # False = no failure
        except concurrent.futures.TimeoutError:
            print(f"   ⚠️ Attempt {attempt} timed out (>150s)")
        except Exception as e:
            print(f"   ⚠️ Attempt {attempt} failed: {e}")

    print("   ❌ All 3 Gemini attempts failed -- using structured fallback")
    fallback="""MARKET AND MACRO
- AI synthesis unavailable today -- all data sections below are complete and current

EARNINGS AND EVENTS
- Check Yahoo Morning Brief and CNBC for earnings calendar details

WHAT TO WATCH
- Review MRS score and FRED signals -- data is complete even without AI narrative

AI FUN FACT
- Mohnish Pabrai paid $650,100 with Guy Spier to lunch with Buffett in 2007 -- his best investment ever.

AI LEARNING
- RAG (Retrieval Augmented Generation): AI fetches relevant data before responding -- exactly what this dashboard does for your stock analysis."""
    return fallback, True  # True = failure occurred


# ============================================================
# STEP 11: PARSE SECTIONS
# ============================================================

def parse_sections(text):
    secs={"MARKET AND MACRO":"","EARNINGS AND EVENTS":"","WHAT TO WATCH":"","AI FUN FACT":"","AI LEARNING":""}
    current=None
    for line in text.splitlines():
        up=line.upper().strip()
        cln=re.sub(r"^\d+[\.\)]\s*","",up)
        cln=re.sub(r"^#+\s*","",cln); cln=re.sub(r"^\*+\s*","",cln)
        cln=cln.encode("ascii","ignore").decode().strip()
        if "MARKET AND MACRO" in cln or ("MARKET AND KEY" in cln): current="MARKET AND MACRO"; continue
        if "MARKET SUMMARY" in cln or "KEY MOVES" in cln:         current="MARKET AND MACRO"; continue
        if "MACRO AND NEWS" in cln or "MACRO & NEWS" in cln:      current="MARKET AND MACRO"; continue
        if "EARNINGS AND EVENTS" in cln or "EARNINGS AND CALENDAR" in cln: current="EARNINGS AND EVENTS"; continue
        if "WHAT TO WATCH" in cln or "PRE-MARKET" in cln:         current="WHAT TO WATCH"; continue
        if "AI FUN FACT" in cln:                                   current="AI FUN FACT"; continue
        if "AI LEARNING" in cln or ("AI" in cln and "LEARN" in cln): current="AI LEARNING"; continue
        if "FUN FACT" in cln and "AI" not in cln:                  current="AI FUN FACT"; continue
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
       "CLOSED":"CLOSED","Unavailable":"N/A"}
    c={"BULLISH":"#057a55","NEUTRAL":"#6b7280","CAUTIOUS":"#b45309","BEARISH":"#c81e1e","CLOSED":"#9ca3af","N/A":"#9ca3af"}
    std=m.get(raw_lbl,raw_lbl); col=c.get(std,raw_col)
    return f'<span style="background:{col};color:white;padding:2px 9px;border-radius:4px;font-size:.68rem;font-weight:700;">{std}</span>'


def build_html(briefing, ai_failed, ej_text, cnbc_text, yahoo_text, mcoscillator_text,
               fred_data, fg_data, mkt_data, mrs, superinvestor_buys):
    print("\n🎨 Building HTML dashboard...")

    secs=parse_sections(briefing)
    now_mt=datetime.now(MT)
    today=now_mt.strftime("%A, %B %d, %Y")
    now=now_mt.strftime("%I:%M %p")

    # Market data
    vix_val=mkt_data["vix"]["value"]; vix_prev=mkt_data["vix"]["prev"]
    vix_lbl=mkt_data["vix"]["label"]; vix_col=mkt_data["vix"]["color"]; vix_sig=mkt_data["vix"]["signal"]
    spx_val=mkt_data["spx"]["value"]; spx_chg=mkt_data["spx"]["chg"]
    spx_lbl=mkt_data["spx"]["label"]; spx_col=mkt_data["spx"]["color"]; spx_prev=mkt_data["spx"]["prev"]
    rut_val=mkt_data["rut"]["value"]; rut_chg=mkt_data["rut"]["chg"]
    rut_lbl=mkt_data["rut"]["label"]; rut_col=mkt_data["rut"]["color"]; rut_prev=mkt_data["rut"]["prev"]
    pulse=mkt_data["pulse"]; mkt_closed=mkt_data.get("market_state")=="CLOSED"

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

    mrs_score=mrs["score"]; mrs_lbl=mrs["label"]; mrs_col=mrs["color"]; mrs_action=mrs["action"]
    mrs_pct=min(100,max(0,mrs_score))
    mrs_breakdown="".join([f'<span style="font-size:.65rem;color:#6b7280;margin-right:10px;">{b}</span>' for b in mrs["breakdown"]])

    # ---- AI failure alert banner ----------------------------
    ai_alert=""
    if ai_failed:
        ai_alert="""<div style="background:#fef2f2;border:2px solid #fca5a5;border-radius:8px;padding:10px 16px;
            margin-bottom:12px;display:flex;align-items:center;gap:10px;">
          <span style="font-size:1.3rem;">⚠️</span>
          <div>
            <div style="font-weight:700;font-size:.82rem;color:#c81e1e;">AI Synthesis Unavailable Today</div>
            <div style="font-size:.73rem;color:#6b7280;margin-top:2px;">
              Gemini API was unavailable (high demand or temporary outage). All data sections below are 
              complete and current -- only the AI narrative summary is missing. Run manually later to retry.
            </div>
          </div>
        </div>"""

    # ---- Market Performance rows ----------------------------
    def pr(name,val,chg,prev,rl,rc,note=""):
        nh=f'<div style="font-size:.6rem;color:#9ca3af;">{note}</div>' if note else ""
        return f"""<tr style="border-bottom:1px solid #f3f4f6;">
      <td style="padding:7px 10px;"><div style="font-weight:600;font-size:.82rem;">{name}</div>{nh}</td>
      <td style="padding:7px 10px;font-weight:700;font-size:.9rem;">{val}</td>
      <td style="padding:7px 10px;font-size:.78rem;color:#6b7280;">{chg}</td>
      <td style="padding:7px 10px;font-size:.75rem;color:#9ca3af;">prev {prev}</td>
      <td style="padding:7px 10px;">{_badge(rl,rc)}</td>
    </tr>"""

    # ---- Sentiment rows -------------------------------------
    def sr(name,val,hist,rl,rc,sig,note=""):
        nh=f'<div style="font-size:.6rem;color:#9ca3af;">{note}</div>' if note else ""
        return f"""<tr style="border-bottom:1px solid #f3f4f6;">
      <td style="padding:7px 10px;"><div style="font-weight:600;font-size:.82rem;">{name}</div>{nh}</td>
      <td style="padding:7px 10px;font-weight:700;font-size:.9rem;">{val}</td>
      <td style="padding:7px 10px;font-size:.75rem;color:#6b7280;">{hist}</td>
      <td style="padding:7px 10px;">{_badge(rl,rc)}</td>
      <td style="padding:7px 10px;font-size:.72rem;color:#374151;">{sig}</td>
    </tr>"""

    # ---- Try to get VIX level safely for badge --------------
    try: vix_num=float(vix_val)
    except: vix_num=20
    vix_badge_lbl="CALM" if vix_num<15 else "NORMAL" if vix_num<20 else "CAUTIOUS" if vix_num<25 else "FEARFUL" if vix_num<30 else "PANIC"

    perf_rows=(
        pr("S&P 500 (Large Cap)",spx_val,spx_chg,spx_prev,spx_lbl,spx_col,"Yahoo Finance · daily")
        +pr("Russell 2000 (Small Cap)",rut_val,rut_chg,rut_prev,rut_lbl,rut_col,"Yahoo Finance · risk appetite indicator")
        +pr("VIX (Volatility Index)",vix_val,f"prev {vix_prev}","",vix_badge_lbl,vix_col,"CBOE · CALM<15 NORMAL<20 CAUTIOUS<25 FEARFUL<30 PANIC≥30")
    )

    sent_rows=(
        sr("Fear & Greed Index",f"{fg_score}/100",
           f"1wk:{fg_data.get('prev_week','N/A')} 1mo:{fg_data.get('prev_month','N/A')} 1yr:{fg_data.get('prev_year','N/A')}",
           fg_lbl,fg_col,fg_sig,"CNN Business · daily composite sentiment")
        +sr("Consumer Sentiment",f"{umich_val}/100",
            f"3mo:{umich_mo3} 12mo:{umich_mo12}",
            umich_raw_lbl,ucol,umich_sig,"U of Michigan · avg ~75 · monthly")
    )

    # ---- FRED table (grouped) --------------------------------
    group_order=["INFLATION","TREASURY","ECONOMIC","CREDIT"]
    fred_rows=""; rn=1
    for g in group_order:
        gm=GROUP_META[g]
        items=[r for r in fred_data if r.get("group")==g]
        if not items: continue
        fred_rows+=f'<tr style="background:#f9fafb;"><td colspan="8" style="padding:6px 10px;font-size:.64rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:{gm["color"]};border-bottom:1px solid #e5e7eb;">{gm["icon"]} {gm["label"]}</td></tr>'
        for r in items:
            tc="#057a55" if (r.get("group")=="INFLATION" and r["trend"]=="▼") or (r.get("group")!="INFLATION" and r["trend"]=="▲") else "#c81e1e" if (r.get("group")=="INFLATION" and r["trend"]=="▲") or (r.get("group")!="INFLATION" and r["trend"]=="▼") else "#6b7280"
            fred_rows+=f"""<tr style="border-bottom:1px solid #f3f4f6;">
      <td style="padding:7px 8px;text-align:center;font-size:.7rem;color:#9ca3af;">{rn}</td>
      <td style="padding:7px 10px;"><div style="font-weight:600;font-size:.8rem;">{r['label']}</div><div style="font-size:.62rem;color:#9ca3af;">[{r['insight']}]</div></td>
      <td style="padding:7px 10px;text-align:center;font-weight:700;font-size:.88rem;">{r['current']}</td>
      <td style="padding:7px 10px;text-align:center;font-size:.78rem;color:#6b7280;">{r['mo3']}</td>
      <td style="padding:7px 10px;text-align:center;font-size:.78rem;color:#6b7280;">{r['mo12']}</td>
      <td style="padding:7px 10px;text-align:center;font-size:1rem;color:{tc};">{r['trend']}</td>
      <td style="padding:7px 8px;font-size:.67rem;color:#9ca3af;white-space:nowrap;">{r['date']}</td>
      <td style="padding:7px 10px;font-size:.72rem;color:#1e3a5f;">{r.get('sig','')}</td>
    </tr>"""; rn+=1

    # ---- Superinvestor buys section -------------------------
    si_html=""
    if superinvestor_buys:
        si_items="".join([f"<li>{b}</li>" for b in superinvestor_buys[:10]])
        si_html=f"""<div class="card ab" style="margin-top:12px;">
      <h2>👑 Superinvestor Quarterly Buys
        <span style="font-weight:400;color:var(--muted);font-size:.55rem;">&nbsp; Dataroma · 13F filings · ~45 day lag</span>
      </h2>
      <ul>{si_items}</ul>
      <div style="font-size:.63rem;color:#9ca3af;margin-top:8px;border-top:1px solid #f3f4f6;padding-top:6px;">
        💡 13F filings are public SEC data, ~45 days after quarter end. Use as idea confirmation, not as primary signal.
        Pabrai clones from these with full awareness of the lag.
      </div>
    </div>"""

    # ---- AI blocks -------------------------------------------
    fun_raw=secs.get("AI FUN FACT","").strip()
    learn_raw=secs.get("AI LEARNING","").strip()
    if fun_raw:  fun_raw=re.sub(r"^[-•*]\s*","",fun_raw.splitlines()[0].strip())
    else:        fun_raw="Mohnish Pabrai paid $650,100 with Guy Spier to lunch with Buffett in 2007 -- his best investment ever."
    if learn_raw: learn_raw=re.sub(r"^[-•*]\s*","",learn_raw.splitlines()[0].strip())
    else:         learn_raw="RAG (Retrieval Augmented Generation): AI fetches relevant context before answering -- exactly how this dashboard enriches your stock analysis."

    # ---- Hidden market-context div (Chrome extension) --------
    fred_plain="\n".join([f"  {r['label']}: {r['current']} (3mo:{r['mo3']} 12mo:{r['mo12']} trend:{r['trend']}) -- {r['insight']}" for r in fred_data])
    si_plain="\n".join([f"  {b}" for b in (superinvestor_buys or [])[:10]])
    mctx=f"""MARKETPULSE AI MACRO CONTEXT - {today} {now} MT
=== MRS (MACRO REGIME SCORE): {mrs_score}/100 -- {mrs_lbl} ===
Action: {mrs_action}

=== MARKET PERFORMANCE ===
               Change        Price        Signal
S&P 500        {spx_chg:<14}{spx_val:<13}{spx_lbl}
Russell 2000   {rut_chg:<14}{rut_val:<13}{rut_lbl}
VIX            {'--':<14}{vix_val:<13}{vix_badge_lbl}

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

=== SUPERINVESTOR BUYS (13F, ~45 day lag) ===
{si_plain if si_plain else 'Data unavailable today'}"""

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

<!-- MRS: MACRO REGIME SCORE -->
<div class="card" style="margin-bottom:12px;border-left:4px solid {mrs_col};">
  <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;">
    <div style="flex-shrink:0;">
      <div style="font-size:.58rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--muted);margin-bottom:3px;">MRS · Macro Regime Score</div>
      <div style="font-size:2rem;font-weight:800;color:{mrs_col};line-height:1;">{mrs_score}<span style="font-size:.85rem;color:var(--muted);">/100</span></div>
    </div>
    <div>
      <div style="font-size:.88rem;font-weight:700;color:{mrs_col};">{mrs_lbl}</div>
      <div style="margin-top:5px;background:#e5e7eb;border-radius:99px;height:7px;width:200px;overflow:hidden;">
        <div style="width:{mrs_pct}%;background:{mrs_col};height:100%;border-radius:99px;"></div>
      </div>
      <div style="font-size:.7rem;color:#6b7280;margin-top:5px;">📋 {mrs_action}</div>
    </div>
    <div style="font-size:.65rem;color:var(--muted);flex:1;min-width:200px;">
      {mrs_breakdown}
    </div>
  </div>
  <div style="margin-top:8px;font-size:.67rem;color:#374151;background:#f9fafb;border-radius:5px;padding:5px 10px;line-height:1.6;">
    <strong>How to use MRS:</strong> 80+ = aggressive · 65-79 = normal pace · 50-64 = selective only (Left Leg &lt;4, MoS &gt;25%) · 35-49 = build cash · 0-34 = no new buys.
    Mixed signals (Consumer bearish + F&G cautious + VIX calm) = people worried but not panic-selling = classic mean reversion setup with no forced selling yet.
  </div>
</div>

<!-- ROW 1: Market Performance + Sentiment | Analysis sections -->
<div class="grid-2">

  <div style="display:flex;flex-direction:column;gap:12px;">
    <div class="card ar">
      <h2>📈 Market Performance</h2>
      {'<div style="background:#fef9c3;border-radius:5px;padding:4px 8px;margin-bottom:7px;font-size:.7rem;color:#92400e;">⏰ Markets closed · last close shown</div>' if mkt_closed else ''}
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

<!-- Superinvestor Buys (if available) -->
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

    fred_data         = fetch_fred_data()
    fg_data           = fetch_fear_greed()
    mkt_data          = fetch_market_indicators()
    mrs               = compute_mrs(fred_data, fg_data, mkt_data)
    superinvestor_buys= fetch_superinvestor_buys()
    ej_text           = scrape_edward_jones()
    cnbc_text         = fetch_cnbc_email()
    yahoo_text        = fetch_yahoo_morning_brief()
    mcoscillator_text = fetch_mcoscillator_email()

    briefing, ai_failed = synthesize_with_gemini(
        ej_text, cnbc_text, yahoo_text, mcoscillator_text,
        fred_data, fg_data, mkt_data, mrs, superinvestor_buys
    )

    build_html(
        briefing, ai_failed, ej_text, cnbc_text, yahoo_text, mcoscillator_text,
        fred_data, fg_data, mkt_data, mrs, superinvestor_buys
    )

    print("\n📧 Email disabled -- dashboard is primary output")
    print("\n"+"="*50)
    print("✅ MarketPulse AI Complete!")
    print("🌐 https://anil2040.github.io/market-pulse-ai")
    print("="*50)