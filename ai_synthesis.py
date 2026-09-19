# ============================================================
# ai_synthesis.py -- AI briefing synthesis
# Mean Reversion Macro Insights
# ============================================================
#
# PUBLIC FUNCTIONS (called by main.py):
#   synthesize_with_ai(...) -> (briefing_str, ai_failed_bool)
#   parse_sections(text)    -> dict {section_name: content_str}
#
# PROMPT PHILOSOPHY:
#   Do NOT restate indicator values -- those are already in the
#   dashboard tables. The AI must interpret what the combination
#   means, identify tensions or confirmations between signals,
#   and surface non-obvious implications for a value investor.
#   Regurgitation = failure.
#
#   EARNINGS AND EVENTS rule: only reference events with a
#   specific date from today's news sources. No filler, no
#   generic context, no recycled headlines.
#
# CLAUDE ROUTINE INTEGRATION:
#   Pre-market intelligence (futures, sentiment, rates, sector
#   movers, global markets, macro events, open_focus) from the
#   4am Claude Routine is injected into the prompt. When fresh,
#   this provides today's context. When stale, it is included
#   with a staleness note so the AI can weight it accordingly.
#
# FALLBACK CHAIN:
#   1. gemini-3.6-flash  (free, 20 RPD -- resets midnight UTC = 6 PM MT)
#   2. gemini-1.5-flash  (free, separate quota pool)
#   3. claude-haiku-4-5  (paid ~$0.003/run -- logged prominently)
#   4. structured text   (always works, no AI narrative)
# ============================================================

import os
import re
import concurrent.futures
import requests
import google.genai as genai

GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# ============================================================
# MODEL CALLERS
# ============================================================

def _call_gemini(prompt, model):
    client = genai.Client(api_key=GEMINI_API_KEY)
    return client.interactions.create(model=model, input=prompt).output_text

def _call_haiku(prompt):
    if not ANTHROPIC_API_KEY:
        raise Exception("ANTHROPIC_API_KEY secret not set in GitHub repo")
    try:
        import anthropic
        client  = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model     = "claude-haiku-4-5",
            max_tokens= 1000,
            messages  = [{"role": "user", "content": prompt}],
        )
        return message.content[0].text
    except ImportError:
        print("  ℹ️ anthropic library not found -- using direct HTTP to Anthropic API")
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key":         ANTHROPIC_API_KEY,
                "anthropic-version": "2023-06-01",
                "content-type":      "application/json",
            },
            json={
                "model":      "claude-haiku-4-5",
                "max_tokens": 1000,
                "messages":   [{"role": "user", "content": prompt}],
            },
            timeout=90,
        )
        if resp.status_code != 200:
            raise Exception(
                f"Anthropic API error {resp.status_code}: {resp.text[:200]}")
        return resp.json()["content"][0]["text"]

# ============================================================
# ROUTINE DATA FORMATTER
# ============================================================

