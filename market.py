# ============================================================
# market.py -- Market data, PE config, Macro Heat Score, ERP
# Mean Reversion Macro Insights
# ============================================================
#
# PUBLIC FUNCTIONS (called by main.py):
#   fetch_market_indicators() -> dict
#   compute_mhs(fred_data, fg_data, mkt_data) -> dict
#   compute_erp(fred_data, cape_val_str) -> (erp, cape_yield, ten_y) | (None,None,None)
#
# ETF PE SOURCING -- PE_CONFIG only (quarterly manual update):
#   Yahoo Finance HTML scrape: blocked -- PE renders via JavaScript, not in raw HTML
#   Yahoo Finance v10 API: blocked -- requires browser session crumb, returns 401
#   iShares CSV: dead as of Sep 2026 -- returns full HTML page, not CSV data
#   Solution: update PE_CONFIG manually each quarter from your browser:
#     finance.yahoo.com/quote/URTH  (look for PE Ratio TTM in the summary table)
#     finance.yahoo.com/quote/EFA   (same)
#
# Macro Heat Score scale (updated Sep 2026):
#   0-33:   DEPLOY           -- panic/dislocation, deploy aggressively
#   34-65:  SELECTIVE        -- best setups only, Left Leg <4, MoS >25%
#   66-85:  OVERHEATED       -- build cash, trim winners
#   86-100: EXTREME OVERHEATED -- most stretched since dot-com, quality and patience only
# ============================================================

import re
import concurrent.futures
from datetime import date
import requests

# ============================================================
# ETF PE CONFIG -- update manually each quarter
# ============================================================
# Check: finance.yahoo.com/quote/URTH and finance.yahoo.com/quote/EFA
# Look for "PE Ratio (TTM)" in the summary stats table on the page.
# Last updated: Sep 10 2026 from Yahoo Finance browser (confirmed live values)

PE_LAST_UPDATED = date(2026, 9, 10)
PE_CONFIG = {
    "URTH": {"pe": 22.57, "label": "iShares MSCI World ETF"},
    "EFA":  {"pe": 18.35, "label": "iShares MSCI EAFE ETF"},
}

# ============================================================
# CLASSIFICATION HELPERS
# ============================================================

def _classify_vix(v):
    if v < 15: return "CALM",     "#059669"
    if v < 20: return "NORMAL",   "#6b7280"
    if v < 25: return "CAUTIOUS", "#e97316"
    if v < 30: return "FEARFUL",  "#c81e1e"
    return      "PANIC",          "#7f1d1d"

def _classify_idx(c):
    if c >  1.0: return "RALLY",   "#059669"
    if c >  0.1: return "UP",      "#86c440"
    if c > -0.1: return "FLAT",    "#6b7280"
    if c > -1.0: return "DOWN",    "#e97316"
    return        "SELLOFF",       "#c81e1e"

def _vix_sig(v):
    if v >= 30: return "Panic -- forced selling, mean reversion entries emerging"
    if v >= 25: return "Elevated fear -- watch for entry points"
    if v >= 20: return "Slightly elevated -- no broad panic signal"
    if v >= 15: return "Normal -- market calm, no stress signal"
    return             "Calm -- low fear -- complacency = less opportunity for value investors"

# ============================================================
# YAHOO FINANCE PRICE FETCHER (SPX, RUT, VIX only -- not PE)
# ============================================================

def _yq(ticker):
    """Fetch price, prev close, pct change, market state from Yahoo Finance v8."""
    url  = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2d"
    hdrs = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept":     "application/json",
    }
    resp = requests.get(url, headers=hdrs, timeout=12)
    meta = resp.json()["chart"]["result"][0]["meta"]
    p    = float(meta.get("regularMarketPrice", 0))
    pv   = float(meta.get("previousClose", p))
    chg  = ((p - pv) / pv * 100) if pv else 0
    return p, pv, chg, meta.get("marketState", "UNKNOWN")

# ============================================================
# MARKET INDICATORS
# ============================================================

