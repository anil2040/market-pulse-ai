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
# PROMPT PHILOSOPHY (rewritten in Session 15):
#   The investor has no time to read the newsletters. The briefing REPLACES
#   reading them and is also pasted into a stock-analysis project, so it must
#   tell one coherent, self-contained story of the day. The model may use only
#   what is in the data below (no memory, no guessing reasons), must not repeat
#   numbers the dashboard already shows, must not name its sources, and must not
#   use em or en dashes. Short on purpose: about 130 words of instructions.
#   Output: one section, MACRO INSIGHTS (8 to 10 items; the page shows them numbered).
#
# SESSION 15 PART 3 (after the first real run, Oct 1 evening):
#   - Dashboard numbers (FRED indicators, CAPE, ex-US P/E, Macro Heat Score): with them
#     mixed into every insight, 5 of 10 insights blended dashboard numbers into the news
#     story. Now they sit in their own block AFTER the news, and the model may use them
#     ONLY in one FINAL bullet, a "dashboard read" (owner's idea). The other bullets come
#     from the news only.
#   - INVESTOR NOTE removed (owner: it repeated the same story, not useful).
#   - Em and en dashes are replaced in code after the model answers (_no_dashes), because
#     Haiku used them in spite of the instruction.
#
# CLAUDE ROUTINE INTEGRATION:
#   Pre-market intelligence (futures, sentiment, rates, sector
#   movers, global markets, macro events, open_focus) from the
#   7:40am Claude Routine is injected into the prompt. When fresh,
#   this provides today's context. When stale, it is included
#   with a staleness note so the AI can weight it accordingly.
#
# CHANGES (Session 15, Sep 30 2026, part 2):
#   - New prompt (see PROMPT PHILOSOPHY). Two sections instead of four:
#     MACRO INSIGHTS and INVESTOR NOTE. The old "max 5 bullets" and "max 20 words"
#     limits are gone (Haiku ignored the 20 word limit and it was too tight for insight).
#   - Six news sources instead of three: WSJ Markets A.M., Axios Markets, CNBC,
#     Yahoo, Yardeni, Edward Jones. news.py cuts each one by section (ads and
#     footers removed); this file sends the whole kept text. Words, not characters.
#   - Sources that are missing today are left out of the prompt entirely.
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
# CHANGES (Session 15, Sep 30 2026): Sonnet 5.5 was DROPPED from the chain at the owner's request.
#   Reason: Sonnet 5.5 thinks by default; it used all 1,500 output tokens thinking, returned no text,
#   and Haiku wrote the briefing anyway (about 3 cents a run for Haiku quality text). Haiku is now first.
#   The output limit was raised from 1500 to 2000 tokens (owner asked for a suggestion; one older
#   Haiku run wrote 1,522 tokens). A higher limit costs nothing extra unless the model uses it.
#   TO PUT SONNET BACK LATER: add ("claude-sonnet-5-5", "Claude Sonnet 5.5", ...) as the first entry of
#   models_to_try, add "claude-sonnet-5-5": (2.00, 10.00) to CLAUDE_PRICES, and FIRST check Anthropic's
#   docs for how to turn its up-front thinking off or limit it, or it will return a blank answer again.
#
# FALLBACK CHAIN (the owner's design, Session 15). ONE try per model. No retries anywhere. No waits.
#   1. claude-haiku-4-5   One try. Paid, $1 in / $5 out per million tokens (about 1 to 1.5 cents per run).
#                         Pinned on purpose. Anthropic lists it Active, retirement NOT sooner than
#                         Oct 15 2026 (a floor, not a date), with at least 60 days notice by email:
#                         watch for the email and for a newer Haiku.
#        If it fails (temporary or permanent), go straight to 2. The top line of the page names the
#        error, for example "Haiku 4.5 HTTP 404: model not found" means the model name needs attention.
#   2. gemini-3.6-flash   One try, immediately (no wait). Free tier, a different company, so an
#                         Anthropic outage does not leave the page without a briefing. Expected
#                         to be used rarely. It sometimes answers 503 "high demand" on the free tier.
#   3. structured text    Always works, no AI narrative. The top line then says every model failed.
#   Why the Gemini-first order was dropped: on the free tier the newest Flash models answered
#   503 "high demand" on many days and RPM limits were hit, which cost time and gave a different
#   writing quality day to day.
#   WHEN MODELS CHANGE: update the model names in models_to_try (and CLAUDE_PRICES) here, nowhere else.
#   Blank response (empty/whitespace) is treated as a failure and falls through.
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
# NEWS INPUT (Session 15):
#   No character caps any more. news.py already removed ads, quote tables and
#   footers. Safety ceiling here: 1500 words per source (a log line prints if it
#   ever bites). Order in the prompt: WSJ, Axios, CNBC, Yahoo, Goldman, Yardeni, McClellan, Edward Jones.
#
# VALUE SCREENS NOT IN PROMPT (intentional):
#   si_tickers, mf_list, am_list are accepted as parameters for signature
#   compatibility with main.py but are NOT sent to the AI model.
#   Screens data belongs in the dashboard chips and Chrome extension div,
#   not in the macro briefing. Removing them keeps the AI focused on
#   macro interpretation and saves ~250 input tokens per run.
#
# ONE CARD (Session 15):
#   MACRO INSIGHTS: one full-width card on the dashboard, 8 to 10 bullets.
#   INVESTOR NOTE:  one short card at the top of the page.
#   (The old two columns and the Fun Fact / AI Learning cards were removed.)
#
# CLAUDE COST NOTE:
#   Haiku 4.5 pricing: $1.00/M input tokens, $5.00/M output tokens
#     Observed (Anthropic dashboard, Sep 2026): $0.008 (light day) to $0.015 (heavy news day)
#   (Sonnet 5.5 is $2.00/M input, $10.00/M output, about twice Haiku; not used at the moment.)
#   The actual cost of every run is printed in the Actions log from message.usage.
# ============================================================

