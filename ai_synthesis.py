# ============================================================
# ai_synthesis.py -- AI briefing synthesis
# Mean Reversion Macro Insights
# ============================================================
#
# PUBLIC FUNCTIONS (called by main.py):
#   synthesize_with_ai(...) -> (briefing_str, ai_failed_bool, ai_info_dict)
#     ai_info = {"model": name that produced the text (or None),
#                "attempts": [{"model": ..., "error": ...}, ...]}  <- what failed first
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
#   7:40am Claude Routine is injected into the prompt. When fresh,
#   this provides today's context. When stale, it is included
#   with a staleness note so the AI can weight it accordingly.
#
# CHANGES (Sep 29 2026):
#   - Returns ai_info so the dashboard can say exactly WHY Gemini failed
#     (a 503 "high demand" is Google's capacity, NOT your quota; the old
#     banner wrongly said "quota exhausted").
#   - (Oct 1 2026: the Claude retries added here were REMOVED at the owner's request.
#     Every model now gets exactly one try. See FALLBACK CHAIN below.)
#   - Keys are stripped of stray spaces/newlines (a pasted secret with a
#     trailing newline causes odd "credential" errors).
#   - Request id is logged on Anthropic errors so support can trace them.
#   - News text that was refused as stale arrives empty and is shown to
#     the model as "not available today".
#   - Calendar sent to the model starts at TODAY (past days are noise).
#   - Each macro indicator line carries its real "as of" date.
#   - A short DATA CAVEATS block lists anything stale so the model does
#     not build a narrative on old numbers.
#
# FALLBACK CHAIN (the owner's design, Oct 1 2026). ONE try per model. No retries anywhere.
#   1. claude-sonnet-5-5  One try. Paid, $2 in / $10 out per million tokens (about 2 to 3 cents
#                         per run). Chosen for the most nuanced macro interpretation.
#        If it fails with a TEMPORARY error (overload 503/529, rate limit 429, timeout,
#        network): wait SECONDS_BEFORE_HAIKU (10 s), then go to 2.
#        If it fails with a PERMANENT error (404 model name not found or changed, 401 key
#        rejected, 403 no access, 400 bad request): do NOT wait, go straight to 2. The top
#        line of the page then names the error with a hint, so you know the primary model
#        needs attention (for example "Sonnet 5.5 HTTP 404, model not found, check the name").
#   2. claude-haiku-4-5   One try. Paid, $1 / $5. Pinned on purpose. Anthropic lists it Active,
#                         retirement NOT sooner than Oct 15 2026, with at least 60 days notice:
#                         watch for the email and for a newer Haiku.
#   3. gemini-3.6-flash   One try, immediately (no wait). Free tier, a different company, so an
#                         Anthropic outage does not leave the page without a briefing. Expected
#                         to be used rarely. It sometimes answers 503 "high demand" on the free tier.
#   4. structured text    Always works, no AI narrative. The top line then says every model failed.
#   Why the Gemini-first order was dropped: on the free tier the newest Flash models answered
#   503 "high demand" on many days and RPM limits were hit, which cost time and gave a different
#   writing quality day to day.
#   WHEN MODELS CHANGE: update the model names in models_to_try (and CLAUDE_PRICES) here, nowhere else.
#   Blank response (empty/whitespace) is treated as a failure and falls through (no wait).
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
# CLAUDE COST NOTE:
#   Haiku 4.5 pricing: $1.00/M input tokens, $5.00/M output tokens
#     Observed (Anthropic dashboard, Sep 2026): $0.008 (light day) to $0.015 (heavy news day)
#   Sonnet 5.5 pricing: $2.00/M input, $10.00/M output (released Sep 28 2026), so about
#     twice Haiku: expect roughly $0.02 to $0.03 per run, about $0.50 a month.
#   The actual cost of every run is printed in the Actions log from message.usage.
# ============================================================

import os
import time
import re
import concurrent.futures
import requests