def fetch_market_indicators():
    """
    Fetch S&P 500, Russell 2000, VIX from Yahoo Finance v8 in parallel.
    ETF PE (URTH, EFA): always uses PE_CONFIG -- live fetch is permanently blocked
    from GitHub Actions (Yahoo requires browser session for PE data).
    """
    print("\n📊 Fetching Market Performance (S&P 500, Russell 2000, VIX)...")

    res = {
        "vix":    {"value": "N/A", "label": "N/A", "color": "#6b7280", "signal": "", "prev": "N/A"},
        "spx":    {"value": "N/A", "chg":   "N/A", "label": "N/A", "color": "#6b7280", "prev": "N/A"},
        "rut":    {"value": "N/A", "chg":   "N/A", "label": "N/A", "color": "#6b7280", "prev": "N/A"},
        "urth_pe": None, "urth_pe_stale": False, "urth_pe_source": "",
        "efa_pe":  None, "efa_pe_stale":  False, "efa_pe_source":  "",
        "market_state": "UNKNOWN", "market_status_label": "", "pulse": "",
    }

    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as ex:
            fv = ex.submit(_yq, "%5EVIX")
            fs = ex.submit(_yq, "%5EGSPC")
            fr = ex.submit(_yq, "%5ERUT")
            vp, vpr, _,  vs = fv.result(timeout=15)
            sp, spr, sc, ss = fs.result(timeout=15)
            rp, rpr, rc, rs = fr.result(timeout=15)

        # PE_CONFIG -- permanent fallback, quarterly manual update
        days_stale = (date.today() - PE_LAST_UPDATED).days
        is_stale   = days_stale > 90
        pe_src     = f"PE_CONFIG ({PE_LAST_UPDATED})"

        res["urth_pe"]        = PE_CONFIG["URTH"]["pe"]
        res["urth_pe_stale"]  = is_stale
        res["urth_pe_source"] = pe_src
        res["efa_pe"]         = PE_CONFIG["EFA"]["pe"]
        res["efa_pe_stale"]   = is_stale
        res["efa_pe_source"]  = pe_src

        state_map    = {"REGULAR": "OPEN", "PRE": "PRE", "POST": "POST", "CLOSED": "CLOSED"}
        mkt_state    = state_map.get(vs, "OPEN" if abs(sc) > 0.005 else "CLOSED")
        status_label = {"OPEN": "", "PRE": "Pre-Market",
                        "POST": "After-Hours", "CLOSED": "Last Close"}.get(mkt_state, "")

        res["market_state"]        = mkt_state
        res["market_status_label"] = status_label

        vl, vc  = _classify_vix(vp)
        sl, sc2 = _classify_idx(sc)
        rl, rc2 = _classify_idx(rc)

        if mkt_state == "PRE":
            scs = "Pre-Market"; rcs = "Pre-Market"
            sl  = "PRE-MKT";    sc2 = "#6366f1"
            rl  = "PRE-MKT";    rc2 = "#6366f1"
        else:
            scs = f"{sc:+.2f}%"
            rcs = f"{rc:+.2f}%"

        res["vix"] = {"value": f"{vp:.2f}", "label": vl, "color": vc,
                      "signal": _vix_sig(vp), "prev": f"{vpr:.2f}"}
        res["spx"] = {"value": f"{sp:,.0f}", "chg": scs,
                      "label": sl, "color": sc2, "prev": f"{spr:,.0f}"}
        res["rut"] = {"value": f"{rp:,.0f}", "chg": rcs,
                      "label": rl, "color": rc2, "prev": f"{rpr:,.0f}"}

        if mkt_state == "OPEN":
            if vp >= 30 or sl == "SELLOFF":
                tone = "broad stress -- mean reversion entries emerging"
            elif sl in ("UP", "RALLY") and rl in ("UP", "RALLY"):
                tone = "broad strength -- be selective"
            elif sl == "FLAT":
                tone = "indecisive -- focus on individual catalysts"
            else:
                tone = "mixed -- stay selective"
            res["pulse"] = (f"S&P {scs} ({sl}) · Russell {rcs} ({rl}) "
                            f"· VIX {vp:.1f} ({vl}) -- {tone}")
        elif mkt_state == "PRE":
            res["pulse"] = (f"Pre-Market · S&P last close {sp:,.0f} "
                            f"· Russell {rp:,.0f} · VIX {vp:.1f} ({vl})")
        else:
            res["pulse"] = (f"S&P {sp:,.0f} ({scs}) · Russell {rp:,.0f} ({rcs}) "
                            f"· VIX {vp:.1f} ({vl})")

        print(f"  ✅ S&P 500: {sp:,.0f} ({scs} {sl})")
        print(f"  ✅ Russell 2000: {rp:,.0f} ({rcs} {rl})")
        print(f"  ✅ VIX: {vp:.2f} ({vl}) | State: {mkt_state}")
        print(f"  ✅ URTH PE: {res['urth_pe']}x | EFA PE: {res['efa_pe']}x "
              f"| Source: {pe_src} | Days since update: {days_stale}")
        if is_stale:
            print(f"  ⚠️ PE data is {days_stale} days old -- update PE_CONFIG in market.py")

    except Exception as e:
        print(f"  ❌ Market indicators failed: {e}")
        res["pulse"] = "Market data unavailable."

    return res

# ============================================================
# MACRO HEAT SCORE
# ============================================================

