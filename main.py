# ============================================================
# MarketPulse AI - main.py
# Updated: September 2026
# ============================================================
# Pipeline:
#   1.  FRED macro indicators (12 series, parallel, 20s)
#   2.  CNN Fear & Greed (JSON)
#   3.  VIX + S&P 500 + Russell 2000 (Yahoo Finance)
#   4.  Macro Regime Score (computed from actual data)
#   5.  Edward Jones daily recap (web scrape)
#   6.  CNBC Morning Squawk (Yahoo IMAP)
#   7.  Yahoo Finance Morning Brief (Yahoo IMAP)
#   8.  McClellan Oscillator newsletter (Yahoo IMAP, weekly)
#   9.  Gemini AI synthesis + Fun Fact + AI Learning (150s)
#  10.  Build HTML dashboard (index.html -> GitHub Pages)
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
# ============================================================
# Grouped by category for display:
#   INFLATION: CPI Headline, CPI Core, PCE Headline, PCE Core
#   TREASURY:  10Y Yield, 2Y Yield, 10Y-2Y Curve
#   ECONOMIC:  Fed Funds, Unemployment, WTI Crude, U of Michigan
#   CREDIT:    HY Spread
# ============================================================

FRED_SERIES = [
    # INFLATION GROUP
    {"label":"CPI Inflation",          "id":"CPIAUCSL",     "is_index":True,  "group":"INFLATION",
     "insight":"Headline CPI including food & energy"},
    {"label":"Core CPI",               "id":"CPILFESL",     "is_index":True,  "group":"INFLATION",
     "insight":"CPI ex food/energy -- Fed watches this closely"},
    {"label":"PCE Inflation",          "id":"PCEPI",        "is_index":True,  "group":"INFLATION",
     "insight":"Fed's preferred inflation gauge (broader than CPI)"},
    {"label":"Core PCE",               "id":"PCEPILFE",     "is_index":True,  "group":"INFLATION",
     "insight":"Fed's 2% target -- most important inflation measure"},
    # TREASURY GROUP
    {"label":"10Y Treasury",           "id":"GS10",         "is_index":False, "group":"TREASURY",
     "insight":"Risk-free benchmark -- rising = headwind for high-multiple stocks"},
    {"label":"2Y Treasury",            "id":"GS2",          "is_index":False, "group":"TREASURY",
     "insight":"Fed rate expectations -- rises when markets price in no cuts"},
    {"label":"Yield Curve (10Y-2Y)",   "id":"T10Y2Y",       "is_index":False, "group":"TREASURY",
     "insight":"Negative = inverted = historically predicts recession ahead"},
    # ECONOMIC GROUP
    {"label":"Fed Funds Rate",         "id":"FEDFUNDS",     "is_index":False, "group":"ECONOMIC",
     "insight":"Cost of borrowing -- cutting cycle = positive for equities"},
    {"label":"Unemployment",           "id":"UNRATE",       "is_index":False, "group":"ECONOMIC",
     "insight":"Labor market -- rising signals recession risk ahead"},
    {"label":"WTI Crude Oil",          "id":"DCOILWTICO",   "is_index":False, "group":"ECONOMIC",
     "prefix":"$", "insight":"Energy prices -- drives inflation & energy stocks"},
    {"label":"Consumer Sentiment",     "id":"UMCSENT",      "is_index":False, "group":"ECONOMIC",
     "no_pct":True, "insight":"U of Michigan 0-100 confidence score (avg ~75)"},
    # CREDIT GROUP
    {"label":"HY Credit Spread",       "id":"BAMLH0A0HYM2", "is_index":False, "group":"CREDIT",
     "insight":"High Yield spread -- widening = credit stress, be selective"},
]

# Group display order and colors
GROUP_META = {
    "INFLATION": {"icon":"🔥","color":"#c81e1e","label":"Inflation"},
    "TREASURY":  {"icon":"📊","color":"#1a56db","label":"Treasury Yields"},
    "ECONOMIC":  {"icon":"⚙️","color":"#b45309","label":"Economic"},
    "CREDIT":    {"icon":"💳","color":"#7f1d1d","label":"Credit"},
}


