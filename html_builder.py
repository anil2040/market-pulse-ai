# ============================================================
# html_builder.py -- HTML dashboard builder
# Mean Reversion Macro Insights
# ============================================================
#
# PUBLIC FUNCTION (called by main.py):
#   build_html(briefing, ai_failed, ej_text, cnbc_text,
#              yahoo_text,
#              fred_data, fg_data, mkt_data, mhs,
#              si_tickers, mf_tickers, am_tickers,
#              run_log, run_start, cache,
#              routine_data={}, routine_fresh=False) -> None
#
# CHANGES IN THIS VERSION (Sep 2026):
#   - Claude Routine JSON integrated:
#       ETF PE source label shows "Claude Routine (HH:MM UTC)" when fresh
#       Amber staleness banner in valuation block when routine is stale
#       Routine source note replaces "approx, Sep 2026"
#   - Hero: "Anil Abraham" removed from sub line (keep just the date)
#   - MHS EXTREME OVERHEATED posture text trimmed to macro observation only
#   - McClellan Oscillator: parameter removed (card was already gone)
#   - Market Performance: exact Chrome extension style
#     (SELLOFF/DOWN/FLAT/UP/RALLY bands, gradient bar, no "closed" language)
#   - Dir column REMOVED from FRED table (redundant with Trend sparkline)
#   - Cache badge: stale indicators show amber "cached [date]" pill
#   - MHS scale: EXTREME OVERHEATED threshold at 86
#   - AI briefing: 2-column grid (Market & Macro + Earnings & Events)
#   - SI-only filter: >= 3 managers
# ============================================================

import re
import time
from datetime import datetime, timezone, timedelta, date

MT = timezone(timedelta(hours=-6))  # Boise MDT = UTC-6 summer

# ============================================================
# HELPERS
# ============================================================

def fmt_bullets(raw):
    if not raw or not raw.strip():
        return "<li>No data available</li>"
    items = ""
    for line in raw.strip().splitlines():
        stripped = line.strip()
        # Divider sentinel inserted by _merge_macro_sections
        # Check before AND after stripping bullet prefix
        if stripped in ("---", "- ---", "* ---", "• ---"):
            items += ('    <li style="list-style:none;border-top:1px solid #e5e7eb;'
                      'margin:4px 0 4px -13px;padding:0;height:1px;"></li>\n')
            continue
        stripped = re.sub(r"^[-•*]\s*", "", stripped)
        if stripped == "---":
            items += ('    <li style="list-style:none;border-top:1px solid #e5e7eb;'
                      'margin:4px 0 4px -13px;padding:0;height:1px;"></li>\n')
            continue
        stripped = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", stripped)
        if stripped:
            items += f"    <li>{stripped}</li>\n"
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

    # Build a lookup of cache fetched dates by label so we can detect stale entries.
    # main.py writes cache as: cache["fred_<label>"] = {"value": {...}, "fetched": "YYYY-MM-DD"}
    # The indicator dict itself has no "cached" field -- we compare fetched date to today.
    fred_fetched = {}
    for key, val in cache.items():
        if key.startswith("fred_") and isinstance(val, dict):
            label = key[5:]  # strip "fred_" prefix
            fred_fetched[label] = val.get("fetched", "")

    # Amber badge staleness threshold:
    # Pipeline and FRED don't update on weekends, so never flag stale on Sat/Sun.
    # On weekdays, only flag if data is strictly older than yesterday (i.e. 2+ days old).
    # This handles Mon correctly: Friday's data is 3 days old and should be flagged.
    now_utc    = datetime.now(timezone.utc)
    is_weekday = now_utc.weekday() < 5  # 0=Mon...4=Fri
    # Stale = fetched date is earlier than yesterday (gives 1 day grace for lag)
    stale_before = (now_utc - timedelta(days=1)).strftime("%Y-%m-%d")

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

            # Amber badge: only on weekdays, only when data is 2+ days old
            fetched_date = fred_fetched.get(r["label"], "")
            is_stale     = bool(
                is_weekday and fetched_date and fetched_date < stale_before
            )
            cache_html   = _cache_badge(fetched_date) if is_stale else ""

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

