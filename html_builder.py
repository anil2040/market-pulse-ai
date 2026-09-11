# ============================================================
# html_builder.py -- HTML dashboard builder
# Mean Reversion Macro Insights
# ============================================================
#
# PUBLIC FUNCTION (called by main.py):
#   build_html(briefing, ai_failed, ej_text, cnbc_text,
#              yahoo_text, mcoscillator_text,
#              fred_data, fg_data, mkt_data, mhs,
#              si_tickers, mf_tickers, am_tickers,
#              run_log, run_start, cache) -> None (writes index.html)
#
# CHANGES IN THIS VERSION:
#   - Market Performance: exact Chrome extension style
#     (SELLOFF/DOWN/FLAT/UP/RALLY bands, gradient bar, no "closed" language)
#   - Dir column REMOVED from FRED table (redundant with Trend sparkline)
#   - McClellan Breadth card REMOVED (email is a paid article teaser, no value)
#   - Cache badge: stale indicators show amber "cached [date]" pill
#   - MHS scale: EXTREME OVERHEATED threshold lowered to 86 (from 90)
#   - AI briefing: 2-column grid (Market & Macro + Earnings & Events)
#   - SI-only filter: >= 3 managers
# ============================================================

import re
import time
from datetime import datetime, timezone, timedelta

MT = timezone(timedelta(hours=-6))  # Boise MDT = UTC-6 summer

# ============================================================
# HELPERS
# ============================================================

def fmt_bullets(raw):
    if not raw or not raw.strip():
        return "<li>No data available</li>"
    items = ""
    for line in raw.strip().splitlines():
        line = re.sub(r"^[-•*]\s*", "", line.strip())
        line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
        if line:
            items += f"    <li>{line}</li>\n"
    return items or "<li>No data available</li>"


def _badge(raw_lbl, raw_col):
    m = {
        "RALLY": "BULLISH",  "UP": "BULLISH",   "CALM": "BULLISH",
        "Greed": "BULLISH",  "Extreme Greed": "BULLISH", "HIGH": "BULLISH",
        "FLAT": "NEUTRAL",   "NORMAL": "NEUTRAL", "Neutral": "NEUTRAL", "MID": "NEUTRAL",
        "DOWN": "CAUTIOUS",  "CAUTIOUS": "CAUTIOUS", "Fear": "CAUTIOUS",
        "SELLOFF": "BEARISH","FEARFUL": "BEARISH","PANIC": "BEARISH",
        "Extreme Fear": "BEARISH", "LOW": "BEARISH",
        "CLOSED": "CLOSED",  "PRE-MKT": "PRE-MKT", "Unavailable": "N/A",
    }
    c = {
        "BULLISH":  "#057a55", "NEUTRAL": "#6b7280", "CAUTIOUS": "#b45309",
        "BEARISH":  "#c81e1e", "CLOSED":  "#9ca3af", "PRE-MKT":  "#6366f1",
        "N/A":      "#9ca3af",
    }
    std = m.get(raw_lbl, raw_lbl)
    col = c.get(std, raw_col)
    return (f'<span style="background:{col};color:white;padding:2px 9px;'
            f'border-radius:4px;font-size:.68rem;font-weight:700;">{std}</span>')


def _sparkline_svg(cur_str, mo3_str, mo12_str):
    try:
        def parse(s): return float(re.sub(r"[^0-9.\-]", "", str(s)))
        v12 = parse(mo12_str); v3 = parse(mo3_str); v0 = parse(cur_str)
        mn  = min(v12, v3, v0); mx = max(v12, v3, v0)
        r   = mx - mn if mx != mn else 1
        def y(v, h=24): return round(h - (v - mn) / r * (h - 4) + 2, 1)
        pts      = f"0,{y(v12)} 20,{y(v3)} 40,{y(v0)}"
        line_col = "#c81e1e" if v0 > v12 else "#057a55"
        return (f'<svg width="42" height="28" viewBox="0 0 42 28" '
                f'style="display:inline-block;vertical-align:middle;">'
                f'<polyline points="{pts}" fill="none" stroke="{line_col}" '
                f'stroke-width="1.8" stroke-linejoin="round"/>'
                f'<circle cx="40" cy="{y(v0)}" r="2.5" fill="{line_col}"/></svg>')
    except Exception:
        return ""


def _cache_badge(cached_date):
    """Amber pill shown when a value came from cache, not a live fetch."""
    return (f'<span style="background:#b45309;color:white;padding:1px 6px;'
            f'border-radius:3px;font-size:.58rem;font-weight:700;margin-left:4px;">'
            f'cached {cached_date}</span>')

# ============================================================
# GAUGE-STYLE MARKET PERFORMANCE
# Matches the Chrome extension layout exactly:
#   SELLOFF  DOWN  FLAT  UP  RALLY
#   [=======o====================]  PILL
#   value  +chg%
# ============================================================

def _gauge_row(name, value_str, chg_str, signal_lbl, signal_col, note=""):
    """
    Renders a market index as a gauge card matching the Chrome extension.
    chg_str is the raw pct change string (e.g. "+0.58%" or "-1.04%").
    No "prev close" or "last close" language -- just the number and signal.
    """
    # Map signal to position 0-100 on the bar
    gauge_map = {"SELLOFF": 5, "DOWN": 25, "FLAT": 50, "UP": 75, "RALLY": 95,
                 "CLOSED": 50, "PRE-MKT": 50}
    pct = gauge_map.get(signal_lbl, 50)

    if   signal_lbl in ("RALLY", "UP"):     bar_col = "#057a55"
    elif signal_lbl in ("SELLOFF", "DOWN"): bar_col = "#c81e1e"
    elif signal_lbl == "FLAT":              bar_col = "#6b7280"
    else:                                   bar_col = "#9ca3af"

    pill = (f'<span style="background:{signal_col};color:white;padding:2px 10px;'
            f'border-radius:4px;font-size:.72rem;font-weight:800;letter-spacing:.5px;">'
            f'{signal_lbl}</span>')

    note_html = (f'<div style="font-size:.58rem;color:#9ca3af;margin-top:1px;">{note}</div>'
                 if note else "")

    # Band labels above the bar (matching Chrome extension)
    band_labels = (
        '<div style="display:flex;justify-content:space-between;'
        'font-size:.55rem;color:#9ca3af;margin-bottom:2px;">'
        '<span>SELLOFF</span><span>DOWN</span><span>FLAT</span>'
        '<span>UP</span><span>RALLY</span></div>'
    )

    return f"""
<div style="background:white;border:1px solid #e5e7eb;border-radius:8px;
            padding:10px 14px;margin-bottom:8px;">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:5px;">
    <div>
      <div style="font-weight:700;font-size:.88rem;color:#111928;">{name}</div>
      {note_html}
    </div>
    <div style="text-align:right;display:flex;align-items:center;gap:8px;">
      <span style="font-weight:800;font-size:1rem;color:#111928;">{value_str}</span>
      <span style="font-size:.78rem;color:{signal_col};font-weight:600;">{chg_str}</span>
      {pill}
    </div>
  </div>
  {band_labels}
  <div style="position:relative;margin-top:2px;">
    <div style="background:linear-gradient(to right,#c81e1e,#e97316,#6b7280,#86c440,#057a55);
                border-radius:99px;height:6px;"></div>
    <div style="position:absolute;top:-3px;left:calc({pct}% - 6px);width:12px;height:12px;
                background:{bar_col};border-radius:50%;border:2px solid white;
                box-shadow:0 1px 3px rgba(0,0,0,.25);"></div>
  </div>
</div>"""

