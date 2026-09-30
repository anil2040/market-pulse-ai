# ============================================================
# main.py -- Pipeline orchestrator
# Mean Reversion Macro Insights
# ============================================================
#
# WHAT THIS DOES:
#   Runs on GitHub Actions whenever the Claude Routine pushes a new
#   clauderoutinedata.json (weekdays about 7:45 AM Boise time), plus one
#   backup schedule in case the routine does not run. See daily.yml.
#   Fetches macro data, sentiment, value screens, news emails,
#   synthesizes with AI, checks the health of every data source, and
#   publishes an HTML dashboard to GitHub Pages. A Chrome extension
#   reads the hidden #market-context div for stock-level analysis.
#
# MODULE RESPONSIBILITY MAP (which file to edit for which bug):
#   Macro indicators (rates, CPI, gold, oil, CAPE) -> fred.py
#   VIX/SPX/PE/MHS/ERP issues                      -> market.py
#   Dataroma/Magic Formula/Acquirer's Multiple     -> screens.py
#   Email / Edward Jones                           -> news.py
#   Gemini/Haiku/AI output issues                  -> ai_synthesis.py
#   Freshness rules, warning banner logic          -> health.py
#   Dashboard display issues                       -> html_builder.py
#   Boise time / daylight saving                   -> timeutil.py
#   Schedule, secrets, git commit                  -> .github/workflows/daily.yml
#   Pipeline order/imports issues                  -> main.py (this file)
#   Claude Routine JSON issues                     -> clauderoutinedata.json (root)
#
# CACHE FILES (just two):
#   run_cache.json      Automatic fallback for every source + MHS history.
#                       Written here, committed by the workflow.
#                       RULE: an empty or failed result is NEVER written
#                       over a good saved copy (that bug hid a working
#                       fallback for weeks).
#   dataroma_cache.json Dataroma 13F list (quarterly data). See screens.py.
#   News text is no longer cached: old news is worse than no news.
#
# PIPELINE (in execution order):
#   0.  Claude Routine JSON + its REAL commit time from git history
#   1.  Macro indicators (fred.py)
#   2.  CNN Fear & Greed (inline below)
#   3.  Market data: SPX, RUT, VIX, ETF PE (market.py)
#   4.  MHS Macro Heat Score (market.py)
#   5.  Dataroma 13F, Magic Formula, Acquirer's Multiple (screens.py)
#   6.  Edward Jones, CNBC, Yahoo Morning Brief (news.py)
#   7.  Health checks on all of the above (health.py)
#   8.  AI synthesis -- Gemini -> Haiku -> fallback text (ai_synthesis.py)
#   9.  Build HTML dashboard (html_builder.py)
#   10. Save run_cache.json. The workflow commits everything in ONE commit.
#   11. If a source needing your attention is RED, exit with code 1 so the
#       GitHub run shows a red X and GitHub emails you (switch below).
#
# MHS SCALE:
#   0-33:  GREEN  DEPLOY          -- Panic/dislocation. Deploy aggressively.
#   34-65: AMBER  SELECTIVE       -- Best setups only. Left Leg <4, MoS >25%.
#   66-85: RED    OVERHEATED      -- Build cash. Trim winners.
#   86-100: DARK  EXTREME OVERH.  -- Most stretched since dot-com.
#
# NOTES:
#   AAII removed -- aaii.com blocks GitHub Actions IPs. Check manually.
#   McClellan removed Sep 2026 -- paid teaser only.
#   ISM PMI is not on FRED (ISM had it removed in 2016) -- do not revisit.
# ============================================================

import os
import sys
import json
import time
import subprocess
from datetime import datetime
import requests

from timeutil import now_mt, to_mt
import health as hl
from fred    import fetch_fred_data, FRED_SERIES, _empty_row as _fred_empty_row
from market  import (fetch_market_indicators, compute_mhs, PE_CONFIG, PE_LAST_UPDATED)
from screens import (fetch_superinvestor_buys, fetch_magic_formula,
                     fetch_acquirers_multiple)
from news    import (scrape_edward_jones, fetch_cnbc_email,
                     fetch_yahoo_morning_brief)
from ai_synthesis import synthesize_with_ai
from html_builder import build_html

