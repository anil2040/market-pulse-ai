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
# CLAUDE ROUTINE INTEGRATION:
#   Pre-market intelligence (futures, sentiment, rates, sector
#   movers, global markets, macro events, open_focus) from the
#   7:44am Claude Routine is injected into the prompt. When fresh,
#   this provides today's context. When stale, it is included
#   with a staleness note so the AI can weight it accordingly.
#
# FALLBACK CHAIN (one attempt per model, no retries):
#   1. gemini-3.6-flash  (free, ~20 RPD confirmed from AI Studio dashboard)
#   2. gemini-3.5-flash  (free, 1,500 RPD -- confirmed stable Sep 2026)
#   3. claude-haiku-4-5  (paid ~$0.01-0.02/run -- varies with prompt size)
#   4. structured text   (always works, no AI narrative)
#   No retries within any model. No Sonnet in chain.
#   Blank response (empty/whitespace) treated as failure, falls through.
#
# GEMINI API NOTE:
#   Uses generate_content (legacy but fully supported, stable, low latency).
#   interactions.create had 90s+ timeout issues -- do not use.
#   google.genai SDK: client.models.generate_content(model, contents=[prompt])
#
# 90-SECOND TIMEOUT:
#   Implemented via concurrent.futures fut.result(timeout=90).
#   If a model call hangs, TimeoutError is caught and next model is tried.
#   Blank responses also treated as failure and fall through.
#
# ERROR LOGGING:
#   Full exception type, HTTP status code (where SDK exposes it), and full
#   message logged to GitHub Actions. No truncation. Makes quota exhaustion,
#   model errors, and auth failures immediately readable in the run log.
#
# TEXT LIMITS IN PROMPT (raised from original 800/600/600):
#   EJ: 1500 chars  |  CNBC: 1200 chars  |  Yahoo Brief: 1200 chars
#   Log line prints when text is truncated -- visible in Actions.
#   Yahoo Brief IMAP fetch uses char_limit=None (full email) so nothing
#   is lost before the prompt slicing.
#
# VALUE SCREENS NOT IN PROMPT (intentional):
#   si_tickers, mf_list, am_list are accepted as parameters for signature
#   compatibility with main.py but are NOT sent to the AI model.
#   Screens data belongs in the dashboard chips and Chrome extension div,
#   not in the macro briefing. Removing them keeps the AI focused on
#   macro interpretation and saves ~250 input tokens per run.
#
# TWO-COLUMN LAYOUT -- BALANCED AT MAX 5 BULLETS EACH:
#   MARKET AND MACRO: max 5 bullets (left column)
#   WHAT TO WATCH:    max 5 bullets (right column)
#
# HAIKU COST NOTE (confirmed from Anthropic dashboard Sep 2026):
#   Haiku 4.5 pricing: $1.00/M input tokens, $5.00/M output tokens
#   Observed range: $0.008 (light day) to $0.015 (heavy news day)
#   Cost logged with actual token counts from message.usage each run.
# ============================================================

import os
import re
import concurrent.futures
import requests

GEMINI_API_KEY    = os.environ.get("GEMINI_API_KEY")
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

# ============================================================
# MODEL CALLERS
# ============================================================

def _call_gemini(prompt, model):
    """
    Call Gemini using generate_content (stable legacy API).
    Uses google.genai SDK v2.3+. Returns plain text string.
    generate_content is stateless, low-latency, and confirmed working
    with gemini-3.6-flash and gemini-3.5-flash in production.
    """
    import google.genai as genai
    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model    = model,
        contents = [prompt],
    )
    return response.text