def _signal(label, cur_str, mo3_str, trend):
    """Signal: trend checked FIRST to prevent contradictions."""
    try:
        cur = float(re.sub(r"[%$]","",str(cur_str)))
        mo3 = float(re.sub(r"[%$]","",str(mo3_str)))
    except:
        return ""
    if "Core PCE" in label or "Core CPI" in label or label in ("Core PCE","Core CPI"):
        if cur <= 2.0:                  return "✅ At Fed 2% target"
        elif cur <= 2.5 and trend=="▼": return "📉 Cooling toward 2% target"
        elif cur > 3.0 and trend=="▲":  return "⚠️ Rising & above target -- rates stay elevated longer"
        elif cur > 3.0:                 return "⚠️ Above target -- rates staying elevated"
        elif trend=="▼":                return "📉 Cooling trend"
        elif trend=="▲":                return "⚠️ Rising -- hawkish Fed signal"
        else:                           return "→ Flat -- watching for sustained cooling"
    elif "PCE" in label or "CPI" in label:
        if trend=="▼": return "📉 Cooling"
        elif trend=="▲": return "⚠️ Heating up"
        else:          return "→ Stable"
    elif "Fed Funds" in label:
        if trend=="▼":   return "📉 Cutting cycle -- positive for rate-sensitive sectors"
        elif trend=="▲": return "⚠️ Rising -- tightening"
        elif cur >= 5.0: return "⚠️ Restrictive -- growth headwind"
        elif cur <= 3.0: return "✅ Accommodative"
        else:            return "→ On hold"
    elif "Unemployment" in label:
        if trend=="▲":               return "⚠️ Rising -- watch consumer discretionary"
        elif trend=="▼" and cur<=4.0:return "✅ Tightening -- strong labor market"
        elif cur <= 4.0:             return "✅ Strong labor market"
        elif cur >= 5.0:             return "⚠️ Weakening -- recession risk elevated"
        else:                        return "✅ Stable"
    elif "HY Credit" in label or "HY" in label:
        if trend=="▲":   return "⚠️ Widening -- systemic risk rising, be selective"
        elif trend=="▼": return "📉 Tightening -- credit improving"
        elif cur <= 3.0: return "✅ Tight -- credit markets calm"
        elif cur >= 6.0: return "⚠️ Wide -- avoid leveraged balance sheets"
        else:            return "→ Stable"
    elif "Yield Curve" in label:
        if cur < 0:      return "⚠️ Inverted -- recession signal (12-18mo lead)"
        elif cur < 0.3:  return "→ Nearly flat"
        elif trend=="▲": return "✅ Steepening -- growth expectations improving"
        else:            return "✅ Positive slope -- normal"
    elif "10Y" in label:
        if trend=="▲" and cur>=5.0: return "⚠️ High & rising -- P/E compression risk"
        elif trend=="▲":            return "⚠️ Rising -- headwind for growth stocks"
        elif trend=="▼":            return "📉 Falling -- relief for rate-sensitive stocks"
        elif cur >= 5.0:            return "⚠️ High -- P/E compression risk"
        elif cur <= 3.5:            return "✅ Low -- supports higher valuations"
        else:                       return "→ Stable"
    elif "2Y" in label:
        if trend=="▲" and cur>=4.5: return "⚠️ Rising & elevated -- no cuts priced in"
        elif trend=="▲":            return "⚠️ Rising -- delayed cuts priced in"
        elif trend=="▼":            return "✅ Falling -- rate cuts priced in"
        elif cur >= 5.0:            return "⚠️ Elevated"
        else:                       return "→ Stable"
    elif "Consumer Sentiment" in label or "Michigan" in label:
        if trend=="▼" and cur<=65:  return "⚠️ Declining & below avg"
        elif trend=="▼":            return "⚠️ Declining"
        elif cur <= 55:             return "⚠️ Well below avg (~75)"
        elif cur <= 65:             return "→ Below average"
        elif cur >= 80:             return "✅ High confidence"
        else:                       return "→ Near average"
    elif "WTI" in label:
        if trend=="▲" and cur>=90:  return "⚠️ High & rising -- inflation pressure"
        elif trend=="▲":            return "⚠️ Rising -- watch for inflation spillover"
        elif trend=="▼":            return "📉 Falling -- easing energy inflation"
        elif cur >= 90:             return "⚠️ High -- inflationary"
        elif cur <= 60:             return "✅ Low -- consumer-friendly"
        else:                       return "→ Stable"
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
# STEP 2: MACRO REGIME SCORE (computed from actual data)
# ============================================================
# Scores 0-100 reflecting how favorable the macro environment
# is for deep-value mean reversion investing.
# Key insight: extreme fear (F&G < 30) gets a BONUS because
# that's exactly the Pabrai/Buffett buying environment!
# ============================================================

