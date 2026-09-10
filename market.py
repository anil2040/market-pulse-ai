# ============================================================
# market.py -- Market data, PE config, MHS, ERP
# Mean Reversion Macro Insights
# ============================================================
#
# PUBLIC FUNCTIONS (called by main.py):
#   fetch_market_indicators() -> dict
#   compute_mhs(fred_data, fg_data, mkt_data) -> dict
#   compute_erp(fred_data, cape_val_str) -> (erp, cape_yield, ten_y) | (None,None,None)
#
# WHAT THIS COVERS:
#   - SPX, RUT, VIX via Yahoo Finance v8/chart
#   - ETF PE ratios via PE_CONFIG (hardcoded quarterly -- see note below)
#   - MHS (Macro Heat Score) 0-100 composite
#     Scale: 0-33 DEPLOY | 34-65 SELECTIVE | 66-89 OVERHEATED | 90-100 EXTREME OVERHEATED
#   - Equity Risk Premium = (1/CAPE)*100 - 10Y yield
#
# ETF PE NOTE (Sep 2026):
#   All automated PE sources are broken or blocked from GitHub Actions:
#     Yahoo v8/v10: broken server-side for ETFs since mid-2026
#     yfinance:     same Yahoo backend, same issue
#     etf.com / etfdb.com / iShares API: Cloudflare CDN blocks GH Actions
#   Update PE_CONFIG manually each quarter from iShares.com product pages:
#     URTH: https://www.ishares.com/us/products/239696 (Fund Characteristics > P/E Ratio)
#     EFA:  https://www.ishares.com/us/products/239727 (Fund Characteristics > P/E Ratio)
#   Then bump PE_LAST_UPDATED to today's date.
#   Run debug_etf_pe.py each quarter to confirm no sources have recovered.
#   Dashboard shows an amber warning if PE_LAST_UPDATED is more than 90 days ago.
# ============================================================

import os
import re
import concurrent.futures
from datetime import date
import requests

# ============================================================
# ETF PE CONFIG -- update quarterly
# ============================================================
PE_LAST_UPDATED = date(2026, 9, 7)   # <-- UPDATE THIS each quarter

PE_CONFIG = {
    "URTH": {"pe": 23.0, "label": "iShares MSCI World ETF"},
    "EFA":  {"pe": 14.0, "label": "iShares MSCI EAFE ETF"},
}


# ============================================================
# CLASSIFICATION HELPERS
# ============================================================

def _classify_vix(v):
    if v < 15: return "CALM",     "#059669"
    if v < 20: return "NORMAL",   "#6b7280"
    if v < 25: return "CAUTIOUS", "#e97316"
    if v < 30: return "FEARFUL",  "#c81e1e"
    return "PANIC", "#7f1d1d"


def _classify_idx(c):
    if c >  1.0: return "RALLY",   "#059669"
    if c >  0.1: return "UP",      "#86c440"
    if c > -0.1: return "FLAT",    "#6b7280"
    if c > -1.0: return "DOWN",    "#e97316"
    return "SELLOFF", "#c81e1e"


def _vix_sig(v):
    if v >= 30: return "⚠️ Panic -- forced selling, mean reversion entries emerging"
    if v >= 25: return "⚠️ Elevated fear -- watch for entry points"
    if v >= 20: return "→ Slightly elevated -- no broad panic signal"
    if v >= 15: return "→ Normal -- market calm, no stress signal"
    return "✅ Calm · low fear · complacency = less opportunity for value investors"


# ============================================================
# YAHOO FINANCE FETCHERS
# ============================================================

def _yq(ticker):
    """Fetch price, prev close, % change, market state from Yahoo Finance v8."""
    url  = f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?interval=1d&range=2d"
    hdrs = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "application/json",
    }
    resp = requests.get(url, headers=hdrs, timeout=12)
    meta = resp.json()["chart"]["result"][0]["meta"]
    p    = float(meta.get("regularMarketPrice", 0))
    pv   = float(meta.get("previousClose", p))
    chg  = ((p - pv) / pv * 100) if pv else 0
    return p, pv, chg, meta.get("marketState", "UNKNOWN")