# ============================================================
# CONFIGURATION
# ============================================================

ANTHROPIC_API_KEY = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
YAHOO_EMAIL       = (os.environ.get("YAHOO_EMAIL") or "").strip()
FRED_API_KEY      = (os.environ.get("FRED_API_KEY") or "").strip()

CACHE_FILE   = "run_cache.json"
ROUTINE_FILE = "clauderoutinedata.json"

# True = when any source that needs your attention is RED, the run ends with
# exit code 1. GitHub then shows a red X and emails you. The dashboard is
# still published first. Set to False to silence the emails.
NOTIFY_ON_FAILURE = True

# Global run log -- every step appends here, shown collapsed in the dashboard
RUN_LOG   = []
RUN_START = time.time()


def log(msg, status="✅"):
    """status: ✅ fine | ⚠️ cached, stale or partial | ❌ failed"""
    elapsed = round(time.time() - RUN_START)
    RUN_LOG.append(f"{status} [{elapsed}s] {msg}")


# ============================================================
# STEP 0: CLAUDE ROUTINE JSON LOADER
# ============================================================

def _routine_commit_info():
    """
    The REAL time clauderoutinedata.json was last committed, from git history,
    in Boise time. The time_collected_utc written inside the file is guessed
    by the model (it said 12:15 UTC when the run was 7:45 AM MDT), so it is
    not trusted. Returns {"date","time","label"} or None.
    """
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%cI", "--", ROUTINE_FILE],
            capture_output=True, text=True, timeout=15).stdout.strip()
        if not out:
            return None
        local = to_mt(datetime.fromisoformat(out))
        return {"date":  local.strftime("%Y-%m-%d"),
                "time":  local.strftime("%H:%M"),
                "label": local.strftime("%I:%M %p").lstrip("0")}
    except Exception as e:
        print(f"  ℹ️ Could not read routine commit time: {e}")
        return None


def load_claude_routine():
    """
    Load clauderoutinedata.json from repo root (written by the 7:40 AM MDT
    Claude Routine before this pipeline runs).

    Returns (routine_data_dict, is_fresh_bool, status_str, commit_info).
    Fresh = the file's date is today (Boise) AND, when git history is
    available, it was committed today. Stale data is still returned so the
    AI can use it with a staleness note.
    """
    print("\n📋 Loading Claude Routine data (clauderoutinedata.json)...")
    today_mt = now_mt().strftime("%Y-%m-%d")
    commit   = _routine_commit_info()

    if not os.path.exists(ROUTINE_FILE):
        print(f"  ⚠️ {ROUTINE_FILE} not found -- routine may not have run yet")
        return {}, False, "clauderoutinedata.json not found", commit

    try:
        with open(ROUTINE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)

        routine_date = data.get("date", "")
        commit_ok    = commit is None or commit["date"] == today_mt
        is_fresh     = (routine_date == today_mt) and commit_ok
        when         = f"committed {commit['label']} MT" if commit else "commit time unknown"

        if is_fresh:
            etf_pe = data.get("etf_pe", {})
            urth   = etf_pe.get("URTH", {}).get("pe_ttm", "N/A")
            efa    = etf_pe.get("EFA",  {}).get("pe_ttm", "N/A")
            sent   = data.get("futures", {}).get("sentiment", "N/A")
            print(f"  ✅ Routine data: {routine_date} ({when}) | "
                  f"URTH PE={urth} EFA PE={efa} | sentiment={sent}")
            status = f"Claude Routine: fresh ({routine_date}, {when})"
        else:
            print(f"  ⚠️ Routine data is from {routine_date} "
                  f"(today is {today_mt}; {when}) -- stale")
            status = f"Claude Routine: stale ({routine_date}, today={today_mt})"

        return data, is_fresh, status, commit

    except json.JSONDecodeError as e:
        print(f"  ❌ Routine JSON parse error: {e}")
        return {}, False, f"Claude Routine: JSON parse error ({e})", commit
    except Exception as e:
        print(f"  ❌ Routine load failed: {e}")
        return {}, False, f"Claude Routine: load failed ({e})", commit


# ============================================================
# RUN CACHE -- per-source persistent fallback
# ============================================================