def compute_regime_score(fred_data, fg_data, mkt_data):
    """
    Macro Regime Score for mean reversion investing (0-100).
    High score = favorable environment for buying beaten-down quality.
    """
    score = 0
    breakdown = []

    def get_fred(label):
        r = next((x for x in fred_data if x["label"]==label), None)
        if not r or r["current"]=="N/A": return None, None
        try: return float(re.sub(r"[%$]","",r["current"])), r["trend"]
        except: return None, None

    # 1. Inflation trend (max 20pts) -- cooling is good for rates & valuations
    core_pce, pce_trend = get_fred("Core PCE")
    if core_pce is not None:
        if core_pce <= 2.0:                   pts=20; note="Core PCE at target"
        elif core_pce <= 2.5 and pce_trend=="▼": pts=16; note="Core PCE cooling"
        elif core_pce <= 3.0 and pce_trend=="▼": pts=12; note="Core PCE easing"
        elif pce_trend=="▼":                  pts=8;  note="Core PCE trending down"
        elif pce_trend=="→":                  pts=5;  note="Core PCE stable"
        else:                                 pts=0;  note="Core PCE rising"
        score+=pts; breakdown.append(f"Inflation: +{pts}/20 ({note})")

    # 2. Credit stress (max 15pts) -- tight spreads = calm markets
    hy, hy_trend = get_fred("HY Credit Spread")
    if hy is not None:
        if hy <= 3.0:                         pts=15; note=f"HY spread {hy:.2f}% tight"
        elif hy <= 4.0:                       pts=10; note=f"HY spread {hy:.2f}% normal"
        elif hy <= 6.0:                       pts=5;  note=f"HY spread {hy:.2f}% elevated"
        else:                                 pts=0;  note=f"HY spread {hy:.2f}% wide"
        score+=pts; breakdown.append(f"Credit: +{pts}/15 ({note})")

    # 3. Fed posture (max 15pts) -- cutting = supportive
    fed, fed_trend = get_fred("Fed Funds Rate")
    if fed is not None:
        if fed_trend=="▼":                    pts=15; note="Fed cutting"
        elif fed_trend=="→" and fed<=3.5:     pts=12; note="Fed on hold, low rates"
        elif fed_trend=="→":                  pts=8;  note="Fed on hold"
        elif fed_trend=="▲":                  pts=2;  note="Fed hiking"
        else:                                 pts=5;  note="Fed neutral"
        score+=pts; breakdown.append(f"Fed: +{pts}/15 ({note})")

    # 4. Yield curve (max 10pts)
    curve, curve_trend = get_fred("Yield Curve (10Y-2Y)")
    if curve is not None:
        if curve >= 0.5:                      pts=10; note="Curve steep, growth expected"
        elif curve >= 0.0:                    pts=7;  note="Curve positive"
        elif curve >= -0.5:                   pts=3;  note="Curve mildly inverted"
        else:                                 pts=0;  note="Curve deeply inverted"
        score+=pts; breakdown.append(f"Yield Curve: +{pts}/10 ({note})")

    # 5. Labor market (max 10pts)
    unemp, unemp_trend = get_fred("Unemployment")
    if unemp is not None:
        if unemp <= 4.0 and unemp_trend!="▲":pts=10; note="Strong labor market"
        elif unemp <= 4.5:                   pts=7;  note="Solid labor market"
        elif unemp <= 5.0:                   pts=4;  note="Softening labor market"
        else:                                pts=0;  note="Weak labor market"
        score+=pts; breakdown.append(f"Labor: +{pts}/10 ({note})")

    # 6. VIX (max 10pts)
    try:
        vix = float(mkt_data["vix"]["value"])
        if vix < 15:   pts=5;  note=f"VIX {vix:.1f} complacent"    # Low VIX = complacent, less opportunity
        elif vix < 20: pts=7;  note=f"VIX {vix:.1f} normal"
        elif vix < 30: pts=10; note=f"VIX {vix:.1f} elevated fear"  # Elevated VIX = opportunity
        else:          pts=10; note=f"VIX {vix:.1f} high fear"
        score+=pts; breakdown.append(f"VIX: +{pts}/10 ({note})")
    except: pass

    # 7. Fear & Greed -- THE MEAN REVERSION SIGNAL (max 20pts)
    # Extreme fear = BONUS because that's the Buffett/Pabrai buying moment
    try:
        fg = int(fg_data.get("score",50))
        if fg <= 25:   pts=20; note=f"F&G {fg} EXTREME FEAR -- Pabrai entry zone"
        elif fg <= 40: pts=16; note=f"F&G {fg} fear -- good setup"
        elif fg <= 55: pts=10; note=f"F&G {fg} neutral"
        elif fg <= 70: pts=4;  note=f"F&G {fg} greed -- caution"
        else:          pts=0;  note=f"F&G {fg} extreme greed -- avoid"
        score+=pts; breakdown.append(f"Fear&Greed: +{pts}/20 ({note})")
    except: pass

    # Classify overall score
    if   score >= 80: label="🟢 STRONG BUY ENVIRONMENT";   color="#057a55"
    elif score >= 65: label="🟡 FAVORABLE";                 color="#059669"
    elif score >= 50: label="🟠 NEUTRAL -- SELECTIVE";      color="#b45309"
    elif score >= 35: label="🔴 CAUTIOUS";                  color="#c81e1e"
    else:             label="⛔ HOSTILE -- WAIT";           color="#7f1d1d"

    print(f"\n📊 Macro Regime Score: {score}/100 ({label})")
    for b in breakdown: print(f"   {b}")

    return {"score":score,"label":label,"color":color,"breakdown":breakdown}


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
        rating=fg.get("rating","Unknown").replace("_"," ").title()
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
# ============================================================
# Exact thresholds from Chrome extension background.js:
#   VIX: CALM(<15) NORMAL(<20) CAUTIOUS(<25) FEARFUL(<30) PANIC(>=30)
#   Index: SELLOFF(≤-1%) DOWN(-1 to -0.1%) FLAT(-0.1 to 0.1%)
#          UP(0.1 to 1%) RALLY(>1%)
# ============================================================

def _classify_vix(v):
    if v<15: return "CALM",    "#059669"
    if v<20: return "NORMAL",  "#6b7280"
    if v<25: return "CAUTIOUS","#e97316"
    if v<30: return "FEARFUL", "#c81e1e"
    return       "PANIC",     "#7f1d1d"

def _classify_index(chg):
    if chg> 1.0: return "RALLY",  "#059669"
    if chg> 0.1: return "UP",     "#86c440"
    if chg>-0.1: return "FLAT",   "#6b7280"
    if chg>-1.0: return "DOWN",   "#e97316"
    return        "SELLOFF",      "#c81e1e"

def _vix_signal(v):
    if v>=30: return "⚠️ Fear/panic -- mean reversion entries emerging"
    if v>=25: return "⚠️ Cautious -- watch for volatility spikes"
    if v>=20: return "→ Slightly elevated"
    if v>=15: return "→ Normal -- no market stress"
    return          "✅ Calm -- low fear, rally intact"

def _yahoo_quote(ticker):
    url=f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2d"
    hdrs={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)","Accept":"application/json"}
    resp=requests.get(url,headers=hdrs,timeout=12)
    meta=resp.json()["chart"]["result"][0]["meta"]
    price=float(meta.get("regularMarketPrice",0))
    prev=float(meta.get("previousClose",price))
    chg=((price-prev)/prev*100) if prev else 0
    state=meta.get("marketState","UNKNOWN")
    return price,prev,chg,state

