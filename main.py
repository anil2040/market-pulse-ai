# ============================================================
# main.py -- Pipeline orchestrator
# Mean Reversion Macro Insights
# ============================================================
#
# WHAT THIS DOES:
#   Runs every weekday at 6:55 AM MT via GitHub Actions.
#   Fetches macro data, sentiment, value screens, news emails,
#   synthesizes with AI, and publishes an HTML dashboard to
#   GitHub Pages. A Chrome extension reads the hidden
#   #market-context div and feeds it into stock-level mean
#   reversion analysis.
#
# MODULE RESPONSIBILITY MAP (which file to edit for which bug):
#   Gold/CAPE/FRED data issues    -> fred.py
#   VIX/SPX/PE/MHS/ERP issues     -> market.py
#   Dataroma/MF/AM/cache issues   -> screens.py
#   Email/Edward Jones issues     -> news.py
#   Gemini/Haiku/AI output issues -> ai_synthesis.py
#   Dashboard display issues      -> html_builder.py
#   Pipeline order/imports issues -> main.py (this file)
#
# RUN CACHE (run_cache.json):
#   Persistent per-indicator fallback. Lives in repo root.
#   Each successful fetch writes its value + timestamp.
#   On failure, the last known good value is used instead.
#   Committed back to repo after every run so it persists.
#   Dashboard shows a "cached [date]" badge on stale values.
#   First-ever run with no cache: failed fetches show N/A.
#
# PIPELINE (in execution order):
#   1.  FRED macro indicators (fred.py)
#   2.  CNN Fear & Greed (main.py -- inline)
#   3.  Market data: SPX, RUT, VIX, ETF PE (market.py)
#   4.  MHS Macro Heat Score (market.py)
#   5.  Dataroma 13F superinvestor buys (screens.py)
#   6.  Magic Formula top 30 (screens.py)
#   7.  Acquirer's Multiple large-cap (screens.py)
#   8.  Edward Jones daily recap (news.py)
#   9.  CNBC Morning Squawk email (news.py)
#   10. Yahoo Morning Brief email (news.py)
#   11. McClellan Oscillator email (news.py)
#   12. AI synthesis -- Gemini -> Haiku -> fallback text (ai_synthesis.py)
#   13. Build HTML dashboard (html_builder.py)
#   14. Save + commit run_cache.json (main.py)
#
# MHS SCALE (updated Sep 2026):
#   0-33:  GREEN  DEPLOY          -- Panic/dislocation. Deploy aggressively.
#   34-65: AMBER  SELECTIVE       -- Best setups only. Left Leg <4, MoS >25%.
#   66-85: RED    OVERHEATED      -- Build cash. Trim winners.
#   86-100: DARK  EXTREME OVERH.  -- Quality and patience only.
#
# NOTE: AAII removed -- aaii.com blocks GitHub Actions IPs via Incapsula CDN.
#   Check manually at aaii.com/sentimentsurvey every Thursday.
# ============================================================

import os
import json
import time
import subprocess
from datetime import datetime, timezone
import requests

# Local modules
from fred    import fetch_fred_data
from market  import fetch_market_indicators, compute_mhs
from screens import (fetch_superinvestor_buys, fetch_magic_formula,
                     fetch_acquirers_multiple)
from news    import (scrape_edward_jones, fetch_cnbc_email,
                     fetch_yahoo_morning_brief, fetch_mcoscillator_email)
from ai_synthesis import synthesize_with_ai
from html_builder import build_html

# ============================================================
# CONFIGURATION
# ============================================================

GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
YAHOO_EMAIL       = os.environ.get("YAHOO_EMAIL")
FRED_API_KEY      = os.environ.get("FRED_API_KEY")

CACHE_FILE = "run_cache.json"

# Global run log -- every step appends here, shown collapsed in dashboard
RUN_LOG  = []
RUN_START = time.time()

def log(msg, status="✅"):
    elapsed = round(time.time() - RUN_START)
    RUN_LOG.append(f"{status} [{elapsed}s] {msg}")

# ============================================================
# RUN CACHE -- per-indicator persistent fallback
# ============================================================

def _load_cache():
    """Load run_cache.json from disk. Returns empty dict if missing."""
    try:
        if os.path.exists(CACHE_FILE):
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        print(f"  ⚠️ Cache load failed: {e}")
    return {}

def _save_cache(cache):
    """Write run_cache.json to disk atomically."""
    try:
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache, f, indent=2, default=str)
    except Exception as e:
        print(f"  ⚠️ Cache save failed: {e}")