def _load_cache():
    """Load run_cache.json. Returns empty dict if missing."""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"  ⚠️ Cache load failed: {e}")
    return {}


def _save_cache(cache):
    """Write run_cache.json to disk."""
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, default=str)
    except Exception as e:
        print(f"  ⚠️ Cache save failed: {e}")


def _tidy_cache(cache):
    """
    One-time and ongoing housekeeping:
      - news text is no longer cached (old news is worse than none)
      - indicator entries for series that no longer exist (renamed/replaced)
    """
    for k in ("news_ej", "news_cnbc", "news_yahoo", "news_yahoo_calendar"):
        cache.pop(k, None)
    valid = {f"fred_{c['label']}" for c in FRED_SERIES}
    for k in [k for k in cache if k.startswith("fred_") and k not in valid]:
        cache.pop(k, None)


def cache_write(cache, key, value, as_of=None):
    """
    Save a SUCCESSFUL result. Never call this with an empty value.
    fetched = the day this run stored it (Boise date). as_of = the date the
    underlying data is really from (defaults to the same day).
    """
    today = now_mt().strftime("%Y-%m-%d")
    cache[key] = {"value": value, "fetched": today, "as_of": as_of or today}


def cache_saved_today(cache, key):
    """
    Returns (value, as_of) if this key was already fetched successfully TODAY (Boise date),
    else (None, None). Used so a second run on the same day does not contact a
    third-party site again.
    """
    entry = cache.get(key)
    if entry and entry.get("value") and entry.get("fetched") == now_mt().strftime("%Y-%m-%d"):
        return entry["value"], entry.get("as_of") or entry["fetched"]
    return None, None


def cache_read(cache, key):
    """
    Returns (value, as_of_date_str) or (None, None).
    Empty values ({} or []) count as "nothing saved".
    """
    entry = cache.get(key)
    if entry and entry.get("value"):
        return entry["value"], entry.get("as_of") or entry.get("fetched", "unknown")
    return None, None


# ============================================================
# STEP 2: CNN FEAR & GREED
# (Inline -- too small to justify a separate module)
# ============================================================

def fetch_fear_greed(cache):
    print("\n😨 Fetching CNN Fear & Greed...")
    try:
        hdrs = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        fg   = requests.get(
            "https://production.dataviz.cnn.io/index/fearandgreed/graphdata",
            headers=hdrs, timeout=10
        ).json().get("fear_and_greed", {})

        score = round(float(fg.get("score", 50)))
        if   score <= 24: lbl = "Extreme Fear"; col = "#c81e1e"; sig = "Historically strong buying opportunity for mean reversion"
        elif score <= 44: lbl = "Fear";         col = "#e97316"; sig = "Pessimism elevated -- watch for entry setups"
        elif score <= 55: lbl = "Neutral";      col = "#6b7280"; sig = "No strong directional sentiment signal"
        elif score <= 74: lbl = "Greed";        col = "#059669"; sig = "Optimism elevated -- exercise caution on new positions"
        else:             lbl = "Extreme Greed";col = "#1a56db"; sig = "Overheated sentiment -- high mean reversion reversal risk"

        result = {
            "score": score, "label": lbl, "color": col, "signal": sig,
            "prev_close": round(float(fg.get("previous_close",  score))),
            "prev_week":  round(float(fg.get("previous_1_week", score))),
            "prev_month": round(float(fg.get("previous_1_month",score))),
            "prev_year":  round(float(fg.get("previous_1_year", score))),
            "cached": False,
        }
        cache_write(cache, "fear_greed", result)
        print(f"  ✅ Fear & Greed: {score}/100 ({lbl})")
        log(f"Fear & Greed: {score}/100 ({lbl})")
        return result

    except Exception as e:
        print(f"  ❌ Fear & Greed failed: {e}")
        cached_val, cached_date = cache_read(cache, "fear_greed")
        if cached_val:
            cached_val = dict(cached_val)
            cached_val["cached"]      = True
            cached_val["cached_date"] = cached_date
            print(f"  ♻️  Using cached Fear & Greed from {cached_date}")
            log(f"Fear & Greed: live fetch failed, cached from {cached_date}", "⚠️")
            return cached_val
        log(f"Fear & Greed: {str(e)[:60]}", "❌")
        return {
            "score": 50, "label": "Unavailable", "color": "#6b7280",
            "signal": "Unavailable",
            "prev_close": "N/A", "prev_week": "N/A",
            "prev_month": "N/A", "prev_year": "N/A",
            "cached": False,
        }