def _yq_pe(ticker):
    """
    Return (pe_float, is_stale_bool) for URTH and EFA.
    Uses PE_CONFIG -- all automated sources broken/blocked (see module header).
    is_stale = True when PE_LAST_UPDATED is more than 90 days ago.
    """
    cfg = PE_CONFIG.get(ticker)
    if not cfg:
        return None, False
    days_stale = (date.today() - PE_LAST_UPDATED).days
    return cfg["pe"], (days_stale > 90)


# ============================================================
# MARKET INDICATORS
# ============================================================

def fetch_market_indicators():
    """
    Fetch SPX, RUT, VIX in parallel via Yahoo Finance v8.
    PE ratios come from PE_CONFIG (no network call).
    Returns a dict consumed by compute_mhs() and build_html().
    """
    print("\n📊 Fetching Market Performance (SPX, RUT, VIX, URTH PE, EFA PE)...")

    res = {
        "vix":   {"value": "N/A", "label": "N/A", "color": "#6b7280", "signal": "", "prev": "N/A"},
        "spx":   {"value": "N/A", "chg": "N/A", "label": "N/A", "color": "#6b7280", "prev": "N/A"},
        "rut":   {"value": "N/A", "chg": "N/A", "label": "N/A", "color": "#6b7280", "prev": "N/A"},
        "urth_pe": None, "urth_pe_stale": False,
        "efa_pe":  None, "efa_pe_stale":  False,
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

        urth_pe, urth_stale = _yq_pe("URTH")
        efa_pe,  efa_stale  = _yq_pe("EFA")

        res["urth_pe"]       = urth_pe
        res["urth_pe_stale"] = urth_stale
        res["efa_pe"]        = efa_pe
        res["efa_pe_stale"]  = efa_stale

        state_map    = {"REGULAR": "OPEN", "PRE": "PRE", "POST": "POST", "CLOSED": "CLOSED"}
        mkt_state    = state_map.get(ss, "OPEN" if abs(sc) > 0.005 else "CLOSED")
        status_label = {"OPEN": "", "PRE": "Pre-Market",
                        "POST": "After-Hours", "CLOSED": "Last Close"}.get(mkt_state, "")
        res["market_state"]        = mkt_state
        res["market_status_label"] = status_label

        vl, vc = _classify_vix(vp)
        sl, sc2 = _classify_idx(sc)
        rl, rc2 = _classify_idx(rc)

        if mkt_state == "PRE":
            scs = "Pre-Market"; rcs = "Pre-Market"
            sl = "PRE-MKT";  sc2 = "#6366f1"
            rl = "PRE-MKT";  rc2 = "#6366f1"
        elif mkt_state in ("POST", "CLOSED"):
            scs = "Last Close"; rcs = "Last Close"
            sl = "CLOSED"; sc2 = "#9ca3af"
            rl = "CLOSED"; rc2 = "#9ca3af"
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
            res["pulse"] = f"S&P {sp:,.0f} · Russell {rp:,.0f} · VIX {vp:.1f} ({vl})"

        stale_w  = " STALE >90d -- UPDATE" if urth_stale else ""
        urth_str = f"URTH PE: {urth_pe:.1f}x{stale_w}" if urth_pe else "URTH PE: N/A"
        stale_w  = " STALE >90d -- UPDATE" if efa_stale else ""
        efa_str  = f"EFA PE: {efa_pe:.1f}x{stale_w}"   if efa_pe  else "EFA PE: N/A"

        print(f"   ✅ S&P 500: {sp:,.0f} ({scs} {sl})")
        print(f"   ✅ Russell: {rp:,.0f} ({rcs} {rl})")
        print(f"   ✅ VIX: {vp:.2f} ({vl}) | State: {mkt_state}")
        print(f"   ✅ {urth_str} | {efa_str}")

    except Exception as e:
        print(f"   ❌ Market indicators failed: {e}")
        res["pulse"] = "Market data unavailable."

    return res


# ============================================================
# MACRO HEAT SCORE
# ============================================================

def compute_mhs(fred_data, fg_data, mkt_data):
    """
    Compute Macro Heat Score (0-100 inverted -- higher = more overheated).
    No aaii_data parameter -- AAII removed (Incapsula CDN blocks GH Actions).

    Scale:
      0-33:  DEPLOY          (panic/dislocation, deploy aggressively)
      34-65: SELECTIVE        (best setups only, Left Leg <4, MoS >25%)
      66-89: OVERHEATED       (build cash, trim winners)
      90-100: EXTREME OVERHEATED (no new positions, aggressive cash build)
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

    # Core PCE (-10 to +20, with trend modifier +/-5)
    cp, cpt = get_fred("Core PCE")
    if cp is not None:
        if   cp > 3.5: adj = +15; note = f"Core PCE {cp:.1f}% -- well above 2% target"
        elif cp > 3.0: adj = +10; note = f"Core PCE {cp:.1f}% -- above 2% target"
        elif cp > 2.5: adj = +5;  note = f"Core PCE {cp:.1f}% -- mildly elevated"
        elif cp > 2.0: adj = +2;  note = f"Core PCE {cp:.1f}% -- near target"
        else:          adj = -5;  note = f"Core PCE {cp:.1f}% -- at/below 2% target"
        if   cpt == "▲": adj += 5; note += " & rising"
        elif cpt == "▼": adj -= 5; note += " & cooling"
        raw += adj; breakdown.append(f"Inflation {adj:+d} ({note})")

    # VIX (-20 to +10)
    try:
        vix = float(mkt_data["vix"]["value"])
        if   vix >= 40: adj = -20; note = f"VIX {vix:.1f} -- panic/forced selling"
        elif vix >= 30: adj = -15; note = f"VIX {vix:.1f} -- fear"
        elif vix >= 25: adj = -8;  note = f"VIX {vix:.1f} -- cautious"
        elif vix >= 20: adj = -3;  note = f"VIX {vix:.1f} -- slightly elevated"
        elif vix >= 15: adj = +5;  note = f"VIX {vix:.1f} -- calm/normal"
        else:           adj = +10; note = f"VIX {vix:.1f} -- complacent"
        raw += adj; breakdown.append(f"VIX {adj:+d} ({note})")
    except Exception:
        pass

    # Fear & Greed (-20 to +20)
    try:
        fg = int(fg_data.get("score", 50))
        if   fg <= 20: adj = -20; note = f"F&G {fg} -- extreme fear"
        elif fg <= 35: adj = -12; note = f"F&G {fg} -- fear"
        elif fg <= 50: adj = -4;  note = f"F&G {fg} -- mild fear"
        elif fg <= 65: adj = +4;  note = f"F&G {fg} -- neutral/mild greed"
        elif fg <= 80: adj = +12; note = f"F&G {fg} -- greed"
        else:          adj = +20; note = f"F&G {fg} -- extreme greed"
        raw += adj; breakdown.append(f"Fear&Greed {adj:+d} ({note})")
    except Exception:
        pass

    # HY Credit Spread (-15 to +12)
    hy, _ = get_fred("HY Credit Spread")
    if hy is not None:
        if   hy >= 8.0: adj = -15; note = f"HY {hy:.2f}% -- very wide (credit stress)"
        elif hy >= 6.0: adj = -10; note = f"HY {hy:.2f}% -- wide"
        elif hy >= 4.5: adj = -4;  note = f"HY {hy:.2f}% -- elevated"
        elif hy <= 2.5: adj = +12; note = f"HY {hy:.2f}% -- very tight (complacent)"
        elif hy <= 3.5: adj = +6;  note = f"HY {hy:.2f}% -- tight"
        else:           adj = +2;  note = f"HY {hy:.2f}% -- normal"
        raw += adj; breakdown.append(f"Credit {adj:+d} ({note})")

    # Yield Curve (-8 to +4)
    cv, _ = get_fred("Yield Curve (10Y-2Y)")
    if cv is not None:
        if   cv < -0.5: adj = -8; note = f"Deeply inverted {cv:.2f}%"
        elif cv < 0.0:  adj = -4; note = f"Inverted {cv:.2f}%"
        elif cv < 0.3:  adj = +2; note = f"Nearly flat {cv:.2f}%"
        elif cv >= 0.5: adj = +4; note = f"Steep {cv:.2f}%"
        else:           adj = +2; note = f"Positive {cv:.2f}%"
        raw += adj; breakdown.append(f"YieldCurve {adj:+d} ({note})")

    # Fed Posture (-6 to +8)
    fed, fedt = get_fred("Fed Funds Rate")
    if fed is not None:
        if   fedt == "▼": adj = -6; note = f"Fed cutting at {fed:.2f}%"
        elif fedt == "▲": adj = +8; note = f"Fed hiking at {fed:.2f}%"
        elif fed >= 5.0:  adj = +6; note = f"Fed restrictive {fed:.2f}%"
        elif fed <= 3.0:  adj = -4; note = f"Fed accommodative {fed:.2f}%"
        else:             adj = +2; note = f"Fed on hold {fed:.2f}%"
        raw += adj; breakdown.append(f"Fed {adj:+d} ({note})")

    # Shiller CAPE (-15 to +15)
    cape, _ = get_fred("Shiller CAPE (US)")
    if cape is not None:
        if   cape >= 40: adj = +15; note = f"CAPE {cape:.1f}x -- extreme (98th pctile, only dot-com was higher)"
        elif cape >= 35: adj = +12; note = f"CAPE {cape:.1f}x -- very high (>2x hist avg 17x)"
        elif cape >= 30: adj = +8;  note = f"CAPE {cape:.1f}x -- elevated"
        elif cape >= 25: adj = +5;  note = f"CAPE {cape:.1f}x -- moderately high"
        elif cape >= 20: adj = 0;   note = f"CAPE {cape:.1f}x -- fair value range"
        elif cape >= 15: adj = -5;  note = f"CAPE {cape:.1f}x -- below avg (opportunity)"
        else:            adj = -15; note = f"CAPE {cape:.1f}x -- deep value territory"
        raw += adj; breakdown.append(f"CAPE Valuation {adj:+d} ({note})")

    # Gold Signal (-3 to +3)
    gold, gold_trend = get_fred("Gold Price")
    try:
        vix_now = float(mkt_data["vix"]["value"])
        if gold is not None and gold_trend == "▲" and vix_now < 20:
            adj = +3; note = "Gold rising with low VIX -- stealth fear/inflation signal"
            raw += adj; breakdown.append(f"Gold Signal {adj:+d} ({note})")
        elif gold is not None and gold_trend == "▼" and vix_now >= 25:
            adj = -3; note = "Gold falling with high VIX -- fear already priced in"
            raw += adj; breakdown.append(f"Gold Signal {adj:+d} ({note})")
    except Exception:
        pass

    score = max(0, min(100, round(raw)))

    # EXTREME OVERHEATED tier at 90+ (darker red, stricter posture)
    if score >= 90:
        lbl    = "🚨 EXTREME OVERHEATED"
        col    = "#7f1d1d"
        action = (
            "EXTREME OVERHEATED (90+): No new positions. Aggressively build cash. "
            "Trim winners to 50% of target size. "
            "Only hold existing names with MoS >35% and Left Leg 0."
        )
    elif score >= 66:
        lbl    = "⛔ OVERHEATED"
        col    = "#c81e1e"
        action = (
            "Build cash. Trim winners. No new positions unless "
            "Left Leg 0-2 + MoS >30% + extraordinary setup."
        )
    elif score >= 34:
        lbl    = "🟠 SELECTIVE"
        col    = "#b45309"
        action = "Best setups only. Left Leg <4, MoS >25%. Measured pace. Keep 25%+ cash."
    else:
        lbl    = "🟢 DEPLOY"
        col    = "#057a55"
        action = "Aggressive deployment. Macro confirms STRONG BUY. Full position pace."

    print(f"\n📊 MHS (Macro Heat Score): {score}/100 ({lbl})")
    for b in breakdown:
        print(f"   {b}")

    return {"score": score, "label": lbl, "color": col,
            "breakdown": breakdown, "action": action}


# ============================================================
# EQUITY RISK PREMIUM
# ============================================================

def compute_erp(fred_data, cape_val_str):
    """
    Equity Risk Premium = (1/CAPE)*100 - 10Y Treasury yield (both as %).
    Negative ERP = bonds yield more than stocks. Last negative reading: ~2002.
    At Sep 2026: CAPE 41.4x -> yield 2.42%, 10Y 4.68% -> ERP = -2.26%.

    Returns (erp_pct, cape_yield_pct, ten_y_pct) or (None, None, None).
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

    erp = round(cape_yield - ten_y, 2)
    return erp, cape_yield, ten_y