def _format_routine_block(routine_data, routine_fresh):
    """
    Format clauderoutinedata.json into a clean prompt block.
    Always included when routine_data is non-empty.
    Staleness note added when not fresh so AI can weight accordingly.
    """
    if not routine_data:
        return ""

    freshness_note = (
        "" if routine_fresh
        else f"  NOTE: This data is from {routine_data.get('date', 'unknown')} -- "
             f"NOT today. Weight accordingly but do not ignore.\n"
    )

    # Futures
    futures = routine_data.get("futures", {})
    sp5   = futures.get("sp500",    {})
    nq    = futures.get("nasdaq100",{})
    dw    = futures.get("dow",      {})
    sent  = futures.get("sentiment", "N/A")

    def fmt_future(d):
        if not d:
            return "N/A"
        chg = d.get("change_pct", 0)
        direction = d.get("direction", "")
        return f"{chg:+.2f}% ({direction})" if isinstance(chg, (int, float)) else f"{chg} ({direction})"

    futures_str = (f"S&P {fmt_future(sp5)} | Nasdaq {fmt_future(nq)} | "
                   f"Dow {fmt_future(dw)} | Sentiment: {sent.upper()}")

    # Rates & commodities
    rc    = routine_data.get("rates_commodities", {})
    t10y  = rc.get("treasury_10yr_pct", "N/A")
    crude = rc.get("crude_oil_usd", "N/A")
    ctype = rc.get("crude_oil_type", "WTI")

    # Macro events
    events = routine_data.get("macro_events", [])
    events_str = " / ".join(events) if events else "None reported"

    # Sector movers
    sm      = routine_data.get("sector_movers", {})
    leaders = sm.get("leading", [])
    laggers = sm.get("lagging", [])

    def fmt_sector(lst):
        parts = []
        for s in lst:
            name   = s.get("sector", "")
            chg    = s.get("change_pct", 0)
            reason = s.get("reason", "")
            chg_str = f"{chg:+.2f}%" if isinstance(chg, (int, float)) else str(chg)
            parts.append(f"{name} {chg_str} ({reason})")
        return " | ".join(parts) if parts else "N/A"

    # Global markets
    gm     = routine_data.get("global_markets", {})
    europe = gm.get("europe", {})
    asia   = gm.get("asia",   {})

    def fmt_global(d):
        if not d:
            return "N/A"
        idx = d.get("index", "")
        chg = d.get("change_pct", 0)
        direction = d.get("direction", "")
        chg_str = f"{chg:+.2f}%" if isinstance(chg, (int, float)) else str(chg)
        return f"{idx} {chg_str} ({direction})"

    # Open focus
    open_focus = routine_data.get("open_focus", "")

    # ETF PE (for reference -- market.py already consumed these)
    etf_pe  = routine_data.get("etf_pe", {})
    urth_pe = etf_pe.get("URTH", {}).get("pe_ttm", "N/A")
    efa_pe  = etf_pe.get("EFA",  {}).get("pe_ttm", "N/A")

    block = f"""
PRE-MARKET INTELLIGENCE (Claude Routine, collected {routine_data.get('time_collected_utc','?')} UTC):
{freshness_note}FUTURES: {futures_str}
10Y TREASURY: {t10y}% | CRUDE: ${crude} ({ctype})
GLOBAL: Europe {fmt_global(europe)} | Asia {fmt_global(asia)}
SECTOR LEADERS: {fmt_sector(leaders)}
SECTOR LAGGARDS: {fmt_sector(laggers)}
MACRO EVENTS TODAY: {events_str}
OPEN FOCUS: {open_focus}
ETF PE (routine source): URTH={urth_pe}x | EFA={efa_pe}x"""

    return block.strip()

# ============================================================
# MAIN SYNTHESIS
# ============================================================