# ============================================================
# FRED TABLE ROWS -- Dir column removed
# ============================================================

def _build_fred_rows(fred_data, trend_color_fn, cache):
    from fred import GROUP_META
    group_order = [
        "INFLATION", "RATES", "CREDIT", "LABOR",
        "COMMODITIES", "CURRENCY", "SENTIMENT_FRED", "VALUATION",
    ]
    rows = ""
    rn   = 1
    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for g in group_order:
        gm    = GROUP_META.get(g, {"icon": "", "color": "#374151", "label": g})
        items = [r for r in fred_data if r.get("group") == g]
        if not items:
            continue
        rows += (f'<tr style="background:#f9fafb;"><td colspan="8" style="padding:6px 10px;'
                 f'font-size:.64rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;'
                 f'color:{gm["color"]};border-bottom:1px solid #e5e7eb;">'
                 f'{gm["icon"]} {gm["label"]}</td></tr>')

        for r in items:
            tc    = trend_color_fn(r["label"], g, r["trend"])
            spark = _sparkline_svg(r["current"], r["mo3"], r["mo12"])

            # Cache badge if this row came from cache
            is_cached   = r.get("cached", False)
            cached_date = r.get("cached_date", "")
            cache_html  = _cache_badge(cached_date) if is_cached else ""

            rows += (
                f'<tr style="border-bottom:1px solid #f3f4f6;">'
                f'<td style="padding:7px 8px;text-align:center;font-size:.7rem;color:#9ca3af;">{rn}</td>'
                f'<td style="padding:7px 10px;min-width:140px;">'
                f'<div style="font-weight:600;font-size:.8rem;">{r["label"]}{cache_html}</div>'
                f'<div style="font-size:.59rem;color:#9ca3af;">{r["insight"]}</div></td>'
                f'<td style="padding:7px 10px;text-align:center;font-weight:700;font-size:.88rem;">{r["current"]}</td>'
                f'<td style="padding:7px 10px;text-align:center;font-size:.78rem;color:#6b7280;">{r["mo3"]}</td>'
                f'<td style="padding:7px 10px;text-align:center;font-size:.78rem;color:#6b7280;">{r["mo12"]}</td>'
                f'<td style="padding:7px 10px;text-align:center;font-size:1rem;color:{tc};">{r["trend"]}</td>'
                f'<td style="padding:7px 6px;text-align:center;">{spark}</td>'
                f'<td style="padding:7px 8px;font-size:.67rem;color:#9ca3af;white-space:nowrap;">{r["date"]}</td>'
                f'<td style="padding:7px 10px;font-size:.7rem;color:#1e3a5f;min-width:200px;">{r.get("sig","")}</td>'
                f'</tr>'
            )
            rn += 1

    return rows

# ============================================================
# VALUE SCREEN CHIPS
# SI filter: show only tickers with >= 3 superinvestors
# ============================================================

def _build_screens_html(si_tickers, mf_tickers, am_tickers):
    all_tickers_set = sorted(set(si_tickers.keys()) | mf_tickers | am_tickers)
    all3 = []; two3 = []; si_only = []; mf_only = []; am_only = []

    for t in all_tickers_set:
        in_si = si_tickers.get(t, 0) > 0
        in_mf = t in mf_tickers
        in_am = t in am_tickers
        cnt   = (1 if in_si else 0) + (1 if in_mf else 0) + (1 if in_am else 0)
        if   cnt == 3: all3.append(t)
        elif cnt == 2: two3.append(t)
        elif in_si:    si_only.append(t)
        elif in_mf:    mf_only.append(t)
        elif in_am:    am_only.append(t)

    si_only_filtered = [t for t in si_only if si_tickers.get(t, 0) >= 3]
    si_only_excluded = len(si_only) - len(si_only_filtered)

    def chip(t, style="one"):
        tags = []
        cnt  = si_tickers.get(t, 0)
        if cnt > 0:    tags.append(f"{cnt}SI")
        if t in mf_tickers: tags.append("MF")
        if t in am_tickers: tags.append("AM")
        tag_str = ",".join(tags)
        if style == "all3":
            return (f'<div style="background:#1a56db;border-radius:6px;padding:5px 9px;'
                    f'white-space:nowrap;display:inline-block;margin:2px;">'
                    f'<span style="font-weight:800;font-size:.82rem;color:white;">{t}</span>'
                    f'<span style="color:rgba(255,255,255,.7);font-size:.65rem;margin-left:3px;">'
                    f'({tag_str})</span></div>')
        elif style == "two":
            return (f'<div style="background:#057a55;border-radius:6px;padding:5px 9px;'
                    f'white-space:nowrap;display:inline-block;margin:2px;">'
                    f'<span style="font-weight:800;font-size:.82rem;color:white;">{t}</span>'
                    f'<span style="color:rgba(255,255,255,.7);font-size:.65rem;margin-left:3px;">'
                    f'({tag_str})</span></div>')
        return (f'<div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;'
                f'padding:4px 8px;white-space:nowrap;display:inline-block;margin:2px;">'
                f'<span style="font-weight:700;font-size:.78rem;color:#374151;">{t}</span>'
                f'<span style="color:#9ca3af;font-size:.63rem;margin-left:3px;">'
                f'({tag_str})</span></div>')

    def screen_row(label, chips_html, count, footnote=""):
        empty  = '<span style="font-size:.75rem;color:#9ca3af;">None today</span>'
        fn_html = (f'<div style="font-size:.6rem;color:#9ca3af;margin-top:2px;">{footnote}</div>'
                   if footnote else "")
        return (f'<div style="margin-bottom:8px;">'
                f'<div style="font-size:.63rem;font-weight:700;color:#374151;margin-bottom:3px;">'
                f'{label} <span style="color:#9ca3af;font-weight:400;">({count})</span></div>'
                f'<div style="display:flex;flex-wrap:wrap;">'
                f'{chips_html if chips_html else empty}</div>{fn_html}</div>')

    si_footnote = (f"Showing 3+ SI managers only. {si_only_excluded} tickers "
                   f"with 1-2 SI managers hidden."
                   if si_only_excluded > 0 else "")

    html = (
        screen_row("🔵 All 3 Screens -- SI + MF + AM (highest conviction)",
                   "".join(chip(t, "all3") for t in all3), len(all3))
        + screen_row("🟢 2 of 3 Screens (strong convergence)",
                     "".join(chip(t, "two") for t in two3), len(two3))
        + screen_row("⭐ Superinvestors only (13F, 3+ managers)",
                     "".join(chip(t, "one") for t in si_only_filtered),
                     len(si_only_filtered), si_footnote)
        + screen_row("🔮 Magic Formula only (Greenblatt, daily)",
                     "".join(chip(t, "one") for t in mf_only[:25]), len(mf_only))
        + screen_row("📐 Acquirer's Multiple only (Carlisle, daily)",
                     "".join(chip(t, "one") for t in am_only[:25]), len(am_only))
    )
    return html, all3, two3, si_only_filtered, mf_only, am_only

# ============================================================
# MARKET CONTEXT STRING (hidden div for Chrome extension)
# ============================================================