def fetch_market_indicators():
    print("\n📊 Fetching Market Performance (VIX, SPX, RUT)...")
    result={"vix":{"value":"N/A","label":"N/A","color":"#6b7280","signal":"","prev":"N/A"},
            "spx":{"value":"N/A","chg":"N/A","label":"N/A","color":"#6b7280","prev":"N/A"},
            "rut":{"value":"N/A","chg":"N/A","label":"N/A","color":"#6b7280","prev":"N/A"},
            "market_state":"UNKNOWN","pulse":""}
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            fv=ex.submit(_yahoo_quote,"%5EVIX")
            fs=ex.submit(_yahoo_quote,"%5EGSPC")
            fr=ex.submit(_yahoo_quote,"%5ERUT")
            vix_p,vix_prev,_,      vstate=fv.result(timeout=15)
            spx_p,spx_prev,spx_chg,sstate=fs.result(timeout=15)
            rut_p,rut_prev,rut_chg,rstate=fr.result(timeout=15)

        mkt_closed=sstate in("CLOSED","POST","PRE") or abs(spx_chg)<0.001
        result["market_state"]="CLOSED" if mkt_closed else "OPEN"

        vix_lbl,vix_col=_classify_vix(vix_p)
        spx_lbl,spx_col=_classify_index(spx_chg)
        rut_lbl,rut_col=_classify_index(rut_chg)
        vix_sig=_vix_signal(vix_p)

        if mkt_closed:
            spx_lbl="CLOSED"; spx_col="#9ca3af"
            rut_lbl="CLOSED"; rut_col="#9ca3af"
            spx_chg_str="last close"; rut_chg_str="last close"
        else:
            spx_chg_str=f"{spx_chg:+.2f}%"; rut_chg_str=f"{rut_chg:+.2f}%"

        result["vix"]={"value":f"{vix_p:.2f}","label":vix_lbl,"color":vix_col,"signal":vix_sig,"prev":f"{vix_prev:.2f}"}
        result["spx"]={"value":f"{spx_p:,.0f}","chg":spx_chg_str,"label":spx_lbl,"color":spx_col,"prev":f"{spx_prev:,.0f}"}
        result["rut"]={"value":f"{rut_p:,.0f}","chg":rut_chg_str,"label":rut_lbl,"color":rut_col,"prev":f"{rut_prev:,.0f}"}

        if mkt_closed:
            result["pulse"]=f"Last close -- S&P 500 {spx_p:,.0f} · Russell {rut_p:,.0f} · VIX {vix_p:.1f} ({vix_lbl})"
        else:
            if vix_p>=30 or spx_lbl=="SELLOFF":   tone="broad stress -- mean reversion entries emerging"
            elif spx_lbl in("UP","RALLY") and rut_lbl in("UP","RALLY"): tone="broad strength -- caution on new buys"
            elif spx_lbl=="FLAT":                  tone="indecisive -- focus on individual catalysts"
            else:                                   tone="mixed -- stay selective"
            result["pulse"]=f"S&P {spx_chg_str} ({spx_lbl}) · Russell {rut_chg_str} ({rut_lbl}) · VIX {vix_p:.1f} ({vix_lbl}) -- {tone}"

        print(f"   ✅ S&P 500: {spx_p:,.0f} ({spx_chg_str} {spx_lbl})")
        print(f"   ✅ Russell: {rut_p:,.0f} ({rut_chg_str} {rut_lbl})")
        print(f"   ✅ VIX: {vix_p:.2f} ({vix_lbl}) | State: {result['market_state']}")
    except Exception as e:
        print(f"   ❌ Market indicators failed: {e}")
        result["pulse"]="Market data unavailable."
    return result


# ============================================================
# STEP 5: EDWARD JONES SCRAPE
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
# STEPS 6-8: EMAIL VIA IMAP
# ============================================================

def _fetch_email(sender, label, char_limit=2500):
    """IMAP fetcher with exact search and domain fallback."""
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
        # Show headers
        _,hdr=mail.fetch(latest,"(BODY[HEADER.FIELDS (FROM SUBJECT DATE)])")
        if hdr and hdr[0] and hdr[0][1]:
            for line in hdr[0][1].decode("utf-8",errors="ignore").strip().splitlines()[:4]:
                if line.strip(): print(f"   {line.strip()}")
        # Fetch body
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
    # Confirmed: finance-morning-brief@newsletters.yahoo.net
    return _fetch_email("finance-morning-brief@newsletters.yahoo.net","Yahoo Morning Brief",char_limit=2000)

def fetch_mcoscillator_email():
    # Tom McClellan weekly -- admin@mcoscillator.com
    return _fetch_email("admin@mcoscillator.com","McClellan Oscillator",char_limit=1500)


# ============================================================
# STEP 9: GEMINI AI SYNTHESIS + FUN FACT + AI LEARNING
# ============================================================

def _call_gemini(prompt):
    client=genai.Client(api_key=GEMINI_API_KEY)
    return client.interactions.create(model="gemini-3.6-flash",input=prompt).output_text