def _build_screens_html(si_tickers, mf_list, am_list):
    """
    si_tickers: dict {ticker: count}
    mf_list:    ordered list of (ticker, rank) tuples -- rank 1 = best
    am_list:    ordered list of (ticker, multiple_str) tuples -- position 1 = best
    """
    mf_dict = {t: r for t, r in mf_list}   # ticker -> rank
    am_dict = {t: m for t, m in am_list}   # ticker -> multiple_str

    all_tickers_set = sorted(set(si_tickers.keys()) | set(mf_dict.keys()) | set(am_dict.keys()))
    all3 = []; two3_raw = []; si_only = []; mf_only_order = []; am_only_order = []

    for t in all_tickers_set:
        in_si = si_tickers.get(t, 0) > 0
        in_mf = t in mf_dict
        in_am = t in am_dict
        cnt   = (1 if in_si else 0) + (1 if in_mf else 0) + (1 if in_am else 0)
        if   cnt == 3: all3.append(t)
        elif cnt == 2: two3_raw.append(t)
        elif in_si:    si_only.append(t)

    # Sort two3 by conviction: MF rank asc (lower=better), then AM multiple asc, then SI count desc
    def _two3_sort_key(t):
        mf_rank = mf_dict.get(t, 9999)
        try:    am_mult = float(str(am_dict.get(t, "9999")).replace("x", ""))
        except: am_mult = 9999.0
        si_cnt  = si_tickers.get(t, 0)
        return (mf_rank, am_mult, -si_cnt, t)

    two3 = sorted(two3_raw, key=_two3_sort_key)
        # MF-only and AM-only will be built in rank order separately below

    # MF-only in rank order (those not in SI or AM)
    mf_only_order = [(t, r) for t, r in mf_list
                     if t not in set(si_tickers.keys()) and t not in am_dict]

    # AM-only in position order (those not in SI or MF)
    am_only_order = [(t, m) for t, m in am_list
                     if t not in set(si_tickers.keys()) and t not in mf_dict]

    si_only_filtered = [t for t in si_only if si_tickers.get(t, 0) >= 3]
    si_only_excluded = len(si_only) - len(si_only_filtered)

    def chip(t, style="one", extra_label=""):
        """
        Build a ticker chip.
        extra_label: rank (MF-only) or multiple (AM-only) shown in chip.
        For all3/two3 chips, MF rank and AM multiple are embedded in tag_str
        so the full signal is visible even when a ticker appears in a higher screen.
        """
        si_cnt = si_tickers.get(t, 0)
        # Build enriched tag string with rank/multiple where available
        tags = []
        if si_cnt > 0:    tags.append(f"{si_cnt}SI")
        if t in mf_dict:
            rank = mf_dict[t]
            tags.append(f"MF#{rank}")
        if t in am_dict:
            mult = am_dict[t]
            tags.append(f"AM {mult}x" if mult != "-" else "AM")
        tag_str = ",".join(tags)
        detail  = f" {extra_label}" if extra_label and extra_label not in ("", "-") else ""
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
        elif style == "am":
            return (f'<div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;'
                    f'padding:4px 8px;white-space:nowrap;display:inline-block;margin:2px;">'
                    f'<span style="font-weight:700;font-size:.78rem;color:#374151;">{t}</span>'
                    f'<span style="color:#059669;font-size:.63rem;font-weight:600;margin-left:3px;">'
                    f'{detail}</span></div>')
        elif style == "mf":
            return (f'<div style="background:#f9fafb;border:1px solid #e5e7eb;border-radius:6px;'
                    f'padding:4px 8px;white-space:nowrap;display:inline-block;margin:2px;">'
                    f'<span style="font-weight:700;font-size:.78rem;color:#374151;">{t}</span>'
                    f'<span style="color:#6366f1;font-size:.63rem;margin-left:3px;">'
                    f'{detail}</span></div>')
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

    mf_footnote = "Rank = Greenblatt composite score (earnings yield + ROIC) -- no raw number published."
    am_footnote = "Rank order = lowest Acquirer's Multiple (EV/EBIT-style) = highest conviction."

    html = (
        screen_row("🔵 All 3 Screens -- SI + MF + AM (highest conviction)",
                   "".join(chip(t, "all3") for t in all3), len(all3))
        + screen_row("🟢 2 of 3 Screens (strong convergence)",
                     "".join(chip(t, "two") for t in two3), len(two3))
        + screen_row("⭐ Superinvestors only (13F, 3+ managers)",
                     "".join(chip(t, "one") for t in si_only_filtered),
                     len(si_only_filtered), si_footnote)
        + screen_row(
            "🔮 Magic Formula only (Greenblatt, daily) -- rank order shown",
            "".join(chip(t, "mf", f"#{r}") for t, r in mf_only_order[:25]),
            len(mf_only_order), mf_footnote)
        + screen_row(
            "📐 Acquirer's Multiple only (Carlisle, daily) -- lowest multiple first",
            "".join(chip(t, "am", f"({m}x)" if m != "-" else "") for t, m in am_only_order[:25]),
            len(am_only_order), am_footnote)
    )
    return html, all3, two3, si_only_filtered, mf_only_order, am_only_order