import os
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


CLAUDE_MAX_TOKENS = 2000   # output limit; the briefing is normally 500 to 1,500 tokens (raised from 1500 in Session 15)
CLAUDE_TIMEOUT    = 45.0   # seconds for the single call

# USD per million tokens (input, output). Used only for the cost line in the Actions log.
CLAUDE_PRICES = {
    "claude-haiku-4-5": (1.00, 5.00),
}


class _HttpError(Exception):
    """Direct-HTTP failure that carries the status code, so it is reported like the SDK's errors."""
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

def _no_dashes(text):
    """
    Owner rule: no em dashes or en dashes anywhere. Haiku uses them anyway, so replace them here.
    Em dash -> comma ("wealth, now $74 trillion"); en dash between numbers -> hyphen ("3-4");
    any other en dash -> comma.
    """
    if not text:
        return text
    text = re.sub(r"\s*\u2014\s*", ", ", text)
    text = re.sub(r"(?<=\d)\s*\u2013\s*(?=\d)", "-", text)
    text = re.sub(r"\s*\u2013\s*", ", ", text)
    text = re.sub(r",\s*,", ",", text)
    return text


def synthesize_with_ai(ej_text, cnbc_text, yahoo_text,
                       fred_data, fg_data, mkt_data, mhs,
                       si_tickers, mf_list, am_list,
                       routine_data=None, routine_fresh=False,
                       yahoo_calendar="", health_notes=None, today_name=None,
                       wsj_text="", axios_text="", yardeni_text="",
                       goldman_text="", mcclellan_text=""):
    """
    Build prompt from all fetched data and call AI models in fallback order.
    ej_text, cnbc_text, yahoo_text, wsj_text, axios_text, yardeni_text, goldman_text,
    mcclellan_text: the kept text of each
    news source ("" when missing; missing sources are left out of the prompt).
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

    # ── News inputs: the whole kept text of each source (news.py already cut ads and
    # footers). Safety ceiling only; a log line prints when it bites.
    _NEWS_WORD_CEILING = 1500

    def _cut_words(txt, limit):
        out, total = [], 0
        for ln in txt.splitlines():
            w = len(ln.split())
            if total + w > limit:
                break
            out.append(ln)
            total += w
        return "\n".join(out)

    news_sources = [
        ("WSJ MARKETS A.M.",    wsj_text),
        ("AXIOS MARKETS",       axios_text),
        ("CNBC MORNING SQUAWK", cnbc_text),
        ("YAHOO MORNING BRIEF", yahoo_text),
        ("GOLDMAN SACHS BRIEFINGS", goldman_text),
        ("YARDENI QUICKTAKES",  yardeni_text),
        ("MCCLELLAN CHART IN FOCUS", mcclellan_text),
        ("EDWARD JONES RECAP",  ej_text),
    ]
    news_parts, news_words = [], 0
    for label, txt in news_sources:
        txt = (txt or "").strip()
        if not txt:
            continue
        n = len(txt.split())
        if n > _NEWS_WORD_CEILING:
            print(f"  [AI] Prompt: {label} cut {n} -> {_NEWS_WORD_CEILING} words")
            txt = _cut_words(txt, _NEWS_WORD_CEILING)
            n = len(txt.split())
        news_parts.append(f"{label}:\n{txt}")
        news_words += n
    news_block = "\n\n".join(news_parts) if news_parts else "(no news sources available today)"
    print(f"  [AI] Prompt news input: {len(news_parts)} sources, {news_words} words")

    from timeutil import now_mt
    _now = now_mt()
    today_label = f"{_now.strftime('%A, %B')} {_now.day}, {_now.year}"

    prompt = f"""You are a financial analyst writing the morning briefing for a deep-value,