def _build_market_context(fred_data, fg_data, mkt_data, mhs,
                           si_tickers, mf_tickers, am_tickers,
                           all3, two3, si_only, mf_only, am_only,
                           cape_val, urth_disp, efa_disp,
                           erp, cape_yield, ten_y_rate):
    def _ctx(lbl, short):
        r = next((x for x in fred_data if x["label"] == lbl), None)
        if not r or r["current"] == "N/A": return f"{short}=N/A"
        cur = r["current"]; mo3 = r["mo3"]; mo12 = r["mo12"]; t3 = r["trend"]
        try:
            c   = float(re.sub(r"[^0-9.\-]", "", cur))
            m12 = float(re.sub(r"[^0-9.\-]", "", mo12))
            t12 = "up" if c > m12 + 0.05 else "dn" if c < m12 - 0.05 else "flat"
        except Exception:
            t12 = "?"
        a3 = "up" if t3 == "▲" else "dn" if t3 == "▼" else "flat"
        return f"{short}={cur}[3m:{mo3},12m:{mo12}]{a3}/{t12}"

    def tlist(lst, si_d=None):
        if not lst: return "none"
        if si_d: return "|".join(f"{t}({si_d.get(t,0)}SI)" for t in lst)
        return "|".join(lst)

    fg_score = fg_data.get("score", 50); fg_lbl = fg_data.get("label", "N/A")
    erp_ctx  = (f"|ERP={erp:+.2f}%(CAPEyield{cape_yield:.2f}%-10Y{ten_y_rate:.2f}%)"
                if erp is not None else "")
    mhs_clean = (mhs["label"]
                 .replace("🟢 ","").replace("🟠 ","").replace("⛔ ","").replace("🚨 ",""))

    return (
        f"MHS={mhs['score']}/100({mhs_clean})|Scale:0=max_fear/deploy,100=max_greed/overheated\n"
        f"POSTURE={mhs['action']}\n"
        f"INFLATION:{_ctx('CPI Inflation','CPI')}|{_ctx('Core CPI','CoreCPI')}|"
        f"{_ctx('PCE Inflation','PCE')}|{_ctx('Core PCE','CorePCE')}\n"
        f"RATES:{_ctx('10Y Treasury','10Y')}|{_ctx('2Y Treasury','2Y')}|"
        f"{_ctx('Yield Curve (10Y-2Y)','YldCurve')}|{_ctx('Fed Funds Rate','FedFunds')}\n"
        f"CREDIT:{_ctx('HY Credit Spread','HYSpread')}(Tight<3%=calm,Wide>6%=stress)\n"
        f"LABOR:{_ctx('Unemployment','Unemp')}(avg~5.7%historic)\n"
        f"COMMODITIES:{_ctx('WTI Crude Oil','WTI')}(>$85=inflation_risk)|"
        f"{_ctx('Gold Price','Gold')}(rising+lowVIX=stealth_fear)\n"
        f"CURRENCY:{_ctx('US Dollar (DXY)','DXY')}(weak_dollar=tailwind_intl_ADRs)\n"
        f"SENTIMENT_CONSUMER:{_ctx('Consumer Sentiment','ConsSent')}(avg~75,<60=stress)\n"
        f"SENTIMENT_MARKET:FG={fg_score}/100({fg_lbl})\n"
        f"VALUATION:CAPE={cape_val}(USonly,histAvg17x,98thPctileSince1881,src:multpl.com)"
        f"|URTH_PE={urth_disp}(MSCIWorldInclUS,approx)"
        f"|EFA_PE={efa_disp}(ExUSdeveloped,approx){erp_ctx}\n"
        f"SCREENS_ALL3(highest_conviction):{tlist(all3)}\n"
        f"SCREENS_2OF3(strong_convergence):{tlist(two3)}\n"
        f"SCREENS_SI_ONLY(13F_3plus_managers):{tlist(si_only, si_tickers)}\n"
        f"SCREENS_MF_ONLY(Greenblatt_MagicFormula):{tlist(mf_only)}\n"
        f"SCREENS_AM_ONLY(Carlisle_AcquirersMultiple):{tlist(am_only)}"
    )

# ============================================================
# MAIN BUILD FUNCTION
# ============================================================

