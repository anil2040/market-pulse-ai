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
#              run_log, run_start) -> None  (writes index.html)
#
# LAYOUT CHANGES vs previous version:
#   - Market Performance: Chrome-extension gauge style
#     (SELLOFF/DOWN/FLAT/UP/RALLY pill + colored progress bar + % change)
#   - "What to Watch" card removed -- was restating value screens
#   - New "Market Breadth" card using McClellan Oscillator email text
#   - AI briefing now 2-column grid (Market & Macro + Earnings & Events)
#   - SI-only tickers filtered to >= 3 managers (removes 1-2SI noise)
# ============================================================

import re
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
            items += f"        <li>{line}</li>\n"
    return items or "<li>No data available</li>"


def _badge(raw_lbl, raw_col):
    m = {
        "RALLY": "BULLISH", "UP": "BULLISH", "CALM": "BULLISH",
        "Greed": "BULLISH", "Extreme Greed": "BULLISH", "HIGH": "BULLISH",
        "FLAT": "NEUTRAL", "NORMAL": "NEUTRAL", "Neutral": "NEUTRAL", "MID": "NEUTRAL",
        "DOWN": "CAUTIOUS", "CAUTIOUS": "CAUTIOUS", "Fear": "CAUTIOUS",
        "SELLOFF": "BEARISH", "FEARFUL": "BEARISH", "PANIC": "BEARISH",
        "Extreme Fear": "BEARISH", "LOW": "BEARISH",
        "CLOSED": "CLOSED", "PRE-MKT": "PRE-MKT", "Unavailable": "N/A",
    }
    c = {
        "BULLISH": "#057a55", "NEUTRAL": "#6b7280", "CAUTIOUS": "#b45309",
        "BEARISH": "#c81e1e", "CLOSED": "#9ca3af", "PRE-MKT": "#6366f1", "N/A": "#9ca3af",
    }
    std = m.get(raw_lbl, raw_lbl)
    col = c.get(std, raw_col)
    return (f'<span style="background:{col};color:white;padding:2px 9px;'
            f'border-radius:4px;font-size:.68rem;font-weight:700;">{std}</span>')


def _sparkline_svg(cur_str, mo3_str, mo12_str):
    try:
        def parse(s): return float(re.sub(r"[^0-9.\-]", "", str(s)))
        v12 = parse(mo12_str); v3 = parse(mo3_str); v0 = parse(cur_str)
        mn  = min(v12, v3, v0); mx = max(v12, v3, v0); r = mx - mn if mx != mn else 1
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


# ============================================================
# GAUGE-STYLE MARKET PERFORMANCE ROW
# (Cloned from Chrome extension view)
# ============================================================

def _gauge_row(name, value_str, chg_str, signal_lbl, signal_col, prev_str, note=""):
    """
    Renders a market index as a gauge card matching the Chrome extension style:
    - Signal pill (SELLOFF / DOWN / FLAT / UP / RALLY)
    - Colored progress bar showing position on the scale
    - % change and prev close
    """
    # Map signal label to a 0-100 position on the gauge bar
    gauge_pct_map = {
        "SELLOFF": 5, "DOWN": 25, "FLAT": 50, "UP": 75, "RALLY": 95,
        "CLOSED": 50, "PRE-MKT": 50,
    }
    gauge_pct = gauge_pct_map.get(signal_lbl, 50)

    # Bar color: green for up, red for down, gray for closed/flat
    if signal_lbl in ("RALLY", "UP"):
        bar_col = "#057a55"
    elif signal_lbl in ("SELLOFF", "DOWN"):
        bar_col = "#c81e1e"
    elif signal_lbl == "FLAT":
        bar_col = "#6b7280"
    else:
        bar_col = "#9ca3af"

    # Signal pill
    pill_col = signal_col
    pill = (f'<span style="background:{pill_col};color:white;padding:2px 10px;'
            f'border-radius:4px;font-size:.7rem;font-weight:800;letter-spacing:.5px;">'
            f'{signal_lbl}</span>')

    note_html = (f'<div style="font-size:.58rem;color:#9ca3af;margin-top:1px;">'
                 f'{note}</div>') if note else ""

    return f"""
<div style="background:white;border:1px solid #e5e7eb;border-radius:8px;padding:10px 14px;margin-bottom:8px;">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;">
    <div>
      <div style="font-weight:700;font-size:.85rem;color:#111928;">{name}</div>
      {note_html}
    </div>
    <div style="text-align:right;">
      <span style="font-weight:800;font-size:1rem;color:#111928;">{value_str}</span>
      <span style="font-size:.75rem;color:#6b7280;margin-left:6px;">{chg_str}</span>
    </div>
  </div>
  <div style="display:flex;align-items:center;gap:10px;">
    <div style="font-size:.6rem;color:#9ca3af;width:40px;text-align:left;">SELLOFF</div>
    <div style="flex:1;position:relative;">
      <div style="background:#e5e7eb;border-radius:99px;height:6px;overflow:hidden;">
        <div style="width:{gauge_pct}%;background:{bar_col};height:100%;border-radius:99px;transition:width .3s;"></div>
      </div>
      <div style="position:absolute;top:-2px;left:calc({gauge_pct}% - 5px);width:10px;height:10px;
                  background:{bar_col};border-radius:50%;border:2px solid white;box-shadow:0 1px 3px rgba(0,0,0,.2);"></div>
    </div>
    <div style="font-size:.6rem;color:#9ca3af;width:36px;text-align:right;">RALLY</div>
    <div style="margin-left:8px;">{pill}</div>
  </div>
  <div style="font-size:.62rem;color:#9ca3af;margin-top:4px;">prev close {prev_str}</div>
</div>"""