# ============================================================
# MARKET CONTEXT STRING (hidden div for Chrome extension)
# ============================================================

def _build_market_context(fred_data, fg_data, mkt_data, mhs,
                           si_tickers, mf_only, am_only,
                           all3, two3, si_only,
                           cape_val, urth_disp, efa_disp,
                           erp, cape_yield, ten_y_rate):
    """
    mf_only: list of (ticker, rank) tuples
    am_only: list of (ticker, multiple_str) tuples
    """
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
        if si_d:
            return "|".join(f"{t}({si_d.get(t,0)}SI)" for t in lst)
        # Handle both plain strings and tuples
        return "|".join(t if isinstance(t, str) else t[0] for t in lst)

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
        f"|URTH_PE={urth_disp}(MSCIWorldInclUS)"
        f"|EFA_PE={efa_disp}(ExUSdeveloped){erp_ctx}\n"
        f"SCREENS_ALL3(highest_conviction):{tlist(all3)}\n"
        f"SCREENS_2OF3(strong_convergence):{tlist(two3)}\n"
        f"SCREENS_SI_ONLY(13F_3plus_managers):{tlist(si_only, si_tickers)}\n"
        f"SCREENS_MF_ONLY(Greenblatt_MagicFormula):{tlist(mf_only)}\n"
        f"SCREENS_AM_ONLY(Carlisle_AcquirersMultiple):{tlist(am_only)}"
    )

# ============================================================
# MACRO SECTION MERGER
# ============================================================

def _merge_macro_sections(market_macro_text, what_to_watch_text):
    """
    Merge Market & Macro and What to Watch bullets into one list.
    Adds a subtle visual separator between the two groups using a
    blank/divider bullet so the reader can see where one ends and
    the other begins, without needing a second header.
    """
    mm   = market_macro_text.strip()
    wtw  = what_to_watch_text.strip()
    if mm and wtw:
        return mm + "\n- ---\n" + wtw
    return mm or wtw


# ============================================================
# WEEKLY CALENDAR -- 5-DAY BOX LAYOUT
# ============================================================

# Day names in order for the calendar
_WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


def _parse_calendar_into_days(calendar_text):
    """
    Parse the raw calendar text into a dict {day_name: {eco: [...], earn: [...]}}.
    Handles both structured (Economic data: / Earnings calendar:) and
    plain bullet formats from the Yahoo Morning Brief.
    Returns dict with keys from _WEEKDAYS.
    """
    days = {d: {"eco": [], "earn": []} for d in _WEEKDAYS}
    if not calendar_text:
        return days

    current_day  = None
    current_type = None  # "eco" or "earn"

    for raw_line in calendar_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # Detect day header
        matched_day = next(
            (d for d in _WEEKDAYS if line.lower().startswith(d.lower())), None)
        if matched_day:
            current_day  = matched_day
            current_type = None
            continue

        if current_day is None:
            continue

        # Detect section type
        if re.match(r"^Economic data:", line, re.IGNORECASE):
            current_type = "eco"
            content = line.split(":", 1)[1].strip() if ":" in line else ""
            if content and content.lower() not in ("no notable economic data.", ""):
                days[current_day]["eco"].append(content)
            continue
        if re.match(r"^Earnings calendar:", line, re.IGNORECASE):
            current_type = "earn"
            content = line.split(":", 1)[1].strip() if ":" in line else ""
            if content and content.lower() not in ("no notable earnings.", ""):
                days[current_day]["earn"].append(content)
            continue

        # Continuation bullet or plain line
        clean = re.sub(r"^[•\-\*]\s*", "", line)
        if clean.lower() in ("no notable economic data.", "no notable earnings.", ""):
            continue
        if current_type == "eco":
            days[current_day]["eco"].append(clean)
        elif current_type == "earn":
            days[current_day]["earn"].append(clean)

    return days