def cache_write(cache, key, value):
    """
    Write a successful fetch result into the cache.
    value can be any JSON-serializable object.
    Timestamp is always today UTC ISO format (date only).
    """
    cache[key] = {
        "value":   value,
        "fetched": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

def cache_read(cache, key):
    """
    Read a cached value. Returns (value, fetched_date_str) or (None, None).
    """
    entry = cache.get(key)
    if entry and entry.get("value") is not None:
        return entry["value"], entry.get("fetched", "unknown")
    return None, None

def _commit_cache():
    """
    Git add + commit + push run_cache.json back to the repo.
    Runs silently -- failures are logged but do not abort the pipeline.
    GitHub Actions runner has write access via GITHUB_TOKEN.
    """
    try:
        subprocess.run(["git", "config", "user.email", "actions@github.com"],
                       check=True, capture_output=True)
        subprocess.run(["git", "config", "user.name", "GitHub Actions"],
                       check=True, capture_output=True)
        subprocess.run(["git", "add", CACHE_FILE],
                       check=True, capture_output=True)
        result = subprocess.run(
            ["git", "diff", "--cached", "--quiet"],
            capture_output=True)
        if result.returncode == 0:
            print("  ℹ️ Cache unchanged -- skipping commit")
            return
        subprocess.run(
            ["git", "commit", "-m",
             f"chore: update run_cache.json [{datetime.now(timezone.utc).strftime('%Y-%m-%d')}]"],
            check=True, capture_output=True)
        subprocess.run(["git", "push"], check=True, capture_output=True)
        print("  ✅ run_cache.json committed and pushed")
    except subprocess.CalledProcessError as e:
        print(f"  ⚠️ Cache commit failed: {e.stderr.decode()[:120]}")
    except Exception as e:
        print(f"  ⚠️ Cache commit error: {e}")

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
            log(f"Fear & Greed: cached ({cached_date})", "♻️")
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
# CACHE WRAPPERS FOR MODULE CALLS
# ============================================================

def _wrap_fred(cache):
    """Fetch FRED data with per-indicator cache fallback."""
    try:
        data = fetch_fred_data()
        # Write each indicator that succeeded into cache
        for r in data:
            if r["current"] != "N/A":
                cache_write(cache, f"fred_{r['label']}", r)
        ok = sum(1 for r in data if r["current"] != "N/A")
        log(f"FRED: {ok}/{len(data)} indicators fetched",
            "✅" if ok == len(data) else "⚠️")
        return data
    except Exception as e:
        print(f"  ❌ FRED fetch failed entirely: {e}")
        # Try to rebuild from cache
        rebuilt = []
        for key in [k for k in cache if k.startswith("fred_")]:
            val, fetched = cache_read(cache, key)
            if val:
                val = dict(val)
                val["cached"]      = True
                val["cached_date"] = fetched
                rebuilt.append(val)
        log(f"FRED: all failed, {len(rebuilt)} from cache", "❌")
        return rebuilt


def _wrap_market(cache):
    """Fetch market indicators with cache fallback per field."""
    try:
        data = fetch_market_indicators()
        # Cache the whole block -- it's atomic (SPX/RUT/VIX fetched together)
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
            log(f"Market: cached ({cached_date})", "♻️")
            return cached_val, True
        log(f"Market: failed, no cache", "❌")
        # Return a safe empty structure
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


def _wrap_screens(cache):
    """Fetch value screens with per-screen cache fallback."""
    # Superinvestors
    try:
        si = fetch_superinvestor_buys()
        cache_write(cache, "screens_si", si)
        log(f"Dataroma 13F: {len(si)} stocks")
    except Exception as e:
        print(f"  ❌ Dataroma failed: {e}")
        cached_val, cached_date = cache_read(cache, "screens_si")
        si = cached_val if cached_val else {}
        if cached_val:
            print(f"  ♻️  Using cached Dataroma from {cached_date}")
            log(f"Dataroma 13F: cached ({cached_date})", "♻️")
        else:
            log("Dataroma 13F: failed, no cache", "❌")

    # Magic Formula
    try:
        mf = fetch_magic_formula()
        cache_write(cache, "screens_mf", list(mf))
        log(f"Magic Formula: {len(mf)} stocks")
    except Exception as e:
        print(f"  ❌ Magic Formula failed: {e}")
        cached_val, cached_date = cache_read(cache, "screens_mf")
        mf = set(cached_val) if cached_val else set()
        if cached_val:
            print(f"  ♻️  Using cached Magic Formula from {cached_date}")
            log(f"Magic Formula: cached ({cached_date})", "♻️")
        else:
            log("Magic Formula: failed, no cache", "❌")

    # Acquirer's Multiple
    try:
        am = fetch_acquirers_multiple()
        cache_write(cache, "screens_am", list(am))
        log(f"Acquirer's Multiple: {len(am)} stocks")
    except Exception as e:
        print(f"  ❌ Acquirer's Multiple failed: {e}")
        cached_val, cached_date = cache_read(cache, "screens_am")
        am = set(cached_val) if cached_val else set()
        if cached_val:
            print(f"  ♻️  Using cached AM from {cached_date}")
            log(f"Acquirer's Multiple: cached ({cached_date})", "♻️")
        else:
            log("Acquirer's Multiple: failed, no cache", "❌")

    return si, mf, am


def _wrap_news(cache):
    """Fetch news/email sources with per-source cache fallback."""
    sources = {
        "ej":           (scrape_edward_jones,       "Edward Jones"),
        "cnbc":         (fetch_cnbc_email,           "CNBC"),
        "yahoo":        (fetch_yahoo_morning_brief,  "Yahoo Brief"),
        "mcoscillator": (fetch_mcoscillator_email,   "McClellan"),
    }
    results = {}
    for key, (fn, name) in sources.items():
        try:
            text = fn()
            cache_write(cache, f"news_{key}", text)
            log(f"{name}: {len(text)} chars")
            results[key] = text
        except Exception as e:
            print(f"  ❌ {name} failed: {e}")
            cached_val, cached_date = cache_read(cache, f"news_{key}")
            if cached_val:
                print(f"  ♻️  Using cached {name} from {cached_date}")
                log(f"{name}: cached ({cached_date})", "♻️")
                results[key] = cached_val
            else:
                log(f"{name}: failed, no cache", "❌")
                results[key] = ""
    return (results["ej"], results["cnbc"],
            results["yahoo"], results["mcoscillator"])

# ============================================================
# MAIN RUNNER
# ============================================================

if __name__ == "__main__":
    print("🚀 Mean Reversion Macro Insights -- Starting...")
    print("=" * 50)
    print(f"📧 Email: {YAHOO_EMAIL}")
    print(f"🔑 Anthropic key: {'set' if ANTHROPIC_API_KEY else 'NOT SET -- Haiku fallback unavailable'}")
    print(f"🔑 FRED key: {'set' if FRED_API_KEY else 'NOT SET'}")

    # Load persistent cache
    cache = _load_cache()
    print(f"  ℹ️ Cache loaded: {len(cache)} entries")
    log("Run started")

    # Step 1: FRED macro data
    fred_data = _wrap_fred(cache)

    # Step 2: Fear & Greed
    fg_data = fetch_fear_greed(cache)

    # Step 3 & 4: Market data + MHS
    mkt_data, mkt_cached = _wrap_market(cache)
    mhs = compute_mhs(fred_data, fg_data, mkt_data)
    log(f"MHS: {mhs['score']}/100 ({mhs['label']})")

    # Step 5-7: Value screens
    si_tickers, mf_tickers, am_tickers = _wrap_screens(cache)

    # Steps 8-11: News & email
    ej_text, cnbc_text, yahoo_text, mcoscillator_text = _wrap_news(cache)

    # Step 12: AI synthesis
    briefing, ai_failed = synthesize_with_ai(
        ej_text, cnbc_text, yahoo_text, mcoscillator_text,
        fred_data, fg_data, mkt_data, mhs,
        si_tickers, mf_tickers, am_tickers,
    )
    log(f"AI: {'fallback' if ai_failed else 'success'} -- {len(briefing)} chars",
        "❌" if ai_failed else "✅")

    # Step 13: Build HTML
    build_html(
        briefing, ai_failed, ej_text, cnbc_text, yahoo_text, mcoscillator_text,
        fred_data, fg_data, mkt_data, mhs,
        si_tickers, mf_tickers, am_tickers,
        RUN_LOG, RUN_START, cache,
    )
    log(f"Dashboard written | Total runtime: {round(time.time() - RUN_START)}s")

    # Step 14: Save + commit cache
    _save_cache(cache)
    _commit_cache()

    print("\n📧 Email disabled -- GitHub Pages dashboard is primary output")
    print("\n" + "=" * 50)
    print("✅ Mean Reversion Macro Insights Complete!")
    print("🌐 https://anil2040.github.io/market-pulse-ai")
    print("=" * 50)