def synthesize_with_gemini(ej_text, cnbc_text, yahoo_text, mcoscillator_text,
                            fred_data, fg_data, mkt_data, regime):
    print("\n🤖 Sending to Gemini (150s timeout)...")
    try:
        fred_summary="\n".join([
            f"- {r['label']}: {r['current']} (trend:{r['trend']}) {r.get('sig','')}"
            for r in fred_data if r["current"]!="N/A"
        ])
        prompt=f"""You are a sharp financial analyst writing a morning briefing for a 
deep-value mean reversion investor (Greenblatt/Munger/Pabrai style).

STRICT RULES:
- Output EXACTLY these 3 section headers (no numbers, no markdown):
  MARKET AND MACRO
  EARNINGS AND EVENTS
  WHAT TO WATCH
- MARKET AND MACRO: 4-5 bullets covering market moves AND macro news together
- EARNINGS AND EVENTS: 3-4 bullets -- extract ALL specific earnings dates and economic
  data releases mentioned in any source. Include the date if mentioned.
- WHAT TO WATCH: 3-4 bullets -- mean reversion lens, cyclical vs structural calls,
  specific sector/stock opportunities for deep-value investors
- Do NOT repeat VIX number, S&P/Russell % changes, Fear & Greed score -- shown in table
- Max 20 words per bullet, starting with dash (-), no paragraphs, no bold

After the 3 sections add:
AI FUN FACT
- One genuinely surprising fact about AI, markets, or investing history. Max 25 words.

AI LEARNING
- One specific AI concept relevant to investing or finance. Explain it in plain English. Max 30 words.
  Examples: "RAG", "embedding", "fine-tuning", "agent", "prompt engineering", "LLM inference"

MACRO REGIME: {regime['score']}/100 -- {regime['label']}
MARKET: {mkt_data['pulse']}
FRED: {fred_summary}
EDWARD JONES: {ej_text[:900]}
CNBC SQUAWK: {cnbc_text[:700]}
YAHOO BRIEF: {yahoo_text[:700]}
McCLELLAN (breadth): {mcoscillator_text[:500]}
"""
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut=ex.submit(_call_gemini,prompt)
            briefing=fut.result(timeout=150)
        print(f"   ✅ Gemini: {len(briefing)} chars")
        return briefing
    except concurrent.futures.TimeoutError:
        print("   ⚠️ Gemini timed out (>150s)")
    except Exception as e:
        print(f"   ❌ Gemini failed: {e}")
    return """MARKET AND MACRO
- AI synthesis unavailable -- see FRED indicators and regime score below

EARNINGS AND EVENTS
- Check Yahoo Morning Brief and CNBC sources for earnings calendar

WHAT TO WATCH
- Review regime score and FRED signals for macro context

AI FUN FACT
- Mohnish Pabrai paid $650,100 with Guy Spier to lunch with Buffett in 2007 -- his best investment ever.

AI LEARNING
- RAG (Retrieval Augmented Generation): AI fetches relevant data before answering, making responses more accurate and current."""


# ============================================================
# STEP 10: PARSE SECTIONS
# ============================================================

def parse_sections(text):
    secs={"MARKET AND MACRO":"","EARNINGS AND EVENTS":"","WHAT TO WATCH":"","AI FUN FACT":"","AI LEARNING":""}
    current=None
    for line in text.splitlines():
        up=line.upper().strip()
        cln=re.sub(r"^\d+[\.\)]\s*","",up)
        cln=re.sub(r"^#+\s*","",cln)
        cln=re.sub(r"^\*+\s*","",cln)
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
    for name,content in secs.items():
        print(f"   {'📋' if content.strip() else '⚠️'} {name}: {len(content)} chars" if content.strip() else f"   ⚠️ {name}: EMPTY")
    return secs


# ============================================================
# STEP 11: BUILD HTML DASHBOARD
# ============================================================
# Layout:
#   [AI Fun Fact + AI Learning] -- full width, blue gradient
#   [Macro Regime Score card] -- full width, prominent
#   [Market Performance table] | [Market Analysis stacked]
#   [Earnings & Events] | [What to Watch]
#   [FRED Macro Table - grouped by category]
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
    """Standardize to BULLISH / CAUTIOUS / NEUTRAL / BEARISH / CLOSED."""
    m={"RALLY":"BULLISH","UP":"BULLISH","CALM":"BULLISH","Greed":"BULLISH","Extreme Greed":"BULLISH","HIGH":"BULLISH",
       "FLAT":"NEUTRAL","NORMAL":"NEUTRAL","Neutral":"NEUTRAL","MID":"NEUTRAL",
       "DOWN":"CAUTIOUS","CAUTIOUS":"CAUTIOUS","Fear":"CAUTIOUS",
       "SELLOFF":"BEARISH","FEARFUL":"BEARISH","PANIC":"BEARISH","Extreme Fear":"BEARISH","LOW":"BEARISH",
       "CLOSED":"CLOSED"}
    c={"BULLISH":"#057a55","NEUTRAL":"#6b7280","CAUTIOUS":"#b45309","BEARISH":"#c81e1e","CLOSED":"#9ca3af"}
    std=m.get(raw_lbl,raw_lbl); col=c.get(std,raw_col)
    return f'<span style="background:{col};color:white;padding:2px 9px;border-radius:4px;font-size:.68rem;font-weight:700;">{std}</span>'

