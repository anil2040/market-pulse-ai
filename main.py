# ============================================================
# main.py -- Pipeline orchestrator
# Mean Reversion Macro Insights
# ============================================================
#
# WHAT THIS DOES:
# Runs every weekday at 6:55 AM MT via GitHub Actions.
# Fetches macro data, sentiment, value screens, news emails,
# synthesizes with AI, and publishes an HTML dashboard to
# GitHub Pages. A Chrome extension reads the hidden
# #market-context div and feeds it into stock-level mean
# reversion analysis.
#
# MODULE RESPONSIBILITY MAP (which file to edit for which bug):
#   Gold/CAPE/FRED data issues     -> fred.py
#   VIX/SPX/PE/MHS/ERP issues      -> market.py
#   Dataroma/MF/AM/cache issues    -> screens.py
#   Email/Edward Jones issues      -> news.py
#   Gemini/Haiku/AI output issues  -> ai_synthesis.py
#   Dashboard display issues       -> html_builder.py
#   Pipeline order/imports issues  -> main.py  (this file)
#
# PIPELINE (in execution order):
#   1.  FRED macro indicators (fred.py)
#       Gold via Yahoo GC=F, CAPE via multpl.com
#   2.  CNN Fear & Greed (main.py -- inline, too small to split)
#   3.  Market data: SPX, RUT, VIX, ETF PE (market.py)
#   4.  MHS Macro Heat Score (market.py)
#       0-33 DEPLOY | 34-65 SELECTIVE | 66-89 OVERHEATED | 90-100 EXTREME OVERHEATED
#   5.  Dataroma 13F superinvestor buys (screens.py)
#   6.  Magic Formula top 30 (screens.py)
#   7.  Acquirer's Multiple large-cap (screens.py)
#   8.  Edward Jones daily recap (news.py)
#   9.  CNBC Morning Squawk email (news.py)
#  10.  Yahoo Morning Brief email (news.py)
#  11.  McClellan Oscillator email (news.py)
#  12.  AI synthesis -- Gemini -> Haiku -> fallback text (ai_synthesis.py)
#  13.  Build HTML dashboard (html_builder.py)
#
# SECRETS REQUIRED (GitHub repo > Settings > Secrets > Actions):
#   GEMINI_API_KEY, ANTHROPIC_API_KEY,
#   YAHOO_EMAIL, YAHOO_APP_PASSWORD, FRED_API_KEY,
#   MFI_EMAIL, MFI_PASSWORD, AM_EMAIL, AM_PASSWORD
#
# MHS SCALE (Macro Heat Score):
#   0-33:   GREEN  DEPLOY          -- Panic/dislocation. Deploy aggressively.
#   34-65:  AMBER  SELECTIVE       -- Best setups only. Left Leg <4, MoS >25%.
#   66-89:  RED    OVERHEATED      -- Build cash. Trim winners. Avoid chasing.
#   90-100: DARK   EXTREME OVERH.  -- No new positions. Aggressive cash build.
#
# NOTE: AAII removed -- aaii.com blocks GitHub Actions IPs via Incapsula CDN.
# Check manually at aaii.com/sentimentsurvey every Thursday.
#
# FUN FACT: The FRED API processes over 1 million requests per day and is
# completely free. Built by the St. Louis Fed starting in 1991.
# ============================================================

import os
import time
import requests

# Local modules
from fred          import fetch_fred_data
from market        import fetch_market_indicators, compute_mhs
from screens       import (fetch_superinvestor_buys, fetch_magic_formula,
                           fetch_acquirers_multiple)
from news          import (scrape_edward_jones, fetch_cnbc_email,
                           fetch_yahoo_morning_brief, fetch_mcoscillator_email)
from ai_synthesis  import synthesize_with_ai
from html_builder  import build_html

# ============================================================
# CONFIGURATION
# ============================================================

GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
YAHOO_EMAIL       = os.environ.get("YAHOO_EMAIL")
FRED_API_KEY      = os.environ.get("FRED_API_KEY")