def _build_weekly_calendar(cache, yahoo_calendar):
    """
    Render the weekly economic/earnings calendar as 5 day-boxes (Mon-Fri).

    PERSISTENCE LOGIC:
      Monday's Yahoo Brief has the full week (Mon-Fri).
      Tue-Fri briefs only have that day onward.
      So: on Monday, store the calendar in run_cache.json under "weekly_calendar"
      keyed by the Monday date. Tue-Fri: read from cache if same week, else
      show what we have from today's brief.

    Cache key: "weekly_calendar" -> {"week_of": "YYYY-MM-DD", "text": "..."}
    where week_of is the Monday date of the current week (ISO format).
    """
    # Determine this week's Monday
    now               = datetime.now(MT)
    days_since_monday = now.weekday()  # 0=Mon, 6=Sun
    this_monday       = (now - timedelta(days=days_since_monday)).strftime("%Y-%m-%d")

    # Compute actual calendar dates for Mon-Fri of this week for day labels
    monday_dt = now - timedelta(days=days_since_monday)
    week_dates = {}
    for i, day in enumerate(_WEEKDAYS):
        dt = monday_dt + timedelta(days=i)
        week_dates[day] = dt.strftime("%-m/%-d")  # e.g. "9/15"

    # On Monday (weekday==0): store fresh calendar from Yahoo Brief.
    # Guard lowered to > 50 chars (was 100) -- a sparse week can still be valid.
    if now.weekday() == 0:
        if yahoo_calendar and len(yahoo_calendar.strip()) > 50:
            cache["weekly_calendar"] = {
                "week_of": this_monday,
                "text":    yahoo_calendar,
            }
            print(f"  📅 Weekly calendar stored for week of {this_monday} "
                  f"({len(yahoo_calendar)} chars)")
            calendar_text = yahoo_calendar
        else:
            # Monday but no calendar -- check cache in case a prior run stored it
            stored = cache.get("weekly_calendar", {})
            if stored.get("week_of") == this_monday and stored.get("text"):
                calendar_text = stored["text"]
                print(f"  📅 Monday: yahoo_calendar empty/short "
                      f"(got {len((yahoo_calendar or '').strip())} chars), "
                      f"falling back to cached calendar for {this_monday}")
            else:
                print(f"  ⚠️  Monday: yahoo_calendar empty/short and no cache "
                      f"-- calendar section will not render. "
                      f"Check news.py Actions log for _extract_calendar output.")
                return ""
    else:
        # Tue-Fri: try cache first
        stored = cache.get("weekly_calendar", {})
        if stored.get("week_of") == this_monday and stored.get("text"):
            calendar_text = stored["text"]
            print(f"  📅 Using cached weekly calendar for week of {this_monday}")
        elif yahoo_calendar and len(yahoo_calendar.strip()) > 50:
            calendar_text = yahoo_calendar
        else:
            return ""  # Nothing to show

    days_data = _parse_calendar_into_days(calendar_text)

    # Build 5-day box layout
    today_name = now.strftime("%A")  # e.g. "Tuesday"

    def _bullet_items(raw_items, color):
        """Split semicolon-joined items into individual bullets."""
        bullets = []
        for raw in raw_items:
            # Items may be semicolon-separated (Yahoo format) or already split
            for part in raw.split(";"):
                part = part.strip()
                if part:
                    bullets.append(part)
        return "".join(
            f'<div style="display:flex;gap:4px;padding:2px 0;border-bottom:1px solid #f3f4f6;">'
            f'<span style="color:{color};font-size:.65rem;flex-shrink:0;">▸</span>'
            f'<span style="font-size:.62rem;color:#374151;line-height:1.4;">{b}</span></div>'
            for b in bullets
        )

    day_boxes = ""
    for day in _WEEKDAYS:
        data      = days_data[day]
        is_today  = (day == today_name)
        border    = "#1a56db" if is_today else "#e5e7eb"
        bg        = "#f0f6ff" if is_today else "#ffffff"
        hdr_col   = "#1a56db" if is_today else "#374151"
        date_str  = week_dates.get(day, "")
        today_tag = (' <span style="background:#1a56db;color:white;font-size:.48rem;'
                     'padding:1px 4px;border-radius:3px;font-weight:700;">TODAY</span>'
                     if is_today else "")

        eco_html = ""
        if data["eco"]:
            eco_html = (
                f'<div style="font-size:.53rem;font-weight:700;color:#b45309;'
                f'text-transform:uppercase;letter-spacing:.5px;margin:5px 0 2px;">Economic</div>'
                + _bullet_items(data["eco"], "#b45309")
            )
        else:
            eco_html = '<div style="font-size:.6rem;color:#9ca3af;margin-top:4px;">No key data</div>'

        earn_html = ""
        if data["earn"]:
            earn_html = (
                f'<div style="font-size:.53rem;font-weight:700;color:#059669;'
                f'text-transform:uppercase;letter-spacing:.5px;margin:5px 0 2px;">Earnings</div>'
                + _bullet_items(data["earn"], "#059669")
            )
        else:
            earn_html = '<div style="font-size:.6rem;color:#9ca3af;margin-top:4px;">No notable earnings</div>'

        day_boxes += f"""
<div style="background:{bg};border:1px solid {border};border-radius:8px;
            padding:8px 10px;min-width:0;overflow:hidden;">
  <div style="font-weight:700;font-size:.73rem;color:{hdr_col};
              border-bottom:1px solid {border};padding-bottom:4px;margin-bottom:4px;">
    {day[:3].upper()} <span style="font-weight:400;font-size:.62rem;color:#9ca3af;">{date_str}</span>{today_tag}
  </div>
  {eco_html}
  {earn_html}
</div>"""

    if not any(days_data[d]["eco"] or days_data[d]["earn"] for d in _WEEKDAYS):
        return ""

    return f"""
<div class="card" style="margin-bottom:12px;border-left:4px solid #059669;">
  <h2>📅 Earnings &amp; Economic Calendar for the Week</h2>
  <div style="display:grid;grid-template-columns:repeat(5,1fr);gap:8px;">
    {day_boxes}
  </div>
</div>"""