GEMINI_API_KEY    = (os.environ.get("GEMINI_API_KEY") or "").strip()
ANTHROPIC_API_KEY = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()

# ============================================================
# MODEL CALLERS
# ============================================================

def _call_gemini(prompt, model):
    """
    Call Gemini using generate_content (stable legacy API).
    Uses google.genai SDK v2.3+. Returns plain text string.
    """
    import google.genai as genai
    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model    = model,
        contents = [prompt],
    )
    return response.text


SECONDS_BEFORE_HAIKU = 10.0   # wait after a TEMPORARY Sonnet failure, before Haiku (owner's choice)
CLAUDE_MAX_TOKENS    = 1500   # output limit; the briefing is normally about 500 tokens
CLAUDE_TIMEOUT       = 45.0   # seconds for the single call (a bigger model can take longer than Haiku)

# USD per million tokens (input, output). Used only for the cost line in the Actions log.
CLAUDE_PRICES = {
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-4-5":  (1.00, 5.00),
}


def _is_temporary(e):
    """
    True for temporary problems (overload, rate limit, timeout, network): worth a short wait
    before the next model. False for permanent ones (404 model not found, 401 bad key,
    403 no access, 400 bad request) and for odd errors: no point waiting, move on at once.
    """
    status = getattr(e, "status_code", None)
    if status is not None:
        return status in (408, 409, 429) or status >= 500
    name = type(e).__name__
    return "Connection" in name or "Timeout" in name


class _HttpError(Exception):
    """Direct-HTTP failure that carries the status code, so it is classified like the SDK's errors."""
    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code


def _claude_text(content_blocks):
    """Join every text block (a model may put a 'thinking' block first; that is skipped)."""
    parts = []
    for b in content_blocks or []:
        btype = b.get("type") if isinstance(b, dict) else getattr(b, "type", "")
        if btype == "text":
            parts.append(b.get("text", "") if isinstance(b, dict) else getattr(b, "text", ""))
    return "".join(parts)


def _call_claude(prompt, model):
    """
    Call a Claude model ONCE. Returns (text, input_tokens, output_tokens).
    No retries: the SDK's own automatic retrying is switched OFF (max_retries=0), and any
    error is raised to the caller, which decides what to do next (see FALLBACK CHAIN).
    Falls back to a single direct HTTP call only if the anthropic library is missing.
    """
    if not ANTHROPIC_API_KEY:
        raise Exception("ANTHROPIC_API_KEY secret not set in GitHub repo")
    try:
        import anthropic
    except ImportError:
        anthropic = None

    if anthropic is not None:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY, max_retries=0, timeout=CLAUDE_TIMEOUT)
        try:
            message = client.messages.create(
                model      = model,
                max_tokens = CLAUDE_MAX_TOKENS,
                messages   = [{"role": "user", "content": prompt}],
            )
        except Exception as e:
            rid = getattr(e, "request_id", None)
            if rid:
                print(f"  ℹ️ Anthropic request id: {rid} (quote this to Anthropic support)")
            raise
        if getattr(message, "stop_reason", "") == "max_tokens":
            print(f"  ⚠️ {model}: answer hit the {CLAUDE_MAX_TOKENS}-token limit and may be cut off")
        return (_claude_text(message.content),
                message.usage.input_tokens, message.usage.output_tokens)

    print("  ℹ️ anthropic library not found -- using direct HTTP to Anthropic API")
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key":         ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type":      "application/json",
        },
        json={
            "model":      model,
            "max_tokens": CLAUDE_MAX_TOKENS,
            "messages":   [{"role": "user", "content": prompt}],
        },
        timeout=CLAUDE_TIMEOUT,
    )
    if resp.status_code != 200:
        raise _HttpError(resp.status_code,
                         f"Anthropic API HTTP {resp.status_code} "
                         f"(request-id {resp.headers.get('request-id', 'none')}): {resp.text[:400]}")
    data = resp.json()
    return (_claude_text(data.get("content")),
            data.get("usage", {}).get("input_tokens", 0),
            data.get("usage", {}).get("output_tokens", 0))