def compute_mhs(fred_data, fg_data, mkt_data):
    """
    Compute Macro Heat Score (0-100, higher = more overheated).
    Inverted scale: lower score = better mean reversion opportunity.

    Scale (updated Sep 2026):
      0-33:   DEPLOY           -- panic and dislocation, deploy aggressively
      34-65:  SELECTIVE        -- best setups only
      66-85:  OVERHEATED       -- build cash, trim winners
      86-100: EXTREME OVERHEATED -- most stretched since dot-com

    Note: AAII sentiment removed -- aaii.com blocks GitHub Actions via Incapsula CDN.
    """
    raw       = 50
    breakdown = []

    def get_fred(lbl):
        r = next((x for x in fred_data if x["label"] == lbl), None)
        if not r or r["current"] == "N/A":
            return None, None
        try:
            return float(re.sub(r"[%$,]", "", r["current"])), r["trend"]
        except Exception:
            return None, None

    # Core PCE inflation
    cp, cpt = get_fred("Core PCE")
    if cp is not None:
        if   cp > 3.5: adj = +15; note = f"Core PCE {cp:.1f}% -- well above 2% target"
        elif cp > 3.0: adj = +10; note = f"Core PCE {cp:.1f}% -- above 2% target"
        elif cp > 2.5: adj =  +5; note = f"Core PCE {cp:.1f}% -- mildly elevated"
        elif cp > 2.0: adj =  +2; note = f"Core PCE {cp:.1f}% -- near target"
        else:          adj =  -5; note = f"Core PCE {cp:.1f}% -- at or below 2% target"
        if cpt == "▲": adj += 5; note += " and rising"
        elif cpt == "▼": adj -= 5; note += " and cooling"
        raw += adj; breakdown.append(f"Inflation {adj:+d} ({note})")

    # VIX fear index
    try:
        vix = float(mkt_data["vix"]["value"])
        if   vix >= 40: adj = -20; note = f"VIX {vix:.1f} -- panic and forced selling"
        elif vix >= 30: adj = -15; note = f"VIX {vix:.1f} -- fear"
        elif vix >= 25: adj =  -8; note = f"VIX {vix:.1f} -- cautious"
        elif vix >= 20: adj =  -3; note = f"VIX {vix:.1f} -- slightly elevated"
        elif vix >= 15: adj =  +5; note = f"VIX {vix:.1f} -- calm and normal"
        else:           adj = +10; note = f"VIX {vix:.1f} -- complacent"
        raw += adj; breakdown.append(f"VIX {adj:+d} ({note})")
    except Exception:
        pass

    # CNN Fear and Greed
    try:
        fg = int(fg_data.get("score", 50))
        if   fg <= 20: adj = -20; note = f"Fear and Greed {fg} -- extreme fear"
        elif fg <= 35: adj = -12; note = f"Fear and Greed {fg} -- fear"
        elif fg <= 50: adj =  -4; note = f"Fear and Greed {fg} -- mild fear"
        elif fg <= 65: adj =  +4; note = f"Fear and Greed {fg} -- neutral to mild greed"
        elif fg <= 80: adj = +12; note = f"Fear and Greed {fg} -- greed"
        else:          adj = +20; note = f"Fear and Greed {fg} -- extreme greed"
        raw += adj; breakdown.append(f"Fear&Greed {adj:+d} ({note})")
    except Exception:
        pass

    # High yield credit spread
    hy, _ = get_fred("HY Credit Spread")
    if hy is not None:
        if   hy >= 8.0: adj = -15; note = f"High yield spread {hy:.2f}% -- very wide, credit stress"
        elif hy >= 6.0: adj = -10; note = f"High yield spread {hy:.2f}% -- wide"
        elif hy >= 4.5: adj =  -4; note = f"High yield spread {hy:.2f}% -- elevated"
        elif hy <= 2.5: adj = +12; note = f"High yield spread {hy:.2f}% -- very tight, complacent"
        elif hy <= 3.5: adj =  +6; note = f"High yield spread {hy:.2f}% -- tight"
        else:           adj =  +2; note = f"High yield spread {hy:.2f}% -- normal"
        raw += adj; breakdown.append(f"Credit {adj:+d} ({note})")

    # Yield curve
    cv, _ = get_fred("Yield Curve (10Y-2Y)")
    if cv is not None:
        if   cv < -0.5: adj = -8; note = f"Deeply inverted {cv:.2f}%"
        elif cv <  0.0: adj = -4; note = f"Inverted {cv:.2f}%"
        elif cv <  0.3: adj = +2; note = f"Nearly flat {cv:.2f}%"
        elif cv >= 0.5: adj = +4; note = f"Steep {cv:.2f}%"
        else:           adj = +2; note = f"Positive {cv:.2f}%"
        raw += adj; breakdown.append(f"Yield Curve {adj:+d} ({note})")

    # Federal Reserve posture
    fed, fedt = get_fred("Fed Funds Rate")
    if fed is not None:
        if   fedt == "▼": adj = -6; note = f"Fed cutting at {fed:.2f}%"
        elif fedt == "▲": adj = +8; note = f"Fed hiking at {fed:.2f}%"
        elif fed >= 5.0:  adj = +6; note = f"Fed restrictive at {fed:.2f}%"
        elif fed <= 3.0:  adj = -4; note = f"Fed accommodative at {fed:.2f}%"
        else:             adj = +2; note = f"Fed on hold at {fed:.2f}%"
        raw += adj; breakdown.append(f"Fed {adj:+d} ({note})")

    # Shiller CAPE valuation
    cape, _ = get_fred("Shiller CAPE (US)")
    if cape is not None:
        if   cape >= 40: adj = +15; note = f"Shiller CAPE {cape:.1f}x -- extreme, 98th percentile"
        elif cape >= 35: adj = +12; note = f"Shiller CAPE {cape:.1f}x -- very high, over 2x historical average"
        elif cape >= 30: adj =  +8; note = f"Shiller CAPE {cape:.1f}x -- elevated"
        elif cape >= 25: adj =  +5; note = f"Shiller CAPE {cape:.1f}x -- moderately high"
        elif cape >= 20: adj =   0; note = f"Shiller CAPE {cape:.1f}x -- fair value range"
        elif cape >= 15: adj =  -5; note = f"Shiller CAPE {cape:.1f}x -- below average, opportunity"
        else:            adj = -15; note = f"Shiller CAPE {cape:.1f}x -- deep value territory"
        raw += adj; breakdown.append(f"Shiller CAPE {adj:+d} ({note})")

    # Gold signal
    gold, gold_trend = get_fred("Gold Price")
    try:
        vix_now = float(mkt_data["vix"]["value"])
        if gold is not None and gold_trend == "▲" and vix_now < 20:
            adj = +3; note = "Gold rising with low VIX -- stealth fear or inflation signal"
            raw += adj; breakdown.append(f"Gold Signal {adj:+d} ({note})")
        elif gold is not None and gold_trend == "▼" and vix_now >= 25:
            adj = -3; note = "Gold falling with high VIX -- fear already priced in"
            raw += adj; breakdown.append(f"Gold Signal {adj:+d} ({note})")
    except Exception:
        pass

    score = max(0, min(100, round(raw)))

    # Thresholds updated Sep 2026: Extreme starts at 86 (was 90)
    if score >= 86:
        lbl    = "EXTREME OVERHEATED"
        col    = "#7f1d1d"
        action = (
            "Macro is at its most stretched since dot-com. "
            "Only the highest-quality names at genuine margins of safety -- "
            "Left Leg 0-2, margin of safety above 30%, top-tier businesses only. "
            "Stay patient and disciplined. Not a signal to panic."
        )
    elif score >= 66:
        lbl    = "OVERHEATED"
        col    = "#c81e1e"
        action = (
            "Build cash. Trim winners. "
            "New positions only with Left Leg 0-2, margin of safety above 25%, "
            "and a clear catalyst."
        )
    elif score >= 34:
        lbl    = "SELECTIVE"
        col    = "#b45309"
        action = ("Best setups only. Left Leg below 4, margin of safety above 25%. "
                  "Measured pace. Keep 25% or more in cash.")
    else:
        lbl    = "DEPLOY"
        col    = "#057a55"
        action = "Aggressive deployment. Macro confirms strong buy. Full position pace."

    print(f"\n📊 Macro Heat Score: {score}/100 ({lbl})")
    for b in breakdown:
        print(f"  {b}")

    return {"score": score, "label": lbl, "color": col,
            "breakdown": breakdown, "action": action}

# ============================================================
# EQUITY RISK PREMIUM
# ============================================================

def compute_erp(fred_data, cape_val_str):
    """
    Equity Risk Premium = (1 / Shiller CAPE) * 100 - 10Y Treasury yield.
    Both expressed as percentages.
    Negative means bonds yield more than stocks -- last seen around 2002.
    """
    try:
        cape = float(re.sub(r"[^0-9.]", "", str(cape_val_str)))
        if cape <= 0:
            return None, None, None
        cape_yield = round((1 / cape) * 100, 2)
    except Exception:
        return None, None, None

    ten_y_row = next((r for r in fred_data if r["label"] == "10Y Treasury"), None)
    if not ten_y_row or ten_y_row["current"] == "N/A":
        return None, None, None
    try:
        ten_y = float(re.sub(r"[^0-9.]", "", str(ten_y_row["current"])))
    except Exception:
        return None, None, None

    return round(cape_yield - ten_y, 2), cape_yield, ten_y