# ============================================================
# WRAPPERS WITH CACHE FALLBACK
# ============================================================

def _wrap_fred(cache):
    """
    Macro indicators with PER-INDICATOR cache fallback (the old code only
    used the cache if the whole fetch crashed). Any single indicator that
    comes back N/A is replaced by its last good value, flagged cached.
    """
    try:
        live = fetch_fred_data()
    except Exception as e:
        print(f"  ❌ Macro fetch failed entirely: {e}")
        live = []
    by_label = {r["label"]: r for r in live}

    out, n_live, n_cached, n_missing = [], 0, 0, 0
    for cfg in FRED_SERIES:
        r = by_label.get(cfg["label"])
        if r and r["current"] != "N/A":
            cache_write(cache, f"fred_{cfg['label']}", r)
            out.append(r)
            n_live += 1
            continue
        val, cdate = cache_read(cache, f"fred_{cfg['label']}")
        if val:
            v = dict(val)
            v["cached"]      = True
            v["cached_date"] = cdate
            out.append(v)
            n_cached += 1
            print(f"  ♻️  {cfg['label']}: live fetch failed, using cached value from {cdate}")
        else:
            out.append(r or _fred_empty_row(cfg))
            n_missing += 1

    total  = len(FRED_SERIES)
    detail = f"Macro indicators: {n_live}/{total} live"
    if n_cached:
        detail += f", {n_cached} from cache"
    if n_missing:
        detail += f", {n_missing} missing"
    log(detail, "✅" if n_live == total else ("❌" if n_missing else "⚠️"))
    return out


def _wrap_market(cache, routine_data):
    """Fetch market indicators with cache fallback. Returns (data, used_cache)."""
    try:
        data = fetch_market_indicators(routine_data=routine_data)
        cache_write(cache, "market_indicators", data)
        log(f"Market: SPX {data['spx']['value']} RUT {data['rut']['value']} "
            f"VIX {data['vix']['value']} | {data['market_state']}")
        return data, False
    except Exception as e:
        print(f"  ❌ Market indicators failed: {e}")
        cached_val, cached_date = cache_read(cache, "market_indicators")
        if cached_val:
            cached_val = dict(cached_val)
            cached_val["cached"]      = True
            cached_val["cached_date"] = cached_date
            print(f"  ♻️  Using cached market data from {cached_date}")
            log(f"Market: live fetch failed, cached from {cached_date}", "⚠️")
            return cached_val, True
        log("Market: failed, no cache", "❌")
        empty = {
            "vix": {"value": "N/A", "label": "N/A", "color": "#6b7280",
                    "signal": "", "prev": "N/A"},
            "spx": {"value": "N/A", "chg": "N/A", "label": "N/A",
                    "color": "#6b7280", "prev": "N/A"},
            "rut": {"value": "N/A", "chg": "N/A", "label": "N/A",
                    "color": "#6b7280", "prev": "N/A"},
            "urth_pe": None, "urth_pe_stale": False, "urth_pe_source": "",
            "efa_pe":  None, "efa_pe_stale":  False, "efa_pe_source":  "",
            "market_state": "UNKNOWN", "market_status_label": "", "pulse": "",
        }
        return empty, True


def _append_mhs_history(cache, mhs):
    """
    Append today's MHS score to mhs_history in run_cache.json (one entry per
    Boise calendar day, capped at 252). Framework LOCKED at v1.0.
    NOTE: on Sep 30 2026 the Fed Funds and 10Y inputs switched from monthly
    averages to daily readings. The formula did not change, but the score
    stepped up (the Sep 16 rate hike is now visible). Expect a one-time jump.
    """
    today_str = now_mt().strftime("%Y-%m-%d")
    entry = {
        "date":  today_str,
        "score": mhs["score"],
        "label": (mhs["label"]
                  .replace("🟢 ", "").replace("🟠 ", "")
                  .replace("⛔ ", "").replace("🚨 ", "")),
    }
    history = cache.get("mhs_history", [])
    if not isinstance(history, list):
        history = []
    history = [h for h in history if h.get("date") != today_str]
    history.append(entry)
    history.sort(key=lambda h: h["date"])
    cache["mhs_history"] = history[-252:]
    print(f"  ✅ MHS history: {len(cache['mhs_history'])} entries (today={mhs['score']})")