def build_html(briefing, ej_text, cnbc_text, yahoo_text, mcoscillator_text,
               fred_data, fg_data, mkt_data, regime):
    print("\n🎨 Building HTML dashboard...")

    secs=parse_sections(briefing)
    now_mt=datetime.now(MT)
    today=now_mt.strftime("%A, %B %d, %Y")
    now=now_mt.strftime("%I:%M %p")

    vix_val=mkt_data["vix"]["value"]; vix_prev=mkt_data["vix"]["prev"]
    vix_lbl=mkt_data["vix"]["label"]; vix_col=mkt_data["vix"]["color"]
    vix_sig=mkt_data["vix"]["signal"]
    spx_val=mkt_data["spx"]["value"]; spx_chg=mkt_data["spx"]["chg"]
    spx_lbl=mkt_data["spx"]["label"]; spx_col=mkt_data["spx"]["color"]
    spx_prev=mkt_data["spx"]["prev"]
    rut_val=mkt_data["rut"]["value"]; rut_chg=mkt_data["rut"]["chg"]
    rut_lbl=mkt_data["rut"]["label"]; rut_col=mkt_data["rut"]["color"]
    rut_prev=mkt_data["rut"]["prev"]
    pulse=mkt_data["pulse"]
    mkt_closed=mkt_data.get("market_state","UNKNOWN")=="CLOSED"

    fg_score=fg_data.get("score",50); fg_lbl=fg_data.get("label","N/A")
    fg_col=fg_data.get("color","#6b7280"); fg_sig=fg_data.get("signal","")

    # U of Michigan from FRED (in sentiment table alongside F&G)
    umich=next((r for r in fred_data if "Consumer Sentiment" in r["label"]),None)
    umich_val=umich["current"] if umich else "N/A"
    umich_mo3=umich["mo3"] if umich else "N/A"
    umich_mo12=umich["mo12"] if umich else "N/A"
    umich_sig=umich.get("sig","") if umich else ""
    try: umich_num=float(str(umich_val))
    except: umich_num=55
    ucol="#c81e1e" if umich_num<60 else "#6b7280" if umich_num<75 else "#057a55"
    umich_raw_lbl="LOW" if umich_num<60 else "MID" if umich_num<75 else "HIGH"

    # ---- Market Performance Table ----------------------------
    def perf_row(name, val, chg, prev, raw_lbl, raw_col, note=""):
        note_html=f'<div style="font-size:.6rem;color:#9ca3af;">{note}</div>' if note else ""
        return f"""
    <tr style="border-bottom:1px solid #f3f4f6;">
      <td style="padding:7px 10px;">
        <div style="font-weight:600;font-size:.82rem;">{name}</div>{note_html}
      </td>
      <td style="padding:7px 10px;font-weight:700;font-size:.9rem;">{val}</td>
      <td style="padding:7px 10px;font-size:.78rem;color:#6b7280;">{chg}</td>
      <td style="padding:7px 10px;font-size:.75rem;color:#9ca3af;">prev {prev}</td>
      <td style="padding:7px 10px;">{_badge(raw_lbl,raw_col)}</td>
    </tr>"""

    # ---- Sentiment Table (Fear & Greed + Consumer Sentiment) ---
    def sent_row(name, val, hist, raw_lbl, raw_col, signal, note=""):
        note_html=f'<div style="font-size:.6rem;color:#9ca3af;">{note}</div>' if note else ""
        return f"""
    <tr style="border-bottom:1px solid #f3f4f6;">
      <td style="padding:7px 10px;">
        <div style="font-weight:600;font-size:.82rem;">{name}</div>{note_html}
      </td>
      <td style="padding:7px 10px;font-weight:700;font-size:.9rem;">{val}</td>
      <td style="padding:7px 10px;font-size:.75rem;color:#6b7280;">{hist}</td>
      <td style="padding:7px 10px;">{_badge(raw_lbl,raw_col)}</td>
      <td style="padding:7px 10px;font-size:.72rem;color:#374151;">{signal}</td>
    </tr>"""

    perf_rows=(
        perf_row("S&P 500 (Large Cap)",spx_val,spx_chg,spx_prev,spx_lbl,spx_col,"Yahoo Finance · large cap benchmark")
        +perf_row("Russell 2000 (Small Cap)",rut_val,rut_chg,rut_prev,rut_lbl,rut_col,"Yahoo Finance · small cap / risk appetite")
        +perf_row("VIX (Volatility)",vix_val,f"prev {vix_prev}","","CALM" if float(vix_val or 20)<15 else "NORMAL" if float(vix_val or 20)<20 else "CAUTIOUS" if float(vix_val or 20)<25 else "FEARFUL" if float(vix_val or 20)<30 else "PANIC",vix_col,"CBOE · CALM<15 NORMAL<20 CAUTIOUS<25 FEARFUL<30 PANIC≥30")
    )

    sent_rows=(
        sent_row("Fear & Greed",f"{fg_score}/100",
                 f"1wk:{fg_data.get('prev_week','N/A')} 1mo:{fg_data.get('prev_month','N/A')} 1yr:{fg_data.get('prev_year','N/A')}",
                 fg_lbl,fg_col,fg_sig,"CNN Business · daily composite")
        +sent_row("Consumer Sentiment",f"{umich_val}/100",
                  f"3mo:{umich_mo3} 12mo:{umich_mo12}",
                  umich_raw_lbl,ucol,umich_sig,"U of Michigan · avg ~75 · monthly")
    )

    # ---- Regime Score display --------------------------------
    regime_score=regime["score"]; regime_lbl=regime["label"]; regime_col=regime["color"]
    regime_pct=min(100,max(0,regime_score))
    regime_breakdown_html="".join([
        f'<span style="font-size:.68rem;color:#6b7280;margin-right:12px;">{b}</span>'
        for b in regime["breakdown"]
    ])

    # ---- FRED Table grouped by category ----------------------
    group_order=["INFLATION","TREASURY","ECONOMIC","CREDIT"]
    fred_rows=""
    row_num=1
    for group in group_order:
        gmeta=GROUP_META[group]
        group_items=[r for r in fred_data if r.get("group")==group]
        if not group_items: continue
        # Group header row
        fred_rows+=f"""
    <tr style="background:#f9fafb;">
      <td colspan="8" style="padding:6px 10px;font-size:.65rem;font-weight:700;
          letter-spacing:1px;text-transform:uppercase;color:{gmeta['color']};
          border-bottom:1px solid #e5e7eb;">
        {gmeta['icon']} {gmeta['label']}
      </td>
    </tr>"""
        for r in group_items:
            # For inflation: DOWN = good
            if r.get("group")=="INFLATION":
                tc="#057a55" if r["trend"]=="▼" else "#c81e1e" if r["trend"]=="▲" else "#6b7280"
            else:
                tc="#057a55" if r["trend"]=="▲" else "#c81e1e" if r["trend"]=="▼" else "#6b7280"
            fred_rows+=f"""
    <tr style="border-bottom:1px solid #f3f4f6;">
      <td style="padding:7px 8px;text-align:center;font-size:.7rem;color:#9ca3af;">{row_num}</td>
      <td style="padding:7px 10px;">
        <div style="font-weight:600;font-size:.8rem;">{r['label']}</div>
        <div style="font-size:.62rem;color:#9ca3af;">[{r['insight']}]</div>
      </td>
      <td style="padding:7px 10px;text-align:center;font-weight:700;font-size:.88rem;">{r['current']}</td>
      <td style="padding:7px 10px;text-align:center;font-size:.78rem;color:#6b7280;">{r['mo3']}</td>
      <td style="padding:7px 10px;text-align:center;font-size:.78rem;color:#6b7280;">{r['mo12']}</td>
      <td style="padding:7px 10px;text-align:center;font-size:1rem;color:{tc};">{r['trend']}</td>
      <td style="padding:7px 8px;font-size:.67rem;color:#9ca3af;white-space:nowrap;">{r['date']}</td>
      <td style="padding:7px 10px;font-size:.72rem;color:#1e3a5f;">{r.get('sig','')}</td>
    </tr>"""
            row_num+=1

    # ---- AI blocks -------------------------------------------
    fun_raw=secs.get("AI FUN FACT","").strip()
    learn_raw=secs.get("AI LEARNING","").strip()
    if fun_raw:  fun_raw=re.sub(r"^[-•*]\s*","",fun_raw.splitlines()[0].strip())
    else:        fun_raw="Mohnish Pabrai paid $650,100 with Guy Spier to lunch with Buffett in 2007 -- his best investment ever."
    if learn_raw: learn_raw=re.sub(r"^[-•*]\s*","",learn_raw.splitlines()[0].strip())
    else:         learn_raw="RAG (Retrieval Augmented Generation): AI combines a knowledge base with language generation -- the same approach powering this dashboard."

    # ---- Hidden market-context div (Chrome extension) --------
    fred_plain="\n".join([f"  {r['label']}: {r['current']} (3mo:{r['mo3']} 12mo:{r['mo12']} trend:{r['trend']}) -- {r['insight']}" for r in fred_data])
    mctx=f"""MARKETPULSE AI MACRO CONTEXT - {today} {now} MT
=== MACRO REGIME SCORE: {regime_score}/100 -- {regime_lbl} ===

=== MARKET PERFORMANCE ===
               Change        Price        Signal
S&P 500        {spx_chg:<14}{spx_val:<13}{spx_lbl}
Russell 2000   {rut_chg:<14}{rut_val:<13}{rut_lbl}
VIX            {'--':<14}{vix_val:<13}{vix_lbl}

=== SENTIMENT ===
Fear & Greed: {fg_score}/100 ({fg_lbl}) -- {fg_sig}
  History: 1wk={fg_data.get('prev_week','N/A')} 1mo={fg_data.get('prev_month','N/A')} 1yr={fg_data.get('prev_year','N/A')}
Consumer Sentiment: {umich_val}/100 -- {umich_sig}
  History: 3mo={umich_mo3} 12mo={umich_mo12}

=== BRIEFING ===
MARKET AND MACRO:
{secs.get('MARKET AND MACRO','').strip()}

EARNINGS AND EVENTS:
{secs.get('EARNINGS AND EVENTS','').strip()}

WHAT TO WATCH:
{secs.get('WHAT TO WATCH','').strip()}

=== FRED MACRO INDICATORS ===
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

<!-- AI BLOCKS: Fun Fact + AI Learning -->
<div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-bottom:12px;">
  <div style="background:linear-gradient(135deg,#1e3a5f,#1a56db);color:white;border-radius:10px;padding:11px 16px;display:flex;align-items:center;gap:12px;">
    <div style="font-size:1.4rem;flex-shrink:0;">🤖</div>
    <div>
      <div style="font-size:.56rem;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;opacity:.6;margin-bottom:2px;">Fun Fact</div>
      <div style="font-size:.82rem;line-height:1.5;opacity:.92;">{fun_raw}</div>
    </div>
  </div>
  <div style="background:linear-gradient(135deg,#064e3b,#059669);color:white;border-radius:10px;padding:11px 16px;display:flex;align-items:center;gap:12px;">
    <div style="font-size:1.4rem;flex-shrink:0;">🧠</div>
    <div>
      <div style="font-size:.56rem;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;opacity:.6;margin-bottom:2px;">AI Learning</div>
      <div style="font-size:.82rem;line-height:1.5;opacity:.92;">{learn_raw}</div>
    </div>
  </div>
</div>

<!-- MACRO REGIME SCORE -->
<div class="card" style="margin-bottom:12px;border-left:4px solid {regime_col};">
  <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;">
    <div style="flex-shrink:0;">
      <div style="font-size:.6rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--muted);margin-bottom:3px;">Macro Regime Score</div>
      <div style="font-size:2rem;font-weight:800;color:{regime_col};line-height:1;">{regime_score}<span style="font-size:.9rem;color:var(--muted);">/100</span></div>
    </div>
    <div style="flex-shrink:0;">
      <div style="font-size:.88rem;font-weight:700;color:{regime_col};">{regime_lbl}</div>
      <div style="margin-top:6px;background:#e5e7eb;border-radius:99px;height:8px;width:200px;overflow:hidden;">
        <div style="width:{regime_pct}%;background:{regime_col};height:100%;border-radius:99px;"></div>
      </div>
    </div>
    <div style="font-size:.67rem;color:var(--muted);flex:1;min-width:200px;">
      {regime_breakdown_html}
    </div>
  </div>
  <div style="margin-top:8px;font-size:.68rem;color:#6b7280;background:#f9fafb;border-radius:5px;padding:5px 10px;">
    💡 Interpreting mixed signals: Consumer Sentiment BEARISH + Fear&Greed CAUTIOUS + VIX BULLISH = 
    classic mean reversion setup. People worried but not panic-selling = beaten-down value stocks 
    exist without forced selling. Score synthesizes all signals into one number for quick context.
  </div>
</div>

<!-- ROW 1: Market Performance | Sentiment + Analysis -->
<div class="grid-2">

  <!-- LEFT: Market Performance + Sentiment combined -->
  <div style="display:flex;flex-direction:column;gap:12px;">

    <div class="card ar">
      <h2>📈 Market Performance</h2>
      {'<div style="background:#fef9c3;border-radius:5px;padding:4px 8px;margin-bottom:7px;font-size:.7rem;color:#92400e;">⏰ Markets closed · last close shown</div>' if mkt_closed else ''}
      <table class="tbl">
        <thead><tr>
          <th>Index</th><th>Price</th><th>Change</th><th>Prev Close</th><th>Signal</th>
        </tr></thead>
        <tbody>{perf_rows}</tbody>
      </table>
    </div>

    <div class="card aa">
      <h2>🌡️ Market Sentiment</h2>
      <table class="tbl">
        <thead><tr>
          <th>Indicator</th><th>Current</th><th>History</th><th>Signal</th><th>What it means</th>
        </tr></thead>
        <tbody>{sent_rows}</tbody>
      </table>
    </div>

  </div>

  <!-- RIGHT: Analysis sections stacked -->
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
        <span style="font-weight:400;color:var(--muted);font-size:.55rem;">&nbsp;Mean reversion · Pabrai/Greenblatt/Munger</span>
      </h2>
      <ul>{fmt_bullets(secs.get("WHAT TO WATCH",""))}</ul>
    </div>
  </div>

</div>

<!-- ROW 2: FRED Macro Indicators (grouped) -->
<div style="margin-top:12px;">
  <div class="card">
    <h2>🏦 Macro Indicators
      <span style="font-weight:400;color:var(--muted);font-size:.55rem;">
        &nbsp; FRED API · grouped by category · Today's Signal at right
      </span>
    </h2>
    <div style="overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:.78rem;">
        <thead>
          <tr style="background:#f9fafb;">
            <th style="padding:6px 8px;text-align:center;font-size:.57rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">#</th>
            <th style="padding:6px 10px;text-align:left;font-size:.57rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);min-width:150px;">Indicator</th>
            <th style="padding:6px 10px;text-align:center;font-size:.57rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">Current</th>
            <th style="padding:6px 10px;text-align:center;font-size:.57rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">3 Mo</th>
            <th style="padding:6px 10px;text-align:center;font-size:.57rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">12 Mo</th>
            <th style="padding:6px 10px;text-align:center;font-size:.57rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">Trend</th>
            <th style="padding:6px 8px;font-size:.57rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">As Of</th>
            <th style="padding:6px 10px;font-size:.57rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);min-width:180px;">Today's Signal</th>
          </tr>
        </thead>
        <tbody>{fred_rows}</tbody>
      </table>
    </div>
    <div style="margin-top:8px;font-size:.62rem;color:#9ca3af;border-top:1px solid #f3f4f6;padding-top:6px;">
      📊 Market Breadth ($SPXA200R) not available via free API.
      <a href="https://stockcharts.com/h-sc/ui?s=%24SPXA200R" target="_blank" style="color:#1a56db;">Check StockCharts manually</a> ·
      Below 25% = deeply oversold (mean reversion buy signal) · Above 75% = be selective.
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

    fred_data         = fetch_fred_data()
    fg_data           = fetch_fear_greed()
    mkt_data          = fetch_market_indicators()
    regime            = compute_regime_score(fred_data, fg_data, mkt_data)
    ej_text           = scrape_edward_jones()
    cnbc_text         = fetch_cnbc_email()
    yahoo_text        = fetch_yahoo_morning_brief()
    mcoscillator_text = fetch_mcoscillator_email()

    briefing = synthesize_with_gemini(
        ej_text, cnbc_text, yahoo_text, mcoscillator_text,
        fred_data, fg_data, mkt_data, regime
    )

    build_html(
        briefing, ej_text, cnbc_text, yahoo_text, mcoscillator_text,
        fred_data, fg_data, mkt_data, regime
    )

    print("\n📧 Email disabled -- dashboard is primary output")
    print("\n"+"="*50)
    print("✅ MarketPulse AI Complete!")
    print("🌐 https://anil2040.github.io/market-pulse-ai")
    print("="*50)