# ============================================================
# MCCLELLAN / BREADTH CARD
# ============================================================

def _breadth_card(mcoscillator_text):
    """
    Build the Market Breadth card from the McClellan Oscillator email.
    Extracts key numbers and context if present; shows raw excerpt otherwise.
    """
    text = mcoscillator_text.strip() if mcoscillator_text else ""

    # Try to extract the oscillator value from the email text
    osc_match  = re.search(r"McClellan\s+Oscillator[:\s]+([+-]?\d+\.?\d*)", text, re.I)
    summ_match = re.search(r"Summation[:\s]+([+-]?\d+\.?\d*)", text, re.I)

    osc_val  = osc_match.group(1)  if osc_match  else None
    summ_val = summ_match.group(1) if summ_match else None

    # Build header line
    header_parts = []
    if osc_val:
        v = float(osc_val)
        col = "#057a55" if v > 0 else "#c81e1e"
        interp = "expanding breadth" if v > 50 else ("shrinking breadth" if v < -50 else "neutral breadth")
        header_parts.append(
            f'Oscillator: <strong style="color:{col};">{osc_val}</strong> '
            f'<span style="color:#6b7280;font-size:.65rem;">({interp})</span>'
        )
    if summ_val:
        v2 = float(summ_val)
        col2 = "#057a55" if v2 > 0 else "#c81e1e"
        header_parts.append(
            f'Summation: <strong style="color:{col2};">{summ_val}</strong>'
        )

    header_html = ""
    if header_parts:
        header_html = (f'<div style="font-size:.75rem;color:#374151;margin-bottom:6px;">'
                       + " &nbsp;·&nbsp; ".join(header_parts) + "</div>")

    # Show first 400 chars of the email as context, cleaned up
    if text and text != "McClellan Oscillator unavailable today." and "not found" not in text.lower():
        lines   = [l.strip() for l in text.splitlines() if l.strip()]
        excerpt = " ".join(lines)[:450]
        excerpt_html = (f'<div style="font-size:.72rem;color:#374151;line-height:1.6;'
                        f'background:#f9fafb;border-radius:5px;padding:6px 10px;">'
                        f'{excerpt}...</div>')
    else:
        excerpt_html = (f'<div style="font-size:.72rem;color:#9ca3af;">'
                        f'McClellan Oscillator email not received this week -- '
                        f'published weekly, usually Thursday.</div>')

    return f"""
<div class="card ag" style="margin-bottom:12px;">
  <h2>📡 Market Breadth · McClellan Oscillator
    <span style="font-weight:400;color:var(--muted);font-size:.55rem;">
      &nbsp; Weekly · Tom McClellan · above 0 = expanding breadth · below -50 = oversold
    </span>
  </h2>
  {header_html}
  {excerpt_html}
  <div style="font-size:.62rem;color:#9ca3af;margin-top:6px;">
    $SPXA200R (% of S&P 500 stocks above 200-day MA):
    <a href="https://stockcharts.com/h-sc/ui?s=%24SPXA200R" target="_blank" style="color:#1a56db;">
      check StockCharts</a>
    &nbsp;·&nbsp; &lt;25% = deeply oversold / deploy zone &nbsp;·&nbsp; &gt;75% = be selective
  </div>
</div>"""