def _daily_screen(cache, key, name, fetch_fn, as_list):
    """
    One value screen that updates daily at most. Order of attempts:
      1. A copy already fetched successfully TODAY (Boise date): reuse it, no network call.
      2. Live fetch (on success it is saved with today's date).
      3. The older saved copy in run_cache.json (flagged amber on the dashboard).
    Returns (list_of_tuples, meta). An empty list is never saved over a good copy.
    """
    saved, saved_as_of = cache_saved_today(cache, key)
    if saved:
        items = as_list(saved)
        log(f"{name}: {len(items)} stocks (reused today's saved copy)")
        return items, {"source": "today_saved", "as_of": saved_as_of, "note": "saved earlier today"}
    try:
        items, m = fetch_fn()
        cache_write(cache, key, [[t, v] for t, v in items], as_of=m["as_of"])
        log(f"{name}: {len(items)} stocks")
        return items, m
    except Exception as e:              # ScreenError or anything unexpected: use the saved copy
        print(f"  ❌ {e}")
        val, as_of = cache_read(cache, key)
        if val:
            log(f"{name}: live fetch failed, saved copy from {as_of}", "⚠️")
            return as_list(val), {"source": "run_cache", "as_of": as_of,
                                  "note": f"saved copy from {as_of}"}
        log(f"{name}: failed, no saved copy", "❌")
        return [], {"source": "none", "as_of": "", "note": "no data"}


def _wrap_screens(cache):
    """
    Value screens. Each screen tries live first, then the saved copy in
    run_cache.json. Empty results are never cached and never pass as success.
    Returns (si, mf, am, screen_meta) where screen_meta = {"si": {...}, "mf": {...}, "am": {...}}
      si -- dict {ticker: count}
      mf -- ordered list of (ticker, rank) tuples
      am -- ordered list of (ticker, multiple_str) tuples
    """
    meta = {}

    # Superinvestors: live -> dataroma_cache.json (inside screens.py) -> run_cache.json
    try:
        si, m = fetch_superinvestor_buys()
        cache_write(cache, "screens_si", si, as_of=m["as_of"])
        meta["si"] = m
        log(f"Dataroma 13F: {len(si)} stocks ({m['note']})")
    except Exception as e:              # ScreenError or anything unexpected: use the saved copy
        print(f"  ❌ {e}")
        val, as_of = cache_read(cache, "screens_si")
        if val:
            si, meta["si"] = val, {"source": "run_cache", "as_of": as_of,
                                   "note": f"older saved copy from {as_of}"}
            log(f"Dataroma 13F: all live sources failed, saved copy from {as_of}", "⚠️")
        else:
            si, meta["si"] = {}, {"source": "none", "as_of": "", "note": "no data"}
            log("Dataroma 13F: no data anywhere", "❌")

    # Magic Formula and Acquirer's Multiple: once per day (see _daily_screen)
    mf, meta["mf"] = _daily_screen(
        cache, "screens_mf", "Magic Formula", fetch_magic_formula,
        lambda v: [tuple(x) for x in v] if isinstance(v[0], list)
        else [(t, i + 1) for i, t in enumerate(v)])
    am, meta["am"] = _daily_screen(
        cache, "screens_am", "Acquirer's Multiple", fetch_acquirers_multiple,
        lambda v: [tuple(x) for x in v] if isinstance(v[0], list)
        else [(t, "-") for t in v])

    return si, mf, am, meta