def _short_error(e):
    """Compact one-line error for the dashboard banner and health list."""
    status = getattr(e, "status_code", None) or getattr(e, "code", None)
    msg    = str(e)
    m = (re.search(r"'message': '([^']{0,90})", msg)
         or re.search(r'"message": ?"([^"]{0,90})', msg))
    txt = m.group(1) if m else msg[:90]
    return f"HTTP {status}: {txt}" if status else f"{type(e).__name__}: {txt}"


def _calendar_from_today(calendar_text, today_name, limit=2000):
    """Start the calendar at today's weekday header (past days are noise for the briefing)."""
    if not calendar_text:
        return ""
    m = re.search(rf"(?m)^{re.escape(today_name)}\b", calendar_text)
    if m and m.start() > 0:
        calendar_text = calendar_text[m.start():]
    return calendar_text[:limit]


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
                       yahoo_calendar="", health_notes=None, today_name=None):
    """
    Build prompt from all fetched data and call AI models in fallback order.
    routine_data: parsed clauderoutinedata.json (or {} if unavailable)
    routine_fresh: True if routine date matches today MT
    health_notes: list of short strings describing stale/missing data
    today_name: weekday name in Boise time ("Tuesday"), used to trim the calendar
    Returns (briefing_str, ai_failed_bool, ai_info_dict).
    ai_failed=True means structured fallback was used (no AI narrative).

    NOTE: si_tickers, mf_list, am_list are accepted for signature compatibility
    but are NOT included in the AI prompt. Screen data belongs in the dashboard
    chips and Chrome extension div -- not in the macro briefing.
    """
    print("\n🤖 Sending to AI synthesis...")

    if routine_data is None:
        routine_data = {}

    fred_summary = "\n".join([
        f"- {r['label']}: {r['current']} (as of {r.get('date', '?')}; "
        f"3mo:{r['mo3']} 12mo:{r['mo12']} trend:{r['trend']})"
        for r in fred_data if r["current"] != "N/A"
    ])

    cape_val = next(
        (r["current"] for r in fred_data if r["label"] == "Shiller CAPE (US)"), "N/A")
    urth_str = f"MSCI World P/E (URTH, incl US): {mkt_data.get('urth_pe', 'N/A')}x"
    efa_str  = f"ex-US Developed P/E (EFA, MSCI EAFE): {mkt_data.get('efa_pe', 'N/A')}x"

    routine_block = _format_routine_block(routine_data, routine_fresh)

    if today_name is None:
        from timeutil import now_mt
        today_name = now_mt().strftime("%A")
    calendar_block = ""
    if yahoo_calendar and len(yahoo_calendar.strip()) > 50:
        calendar_block = (f"\nWEEK AHEAD (from Yahoo Morning Brief, from today onward -- use specific dates):\n"
                          f"{_calendar_from_today(yahoo_calendar, today_name)}")

    caveat_block = ""
    if health_notes:
        caveat_block = ("\nDATA CAVEATS (these inputs are stale or missing -- weight accordingly, "
                        "do not build conclusions on them):\n"
                        + "\n".join(f"- {n}" for n in health_notes[:8]))

    # ── Text limits with log notes ──────────────────────────────────────────
    # Raised from original 800/600/600. Log lines visible in GitHub Actions
    # when text is actually truncated so nothing is silently lost.
    _EJ_LIMIT    = 1500
    _CNBC_LIMIT  = 1200
    _YAHOO_LIMIT = 1200

    _NA = "(not available today)"
    ej_trimmed    = ej_text   [:_EJ_LIMIT]    or _NA
    cnbc_trimmed  = cnbc_text [:_CNBC_LIMIT]  or _NA
    yahoo_trimmed = yahoo_text[:_YAHOO_LIMIT] or _NA

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
{caveat_block}