# Global run log -- every step appends here, shown collapsed in dashboard
RUN_LOG   = []
RUN_START = time.time()

def log(msg, status="✅"):
    """Append a timestamped entry to the run log."""
    elapsed = round(time.time() - RUN_START)
    RUN_LOG.append(f"{status} [{elapsed}s] {msg}")


# ============================================================
# STEP 2: CNN FEAR & GREED
# (Inline -- too small to justify a separate module)
# ============================================================

def fetch_fear_greed():
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

        print(f"   ✅ Fear & Greed: {score}/100 ({lbl})")
        log(f"Fear & Greed: {score}/100 ({lbl})")
        return {
            "score":      score, "label": lbl, "color": col, "signal": sig,
            "prev_close": round(float(fg.get("previous_close",   score))),
            "prev_week":  round(float(fg.get("previous_1_week",  score))),
            "prev_month": round(float(fg.get("previous_1_month", score))),
            "prev_year":  round(float(fg.get("previous_1_year",  score))),
        }
    except Exception as e:
        print(f"   ❌ Fear & Greed failed: {e}")
        log(f"Fear & Greed: {str(e)[:60]}", "❌")
        return {
            "score": 50, "label": "Unavailable", "color": "#6b7280",
            "signal": "Unavailable",
            "prev_close": "N/A", "prev_week": "N/A",
            "prev_month": "N/A", "prev_year": "N/A",
        }


# ============================================================
# MAIN RUNNER
# ============================================================

if __name__ == "__main__":
    print("🚀 Mean Reversion Macro Insights -- Starting...")
    print("=" * 50)
    print(f"📧 Email: {YAHOO_EMAIL}")
    print(f"🔑 Anthropic key: {'set' if ANTHROPIC_API_KEY else 'NOT SET -- Haiku fallback unavailable'}")
    print(f"🔑 FRED key: {'set' if FRED_API_KEY else 'NOT SET'}")
    log("Run started")

    # Step 1: FRED macro data
    fred_data = fetch_fred_data()
    ok = sum(1 for r in fred_data if r["current"] != "N/A")
    log(f"FRED: {ok}/{len(fred_data)} indicators fetched",
        "✅" if ok == len(fred_data) else "⚠️")

    # Step 2: Fear & Greed
    fg_data = fetch_fear_greed()

    # Step 3 & 4: Market data + MHS
    mkt_data = fetch_market_indicators()
    log(f"Market: SPX {mkt_data['spx']['value']} RUT {mkt_data['rut']['value']} "
        f"VIX {mkt_data['vix']['value']} | {mkt_data['market_state']}")

    mhs = compute_mhs(fred_data, fg_data, mkt_data)
    log(f"MHS: {mhs['score']}/100 ({mhs['label']})")

    # Step 5-7: Value screens
    si_tickers = fetch_superinvestor_buys()
    log(f"Dataroma 13F: {len(si_tickers)} stocks")

    mf_tickers = fetch_magic_formula()
    log(f"Magic Formula: {len(mf_tickers)} stocks")

    am_tickers = fetch_acquirers_multiple()
    log(f"Acquirer's Multiple: {len(am_tickers)} stocks")

    # Steps 8-11: News & email
    ej_text           = scrape_edward_jones()
    log(f"Edward Jones: {len(ej_text)} chars")

    cnbc_text         = fetch_cnbc_email()
    log(f"CNBC: {len(cnbc_text)} chars")

    yahoo_text        = fetch_yahoo_morning_brief()
    log(f"Yahoo Brief: {len(yahoo_text)} chars")

    mcoscillator_text = fetch_mcoscillator_email()
    log(f"McClellan: {len(mcoscillator_text)} chars")

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
        RUN_LOG, RUN_START,
    )
    log(f"Dashboard written | Total runtime: {round(time.time() - RUN_START)}s")

    print("\n📧 Email disabled -- GitHub Pages dashboard is primary output")
    print("\n" + "=" * 50)
    print("✅ Mean Reversion Macro Insights Complete!")
    print("🌐 https://anil2040.github.io/market-pulse-ai")
    print("=" * 50)