def synthesize_with_ai(ej_text, cnbc_text, yahoo_text,
                       fred_data, fg_data, mkt_data, mhs,
                       si_tickers, mf_list, am_list,
                       routine_data=None, routine_fresh=False,
                       yahoo_calendar=""):
    """
    Build prompt from all fetched data and call AI models in fallback order.
    routine_data: parsed clauderoutinedata.json (or {} if unavailable)
    routine_fresh: True if routine date matches today MT
    Returns (briefing_str, ai_failed_bool).
    ai_failed=True means structured fallback was used (no AI narrative).
    """
    print("\n🤖 Sending to AI synthesis...")

    if routine_data is None:
        routine_data = {}

    fred_summary = "\n".join([
        f"- {r['label']}: {r['current']} (3mo:{r['mo3']} 12mo:{r['mo12']} trend:{r['trend']})"
        for r in fred_data if r["current"] != "N/A"
    ])

    # mf_list: [(ticker, rank), ...] -- convert to set for membership tests
    # am_list: [(ticker, multiple_str), ...] -- convert to dict for lookup
    mf_set = {t for t, _ in mf_list}
    am_dict = dict(am_list)  # ticker -> multiple_str

    all_tickers = sorted(set(si_tickers.keys()) | mf_set | set(am_dict.keys()))
    overlap = []
    for t in all_tickers:
        tags = []
        if si_tickers.get(t, 0) > 0: tags.append(f"{si_tickers[t]}SI")
        if t in mf_set:               tags.append("MF")
        if t in am_dict:              tags.append("AM")
        if len(tags) >= 2:
            overlap.append(f"{t}({','.join(tags)})")

    cape_val = next(
        (r["current"] for r in fred_data if r["label"] == "Shiller CAPE (US)"), "N/A")
    urth_str = f"URTH(MSCI World incl US) PE: {mkt_data.get('urth_pe', 'N/A')}x"
    efa_str  = f"EFA(MSCI EAFE ex-US) PE: {mkt_data.get('efa_pe', 'N/A')}x"

    routine_block = _format_routine_block(routine_data, routine_fresh)

    # Calendar block for prompt
    calendar_block = ""
    if yahoo_calendar and len(yahoo_calendar.strip()) > 50:
        calendar_block = f"\nWEEK AHEAD (from Yahoo Morning Brief -- use specific dates):\n{yahoo_calendar[:2000]}"

    prompt = f"""You are a sharp financial analyst writing a morning briefing for a
deep-value mean reversion investor (Greenblatt, Carlisle, Howard Marks, Burry, Pabrai
style). US-focused but holds international ADRs. Long-term holder, not a trader.

STRICT OUTPUT FORMAT -- use EXACTLY these 4 headers, nothing else:

MARKET AND MACRO
WHAT TO WATCH
AI FUN FACT
AI LEARNING

CRITICAL RULES -- READ CAREFULLY:

1. DO NOT restate raw indicator numbers. VIX, SPX %, CAPE, MHS score, F&G score --
   these are already shown in the dashboard tables. The investor sees them before
   reading your briefing. Repeating them is noise.

2. INTERPRET, do not describe. Instead of "VIX is 15 indicating calm markets",
   say what that calm means for a value investor today given everything else --
   e.g. "Low volatility with negative ERP is an unusual combination -- cheap
   protection available while stocks price in perfection."

3. Look for TENSIONS and CONFIRMATIONS between signals. When two indicators
   point different directions (e.g. credit spreads tight but gold rising),
   name the tension and what it might mean. When multiple signals align
   (e.g. CAPE extreme AND ERP negative AND F&G fear), say what that
   combination historically implies.

4. MARKET AND MACRO: Your primary section. 6-8 bullets. Synthesize the
   FRED/MHS macro picture WITH the pre-market intelligence (futures, sectors,
   global moves, open focus). Surface what the COMBINATION means.
   If there is a key macro event this week (Fed decision, CPI, jobs),
   mention it here with the date and its implications.

5. WHAT TO WATCH: 3-4 bullets. Actionable mean reversion lens.
   Reference specific tickers from high-conviction screens where relevant.
   Name the macro trip wires -- what data prints or events would shift
   the MHS meaningfully up or down?

6. AI FUN FACT: 1 surprising fact about AI, markets, or investing history.
   Max 25 words. Not about the current data.

7. AI LEARNING: 1 AI/ML concept in plain English, relevant to investing
   or data analysis. Max 30 words.

8. Each bullet: dash (-) prefix, max 20 words, no bold, no markdown headers.

DATA (for interpretation -- do NOT repeat these numbers verbatim):

MHS: {mhs['score']}/100 -- {mhs['label']} | Posture: {mhs['action']}
VALUATION: US CAPE={cape_val} (hist avg 17x) | {urth_str} | {efa_str}
MARKET PULSE: {mkt_data['pulse']}

MACRO INDICATORS:
{fred_summary}

HIGH CONVICTION SCREENS (2+ screens overlap):
{', '.join(overlap[:15]) if overlap else 'None today'}

{routine_block}

{routine_block}
{calendar_block}

NEWS SOURCES (for macro context -- no stock-specific stories):
EDWARD JONES: {ej_text[:800]}
CNBC SQUAWK: {cnbc_text[:600]}
YAHOO BRIEF: {yahoo_text[:600]}
"""

    models_to_try = [
        ("gemini-3.6-flash", "Gemini 3.6 Flash (free tier)",
         lambda: _call_gemini(prompt, "gemini-3.6-flash")),
        ("gemini-1.5-flash", "Gemini 1.5 Flash (free tier)",
         lambda: _call_gemini(prompt, "gemini-1.5-flash")),
        ("claude-haiku-4-5", "Claude Haiku 4.5 (paid ~$0.003)",
         lambda: _call_haiku(prompt)),
    ]

    for model_id, model_name, call_fn in models_to_try:
        try:
            print(f"  Trying {model_name}...")
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                fut      = ex.submit(call_fn)
                briefing = fut.result(timeout=90)
            if model_id == "claude-haiku-4-5":
                print(f"  ✅ Claude Haiku used as fallback: {len(briefing)} chars")
                print("  💰 Estimated cost: ~$0.003 (input ~2000 tokens + output ~400 tokens)")
            else:
                print(f"  ✅ {model_name}: {len(briefing)} chars")
            return briefing, False
        except concurrent.futures.TimeoutError:
            print(f"  ⚠️ {model_name} timed out (>90s)")
        except Exception as e:
            print(f"  ⚠️ {model_name} failed: {str(e)[:100]}")

    print("  ❌ All AI models failed -- using structured fallback")
    fallback = """MARKET AND MACRO
- AI synthesis unavailable -- all models failed or quota exhausted today
- All data sections below are complete and current -- no data loss

EARNINGS AND EVENTS
- Check Yahoo Morning Brief and CNBC Squawk sections for today's calendar
- Edward Jones recap has previous session summary

WHAT TO WATCH
- Review MHS score and FRED indicator table -- all data is fresh
- High-conviction tickers (2+ screens) are listed in Value Screens section below

AI FUN FACT
- Shiller CAPE above 40x has occurred only twice in 145 years: 1999 and today.

AI LEARNING
- Attention mechanism: lets LLMs weight relationships between all tokens simultaneously."""
    return fallback, True