NEWS SOURCES (for macro context -- no stock-specific stories):
EDWARD JONES: {ej_trimmed}
CNBC SQUAWK: {cnbc_trimmed}
YAHOO BRIEF: {yahoo_trimmed}
"""

    models_to_try = [
        ("claude-sonnet-5-5", "Claude Sonnet 5.5",
         lambda: _call_claude(prompt, "claude-sonnet-5-5")),
        ("claude-haiku-4-5", "Claude Haiku 4.5",
         lambda: _call_claude(prompt, "claude-haiku-4-5")),
        ("gemini-3.6-flash", "Gemini 3.6 Flash (free tier)",
         lambda: _call_gemini(prompt, "gemini-3.6-flash")),
    ]

    attempts = []              # what failed before something worked
    wait_before_haiku = False  # set after a TEMPORARY Sonnet failure
    for model_id, model_name, call_fn in models_to_try:
        is_claude  = model_id.startswith("claude-")
        short_name = model_name.replace(" (free tier)", "")

        # The only wait in the chain: between Sonnet and Haiku, and only for temporary errors.
        if model_id == "claude-haiku-4-5" and wait_before_haiku:
            print(f"  ⏳ Sonnet had a temporary problem: waiting {SECONDS_BEFORE_HAIKU:.0f}s before Haiku")
            time.sleep(SECONDS_BEFORE_HAIKU)

        try:
            print(f"  Trying {model_name}...")
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                fut    = ex.submit(call_fn)
                result = fut.result(timeout=60 if is_claude else 90)

            if is_claude:
                briefing, in_tok, out_tok = result
            else:
                briefing = result

            # Blank response = failure -- fall through to next model (no wait)
            if not briefing or not briefing.strip():
                raise ValueError("Blank response returned (0 usable chars)")

            print(f"  ✅ {model_name}: {len(briefing)} chars")
            if is_claude:
                p_in, p_out = CLAUDE_PRICES.get(model_id, (0.0, 0.0))
                cost = (in_tok * p_in + out_tok * p_out) / 1_000_000
                print(f"  💰 Cost: ~${cost:.4f} "
                      f"(input {in_tok:,} tokens + output {out_tok:,} tokens)")
            return briefing, False, {"model": short_name, "attempts": attempts}

        except concurrent.futures.TimeoutError:
            limit = 60 if is_claude else 90
            print(f"  ⚠️ {model_name} timed out after {limit}s -- trying next model")
            attempts.append({"model": short_name, "error": f"timed out after {limit}s"})
            if model_id == "claude-sonnet-5-5":
                wait_before_haiku = True           # a timeout is a temporary problem
        except Exception as e:
            err_type = type(e).__name__
            status   = getattr(e, "status_code", None) or getattr(e, "code", None)
            if status:
                print(f"  ⚠️ {model_name} FAILED: {err_type} | HTTP {status} | {str(e)}")
            else:
                print(f"  ⚠️ {model_name} FAILED: {err_type} | {str(e)}")
            attempts.append({"model": short_name, "error": _short_error(e)})
            if model_id == "claude-sonnet-5-5":
                wait_before_haiku = _is_temporary(e)
                if not wait_before_haiku:
                    print("  ℹ️ That error is permanent (model name, key or access): no wait, going straight to Haiku")

    print("  ❌ All AI models failed -- using structured fallback")
    fallback = """MARKET AND MACRO
- AI synthesis unavailable today -- every model failed (see the notice at the top of the page)
- Data tables below are still built from the live sources; check the data health notice for anything stale

WHAT TO WATCH
- Review the Macro Heat Score, the weekly calendar and the indicator table directly
- Value screen chips below show today's conviction tickers

AI FUN FACT
- Shiller CAPE above 40x has occurred only twice in 145 years: 1999 and today.

AI LEARNING
- Attention mechanism: lets LLMs weight relationships between all tokens simultaneously."""
    return fallback, True, {"model": None, "attempts": attempts}


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