# ============================================================
# FRED TABLE ROWS
# ============================================================

def _build_fred_rows(fred_data, trend_color_fn):
    from fred import GROUP_META
    group_order = [
        "INFLATION", "RATES", "CREDIT", "LABOR",
        "COMMODITIES", "CURRENCY", "SENTIMENT_FRED", "VALUATION",
    ]
    rows = ""
    rn   = 1
    for g in group_order:
        gm    = GROUP_META.get(g, {"icon": "", "color": "#374151", "label": g})
        items = [r for r in fred_data if r.get("group") == g]
        if not items:
            continue
        rows += (f'<tr style="background:#f9fafb;"><td colspan="9" style="padding:6px 10px;'
                 f'font-size:.64rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;'
                 f'color:{gm["color"]};border-bottom:1px solid #e5e7eb;">'
                 f'{gm["icon"]} {gm["label"]}</td></tr>')
        for r in items:
            tc    = trend_color_fn(r["label"], g, r["trend"])
            spark = _sparkline_svg(r["current"], r["mo3"], r["mo12"])
            rows += (
                f'<tr style="border-bottom:1px solid #f3f4f6;">'
                f'<td style="padding:7px 8px;text-align:center;font-size:.7rem;color:#9ca3af;">{rn}</td>'
                f'<td style="padding:7px 10px;min-width:140px;">'
                f'<div style="font-weight:600;font-size:.8rem;">{r["label"]}</div>'
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
# SI filter: show only tickers with >= 3 superinvestors (removes noise)
# ============================================================

def _build_screens_html(si_tickers, mf_tickers, am_tickers):
    all_tickers_set = sorted(set(si_tickers.keys()) | mf_tickers | am_tickers)
    all3    = []; two3 = []; si_only = []; mf_only = []; am_only = []

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

    # SI-only: filter to >= 3 managers -- removes single-fund noise
    si_only_filtered = [t for t in si_only if si_tickers.get(t, 0) >= 3]
    si_only_excluded = len(si_only) - len(si_only_filtered)

    def chip(t, style="one"):
        tags = []
        cnt  = si_tickers.get(t, 0)
        if cnt > 0:         tags.append(f"{cnt}SI")
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
        empty = '<span style="font-size:.75rem;color:#9ca3af;">None today</span>'
        fn_html = (f'<div style="font-size:.6rem;color:#9ca3af;margin-top:2px;">{footnote}</div>'
                   if footnote else "")
        return (f'<div style="margin-bottom:8px;">'
                f'<div style="font-size:.63rem;font-weight:700;color:#374151;margin-bottom:3px;">'
                f'{label} <span style="color:#9ca3af;font-weight:400;">({count})</span></div>'
                f'<div style="display:flex;flex-wrap:wrap;">'
                f'{chips_html if chips_html else empty}</div>{fn_html}</div>')

    si_footnote = (f"Showing 3+ SI managers only. {si_only_excluded} tickers with 1-2 SI managers hidden."
                   if si_only_excluded > 0 else "")

    html = (
        screen_row("🔵 All 3 Screens -- SI + MF + AM (highest conviction)",
                   "".join(chip(t, "all3") for t in all3), len(all3))
        + screen_row("🟢 2 of 3 Screens (strong convergence)",
                     "".join(chip(t, "two") for t in two3), len(two3))
        + screen_row("⭐ Superinvestors only (13F, 3+ managers)",
                     "".join(chip(t, "one") for t in si_only_filtered), len(si_only_filtered),
                     si_footnote)
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
            t12 = "↑" if c > m12 + 0.05 else "↓" if c < m12 - 0.05 else "→"
        except Exception:
            t12 = "?"
        a3 = "↑" if t3 == "▲" else "↓" if t3 == "▼" else "→"
        return f"{short}={cur}[3m:{mo3},12m:{mo12}]{a3}{t12}"

    def tlist(lst, si_d=None):
        if not lst: return "none"
        if si_d:    return "|".join(f"{t}({si_d.get(t,0)}SI)" for t in lst)
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
               run_log, run_start):
    import time
    from fred         import trend_color as _trend_color
    from market       import PE_LAST_UPDATED, compute_erp
    from ai_synthesis import parse_sections

    print("\n🎨 Building HTML dashboard...")
    secs    = parse_sections(briefing)
    now_mt  = datetime.now(MT)
    today   = now_mt.strftime("%A, %B %d, %Y")
    now_str = now_mt.strftime("%I:%M %p")

    # ---- Market values ----
    vix_val  = mkt_data["vix"]["value"];  vix_prev = mkt_data["vix"]["prev"]
    vix_lbl  = mkt_data["vix"]["label"];  vix_col  = mkt_data["vix"]["color"]
    vix_sig  = mkt_data["vix"]["signal"]
    spx_val  = mkt_data["spx"]["value"];  spx_chg  = mkt_data["spx"]["chg"]
    spx_lbl  = mkt_data["spx"]["label"];  spx_col  = mkt_data["spx"]["color"]
    spx_prev = mkt_data["spx"]["prev"]
    rut_val  = mkt_data["rut"]["value"];  rut_chg  = mkt_data["rut"]["chg"]
    rut_lbl  = mkt_data["rut"]["label"];  rut_col  = mkt_data["rut"]["color"]
    rut_prev = mkt_data["rut"]["prev"]
    pulse     = mkt_data["pulse"]
    mkt_state = mkt_data.get("market_state", "UNKNOWN")
    urth_pe   = mkt_data.get("urth_pe");  urth_stale = mkt_data.get("urth_pe_stale", False)
    efa_pe    = mkt_data.get("efa_pe");   efa_stale  = mkt_data.get("efa_pe_stale",  False)
    urth_src  = mkt_data.get("urth_pe_source", "")
    efa_src   = mkt_data.get("efa_pe_source",  "")

    # ---- F&G ----
    fg_score = fg_data.get("score", 50); fg_lbl = fg_data.get("label", "N/A")
    fg_col   = fg_data.get("color", "#6b7280"); fg_sig = fg_data.get("signal", "")

    # ---- Consumer Sentiment ----
    umich     = next((r for r in fred_data if r["label"] == "Consumer Sentiment"), None)
    umich_val = umich["current"] if umich else "N/A"
    umich_mo3 = umich["mo3"]     if umich else "N/A"
    umich_m12 = umich["mo12"]    if umich else "N/A"
    umich_sig = umich.get("sig", "") if umich else ""
    try:    umich_num = float(str(umich_val))
    except: umich_num = 55
    ucol  = "#c81e1e" if umich_num < 60 else "#6b7280" if umich_num < 75 else "#057a55"
    u_lbl = "LOW"     if umich_num < 60 else "MID"     if umich_num < 75 else "HIGH"

    # ---- CAPE + ERP ----
    cape_row = next((r for r in fred_data if r["label"] == "Shiller CAPE (US)"), None)
    cape_val = cape_row["current"] if cape_row else "N/A"
    try:    cape_num = float(re.sub(r"[^0-9.]", "", str(cape_val)))
    except: cape_num = 0
    erp, cape_yield, ten_y_rate = compute_erp(fred_data, cape_val)

    # ---- MHS ----
    mhs_score  = mhs["score"]; mhs_lbl = mhs["label"]
    mhs_col    = mhs["color"]; mhs_action = mhs["action"]
    mhs_bdown  = (
        '<span style="font-size:.63rem;color:#6b7280;margin-right:8px;">Base +50</span>'
        + "".join(f'<span style="font-size:.63rem;color:#6b7280;margin-right:8px;">{b}</span>'
                  for b in mhs["breakdown"])
    )

    # ---- Market state banner ----
    if mkt_state == "PRE":
        mkt_banner = ('<div style="background:#eef2ff;border:1px solid #c7d2fe;border-radius:5px;'
                      'padding:4px 8px;margin-bottom:7px;font-size:.72rem;color:#3730a3;">'
                      '🌅 Pre-Market · Opens 9:30 AM ET (7:30 AM MT)</div>')
    elif mkt_state == "POST":
        mkt_banner = ('<div style="background:#faf5ff;border:1px solid #e9d5ff;border-radius:5px;'
                      'padding:4px 8px;margin-bottom:7px;font-size:.72rem;color:#6d28d9;">'
                      '🌙 After-Hours</div>')
    else:
        mkt_banner = ""

    # ---- AI failure alert ----
    ai_alert = ""
    if ai_failed:
        ai_alert = ('<div style="background:#fef2f2;border:2px solid #fca5a5;border-radius:8px;'
                    'padding:10px 16px;margin-bottom:12px;display:flex;align-items:center;gap:10px;">'
                    '<span style="font-size:1.3rem;">⚠️</span><div>'
                    '<div style="font-weight:700;font-size:.82rem;color:#c81e1e;">AI Synthesis Unavailable</div>'
                    '<div style="font-size:.73rem;color:#6b7280;margin-top:2px;">'
                    'Gemini quota exhausted AND Claude Haiku fallback failed. All data sections complete. '
                    'Gemini resets at midnight UTC (6 PM MT).</div></div></div>')

    # ---- Gauge-style market performance ----
    gauge_section = f"""
<div class="card ar" style="margin-bottom:12px;">
  <h2>📈 Market Performance</h2>
  {mkt_banner}
  {_gauge_row("S&P 500", spx_val, spx_chg, spx_lbl, spx_col, spx_prev,
               "Large-cap benchmark · Yahoo Finance")}
  {_gauge_row("Russell 2000", rut_val, rut_chg, rut_lbl, rut_col, rut_prev,
               "Small-cap · risk appetite proxy · Yahoo Finance")}
  <div style="margin-top:4px;font-size:.65rem;color:#9ca3af;">⚡ {pulse}</div>
</div>"""

    # ---- Sentiment table ----
    def sr(name, val, hist, rl, rc, sig, note=""):
        nh = f'<div style="font-size:.6rem;color:#9ca3af;">{note}</div>' if note else ""
        return (f'<tr style="border-bottom:1px solid #f3f4f6;">'
                f'<td style="padding:7px 10px;"><div style="font-weight:600;font-size:.82rem;">{name}</div>{nh}</td>'
                f'<td style="padding:7px 10px;font-weight:700;font-size:.9rem;">{val}</td>'
                f'<td style="padding:7px 10px;font-size:.75rem;color:#6b7280;">{hist}</td>'
                f'<td style="padding:7px 10px;">{_badge(rl,rc)}</td>'
                f'<td style="padding:7px 10px;font-size:.72rem;color:#374151;">{sig}</td></tr>')

    try:    vix_num = float(vix_val)
    except: vix_num = 20
    vix_badge = ("CALM" if vix_num<15 else "NORMAL" if vix_num<20
                 else "CAUTIOUS" if vix_num<25 else "FEARFUL" if vix_num<30 else "PANIC")

    sent_rows = (
        sr("VIX", vix_val, f"prev {vix_prev}", vix_badge, vix_col, vix_sig,
           "CBOE · CALM<15 · NORMAL<20 · CAUTIOUS<25 · FEARFUL<30 · PANIC>=30")
        + sr("Fear & Greed", f"{fg_score}/100",
             f"1wk:{fg_data.get('prev_week','N/A')} 1mo:{fg_data.get('prev_month','N/A')} 1yr:{fg_data.get('prev_year','N/A')}",
             fg_lbl, fg_col, fg_sig, "CNN Business · 0=extreme fear · 100=extreme greed")
        + sr("Consumer Sentiment", f"{umich_val}", f"3mo:{umich_mo3} 12mo:{umich_m12}",
             u_lbl, ucol, umich_sig, "U of Michigan · avg ~75 · <60 = consumer stress")
    )

    # ---- Valuation block ----
    cape_color  = "#c81e1e" if cape_num >= 35 else "#b45309" if cape_num >= 25 else "#057a55"
    pe_updated  = PE_LAST_UPDATED.strftime("%b %Y")
    urth_disp   = f"{urth_pe:.1f}x" if urth_pe else "N/A"
    efa_disp    = f"{efa_pe:.1f}x"  if efa_pe  else "N/A"
    cape_times  = round(cape_num / 17, 1) if cape_num else "?"
    cape_status = ("⚠️ EXTREME (98th pctile)" if cape_num >= 40
                   else "⚠️ ELEVATED" if cape_num >= 30 else "→ MODERATE")
    urth_note   = (' <span style="color:#b45309;font-size:.55rem;font-weight:700;">⚠️ UPDATE NEEDED</span>'
                   if urth_stale else "")
    efa_note    = (' <span style="color:#b45309;font-size:.55rem;font-weight:700;">⚠️ UPDATE NEEDED</span>'
                   if efa_stale else "")
    pe_src_note = f"source: {urth_src}" if urth_src and "iShares CSV (live)" in urth_src else f"approx, {pe_updated}"

    if erp is not None:
        erp_col = "#c81e1e" if erp < 0 else "#b45309" if erp < 1.0 else "#057a55"
        erp_label = ("⚠️ NEGATIVE ERP" if erp < 0
                     else "→ LOW ERP" if erp < 1.0 else "✅ POSITIVE ERP")
        erp_desc  = (f"Bonds yield {abs(erp):.2f}% MORE than stocks (last seen ~2002)" if erp < 0
                     else "Stocks barely out-earn bonds -- thin margin of safety" if erp < 1.0
                     else f"Stocks yield {erp:.2f}% more than 10Y bonds")
        erp_html  = f"""
    <div style="background:#fff7ed;border:1px solid #fed7aa;border-radius:8px;padding:8px 12px;margin-top:8px;">
      <div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap;">
        <div>
          <div style="font-size:.58rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#b45309;margin-bottom:2px;">
            Equity Risk Premium (ERP = CAPE Yield - 10Y)
          </div>
          <div style="font-size:1.4rem;font-weight:800;color:{erp_col};">{erp:+.2f}%</div>
        </div>
        <div style="font-size:.7rem;color:#374151;line-height:1.6;flex:1;min-width:200px;">
          <strong style="color:{erp_col};">{erp_label}:</strong> {erp_desc}<br>
          <span style="color:#9ca3af;">CAPE yield (1/{cape_num:.0f}x) = {cape_yield:.2f}% &nbsp;vs&nbsp; 10Y Treasury = {ten_y_rate:.2f}%</span>
        </div>
      </div>
    </div>"""
    else:
        erp_html = ""

    valuation_block = f"""
<div class="card" style="margin-bottom:12px;border-left:4px solid #7c3aed;">
  <h2>📐 Global Market Valuation
    <span style="font-weight:400;color:var(--muted);font-size:.55rem;">
      &nbsp; Shiller CAPE (US) = 10yr smoothed (multpl.com) · URTH/EFA PE: {pe_src_note}
    </span>
  </h2>
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px;margin-bottom:10px;">
    <div style="text-align:center;padding:10px;background:#fdf4ff;border-radius:8px;border:1px solid #e9d5ff;">
      <div style="font-size:.58rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#7c3aed;margin-bottom:4px;">Shiller CAPE (US)</div>
      <div style="font-size:1.8rem;font-weight:800;color:{cape_color};">{cape_val}</div>
      <div style="font-size:.63rem;color:#6b7280;margin-top:3px;">Hist avg 17x · 2nd highest ever</div>
      <div style="font-size:.6rem;color:{cape_color};margin-top:2px;font-weight:600;">{cape_status}</div>
    </div>
    <div style="text-align:center;padding:10px;background:#f0fdf4;border-radius:8px;border:1px solid #bbf7d0;">
      <div style="font-size:.58rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#059669;margin-bottom:4px;">URTH (MSCI World)</div>
      <div style="font-size:1.8rem;font-weight:800;color:#059669;">{urth_disp}{urth_note}</div>
      <div style="font-size:.63rem;color:#6b7280;margin-top:3px;">incl ~70% US · trailing PE</div>
      <div style="font-size:.6rem;color:#059669;margin-top:2px;font-weight:600;">GLOBAL BLEND</div>
    </div>
    <div style="text-align:center;padding:10px;background:#eff6ff;border-radius:8px;border:1px solid #bfdbfe;">
      <div style="font-size:.58rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#1a56db;margin-bottom:4px;">EFA (ex-US Developed)</div>
      <div style="font-size:1.8rem;font-weight:800;color:#057a55;">{efa_disp}{efa_note}</div>
      <div style="font-size:.63rem;color:#6b7280;margin-top:3px;">Europe/Japan/Aus · trailing PE</div>
      <div style="font-size:.6rem;color:#057a55;margin-top:2px;font-weight:600;">✅ SIGNIFICANTLY CHEAPER</div>
    </div>
  </div>
  {erp_html}
  <div style="font-size:.67rem;color:#374151;background:#f9fafb;border-radius:5px;padding:6px 10px;line-height:1.6;margin-top:8px;">
    <strong>Why this matters:</strong> US trades at {cape_times}x the 145-year historical average (CAPE 17x).
    Ex-US developed markets ({efa_disp} PE) offer dramatically better valuation support.
    Many AM screen picks are intl ADRs (EQNR, PBR, SNY, NVO, SHEL, BP) -- cheaper valuations
    AND potential dollar weakness tailwind (DXY {next((r['current'] for r in fred_data if r['label']=='US Dollar (DXY)'), 'N/A')}).
  </div>
</div>"""

    # ---- Value screens ----
    screens_html, all3, two3, si_only, mf_only, am_only = _build_screens_html(
        si_tickers, mf_tickers, am_tickers)

    # ---- FRED table ----
    fred_rows = _build_fred_rows(fred_data, _trend_color)

    # ---- AI fun fact / learning ----
    fun_raw   = secs.get("AI FUN FACT", "").strip()
    learn_raw = secs.get("AI LEARNING", "").strip()
    if fun_raw:   fun_raw   = re.sub(r"^[-•*]\s*", "", fun_raw.splitlines()[0].strip())
    else:         fun_raw   = ("Shiller CAPE at 41x is only the 2nd highest reading in 145 years -- "
                               "exceeded only at the dot-com peak of 44.2x in Dec 1999.")
    if learn_raw: learn_raw = re.sub(r"^[-•*]\s*", "", learn_raw.splitlines()[0].strip())
    else:         learn_raw = ("Attention mechanism: LLMs weight relationships between all tokens "
                               "simultaneously, enabling context-aware reasoning across long documents.")

    # ---- Market context for Chrome extension ----
    mctx = _build_market_context(
        fred_data, fg_data, mkt_data, mhs,
        si_tickers, mf_tickers, am_tickers,
        all3, two3, si_only, mf_only, am_only,
        cape_val, urth_disp, efa_disp, erp, cape_yield, ten_y_rate,
    )

    # ---- Run log ----
    elapsed       = round(time.time() - run_start)
    run_log_items = "".join(
        f'<div style="font-size:.72rem;padding:2px 0;border-bottom:1px solid #f3f4f6;font-family:monospace;">{e}</div>'
        for e in run_log
    )
    run_log_html = f"""
<div style="margin-top:12px;">
  <button onclick="var d=this.nextElementSibling;d.style.display=d.style.display==='none'?'block':'none';"
          style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;padding:6px 14px;
                 font-size:.72rem;color:#6b7280;cursor:pointer;width:100%;text-align:left;">
    📋 View Run Log &nbsp;·&nbsp; Total time: {elapsed}s &nbsp;·&nbsp; {len(run_log)} steps
  </button>
  <div style="display:none;background:#f9fafb;border:1px solid #e5e7eb;border-top:none;
              border-radius:0 0 6px 6px;padding:10px 14px;max-height:400px;overflow-y:auto;">
    {run_log_items}
    <div style="font-size:.7rem;color:#9ca3af;margin-top:4px;padding-top:4px;border-top:1px solid #e5e7eb;">
      Total runtime: {elapsed}s &nbsp;·&nbsp; {today} {now_str} MT
    </div>
  </div>
</div>"""

    mhs_scale = (
        "🟢 DEPLOY (0-33): Panic &amp; dislocation -- aggressive deployment &nbsp;·&nbsp; "
        "🟠 SELECTIVE (34-65): Best setups only, Left Leg &lt;4 &amp; MoS &gt;25% &nbsp;·&nbsp; "
        "⛔ OVERHEATED (66-89): Build cash, trim winners &nbsp;·&nbsp; "
        "🚨 EXTREME (90-100): Most stretched since dot-com -- quality and patience above all."
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

<div class="card" style="margin-bottom:12px;border-left:4px solid {mhs_col};">
  <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;">
    <div style="flex-shrink:0;">
      <div style="font-size:.58rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:var(--muted);margin-bottom:3px;">MHS · Macro Heat Score</div>
      <div style="font-size:2rem;font-weight:800;color:{mhs_col};line-height:1;">{mhs_score}<span style="font-size:.85rem;color:var(--muted);">/100</span></div>
    </div>
    <div>
      <div style="font-size:.9rem;font-weight:700;color:{mhs_col};">{mhs_lbl}</div>
      <div style="margin-top:5px;background:#e5e7eb;border-radius:99px;height:7px;width:220px;overflow:hidden;">
        <div style="width:{mhs_score}%;background:{mhs_col};height:100%;border-radius:99px;"></div>
      </div>
      <div style="font-size:.7rem;color:#374151;margin-top:5px;">📋 {mhs_action}</div>
    </div>
    <div style="font-size:.63rem;color:var(--muted);flex:1;min-width:200px;line-height:1.8;">{mhs_bdown}</div>
  </div>
  <div style="margin-top:8px;font-size:.67rem;color:#374151;background:#f9fafb;border-radius:5px;padding:6px 10px;line-height:1.6;">
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
      <thead><tr><th>Indicator</th><th>Current</th><th>History</th><th>Level</th><th>Insight</th></tr></thead>
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

{_breadth_card(mcoscillator_text)}

<div class="card ab" style="margin-bottom:12px;">
  <h2>📋 Value Screens
    <span style="font-weight:400;color:var(--muted);font-size:.55rem;">
      &nbsp; SI=Superinvestors 13F (3+ managers, ~45d lag) · MF=Greenblatt Magic Formula (daily) · AM=Carlisle Acquirer's Multiple (daily)
    </span>
  </h2>
  {screens_html}
  <div style="font-size:.67rem;color:#6b7280;background:#f0f9ff;border-radius:5px;padding:6px 10px;line-height:1.6;margin-top:8px;">
    <strong>How to use:</strong> Blue (All 3) = highest conviction. Green (2 of 3) = strong convergence.
    Cross-reference with Finviz. Left Leg &lt;4 + MoS &gt;25% = strong setup.
    13F lag: ~45 days after quarter end. MF and AM update daily.
  </div>
</div>

<div class="card" style="margin-bottom:12px;">
  <h2>🏦 Macro Indicators
    <span style="font-weight:400;color:var(--muted);font-size:.55rem;">
      &nbsp; FRED API · Gold via Yahoo GC=F · CAPE via multpl.com · sparkline = 12mo → 3mo → today · green=good / red=bad for equities
    </span>
  </h2>
  <div style="overflow-x:auto;">
    <table style="width:100%;border-collapse:collapse;font-size:.78rem;">
      <thead><tr style="background:#f9fafb;">
        <th style="padding:6px 8px;text-align:center;font-size:.55rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">#</th>
        <th style="padding:6px 10px;text-align:left;font-size:.55rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);min-width:140px;">Indicator</th>
        <th style="padding:6px 10px;text-align:center;font-size:.55rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">Current</th>
        <th style="padding:6px 10px;text-align:center;font-size:.55rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">3 Mo</th>
        <th style="padding:6px 10px;text-align:center;font-size:.55rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">12 Mo</th>
        <th style="padding:6px 10px;text-align:center;font-size:.55rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">Dir</th>
        <th style="padding:6px 10px;text-align:center;font-size:.55rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">Trend</th>
        <th style="padding:6px 8px;font-size:.55rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);">As Of</th>
        <th style="padding:6px 10px;font-size:.55rem;text-transform:uppercase;color:var(--muted);border-bottom:2px solid var(--border);min-width:220px;">Insights</th>
      </tr></thead>
      <tbody>{fred_rows}</tbody>
    </table>
  </div>
  <div style="margin-top:8px;font-size:.62rem;color:#9ca3af;border-top:1px solid #f3f4f6;padding-top:6px;">
    Trend colors: green=good for equities, red=bad, amber=context-dependent ·
    AAII: check <a href="https://www.aaii.com/sentimentsurvey" target="_blank" style="color:#1a56db;">aaii.com</a> manually every Thursday.
  </div>
</div>

{run_log_html}

<div class="footer" style="margin-top:20px;">
  Built by <strong>Anil Abraham</strong> &nbsp;·&nbsp;
  <a href="https://fred.stlouisfed.org" target="_blank">FRED API</a> &nbsp;·&nbsp;
  <a href="https://www.cnn.com/markets/fear-and-greed" target="_blank">CNN Fear &amp; Greed</a> &nbsp;·&nbsp;
  <a href="https://www.edwardjones.com/us-en/market-news-insights/stock-market-news/daily-market-recap" target="_blank">Edward Jones</a> &nbsp;·&nbsp;
  <a href="https://www.cnbc.com/newsletters/" target="_blank">CNBC Squawk</a> &nbsp;·&nbsp;
  <a href="https://finance.yahoo.com" target="_blank">Yahoo Finance</a> &nbsp;·&nbsp;
  <a href="https://www.dataroma.com" target="_blank">Dataroma 13F</a> &nbsp;·&nbsp;
  <a href="https://www.magicformulainvesting.com" target="_blank">Magic Formula</a> &nbsp;·&nbsp;
  <a href="https://acquirersmultiple.com" target="_blank">Acquirer's Multiple</a> &nbsp;·&nbsp;
  <a href="https://www.mcoscillator.com" target="_blank">McClellan</a> &nbsp;·&nbsp;
  <a href="https://www.multpl.com/shiller-pe" target="_blank">multpl.com CAPE</a> &nbsp;·&nbsp;
  Gemini · Claude Haiku (fallback) · Not financial advice.
</div>

</div>
</body>
</html>"""

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    elapsed = round(time.time() - run_start)
    print(f"   ✅ index.html written | Total runtime: {elapsed}s")