def _news_log(name, text, meta):
    st = meta.get("status")
    if st == "ok":
        note = f" ({meta['detail']})" if meta.get("detail") else ""
        log(f"{name}: {len(text)} chars, dated {meta.get('date') or 'n/a'}{note}",
            "⚠️" if meta.get("detail") else "✅")
    elif st == "stale":
        log(f"{name}: NOT USED -- {meta.get('detail', 'content too old')}", "⚠️")
    else:
        log(f"{name}: {meta.get('detail', 'unavailable')}", "❌")


def _wrap_news():
    """
    News/email sources. No cache: stale news is dropped, not replayed.
    Returns ej_text, cnbc_text, yahoo_text, yahoo_calendar, metas dict.
    """
    metas = {}

    def safe(name, fn):
        try:
            return fn()
        except Exception as e:                       # news.py should not raise, but never crash the run
            print(f"  ❌ {name} crashed: {e}")
            return None

    r = safe("Edward Jones", scrape_edward_jones)
    ej_text, metas["ej"] = r if r else ("", {"status": "error", "detail": "Edward Jones crashed"})
    _news_log("Edward Jones", ej_text, metas["ej"])

    r = safe("CNBC", fetch_cnbc_email)
    cnbc_text, metas["cnbc"] = r if r else ("", {"status": "error", "detail": "CNBC crashed"})
    _news_log("CNBC Morning Squawk", cnbc_text, metas["cnbc"])

    r = safe("Yahoo Brief", fetch_yahoo_morning_brief)
    yahoo_text, yahoo_cal, metas["yahoo"] = r if r else ("", "", {"status": "error",
                                                                  "detail": "Yahoo Brief crashed"})
    _news_log("Yahoo Brief", yahoo_text, metas["yahoo"])
    if yahoo_cal:
        log(f"Yahoo calendar: {len(yahoo_cal)} chars")

    return ej_text, cnbc_text, yahoo_text, yahoo_cal, metas


# ============================================================
# HEALTH ASSEMBLY
# ============================================================

def _collect_health(today, fred_data, routine_data, routine_fresh, commit,
                    mkt_data, mkt_cached, fg_data, si, mf, am, screen_meta,
                    news_metas):
    """Everything except the AI item (added after synthesis) and the calendar (added in html_builder)."""
    items = []
    items += hl.check_routine(routine_data, routine_fresh, commit["label"] if commit else None)
    items.append(hl.check_market(mkt_cached, mkt_data.get("cached_date", "")))
    items += hl.check_pe_sanity(mkt_data, PE_CONFIG, PE_LAST_UPDATED.strftime("%b %d"))
    items.append(hl.check_sentiment(fg_data))
    items += hl.check_indicators(fred_data, today)
    items += hl.check_rate_crosscheck(fred_data, routine_data, routine_fresh)
    items.append(hl.check_13f(screen_meta["si"], len(si), today))
    items.append(hl.check_screen("Magic Formula", screen_meta["mf"], len(mf), today))
    items.append(hl.check_screen("Acquirer's Multiple", screen_meta["am"], len(am), today))
    items.append(hl.check_news("Edward Jones", news_metas["ej"]))
    items.append(hl.check_news("CNBC Morning Squawk", news_metas["cnbc"]))
    items.append(hl.check_news("Yahoo Morning Brief", news_metas["yahoo"]))
    return items


def _print_and_summarize(items):
    """Print the health list to the Actions log and to the run's summary page."""
    probs = hl.problems(items)
    print("\n🩺 DATA HEALTH")
    if not probs:
        print("   ✅ All sources fresh")
    for i in probs:
        icon = "🔴" if i["level"] == hl.BAD else "🟠"
        print(f"   {icon} {i['source']}: {i['detail']}")
        log(f"HEALTH {i['level'].upper()}: {i['source']} -- {i['detail']}",
            "❌" if i["level"] == hl.BAD else "⚠️")
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write("## Data health\n\n")
                if not probs:
                    f.write("All sources fresh.\n")
                else:
                    f.write("| Level | Source | Detail |\n|---|---|---|\n")
                    for i in probs:
                        f.write(f"| {i['level']} | {i['source']} | {i['detail']} |\n")
        except Exception:
            pass


# ============================================================
# MAIN RUNNER
# ============================================================