# ============================================================
# MHS HISTORY CHART
# ============================================================

def _build_mhs_history_chart(cache):
    """
    Build an inline SVG chart of the MHS score over time.
    Reads mhs_history from run_cache.json (appended each weekday run).
    Shows:
      - Daily score line
      - 20-day simple moving average overlay
      - Zone bands (DEPLOY/SELECTIVE/OVERHEATED/EXTREME)
      - Compact zone legend embedded on the right side of the SVG
      - Last 60 data points max (3 trading months)
    Returns HTML string with embedded SVG, or empty string if <3 data points.
    MHS framework locked at v1.0 -- do not change thresholds without version bump.
    """
    history = cache.get("mhs_history", [])
    if not isinstance(history, list) or len(history) < 3:
        return ""

    # Use last 60 entries
    history = sorted(history, key=lambda h: h["date"])[-60:]
    scores  = [h["score"] for h in history]
    dates   = [h["date"] for h in history]
    n       = len(scores)

    # Chart dimensions -- legend panel added on right (160px)
    LEGEND_W = 160
    W = 560; H = 160; PAD_L = 36; PAD_R = 10; PAD_T = 10; PAD_B = 24
    TOTAL_W  = W + LEGEND_W          # 720px total SVG width
    chart_w  = W - PAD_L - PAD_R     # plot area width
    chart_h  = H - PAD_T - PAD_B

    def sx(i):    return PAD_L + i / max(n - 1, 1) * chart_w
    def sy(v):    return PAD_T + (1 - v / 100) * chart_h

    # Zone bands (within chart area only, not into legend)
    zones = [
        (0,  33,  "#dcfce7", "#166534", "🟢", "DEPLOY",     "0-33"),
        (34, 65,  "#fef9c3", "#b45309", "🟠", "SELECTIVE",  "34-65"),
        (66, 85,  "#fee2e2", "#c81e1e", "⛔", "OVERHEATED", "66-85"),
        (86, 100, "#7f1d1d22","#7f1d1d","🚨", "EXTREME",    "86-100"),
    ]
    band_svg = ""
    for lo, hi, col, _, _e, _l, _r in zones:
        y1 = sy(hi); y2 = sy(lo)
        band_svg += (f'<rect x="{PAD_L}" y="{y1:.1f}" width="{chart_w}" '
                     f'height="{y2-y1:.1f}" fill="{col}" opacity="0.5"/>')

    # Threshold lines (span only chart area)
    thresh_svg = ""
    for v, col in [(86, "#7f1d1d"), (66, "#c81e1e"), (34, "#b45309"), (33, "#057a55")]:
        y = sy(v)
        thresh_svg += (f'<line x1="{PAD_L}" y1="{y:.1f}" x2="{W-PAD_R}" y2="{y:.1f}" '
                       f'stroke="{col}" stroke-width="0.5" stroke-dasharray="3,3" opacity="0.7"/>')

    # Divider between chart and legend
    divider_svg = (f'<line x1="{W+4}" y1="{PAD_T}" x2="{W+4}" y2="{H-PAD_B}" '
                   f'stroke="#e5e7eb" stroke-width="1"/>')

    # Daily score polyline
    pts = " ".join(f"{sx(i):.1f},{sy(s):.1f}" for i, s in enumerate(scores))
    line_svg = (f'<polyline points="{pts}" fill="none" stroke="#1a56db" '
                f'stroke-width="1.5" stroke-linejoin="round" opacity="0.8"/>')

    # 20-day SMA
    sma_pts = []
    for i in range(n):
        if i >= 19:
            avg = sum(scores[i-19:i+1]) / 20
            sma_pts.append(f"{sx(i):.1f},{sy(avg):.1f}")
    if len(sma_pts) >= 2:
        sma_svg = (f'<polyline points="{" ".join(sma_pts)}" fill="none" '
                   f'stroke="#b45309" stroke-width="2" stroke-linejoin="round"/>')
    else:
        sma_svg = ""

    # Dot for latest point
    latest_x = sx(n - 1); latest_y = sy(scores[-1])
    latest_col = ("#7f1d1d" if scores[-1] >= 86 else
                  "#c81e1e" if scores[-1] >= 66 else
                  "#b45309" if scores[-1] >= 34 else "#057a55")
    dot_svg = (f'<circle cx="{latest_x:.1f}" cy="{latest_y:.1f}" r="4" '
               f'fill="{latest_col}" stroke="white" stroke-width="1.5"/>')

    # Y axis labels
    yaxis_svg = ""
    for v in [0, 33, 66, 86, 100]:
        y = sy(v)
        yaxis_svg += (f'<text x="{PAD_L-4}" y="{y+4:.1f}" text-anchor="end" '
                      f'font-size="8" fill="#9ca3af">{v}</text>')

    # X axis date labels (show first, middle, last)
    xaxis_svg = ""
    for idx in [0, n // 2, n - 1]:
        if idx < n:
            label = dates[idx][5:]  # MM-DD
            x     = sx(idx)
            xaxis_svg += (f'<text x="{x:.1f}" y="{H-4}" text-anchor="middle" '
                          f'font-size="8" fill="#9ca3af">{label}</text>')

    # ---- Right-side legend panel ----
    LX = W + 14           # legend content left edge
    LY0 = PAD_T + 2       # top of legend content

    # Header: "SCALE  lower = better"
    legend_svg = (
        f'<text x="{LX}" y="{LY0 + 7}" font-size="7.5" font-weight="700" '
        f'fill="#6b7280" font-family="monospace" letter-spacing="0.5">SCALE</text>'
        f'<text x="{LX + 40}" y="{LY0 + 7}" font-size="6.5" fill="#9ca3af" '
        f'font-family="monospace"> lower = better</text>'
    )

    # Four zone rows: emoji  LABEL  range
    row_h  = 30   # vertical spacing per row
    for i, (lo, hi, band_col, text_col, emoji, label, rng) in enumerate(zones):
        ry = LY0 + 18 + i * row_h
        # Colored swatch square
        legend_svg += (
            f'<rect x="{LX}" y="{ry}" width="9" height="9" '
            f'fill="{text_col}" rx="1.5" opacity="0.85"/>'
        )
        # Emoji
        legend_svg += (
            f'<text x="{LX + 13}" y="{ry + 8}" font-size="9">{emoji}</text>'
        )
        # Label (bold, zone color)
        legend_svg += (
            f'<text x="{LX + 28}" y="{ry + 8}" font-size="8" font-weight="700" '
            f'fill="{text_col}" font-family="monospace">{label}</text>'
        )
        # Range (muted, smaller)
        legend_svg += (
            f'<text x="{LX + 28}" y="{ry + 18}" font-size="7" '
            f'fill="#9ca3af" font-family="monospace">{rng}</text>'
        )

    # Bottom note: base=50
    legend_svg += (
        f'<text x="{LX}" y="{H - PAD_B - 2}" font-size="6.5" '
        f'fill="#9ca3af" font-family="monospace">base=50</text>'
    )

    latest_score = scores[-1]
    days_shown   = n

    return f"""
<div style="margin-top:12px;padding-top:10px;border-top:1px solid #e5e7eb;">
  <div style="font-size:.6rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;
              color:#6b7280;margin-bottom:4px;">
    MHS TREND ({days_shown}d) &nbsp;·&nbsp;
    <span style="color:#b45309;">orange = 20-day avg</span> &nbsp;·&nbsp;
    <span style="color:#1a56db;">blue = daily</span>
  </div>
  <svg width="{TOTAL_W}" height="{H}" viewBox="0 0 {TOTAL_W} {H}"
       style="width:100%;max-width:{TOTAL_W}px;height:auto;display:block;"
       xmlns="http://www.w3.org/2000/svg">
    {band_svg}
    {thresh_svg}
    {line_svg}
    {sma_svg}
    {dot_svg}
    {yaxis_svg}
    {xaxis_svg}
    <text x="{latest_x:.1f}" y="{latest_y-8:.1f}" text-anchor="middle"
          font-size="9" font-weight="bold" fill="{latest_col}">{latest_score}</text>
    {divider_svg}
    {legend_svg}
  </svg>
  <div style="font-size:.58rem;color:#9ca3af;margin-top:2px;">
    Framework v1.0 locked · zone thresholds fixed · comparable across all dates shown
  </div>
</div>"""


# ============================================================
# MAIN BUILD FUNCTION
# ============================================================

def build_html(briefing, ai_failed, ej_text, cnbc_text, yahoo_text,
               fred_data, fg_data, mkt_data, mhs,
               si_tickers, mf_list, am_list,
               run_log, run_start, cache=None,
               routine_data=None, routine_fresh=False,
               yahoo_calendar=""):

    from fred    import trend_color as _trend_color
    from market  import PE_LAST_UPDATED, compute_erp
    from ai_synthesis import parse_sections

    if cache is None:
        cache = {}
    if routine_data is None:
        routine_data = {}

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
// chg computed manually as (price - prev) / prev to avoid Yahoo's
// regularMarketChangePercent which resets to 0 at open/close/pre-market.
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
        // Always compute manually -- never trust regularMarketChangePercent
        var chg  = pv ? (p - pv) / pv * 100 : 0;
        var state = meta.marketState || "UNKNOWN";
        callback(null, {{price:p, prev:pv, chg:chg, state:state}});
      }})
      .catch(function(e) {{ callback(e, null); }});
  }}

  function refresh() {{
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

    var el;
    el = document.getElementById("spx-val");  if(el) el.textContent = spx.price.toLocaleString("en-US", {{maximumFractionDigits:0}});
    el = document.getElementById("spx-chg");  if(el) {{ el.textContent = spxChgStr; el.style.color = spxCol; }}
    el = document.getElementById("spx-pill"); if(el) {{ el.textContent = spxLbl; el.style.background = spxCol; }}
    updateDot("spx-dot", spxLbl, spxCol);

    el = document.getElementById("rut-val");  if(el) el.textContent = rut.price.toLocaleString("en-US", {{maximumFractionDigits:0}});
    el = document.getElementById("rut-chg");  if(el) {{ el.textContent = rutChgStr; el.style.color = rutCol; }}
    el = document.getElementById("rut-pill"); if(el) {{ el.textContent = rutLbl; el.style.background = rutCol; }}
    updateDot("rut-dot", rutLbl, rutCol);

    el = document.getElementById("vix-val");  if(el) el.textContent = vix.price.toFixed(2);
    el = document.getElementById("vix-prev"); if(el) {{ el.textContent = "prev " + vix.prev.toFixed(2); el.style.color = vixCol; }}
    el = document.getElementById("vix-pill"); if(el) {{ el.textContent = vixLbl; el.style.background = vixCol; }}
    el = document.getElementById("vix-sig");  if(el) el.textContent = vixSig(vix.price);

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

    var now = new Date();
    var hh = now.getHours(); var mm = now.getMinutes();
    var ampm = hh >= 12 ? "PM" : "AM"; hh = hh % 12 || 12;
    var ts = "refreshed " + hh + ":" + (mm < 10 ? "0" : "") + mm + " " + ampm;
    el = document.getElementById("mkt-refresh-ts"); if(el) el.textContent = ts;

    var day = now.getDay();
    var minOfDay = now.getHours() * 60 + now.getMinutes();
    var mktOpen  = 7 * 60 + 30;
    var mktClose = 16 * 60 + 5;
    if (day >= 1 && day <= 5 && minOfDay >= mktOpen && minOfDay < mktClose) {{
      setTimeout(refresh, 60000);
    }}
  }}

  refresh();
}})();
</script>"""

    # Sentiment table
    fg_cache_html    = _cache_badge(fg_cdate) if fg_cached else ""
    umich_cache_html = _cache_badge(umich.get("cached_date","")) if (umich and umich.get("cached")) else ""

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

    # ============================================================
    # VALUATION BLOCK -- ETF PE source note from Claude Routine
    # ============================================================
    cape_color  = "#c81e1e" if cape_num >= 35 else "#b45309" if cape_num >= 25 else "#057a55"
    urth_disp   = f"{urth_pe:.1f}x" if urth_pe else "N/A"
    efa_disp    = f"{efa_pe:.1f}x"  if efa_pe  else "N/A"
    cape_times  = round(cape_num / 17, 1) if cape_num else "?"
    cape_status = ("EXTREME (98th pctile)" if cape_num >= 40
                   else "ELEVATED"          if cape_num >= 30 else "MODERATE")
    urth_note   = (' <span style="color:#b45309;font-size:.55rem;font-weight:700;">UPDATE NEEDED</span>'
                   if urth_stale else "")
    efa_note    = (' <span style="color:#b45309;font-size:.55rem;font-weight:700;">UPDATE NEEDED</span>'
                   if efa_stale else "")

    # PE source note: Claude Routine > iShares CSV > PE_CONFIG fallback
    # Show just "Claude Routine" with no timestamp -- it always runs at 4am MT
    if urth_src and "Claude Routine" in urth_src:
        pe_src_note = "Claude Routine"
    elif urth_src and "iShares CSV" in urth_src:
        pe_src_note = "iShares CSV (live)"
    else:
        pe_updated  = PE_LAST_UPDATED.strftime("%b %Y")
        pe_src_note = f"PE_CONFIG fallback ({pe_updated})"

    # Routine staleness banner for valuation block
    routine_stale_banner = ""
    if routine_data and not routine_fresh:
        routine_date = routine_data.get("date", "unknown")
        routine_stale_banner = (
            f'<div style="background:#fff7ed;border:1px solid #fed7aa;border-radius:5px;'
            f'padding:4px 8px;margin-bottom:8px;font-size:.72rem;color:#b45309;">'
            f'Pre-market data from {routine_date} -- today\'s routine may not have run yet</div>'
        )

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
  {routine_stale_banner}
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

    # Value screens -- mf_list and am_list are ordered lists of tuples
    screens_html, all3, two3, si_only, mf_only, am_only = _build_screens_html(
        si_tickers, mf_list, am_list)

    # FRED table
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
        si_tickers, mf_only, am_only,
        all3, two3, si_only,
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

    mhs_chart_html = _build_mhs_history_chart(cache)

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
.card h2{{font-size:.76rem;font-weight:700;letter-spacing:1.2px;text-transform:uppercase;color:var(--blue);margin-bottom:9px;padding-bottom:7px;border-bottom:2px solid var(--border);}}
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
  <div class="sub">{today}</div>
  <div class="ts">Updated {now_str} MT · anil2040.github.io/market-pulse-ai</div>
</div>

<div class="container">
  {ai_alert}

  <!-- 1. AI Fun Fact + AI Learning -- quick daily orientation -->
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

  <!-- 2. Weekly Calendar -- what events matter this week, read before anything else -->
  {_build_weekly_calendar(cache, yahoo_calendar)}

  <!-- 3. MHS -- macro posture, sets the decision framework -->
  <div class="card" style="margin-bottom:12px;border-left:4px solid {mhs_col};">
    <h2>🌡 MHS · Macro Heat Score</h2>
    <div style="display:flex;align-items:center;gap:16px;flex-wrap:wrap;">
      <div style="flex-shrink:0;">
        <div style="font-size:.58rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;
                    color:var(--muted);margin-bottom:3px;">Score</div>
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
    {mhs_chart_html}
  </div>

  <!-- 4. Market Performance + Sentiment -- where are we right now -->
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

  <!-- 5. Global Valuation -- the structural backdrop -->
  {valuation_block}

  <!-- 6. Market & Macro + What to Watch -- AI interpretation, true 2-column -->
  <div class="card ab" style="margin-bottom:12px;">
    <h2>📊 Market &amp; Macro
      <span style="font-weight:400;color:var(--muted);font-size:.55rem;">
        · macro interpretation + what to watch
      </span>
    </h2>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px;">
      <div>
        <div style="font-size:.53rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;
                    color:var(--blue);margin-bottom:6px;">Macro Interpretation</div>
        <ul style="margin:0;">
          {fmt_bullets(secs.get("MARKET AND MACRO",""))}
        </ul>
      </div>
      <div>
        <div style="font-size:.53rem;font-weight:700;letter-spacing:1px;text-transform:uppercase;
                    color:#059669;margin-bottom:6px;">What to Watch</div>
        <ul style="margin:0;">
          {fmt_bullets(secs.get("WHAT TO WATCH",""))}
        </ul>
      </div>
    </div>
  </div>

  <!-- 7. Value Screens -- who to look at -->
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
      Green (2 of 3) = strong convergence. Sorted by MF rank then AM multiple.
      Cross-reference with Finviz. Left Leg &lt;4 + MoS &gt;25% = strong setup.
      13F lag: ~45 days after quarter end. MF and AM update daily.
    </div>
  </div>

  <!-- 8. Macro Indicators -- detailed reference table -->
  <div class="card" style="margin-bottom:12px;">
    <h2>🏦 Macro Indicators
      <span style="font-weight:400;color:var(--muted);font-size:.55rem;">
        sparkline = 12mo → 3mo → today · green=good / red=bad for equities ·
        ⚠️ in Insights = interpretive signal · amber pill = cached (live FRED fetch failed)
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