def build_html(briefing, ai_failed, ej_text, cnbc_text, yahoo_text, mcoscillator_text,
               fred_data, fg_data, mkt_data, mhs,
               si_tickers, mf_tickers, am_tickers,
               run_log, run_start, cache=None):

    from fred    import trend_color as _trend_color
    from market  import PE_LAST_UPDATED, compute_erp
    from ai_synthesis import parse_sections

    if cache is None:
        cache = {}

    print("\n🎨 Building HTML dashboard...")

    secs     = parse_sections(briefing)
    now_mt   = datetime.now(MT)
    today    = now_mt.strftime("%A, %B %d, %Y")
    now_str  = now_mt.strftime("%I:%M %p")

    # Market values
    vix_val  = mkt_data["vix"]["value"];  vix_prev = mkt_data["vix"]["prev"]
    vix_lbl  = mkt_data["vix"]["label"];  vix_col  = mkt_data["vix"]["color"]
    vix_sig  = mkt_data["vix"]["signal"]

    spx_val  = mkt_data["spx"]["value"];  spx_chg  = mkt_data["spx"]["chg"]
    spx_lbl  = mkt_data["spx"]["label"];  spx_col  = mkt_data["spx"]["color"]

    rut_val  = mkt_data["rut"]["value"];  rut_chg  = mkt_data["rut"]["chg"]
    rut_lbl  = mkt_data["rut"]["label"];  rut_col  = mkt_data["rut"]["color"]

    pulse     = mkt_data["pulse"]
    mkt_state = mkt_data.get("market_state", "UNKNOWN")
    mkt_cached= mkt_data.get("cached", False)
    mkt_cdate = mkt_data.get("cached_date", "")

    urth_pe    = mkt_data.get("urth_pe");  urth_stale = mkt_data.get("urth_pe_stale", False)
    efa_pe     = mkt_data.get("efa_pe");   efa_stale  = mkt_data.get("efa_pe_stale",  False)
    urth_src   = mkt_data.get("urth_pe_source", "")
    efa_src    = mkt_data.get("efa_pe_source",  "")

    # F&G
    fg_score   = fg_data.get("score", 50); fg_lbl = fg_data.get("label", "N/A")
    fg_col     = fg_data.get("color", "#6b7280"); fg_sig = fg_data.get("signal", "")
    fg_cached  = fg_data.get("cached", False);    fg_cdate = fg_data.get("cached_date", "")

    # Consumer Sentiment
    umich      = next((r for r in fred_data if r["label"] == "Consumer Sentiment"), None)
    umich_val  = umich["current"] if umich else "N/A"
    umich_mo3  = umich["mo3"]     if umich else "N/A"
    umich_m12  = umich["mo12"]    if umich else "N/A"
    umich_sig  = umich.get("sig", "") if umich else ""
    try:   umich_num = float(str(umich_val))
    except: umich_num = 55
    ucol  = "#c81e1e" if umich_num < 60 else "#6b7280" if umich_num < 75 else "#057a55"
    u_lbl = "LOW"     if umich_num < 60 else "MID"     if umich_num < 75 else "HIGH"

    # CAPE + ERP
    cape_row  = next((r for r in fred_data if r["label"] == "Shiller CAPE (US)"), None)
    cape_val  = cape_row["current"] if cape_row else "N/A"
    try:   cape_num = float(re.sub(r"[^0-9.]", "", str(cape_val)))
    except: cape_num = 0
    erp, cape_yield, ten_y_rate = compute_erp(fred_data, cape_val)

    # MHS
    mhs_score  = mhs["score"]; mhs_lbl = mhs["label"]
    mhs_col    = mhs["color"]; mhs_action = mhs["action"]
    mhs_bdown  = (
        '<span style="font-size:.63rem;color:#6b7280;margin-right:8px;">Base +50</span>'
        + "".join(f'<span style="font-size:.63rem;color:#6b7280;margin-right:8px;">{b}</span>'
                  for b in mhs["breakdown"])
    )

    # Market state banner
    if mkt_state == "PRE":
        mkt_banner = ('<div style="background:#eef2ff;border:1px solid #c7d2fe;border-radius:5px;'
                      'padding:4px 8px;margin-bottom:7px;font-size:.72rem;color:#3730a3;">'
                      'Pre-Market -- Opens 9:30 AM ET (7:30 AM MT)</div>')
    elif mkt_state == "POST":
        mkt_banner = ('<div style="background:#faf5ff;border:1px solid #e9d5ff;border-radius:5px;'
                      'padding:4px 8px;margin-bottom:7px;font-size:.72rem;color:#6d28d9;">'
                      'After-Hours</div>')
    else:
        mkt_banner = ""

    # Cache warning for market data
    mkt_cache_banner = ""
    if mkt_cached:
        mkt_cache_banner = (
            f'<div style="background:#fff7ed;border:1px solid #fed7aa;border-radius:5px;'
            f'padding:4px 8px;margin-bottom:7px;font-size:.72rem;color:#b45309;">'
            f'Market data from cache ({mkt_cdate}) -- live fetch failed</div>')

    # AI failure alert
    ai_alert = ""
    if ai_failed:
        ai_alert = ('<div style="background:#fef2f2;border:2px solid #fca5a5;border-radius:8px;'
                    'padding:10px 16px;margin-bottom:12px;display:flex;align-items:center;gap:10px;">'
                    '<span style="font-size:1.3rem;">⚠️</span><div>'
                    '<div style="font-weight:700;font-size:.82rem;color:#c81e1e;">AI Synthesis Unavailable</div>'
                    '<div style="font-size:.73rem;color:#6b7280;margin-top:2px;">'
                    'Gemini quota exhausted AND Claude Haiku fallback failed. All data sections complete. '
                    'Gemini resets at midnight UTC (6 PM MT).</div></div></div>')

    # Gauge market performance -- Chrome extension style
    # Live JS refresh: on page load + every 60s, fetches Yahoo v8 from browser
    # (browser fetch works; GitHub Actions server-side fetch is what fails for market state)
    gauge_section = f"""
<div class="card ar" style="margin-bottom:12px;" id="market-perf-card">
  <h2>📈 Market Performance
    <span id="mkt-refresh-ts" style="font-weight:400;color:var(--muted);font-size:.55rem;margin-left:8px;"></span>
  </h2>
  {mkt_banner}{mkt_cache_banner}

  <!-- S&P 500 gauge row -->
  <div id="gauge-spx" style="background:white;border:1px solid #e5e7eb;border-radius:8px;
              padding:10px 14px;margin-bottom:8px;">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:5px;">
      <div>
        <div style="font-weight:700;font-size:.88rem;color:#111928;">S&amp;P 500</div>
        <div style="font-size:.58rem;color:#9ca3af;margin-top:1px;">Large-cap benchmark</div>
      </div>
      <div style="text-align:right;display:flex;align-items:center;gap:8px;">
        <span id="spx-val" style="font-weight:800;font-size:1rem;color:#111928;">{spx_val}</span>
        <span id="spx-chg" style="font-size:.78rem;font-weight:600;color:{spx_col};">{spx_chg}</span>
        <span id="spx-pill" style="background:{spx_col};color:white;padding:2px 10px;
              border-radius:4px;font-size:.72rem;font-weight:800;letter-spacing:.5px;">{spx_lbl}</span>
      </div>
    </div>
    <div style="display:flex;justify-content:space-between;font-size:.55rem;color:#9ca3af;margin-bottom:2px;">
      <span>SELLOFF</span><span>DOWN</span><span>FLAT</span><span>UP</span><span>RALLY</span>
    </div>
    <div style="position:relative;margin-top:2px;">
      <div style="background:linear-gradient(to right,#c81e1e,#e97316,#6b7280,#86c440,#057a55);
                  border-radius:99px;height:6px;"></div>
      <div id="spx-dot" style="position:absolute;top:-3px;left:calc(50% - 6px);width:12px;height:12px;
                  background:{spx_col};border-radius:50%;border:2px solid white;
                  box-shadow:0 1px 3px rgba(0,0,0,.25);"></div>
    </div>
  </div>

  <!-- Russell 2000 gauge row -->
  <div id="gauge-rut" style="background:white;border:1px solid #e5e7eb;border-radius:8px;
              padding:10px 14px;margin-bottom:8px;">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:5px;">
      <div>
        <div style="font-weight:700;font-size:.88rem;color:#111928;">Russell 2000</div>
        <div style="font-size:.58rem;color:#9ca3af;margin-top:1px;">Small-cap · risk appetite proxy</div>
      </div>
      <div style="text-align:right;display:flex;align-items:center;gap:8px;">
        <span id="rut-val" style="font-weight:800;font-size:1rem;color:#111928;">{rut_val}</span>
        <span id="rut-chg" style="font-size:.78rem;font-weight:600;color:{rut_col};">{rut_chg}</span>
        <span id="rut-pill" style="background:{rut_col};color:white;padding:2px 10px;
              border-radius:4px;font-size:.72rem;font-weight:800;letter-spacing:.5px;">{rut_lbl}</span>
      </div>
    </div>
    <div style="display:flex;justify-content:space-between;font-size:.55rem;color:#9ca3af;margin-bottom:2px;">
      <span>SELLOFF</span><span>DOWN</span><span>FLAT</span><span>UP</span><span>RALLY</span>
    </div>
    <div style="position:relative;margin-top:2px;">
      <div style="background:linear-gradient(to right,#c81e1e,#e97316,#6b7280,#86c440,#057a55);
                  border-radius:99px;height:6px;"></div>
      <div id="rut-dot" style="position:absolute;top:-3px;left:calc(50% - 6px);width:12px;height:12px;
                  background:{rut_col};border-radius:50%;border:2px solid white;
                  box-shadow:0 1px 3px rgba(0,0,0,.25);"></div>
    </div>
  </div>

  <!-- VIX row -->
  <div style="margin-top:8px;background:white;border:1px solid #e5e7eb;border-radius:8px;
              padding:8px 14px;">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:4px;">
      <div style="font-weight:700;font-size:.88rem;color:#111928;">VIX</div>
      <div style="display:flex;align-items:center;gap:8px;">
        <span id="vix-val" style="font-weight:800;font-size:1rem;color:#111928;">{vix_val}</span>
        <span id="vix-prev" style="font-size:.7rem;color:{vix_col};font-weight:600;">prev {vix_prev}</span>
        <span id="vix-pill" style="background:{vix_col};color:white;padding:2px 9px;
              border-radius:4px;font-size:.68rem;font-weight:700;">{vix_lbl}</span>
      </div>
    </div>
    <div id="vix-sig" style="font-size:.68rem;color:#6b7280;">{vix_sig}</div>
  </div>

  <div id="pulse-line" style="margin-top:4px;font-size:.63rem;color:#9ca3af;">
    ⚡ {pulse}
  </div>
</div>

<script>
// ============================================================
// Live market refresh -- calls Yahoo Finance v8 directly from browser.
// Works because the browser is not blocked (only GitHub Actions IPs are).
// Refreshes on page load and every 60 seconds while market is open.
// ============================================================
(function() {{
  var BANDS = {{SELLOFF:5, DOWN:25, FLAT:50, UP:75, RALLY:95}};
  var COLORS = {{
    RALLY:"#057a55", UP:"#86c440", FLAT:"#6b7280",
    DOWN:"#e97316", SELLOFF:"#c81e1e",
    CALM:"#059669", NORMAL:"#6b7280", CAUTIOUS:"#e97316",
    FEARFUL:"#c81e1e", PANIC:"#7f1d1d"
  }};

  function classifyIdx(c) {{
    if (c >  1.0) return "RALLY";
    if (c >  0.1) return "UP";
    if (c > -0.1) return "FLAT";
    if (c > -1.0) return "DOWN";
    return "SELLOFF";
  }}

  function classifyVix(v) {{
    if (v < 15) return "CALM";
    if (v < 20) return "NORMAL";
    if (v < 25) return "CAUTIOUS";
    if (v < 30) return "FEARFUL";
    return "PANIC";
  }}

  function vixSig(v) {{
    if (v >= 30) return "Panic -- forced selling, mean reversion entries emerging";
    if (v >= 25) return "Elevated fear -- watch for entry points";
    if (v >= 20) return "Slightly elevated -- no broad panic signal";
    if (v >= 15) return "Normal -- market calm, no stress signal";
    return "Calm -- low fear, complacency = less opportunity for value investors";
  }}

  function updateDot(dotId, lbl, col) {{
    var dot = document.getElementById(dotId);
    if (!dot) return;
    var pct = BANDS[lbl] !== undefined ? BANDS[lbl] : 50;
    dot.style.left = "calc(" + pct + "% - 6px)";
    dot.style.background = col;
  }}

  function fetchTicker(sym, callback) {{
    var url = "https://query1.finance.yahoo.com/v8/finance/chart/" + sym +
              "?interval=1d&range=2d&cors=true";
    fetch(url, {{headers: {{"Accept": "application/json"}}}})
      .then(function(r) {{ return r.json(); }})
      .then(function(d) {{
        var meta = d.chart.result[0].meta;
        var p    = parseFloat(meta.regularMarketPrice || 0);
        var pv   = parseFloat(meta.previousClose || p);
        var chg  = pv ? (p - pv) / pv * 100 : 0;
        var state = meta.marketState || "UNKNOWN";
        callback(null, {{price:p, prev:pv, chg:chg, state:state}});
      }})
      .catch(function(e) {{ callback(e, null); }});
  }}

  function refresh() {{
    // Fetch SPX (state source), RUT, VIX in parallel
    var results = {{}};
    var done = 0;
    var tickers = ["%5EGSPC", "%5ERUT", "%5EVIX"];
    var keys    = ["spx",     "rut",    "vix"];

    tickers.forEach(function(sym, i) {{
      fetchTicker(sym, function(err, data) {{
        done++;
        if (!err) results[keys[i]] = data;
        if (done === tickers.length) apply(results);
      }});
    }});
  }}

  function apply(r) {{
    var spx = r.spx; var rut = r.rut; var vix = r.vix;
    if (!spx || !rut || !vix) return;

    // Market state from SPX
    var stateMap = {{REGULAR:"OPEN", PRE:"PRE", POST:"POST", CLOSED:"CLOSED"}};
    var state = stateMap[spx.state] || "OPEN";

    var spxLbl, rutLbl, spxChgStr, rutChgStr;
    if (state === "PRE") {{
      spxLbl = "PRE-MKT"; rutLbl = "PRE-MKT";
      spxChgStr = "Pre-Market"; rutChgStr = "Pre-Market";
    }} else {{
      spxLbl = classifyIdx(spx.chg); rutLbl = classifyIdx(rut.chg);
      spxChgStr = (spx.chg >= 0 ? "+" : "") + spx.chg.toFixed(2) + "%";
      rutChgStr = (rut.chg >= 0 ? "+" : "") + rut.chg.toFixed(2) + "%";
    }}
    var spxCol = COLORS[spxLbl] || "#6b7280";
    var rutCol = COLORS[rutLbl] || "#6b7280";
    var vixLbl = classifyVix(vix.price);
    var vixCol = COLORS[vixLbl] || "#6b7280";

    // Update SPX
    var el;
    el = document.getElementById("spx-val");  if(el) el.textContent = spx.price.toLocaleString("en-US", {{maximumFractionDigits:0}});
    el = document.getElementById("spx-chg");  if(el) {{ el.textContent = spxChgStr; el.style.color = spxCol; }}
    el = document.getElementById("spx-pill"); if(el) {{ el.textContent = spxLbl; el.style.background = spxCol; }}
    updateDot("spx-dot", spxLbl, spxCol);

    // Update RUT
    el = document.getElementById("rut-val");  if(el) el.textContent = rut.price.toLocaleString("en-US", {{maximumFractionDigits:0}});
    el = document.getElementById("rut-chg");  if(el) {{ el.textContent = rutChgStr; el.style.color = rutCol; }}
    el = document.getElementById("rut-pill"); if(el) {{ el.textContent = rutLbl; el.style.background = rutCol; }}
    updateDot("rut-dot", rutLbl, rutCol);

    // Update VIX
    el = document.getElementById("vix-val");  if(el) el.textContent = vix.price.toFixed(2);
    el = document.getElementById("vix-prev"); if(el) {{ el.textContent = "prev " + vix.prev.toFixed(2); el.style.color = vixCol; }}
    el = document.getElementById("vix-pill"); if(el) {{ el.textContent = vixLbl; el.style.background = vixCol; }}
    el = document.getElementById("vix-sig");  if(el) el.textContent = vixSig(vix.price);

    // Pulse line
    var tone = "";
    if (state === "PRE") {{
      tone = "Pre-Market · S&P last close " + spx.price.toLocaleString("en-US",{{maximumFractionDigits:0}}) +
             " · Russell " + rut.price.toLocaleString("en-US",{{maximumFractionDigits:0}}) +
             " · VIX " + vix.price.toFixed(1) + " (" + vixLbl + ")";
    }} else {{
      var mood = "";
      if (vix.price >= 30 || spxLbl === "SELLOFF") mood = "broad stress -- mean reversion entries emerging";
      else if (spxLbl === "FLAT") mood = "indecisive -- focus on individual catalysts";
      else if (["UP","RALLY"].includes(spxLbl) && ["UP","RALLY"].includes(rutLbl)) mood = "broad strength -- be selective";
      else mood = "mixed -- stay selective";
      tone = "S&P " + spxChgStr + " (" + spxLbl + ") · Russell " + rutChgStr + " (" + rutLbl + ") · VIX " + vix.price.toFixed(1) + " (" + vixLbl + ") -- " + mood;
    }}
    el = document.getElementById("pulse-line"); if(el) el.textContent = "⚡ " + tone;

    // Timestamp
    var now = new Date();
    var hh = now.getHours(); var mm = now.getMinutes();
    var ampm = hh >= 12 ? "PM" : "AM"; hh = hh % 12 || 12;
    var ts = "refreshed " + hh + ":" + (mm < 10 ? "0" : "") + mm + " " + ampm;
    el = document.getElementById("mkt-refresh-ts"); if(el) el.textContent = ts;

    // Auto-refresh every 60s only when market likely open (Mon-Fri, 7:30-16:05 MT)
    var day = now.getDay(); // 0=Sun,6=Sat
    var minOfDay = now.getHours() * 60 + now.getMinutes();
    var mktOpen  = 7 * 60 + 30;   // 7:30 AM MT
    var mktClose = 16 * 60 + 5;   // 4:05 PM MT
    if (day >= 1 && day <= 5 && minOfDay >= mktOpen && minOfDay < mktClose) {{
      setTimeout(refresh, 60000);
    }}
  }}

  // Run on page load
  refresh();
}})();
</script>"""

    # Sentiment table (F&G + Consumer Sentiment -- VIX now in gauge block)
    fg_cache_html   = _cache_badge(fg_cdate) if fg_cached else ""
    umich_cache_html= _cache_badge(umich.get("cached_date","")) if (umich and umich.get("cached")) else ""

    def sr(name, val, hist, rl, rc, sig, note="", extra_badge=""):
        nh = f'<div style="font-size:.6rem;color:#9ca3af;">{note}</div>' if note else ""
        return (f'<tr style="border-bottom:1px solid #f3f4f6;">'
                f'<td style="padding:7px 10px;">'
                f'<div style="font-weight:600;font-size:.82rem;">{name}{extra_badge}</div>{nh}</td>'
                f'<td style="padding:7px 10px;font-weight:700;font-size:.9rem;">{val}</td>'
                f'<td style="padding:7px 10px;font-size:.75rem;color:#6b7280;">{hist}</td>'
                f'<td style="padding:7px 10px;">{_badge(rl,rc)}</td>'
                f'<td style="padding:7px 10px;font-size:.72rem;color:#374151;">{sig}</td></tr>')

    sent_rows = (
        sr("Fear & Greed", f"{fg_score}/100",
           f"1wk:{fg_data.get('prev_week','N/A')} 1mo:{fg_data.get('prev_month','N/A')} "
           f"1yr:{fg_data.get('prev_year','N/A')}",
           fg_lbl, fg_col, fg_sig,
           "CNN Business · 0=extreme fear · 100=extreme greed",
           extra_badge=fg_cache_html)
        + sr("Consumer Sentiment", f"{umich_val}", f"3mo:{umich_mo3} 12mo:{umich_m12}",
             u_lbl, ucol, umich_sig,
             "U of Michigan · avg ~75 · <60 = consumer stress",
             extra_badge=umich_cache_html)
    )

    # Valuation block
    cape_color  = "#c81e1e" if cape_num >= 35 else "#b45309" if cape_num >= 25 else "#057a55"
    pe_updated  = PE_LAST_UPDATED.strftime("%b %Y")
    urth_disp   = f"{urth_pe:.1f}x" if urth_pe else "N/A"
    efa_disp    = f"{efa_pe:.1f}x"  if efa_pe  else "N/A"
    cape_times  = round(cape_num / 17, 1) if cape_num else "?"
    cape_status = ("EXTREME (98th pctile)" if cape_num >= 40
                   else "ELEVATED"          if cape_num >= 30 else "MODERATE")
    urth_note   = (' <span style="color:#b45309;font-size:.55rem;font-weight:700;">UPDATE NEEDED</span>'
                   if urth_stale else "")
    efa_note    = (' <span style="color:#b45309;font-size:.55rem;font-weight:700;">UPDATE NEEDED</span>'
                   if efa_stale else "")
    pe_src_note = (f"source: {urth_src}"
                   if urth_src and "Yahoo Finance" in urth_src
                   else f"approx, {pe_updated}")

    if erp is not None:
        erp_col   = "#c81e1e" if erp < 0 else "#b45309" if erp < 1.0 else "#057a55"
        erp_label = ("NEGATIVE ERP" if erp < 0 else "LOW ERP" if erp < 1.0 else "POSITIVE ERP")
        erp_desc  = (f"Bonds yield {abs(erp):.2f}% MORE than stocks (last seen ~2002)" if erp < 0
                     else "Stocks barely out-earn bonds -- thin margin of safety" if erp < 1.0
                     else f"Stocks yield {erp:.2f}% more than 10Y bonds")
        erp_html  = f"""
<div style="background:#fff7ed;border:1px solid #fed7aa;border-radius:8px;padding:8px 12px;margin-top:8px;">
  <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
    <div>
      <div style="font-size:.58rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;
                  color:#b45309;margin-bottom:2px;">Equity Risk Premium (ERP = CAPE Yield - 10Y)</div>
      <div style="font-size:1.4rem;font-weight:800;color:{erp_col};">{erp:+.2f}%</div>
    </div>
    <div style="font-size:.7rem;color:#374151;line-height:1.6;flex:1;min-width:200px;">
      <strong style="color:{erp_col};">{erp_label}:</strong> {erp_desc}<br>
      <span style="color:#9ca3af;">CAPE yield (1/{cape_num:.0f}x) = {cape_yield:.2f}%
        vs 10Y Treasury = {ten_y_rate:.2f}%</span>
    </div>
  </div>
</div>"""
    else:
        erp_html = ""

    valuation_block = f"""
<div class="card" style="margin-bottom:12px;border-left:4px solid #7c3aed;">
  <h2>📐 Global Market Valuation
    <span style="font-weight:400;color:var(--muted);font-size:.55rem;">
      Shiller CAPE (US) = 10yr smoothed (multpl.com) · URTH/EFA PE: {pe_src_note}
    </span>
  </h2>
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:10px;">
    <div style="text-align:center;padding:10px;background:#fdf4ff;border-radius:8px;border:1px solid #e9d5ff;">
      <div style="font-size:.58rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;
                  color:#7c3aed;margin-bottom:4px;">Shiller CAPE (US)</div>
      <div style="font-size:1.8rem;font-weight:800;color:{cape_color};">{cape_val}</div>
      <div style="font-size:.63rem;color:#6b7280;margin-top:3px;">Hist avg 17x · 2nd highest ever</div>
      <div style="font-size:.6rem;color:{cape_color};margin-top:2px;font-weight:600;">{cape_status}</div>
    </div>
    <div style="text-align:center;padding:10px;background:#f0fdf4;border-radius:8px;border:1px solid #bbf7d0;">
      <div style="font-size:.58rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;
                  color:#059669;margin-bottom:4px;">URTH (MSCI World)</div>
      <div style="font-size:1.8rem;font-weight:800;color:#059669;">{urth_disp}{urth_note}</div>
      <div style="font-size:.63rem;color:#6b7280;margin-top:3px;">incl ~70% US · trailing PE</div>
      <div style="font-size:.6rem;color:#059669;margin-top:2px;font-weight:600;">GLOBAL BLEND</div>
    </div>
    <div style="text-align:center;padding:10px;background:#eff6ff;border-radius:8px;border:1px solid #bfdbfe;">
      <div style="font-size:.58rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;
                  color:#1a56db;margin-bottom:4px;">EFA (ex-US Developed)</div>
      <div style="font-size:1.8rem;font-weight:800;color:#057a55;">{efa_disp}{efa_note}</div>
      <div style="font-size:.63rem;color:#6b7280;margin-top:3px;">Europe/Japan/Aus · trailing PE</div>
      <div style="font-size:.6rem;color:#057a55;margin-top:2px;font-weight:600;">SIGNIFICANTLY CHEAPER</div>
    </div>
  </div>
  {erp_html}
  <div style="font-size:.67rem;color:#374151;background:#f9fafb;border-radius:5px;
              padding:6px 10px;line-height:1.6;margin-top:8px;">
    <strong>Why this matters:</strong> US trades at {cape_times}x the 145-year historical average (CAPE 17x).
    Ex-US developed markets ({efa_disp} PE) offer dramatically better valuation support.
    Many AM screen picks are intl ADRs (EQNR, PBR, SNY, NVO, SHEL, BP) -- cheaper valuations
    AND potential dollar weakness tailwind
    (DXY {next((r['current'] for r in fred_data if r['label']=='US Dollar (DXY)'), 'N/A')}).
  </div>
</div>"""

    # Value screens
    screens_html, all3, two3, si_only, mf_only, am_only = _build_screens_html(
        si_tickers, mf_tickers, am_tickers)

    # FRED table -- Dir column removed
    fred_rows = _build_fred_rows(fred_data, _trend_color, cache)

    # AI fun fact / learning
    fun_raw   = secs.get("AI FUN FACT",  "").strip()
    learn_raw = secs.get("AI LEARNING",  "").strip()
    if fun_raw:   fun_raw   = re.sub(r"^[-•*]\s*", "", fun_raw.splitlines()[0].strip())
    else:         fun_raw   = ("Shiller CAPE above 40x has occurred only twice in 145 years: "
                               "at the dot-com peak in 1999, and today.")
    if learn_raw: learn_raw = re.sub(r"^[-•*]\s*", "", learn_raw.splitlines()[0].strip())
    else:         learn_raw = ("Attention mechanism: LLMs weight relationships between all tokens "
                               "simultaneously, enabling context-aware reasoning across long documents.")

    # Market context for Chrome extension
    mctx = _build_market_context(
        fred_data, fg_data, mkt_data, mhs,
        si_tickers, mf_tickers, am_tickers,
        all3, two3, si_only, mf_only, am_only,
        cape_val, urth_disp, efa_disp, erp, cape_yield, ten_y_rate,
    )

    # Run log
    elapsed       = round(time.time() - run_start)
    run_log_items = "".join(
        f'<div style="font-size:.72rem;padding:2px 0;border-bottom:1px solid #f3f4f6;'
        f'font-family:monospace;">{e}</div>'
        for e in run_log
    )
    run_log_html = f"""
<div style="margin-top:12px;">
  <button onclick="var d=this.nextElementSibling;d.style.display=d.style.display==='none'?'block':'none';"
          style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;padding:6px 14px;
                 font-size:.72rem;color:#6b7280;cursor:pointer;width:100%;text-align:left;">
    View Run Log &nbsp;·&nbsp; Total time: {elapsed}s &nbsp;·&nbsp; {len(run_log)} steps
  </button>
  <div style="display:none;background:#f9fafb;border:1px solid #e5e7eb;border-top:none;
              border-radius:0 0 6px 6px;padding:10px 14px;max-height:400px;overflow-y:auto;">
    {run_log_items}
    <div style="font-size:.7rem;color:#9ca3af;margin-top:4px;padding-top:4px;
                border-top:1px solid #e5e7eb;">
      Total runtime: {elapsed}s &nbsp;·&nbsp; {today} {now_str} MT
    </div>
  </div>
</div>"""

    mhs_scale = (
        "🟢 DEPLOY (0-33): Panic &amp; dislocation -- aggressive deployment &nbsp;·&nbsp; "
        "🟠 SELECTIVE (34-65): Best setups only, Left Leg &lt;4 &amp; MoS &gt;25% &nbsp;·&nbsp; "
        "⛔ OVERHEATED (66-85): Build cash, trim winners &nbsp;·&nbsp; "
        "🚨 EXTREME (86-100): Most stretched since dot-com -- quality and patience above all."
    )

    # ============================================================
    # FULL HTML
    # ============================================================

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Mean Reversion Macro Insights · {today}</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'><text y='.9em' font-size='90'>📈</text></svg>">
<style>
:root{{--blue:#1a56db;--green:#057a55;--red:#c81e1e;--amber:#b45309;--ink:#111928;--muted:#6b7280;--border:#e5e7eb;--bg:#f3f4f6;--card:#fff;}}
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--ink);padding-bottom:60px;}}
.hero{{background:linear-gradient(135deg,#1e3a5f,#1a56db);color:#fff;padding:20px 20px 14px;text-align:center;}}
.hero h1{{font-size:1.5rem;letter-spacing:3px;font-weight:800;}}
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
.tbl{{width:100%;border-collapse:collapse;font-size:.8rem;}}
.tbl th{{padding:6px 10px;text-align:left;font-size:.58rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);background:#f9fafb;}}
.footer{{text-align:center;color:var(--muted);font-size:.68rem;margin-top:22px;}}
.footer a{{color:var(--blue);text-decoration:none;}}
@media(max-width:680px){{.grid-2,.grid-3{{grid-template-columns:1fr;}}.hero h1{{font-size:1.1rem;}}}}
</style>
</head>
<body>

<div id="market-context" style="display:none;white-space:pre;">{mctx}</div>

<div class="hero">
  <h1>📈 MEAN REVERSION MACRO INSIGHTS</h1>
  <div class="sub">Anil Abraham &nbsp;·&nbsp; {today}</div>
  <div class="ts">Updated {now_str} MT · anil2040.github.io/market-pulse-ai</div>
</div>

<div class="container">
  {ai_alert}

  <div class="grid-2" style="margin-bottom:12px;">
    <div style="background:linear-gradient(135deg,#1e3a5f,#1a56db);color:white;border-radius:10px;
                padding:11px 16px;display:flex;align-items:center;gap:12px;">
      <div style="font-size:1.3rem;flex-shrink:0;">🤖</div>
      <div>
        <div style="font-size:.55rem;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;
                    opacity:.6;margin-bottom:2px;">Fun Fact</div>
        <div style="font-size:.82rem;line-height:1.5;opacity:.92;">{fun_raw}</div>
      </div>
    </div>
    <div style="background:linear-gradient(135deg,#064e3b,#059669);color:white;border-radius:10px;
                padding:11px 16px;display:flex;align-items:center;gap:12px;">
      <div style="font-size:1.3rem;flex-shrink:0;">🧠</div>
      <div>
        <div style="font-size:.55rem;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;
                    opacity:.6;margin-bottom:2px;">AI Learning</div>
        <div style="font-size:.82rem;line-height:1.5;opacity:.92;">{learn_raw}</div>
      </div>
    </div>
  </div>

  <div class="card" style="margin-bottom:12px;border-left:4px solid {mhs_col};">
    <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;">
      <div style="flex-shrink:0;">
        <div style="font-size:.58rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;
                    color:var(--muted);margin-bottom:3px;">MHS · Macro Heat Score</div>
        <div style="font-size:2rem;font-weight:800;color:{mhs_col};line-height:1;">
          {mhs_score}<span style="font-size:.85rem;color:var(--muted);">/100</span></div>
      </div>
      <div>
        <div style="font-size:.9rem;font-weight:700;color:{mhs_col};">{mhs_lbl}</div>
        <div style="margin-top:5px;background:#e5e7eb;border-radius:99px;height:7px;
                    width:220px;overflow:hidden;">
          <div style="width:{mhs_score}%;background:{mhs_col};height:100%;border-radius:99px;"></div>
        </div>
        <div style="font-size:.7rem;color:#374151;margin-top:5px;">📋 {mhs_action}</div>
      </div>
      <div style="font-size:.63rem;color:var(--muted);flex:1;min-width:200px;line-height:1.8;">
        {mhs_bdown}
      </div>
    </div>
    <div style="margin-top:8px;font-size:.67rem;color:#374151;background:#f9fafb;
                border-radius:5px;padding:6px 10px;line-height:1.6;">
      <strong>Scale (LOWER = better mean reversion opportunity):</strong>
      {mhs_scale}
      Base=50. Components adjust up (overheated signals) or down (fear/opportunity signals).
    </div>
  </div>

  <div class="grid-2" style="margin-bottom:12px;">
    {gauge_section}
    <div class="card aa">
      <h2>🌡️ Market Sentiment</h2>
      <table class="tbl">
        <thead><tr>
          <th>Indicator</th><th>Current</th><th>History</th>
          <th>Level</th><th>Insight</th>
        </tr></thead>
        <tbody>{sent_rows}</tbody>
      </table>
    </div>
  </div>

  {valuation_block}

  <div class="grid-2" style="margin-bottom:12px;">
    <div class="card ab">
      <h2>📊 Market &amp; Macro</h2>
      <ul>{fmt_bullets(secs.get("MARKET AND MACRO",""))}</ul>
    </div>
    <div class="card ag">
      <h2>💰 Earnings &amp; Events</h2>
      <ul>{fmt_bullets(secs.get("EARNINGS AND EVENTS",""))}</ul>
    </div>
  </div>

  <div class="card ab" style="margin-bottom:12px;">
    <h2>📋 Value Screens
      <span style="font-weight:400;color:var(--muted);font-size:.55rem;">
        SI=Superinvestors 13F (3+ managers, ~45d lag) ·
        MF=Greenblatt Magic Formula (daily) ·
        AM=Carlisle Acquirer's Multiple (daily)
      </span>
    </h2>
    {screens_html}
    <div style="font-size:.67rem;color:#6b7280;background:#f0f9ff;border-radius:5px;
                padding:6px 10px;line-height:1.6;margin-top:8px;">
      <strong>How to use:</strong> Blue (All 3) = highest conviction.
      Green (2 of 3) = strong convergence.
      Cross-reference with Finviz. Left Leg &lt;4 + MoS &gt;25% = strong setup.
      13F lag: ~45 days after quarter end. MF and AM update daily.
    </div>
  </div>

  <div class="card" style="margin-bottom:12px;">
    <h2>🏦 Macro Indicators
      <span style="font-weight:400;color:var(--muted);font-size:.55rem;">
        FRED API · Gold via Yahoo GC=F · CAPE via multpl.com ·
        sparkline = 12mo to 3mo to today · green=good / red=bad for equities ·
        amber badge = cached value (live fetch failed)
      </span>
    </h2>
    <div style="overflow-x:auto;">
      <table style="width:100%;border-collapse:collapse;font-size:.78rem;">
        <thead><tr style="background:#f9fafb;">
          <th style="padding:6px 8px;text-align:center;font-size:.55rem;text-transform:uppercase;
                     color:var(--muted);border-bottom:2px solid var(--border);">#</th>
          <th style="padding:6px 10px;text-align:left;font-size:.55rem;text-transform:uppercase;
                     color:var(--muted);border-bottom:2px solid var(--border);min-width:140px;">Indicator</th>
          <th style="padding:6px 10px;text-align:center;font-size:.55rem;text-transform:uppercase;
                     color:var(--muted);border-bottom:2px solid var(--border);">Current</th>
          <th style="padding:6px 10px;text-align:center;font-size:.55rem;text-transform:uppercase;
                     color:var(--muted);border-bottom:2px solid var(--border);">3 Mo</th>
          <th style="padding:6px 10px;text-align:center;font-size:.55rem;text-transform:uppercase;
                     color:var(--muted);border-bottom:2px solid var(--border);">12 Mo</th>
          <th style="padding:6px 10px;text-align:center;font-size:.55rem;text-transform:uppercase;
                     color:var(--muted);border-bottom:2px solid var(--border);">Trend</th>
          <th style="padding:6px 10px;text-align:center;font-size:.55rem;text-transform:uppercase;
                     color:var(--muted);border-bottom:2px solid var(--border);"></th>
          <th style="padding:6px 8px;font-size:.55rem;text-transform:uppercase;
                     color:var(--muted);border-bottom:2px solid var(--border);">As Of</th>
          <th style="padding:6px 10px;font-size:.55rem;text-transform:uppercase;
                     color:var(--muted);border-bottom:2px solid var(--border);min-width:220px;">Insights</th>
        </tr></thead>
        <tbody>{fred_rows}</tbody>
      </table>
    </div>
    <div style="margin-top:8px;font-size:.62rem;color:#9ca3af;border-top:1px solid #f3f4f6;padding-top:6px;">
      Trend colors: green=good for equities, red=bad, amber=context-dependent ·
      AAII: check <a href="https://www.aaii.com/sentimentsurvey" target="_blank"
      style="color:#1a56db;">aaii.com</a> manually every Thursday.
    </div>
  </div>

  {run_log_html}

  <div class="footer" style="margin-top:20px;">
    Built by <strong>Anil Abraham</strong> &nbsp;·&nbsp;
    <a href="https://fred.stlouisfed.org" target="_blank">FRED API</a> &nbsp;·&nbsp;
    <a href="https://www.cnn.com/markets/fear-and-greed" target="_blank">CNN Fear &amp; Greed</a> &nbsp;·&nbsp;
    <a href="https://www.edwardjones.com/us-en/market-news-insights/stock-market-news/daily-market-recap"
       target="_blank">Edward Jones</a> &nbsp;·&nbsp;
    <a href="https://www.cnbc.com/newsletters/" target="_blank">CNBC Squawk</a> &nbsp;·&nbsp;
    <a href="https://finance.yahoo.com" target="_blank">Yahoo Finance</a> &nbsp;·&nbsp;
    <a href="https://www.dataroma.com" target="_blank">Dataroma 13F</a> &nbsp;·&nbsp;
    <a href="https://www.magicformulainvesting.com" target="_blank">Magic Formula</a> &nbsp;·&nbsp;
    <a href="https://acquirersmultiple.com" target="_blank">Acquirer's Multiple</a> &nbsp;·&nbsp;
    <a href="https://www.multpl.com/shiller-pe" target="_blank">multpl.com CAPE</a> &nbsp;·&nbsp;
    Gemini · Claude Haiku (fallback) · Not financial advice.
  </div>
</div>

</body>
</html>"""

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    elapsed = round(time.time() - run_start)
    print(f"  ✅ index.html written | Total runtime: {elapsed}s")