mean-reversion investor (Greenblatt, Marks, Burry, Pabrai style). US focused,
long-term holder, not a trader.

The investor has no time to read the newsletters below. Your briefing replaces
them, and it is also pasted into a stock-analysis project as macro context. Tell
one coherent story of what is happening in markets and the economy today and
what it means for a long-term value investor.

Under the header MACRO INSIGHTS write 8 to 10 bullets from the news, most
important first, ending with what could change the picture next. Then add one
final bullet, a dashboard read: what the dashboard numbers below say together
(rates, inflation, credit, valuation, Macro Heat Score), tied to the day's news
only where the news supports it. Each bullet is 1 to 3 sentences and makes sense
on its own. Merge repeated facts. Skip one-off company stories.

Use only what the data below says. Add nothing from memory and do not guess
reasons. If unsure, leave it out. Apart from the final bullet, do not repeat
numbers the dashboard already shows (VIX, index moves, CAPE, Macro Heat Score,
Fear and Greed, the macro indicators). Do not name the sources.

One bullet per line starting with "- ". No bold or markdown. No em dashes or
en dashes.

Today is {today_label}.

{routine_block}
{calendar_block}
{caveat_block}

NEWS:
{news_block}

DASHBOARD NUMBERS (for the final bullet only):

MACRO HEAT SCORE: {mhs['score']}/100 -- {mhs['label']} | Posture: {mhs['action']}
VALUATION: US CAPE={cape_val} (hist avg 17x) | {urth_str} | {efa_str}
MARKET PULSE: {mkt_data.get('pulse', 'N/A')}

MACRO INDICATORS:
{fred_summary}
"""

    models_to_try = [
        ("claude-haiku-4-5", "Claude Haiku 4.5",
         lambda: _call_claude(prompt, "claude-haiku-4-5")),
        ("gemini-3.6-flash", "Gemini 3.6 Flash (free tier)",
         lambda: _call_gemini(prompt, "gemini-3.6-flash")),
    ]

    attempts = []              # what failed before something worked
    for model_id, model_name, call_fn in models_to_try:
        is_claude  = model_id.startswith("claude-")
        short_name = model_name.replace(" (free tier)", "")

        try:
            print(f"  Trying {model_name}...")
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
                fut    = ex.submit(call_fn)
                result = fut.result(timeout=60 if is_claude else 90)

            if is_claude:
                briefing, in_tok, out_tok = result
            else:
                briefing = result

            # Blank response = failure -- fall through to next model
            if not briefing or not briefing.strip():
                raise ValueError("Blank response returned (0 usable chars)")

            briefing = _no_dashes(briefing)
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
        except Exception as e:
            err_type = type(e).__name__
            status   = getattr(e, "status_code", None) or getattr(e, "code", None)
            if status:
                print(f"  ⚠️ {model_name} FAILED: {err_type} | HTTP {status} | {str(e)}")
            else:
                print(f"  ⚠️ {model_name} FAILED: {err_type} | {str(e)}")
            attempts.append({"model": short_name, "error": _short_error(e)})

    print("  ❌ All AI models failed -- using structured fallback")
    fallback = """MACRO INSIGHTS
- AI synthesis unavailable today. Every model failed (see the notice at the top of the page).
- The data tables below are still built from the live sources. Check the data health notice for anything stale.
- Review the Macro Heat Score, the weekly calendar and the indicator table directly."""
    return fallback, True, {"model": None, "attempts": attempts}


# ============================================================
# SECTION PARSER
# ============================================================

def parse_sections(text):
    """
    Split raw AI output into its one section: MACRO INSIGHTS.
    Handles slight header variations (numbered, prefixed with #, bold stars, colon).
    An INVESTOR NOTE section (removed in Session 15 part 3) is ignored if a model still writes one.
    Returns dict {section_name: raw_content_str}.
    """
    secs = {
        "MACRO INSIGHTS": "",
    }
    current = None
    for line in text.splitlines():
        up  = line.upper().strip()
        cln = re.sub(r"^\d+[\.\)]\s*", "", up)
        cln = re.sub(r"^#+\s*",         "", cln)
        cln = re.sub(r"^\*+\s*",        "", cln)
        cln = cln.encode("ascii", "ignore").decode().strip()
        cln = cln.rstrip("*:# ").strip()

        # Only short lines can be headers (a long bullet must never switch sections)
        is_header = len(cln) <= 40 and not cln.startswith("-")
        if is_header and ("MACRO INSIGHT" in cln or "MARKET AND MACRO" in cln
                          or "MARKET SUMMARY" in cln):
            current = "MACRO INSIGHTS"; continue
        if is_header and "INVESTOR NOTE" in cln:
            current = None; continue

        if current and line.strip():
            secs[current] += line.strip() + "\n"

    for n, c in secs.items():
        icon = "📋" if c.strip() else "⚠️"
        print(f"  {icon} {n}: {len(c)} chars")

    return secs