# ============================================================
# SECTION PARSER
# ============================================================

def parse_sections(text):
    """
    Split raw AI output into 5 named sections.
    Handles slight header variations (numbered, prefixed with #, etc).
    Returns dict {section_name: raw_content_str}.
    """
    secs = {
        "MARKET AND MACRO": "",
        "WHAT TO WATCH":    "",
        "AI FUN FACT":      "",
        "AI LEARNING":      "",
    }
    current = None
    for line in text.splitlines():
        up  = line.upper().strip()
        cln = re.sub(r"^\d+[\.\)]\s*", "", up)
        cln = re.sub(r"^#+\s*",        "", cln)
        cln = re.sub(r"^\*+\s*",       "", cln)
        cln = cln.encode("ascii", "ignore").decode().strip()

        if   "MARKET AND MACRO"  in cln: current = "MARKET AND MACRO"; continue
        elif "WHAT TO WATCH"     in cln: current = "WHAT TO WATCH";    continue
        elif "AI FUN FACT"       in cln: current = "AI FUN FACT";      continue
        elif "AI LEARNING"       in cln: current = "AI LEARNING";      continue
        elif "MARKET SUMMARY"    in cln: current = "MARKET AND MACRO"; continue
        elif "FUN FACT" in cln and "AI" not in cln: current = "AI FUN FACT"; continue

        if current and line.strip():
            secs[current] += line.strip() + "\n"

    for n, c in secs.items():
        icon = "📋" if c.strip() else "⚠️"
        print(f"  {icon} {n}: {len(c)} chars")

    return secs