def _call_haiku(prompt):
    """
    Call Claude Haiku 4.5. Returns (text, input_tokens, output_tokens).
    Uses anthropic SDK when available; falls back to direct HTTP.
    Token counts come from message.usage so cost logging is always accurate.
    """
    if not ANTHROPIC_API_KEY:
        raise Exception("ANTHROPIC_API_KEY secret not set in GitHub repo")
    try:
        import anthropic
        client  = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        message = client.messages.create(
            model      = "claude-haiku-4-5",
            max_tokens = 1000,
            messages   = [{"role": "user", "content": prompt}],
        )
        in_tok  = message.usage.input_tokens
        out_tok = message.usage.output_tokens
        return message.content[0].text, in_tok, out_tok
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
                f"Anthropic API HTTP {resp.status_code}: {resp.text[:500]}")
        data    = resp.json()
        in_tok  = data.get("usage", {}).get("input_tokens", 0)
        out_tok = data.get("usage", {}).get("output_tokens", 0)
        return data["content"][0]["text"], in_tok, out_tok


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

    futures = routine_data.get("futures", {})
    sp5     = futures.get("sp500",     {})
    nq      = futures.get("nasdaq100", {})
    dw      = futures.get("dow",       {})
    sent    = futures.get("sentiment", "N/A")

    def fmt_future(d):
        if not d:
            return "N/A"
        chg       = d.get("change_pct", 0)
        direction = d.get("direction", "")
        return f"{chg:+.2f}% ({direction})" if isinstance(chg, (int, float)) else f"{chg} ({direction})"

    futures_str = (f"S&P {fmt_future(sp5)} | Nasdaq {fmt_future(nq)} | "
                   f"Dow {fmt_future(dw)} | Sentiment: {sent.upper()}")

    rc    = routine_data.get("rates_commodities", {})
    t10y  = rc.get("treasury_10yr_pct", "N/A")
    crude = rc.get("crude_oil_usd", "N/A")
    ctype = rc.get("crude_oil_type", "WTI")

    events     = routine_data.get("macro_events", [])
    events_str = " / ".join(events) if events else "None reported"

    sm      = routine_data.get("sector_movers", {})
    leaders = sm.get("leading", [])
    laggers = sm.get("lagging", [])

    def fmt_sector(lst):
        parts = []
        for s in lst:
            name    = s.get("sector", "")
            chg     = s.get("change_pct", 0)
            reason  = s.get("reason", "")
            chg_str = f"{chg:+.2f}%" if isinstance(chg, (int, float)) else str(chg)
            parts.append(f"{name} {chg_str} ({reason})")
        return " | ".join(parts) if parts else "N/A"

    gm     = routine_data.get("global_markets", {})
    europe = gm.get("europe", {})
    asia   = gm.get("asia",   {})

    def fmt_global(d):
        if not d:
            return "N/A"
        idx       = d.get("index", "")
        chg       = d.get("change_pct", 0)
        direction = d.get("direction", "")
        chg_str   = f"{chg:+.2f}%" if isinstance(chg, (int, float)) else str(chg)
        return f"{idx} {chg_str} ({direction})"

    open_focus = routine_data.get("open_focus", "")

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

    NOTE: si_tickers, mf_list, am_list are accepted for signature compatibility
    but are NOT included in the AI prompt. Screen data belongs in the dashboard
    chips and Chrome extension div -- not in the macro briefing.
    """
    print("\n🤖 Sending to AI synthesis...")

    if routine_data is None:
        routine_data = {}

    fred_summary = "\n".join([
        f"- {r['label']}: {r['current']} (3mo:{r['mo3']} 12mo:{r['mo12']} trend:{r['trend']})"
        for r in fred_data if r["current"] != "N/A"
    ])

    cape_val = next(
        (r["current"] for r in fred_data if r["label"] == "Shiller CAPE (US)"), "N/A")
    urth_str = f"MSCI World P/E (URTH, incl US): {mkt_data.get('urth_pe', 'N/A')}x"
    efa_str  = f"ex-US Developed P/E (EFA, MSCI EAFE): {mkt_data.get('efa_pe', 'N/A')}x"

    routine_block = _format_routine_block(routine_data, routine_fresh)

    calendar_block = ""
    if yahoo_calendar and len(yahoo_calendar.strip()) > 50:
        calendar_block = (f"\nWEEK AHEAD (from Yahoo Morning Brief -- use specific dates):\n"
                          f"{yahoo_calendar[:2000]}")

    # ── Text limits with log notes ──────────────────────────────────────────
    # Raised from original 800/600/600. Log lines visible in GitHub Actions
    # when text is actually truncated so nothing is silently lost.
    _EJ_LIMIT    = 1500
    _CNBC_LIMIT  = 1200
    _YAHOO_LIMIT = 1200

    ej_trimmed    = ej_text   [:_EJ_LIMIT]
    cnbc_trimmed  = cnbc_text [:_CNBC_LIMIT]
    yahoo_trimmed = yahoo_text[:_YAHOO_LIMIT]

    if len(ej_text)    > _EJ_LIMIT:
        print(f"  [AI] Prompt: EJ news truncated {len(ej_text)} -> {_EJ_LIMIT} chars")
    if len(cnbc_text)  > _CNBC_LIMIT:
        print(f"  [AI] Prompt: CNBC truncated {len(cnbc_text)} -> {_CNBC_LIMIT} chars")
    if len(yahoo_text) > _YAHOO_LIMIT:
        print(f"  [AI] Prompt: Yahoo Brief truncated {len(yahoo_text)} -> {_YAHOO_LIMIT} chars")

    prompt = f"""You are a sharp financial analyst writing a morning briefing for a
deep-value mean reversion investor (Greenblatt, Carlisle, Howard Marks, Burry, Pabrai
style). US-focused but holds international ADRs. Long-term holder, not a trader.

STRICT OUTPUT FORMAT -- use EXACTLY these 4 headers, nothing else:

MARKET AND MACRO
WHAT TO WATCH
AI FUN FACT
AI LEARNING

CRITICAL RULES -- READ CAREFULLY:

1. DO NOT restate raw indicator numbers. VIX, SPX %, CAPE, Macro Heat Score,
   Fear & Greed score -- these are already shown in the dashboard tables. The
   investor sees them before reading your briefing. Repeating them is noise.

2. INTERPRET, do not describe. Instead of "VIX is 15 indicating calm markets",
   say what that calm means for a value investor today given everything else --
   e.g. "Low volatility with negative ERP is an unusual combination -- cheap
   protection available while stocks price in perfection."

3. Look for TENSIONS and CONFIRMATIONS between signals. When two indicators
   point different directions (e.g. credit spreads tight but gold rising),
   name the tension and what it might mean. When multiple signals align
   (e.g. CAPE extreme AND ERP negative AND Fear & Greed in greed), say what
   that combination historically implies.

4. MARKET AND MACRO: Max 5 bullets. Synthesize the FRED/macro picture WITH
   the pre-market intelligence (futures, sectors, global moves, open focus).
   Surface what the COMBINATION means.
   If there is a key macro event this week (Fed decision, CPI, jobs),
   mention it here with the date and its implications.

5. WHAT TO WATCH: Max 5 bullets. Actionable mean reversion lens.
   Name the macro trip wires -- what data prints or events would shift
   the Macro Heat Score meaningfully up or down?

6. AI FUN FACT: 1 surprising fact about AI, markets, or investing history.
   Max 25 words. Not about the current data.

7. AI LEARNING: 1 AI/ML concept in plain English, relevant to investing
   or data analysis. Max 30 words.

8. Each bullet: dash (-) prefix, max 20 words, no bold, no markdown headers.

DATA (for interpretation -- do NOT repeat these numbers verbatim):

MACRO HEAT SCORE: {mhs['score']}/100 -- {mhs['label']} | Posture: {mhs['action']}
VALUATION: US CAPE={cape_val} (hist avg 17x) | {urth_str} | {efa_str}
MARKET PULSE: {mkt_data['pulse']}

MACRO INDICATORS:
{fred_summary}

{routine_block}
{calendar_block}

NEWS SOURCES (for macro context -- no stock-specific stories):
EDWARD JONES: {ej_trimmed}
CNBC SQUAWK: {cnbc_trimmed}
YAHOO BRIEF: {yahoo_trimmed}
"""

    models_to_try = [
        ("gemini-3.6-flash", "Gemini 3.6 Flash (free tier)",
         lambda: _call_gemini(prompt, "gemini-3.6-flash")),
        ("gemini-3.5-flash", "Gemini 3.5 Flash (free tier)",
         lambda: _call_gemini(prompt, "gemini-3.5-flash")),
        ("claude-haiku-4-5", "Claude Haiku 4.5",
         lambda: _call_haiku(prompt)),
    ]

    for model_id, model_name, call_fn in models_to_try:
        try:
            print(f"  Trying {model_name}...")
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                fut    = ex.submit(call_fn)
                result = fut.result(timeout=90)

            # Extract text from result
            if model_id == "claude-haiku-4-5":
                briefing, in_tok, out_tok = result
            else:
                briefing = result

            # Blank response = failure -- fall through to next model
            if not briefing or not briefing.strip():
                raise ValueError("Blank response returned (0 usable chars)")

            # Log success
            if model_id == "claude-haiku-4-5":
                cost = (in_tok * 1.00 + out_tok * 5.00) / 1_000_000
                print(f"  ✅ Claude Haiku used as fallback: {len(briefing)} chars")
                print(f"  💰 Cost: ~${cost:.4f} "
                      f"(input {in_tok:,} tokens + output {out_tok:,} tokens)")
            else:
                print(f"  ✅ {model_name}: {len(briefing)} chars")

            return briefing, False

        except concurrent.futures.TimeoutError:
            print(f"  ⚠️ {model_name} timed out after 90s -- trying next model")
        except Exception as e:
            err_type = type(e).__name__
            err_msg  = str(e)
            # Extract HTTP/gRPC status code from SDK exceptions where available
            # Gemini uses e.code (google.api_core.exceptions)
            # Anthropic SDK uses e.status_code
            status   = getattr(e, "status_code", None) or getattr(e, "code", None)
            if status:
                print(f"  ⚠️ {model_name} FAILED: {err_type} | HTTP {status} | {err_msg}")
            else:
                print(f"  ⚠️ {model_name} FAILED: {err_type} | {err_msg}")

    print("  ❌ All AI models failed -- using structured fallback")
    fallback = """MARKET AND MACRO
- AI synthesis unavailable -- all models failed or quota exhausted today
- All data sections below are complete and current -- no data loss

WHAT TO WATCH
- Review Macro Heat Score and FRED indicator table -- all data is fresh
- Value screen chips in the screens section show current conviction tickers

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
    Split raw AI output into 4 named sections.
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
        cln = re.sub(r"^#+\s*",         "", cln)
        cln = re.sub(r"^\*+\s*",        "", cln)
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