if __name__ == "__main__":
    print("🚀 Mean Reversion Macro Insights -- Starting...")
    print("=" * 50)
    print(f"📧 Email: {'set' if YAHOO_EMAIL else 'NOT SET'}")
    print(f"🔑 Anthropic key: {'set' if ANTHROPIC_API_KEY else 'NOT SET -- Haiku fallback unavailable'}")
    print(f"🔑 FRED key: {'set' if FRED_API_KEY else 'NOT SET'}")

    now       = now_mt()
    today_d   = now.date()
    print(f"🕒 Boise time: {now.strftime('%Y-%m-%d %I:%M %p %Z')}")

    cache = _load_cache()
    _tidy_cache(cache)
    print(f"  ℹ️ Cache loaded: {len(cache)} entries")
    log("Run started")

    # Step 0: Claude Routine
    routine_data, routine_fresh, routine_status, commit = load_claude_routine()
    log(routine_status, "✅" if routine_fresh else "⚠️")

    # Step 1: macro indicators
    fred_data = _wrap_fred(cache)

    # Step 2: Fear & Greed
    fg_data = fetch_fear_greed(cache)

    # Steps 3 & 4: Market data + MHS
    mkt_data, mkt_cached = _wrap_market(cache, routine_data)
    mhs = compute_mhs(fred_data, fg_data, mkt_data)
    log(f"MHS: {mhs['score']}/100 ({mhs['label']})")
    _append_mhs_history(cache, mhs)

    # Step 5: value screens
    si_tickers, mf_list, am_list, screen_meta = _wrap_screens(cache)

    # Step 6: news & email
    ej_text, cnbc_text, yahoo_text, yahoo_calendar, news_metas = _wrap_news()

    # Step 7: health checks (before the AI so it can be told what is stale)
    HEALTH = _collect_health(today_d, fred_data, routine_data, routine_fresh, commit,
                             mkt_data, mkt_cached, fg_data,
                             si_tickers, mf_list, am_list, screen_meta, news_metas)

    # Step 8: AI synthesis
    briefing, ai_failed, ai_info = synthesize_with_ai(
        ej_text, cnbc_text, yahoo_text,
        fred_data, fg_data, mkt_data, mhs,
        si_tickers, mf_list, am_list,
        routine_data=routine_data,
        routine_fresh=routine_fresh,
        yahoo_calendar=yahoo_calendar,
        health_notes=hl.stale_notes_for_ai(HEALTH),
        today_name=now.strftime("%A"),
    )
    HEALTH.append(hl.check_ai(ai_failed, ai_info))
    if ai_failed:
        log(f"AI: all models failed -- {len(briefing)} chars of fallback text", "❌")
    elif ai_info.get("attempts"):
        log(f"AI: {ai_info['model']} used after "
            f"{', '.join(a['model'] for a in ai_info['attempts'])} failed", "⚠️")
    else:
        log(f"AI: {ai_info['model']} -- {len(briefing)} chars")

    _print_and_summarize(HEALTH)

    # Step 9: dashboard
    build_html(
        briefing, ai_failed, ej_text, cnbc_text, yahoo_text,
        fred_data, fg_data, mkt_data, mhs,
        si_tickers, mf_list, am_list,
        RUN_LOG, RUN_START, cache,
        routine_data=routine_data,
        routine_fresh=routine_fresh,
        yahoo_calendar=yahoo_calendar,
        health=HEALTH,
        screen_meta=screen_meta,
        routine_meta=commit,
        ai_info=ai_info,
    )
    log(f"Dashboard written | Total runtime: {round(time.time() - RUN_START)}s")

    # Step 10: save cache (the workflow commits index.html + caches in one commit)
    _save_cache(cache)

    print("\n" + "=" * 50)
    print("✅ Mean Reversion Macro Insights Complete!")
    print("🌐 https://anil2040.github.io/market-pulse-ai")
    print("=" * 50)

    # Step 11: red X + email if something needs your attention
    if NOTIFY_ON_FAILURE and hl.needs_notification(HEALTH):
        bad = [i for i in HEALTH if i["level"] == hl.BAD and i.get("notify")]
        print("\n🔴 Ending with exit code 1 so GitHub emails you. Needs attention:")
        for i in bad:
            print(f"   - {i['source']}: {i['detail']}")
        sys.exit(1)