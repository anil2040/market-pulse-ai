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
# MAIN SYNTHESIS
# ============================================================

def synthesize_with_ai(ej_text, cnbc_text, yahoo_text, mcoscillator_text,
                       fred_data, fg_data, mkt_data, mhs,
                       si_tickers, mf_tickers, am_tickers):
    """
    Build prompt from all fetched data and call AI models in fallback order.
    Returns (briefing_str, ai_failed_bool).
    ai_failed=True means structured fallback was used (no AI narrative).
    """
    print("\n🤖 Sending to AI synthesis...")

    fred_summary = "\n".join([
        f"- {r['label']}: {r['current']} (3mo:{r['mo3']} 12mo:{r['mo12']} trend:{r['trend']})"
        for r in fred_data if r["current"] != "N/A"
    ])

    all_tickers = sorted(set(si_tickers.keys()) | mf_tickers | am_tickers)
    overlap = []
    for t in all_tickers:
        tags = []
        if si_tickers.get(t, 0) > 0: tags.append(f"{si_tickers[t]}SI")
        if t in mf_tickers:           tags.append("MF")
        if t in am_tickers:           tags.append("AM")
        if len(tags) >= 2:
            overlap.append(f"{t}({','.join(tags)})")

    cape_val = next(
        (r["current"] for r in fred_data if r["label"] == "Shiller CAPE (US)"), "N/A")
    urth_str = f"URTH(MSCI World incl US) PE: {mkt_data.get('urth_pe', 'N/A')}x"
    efa_str  = f"EFA(MSCI EAFE ex-US) PE: {mkt_data.get('efa_pe', 'N/A')}x"

    prompt = f"""You are a sharp financial analyst writing a morning briefing for a
deep-value mean reversion investor (Greenblatt, Carlisle, Howard Marks, Burry, Pabrai
style). US-focused but holds international ADRs. Long-term holder, not a trader.

STRICT OUTPUT FORMAT -- use EXACTLY these 5 headers, nothing else:

MARKET AND MACRO
EARNINGS AND EVENTS
WHAT TO WATCH
AI FUN FACT
AI LEARNING

CRITICAL RULES -- READ CAREFULLY:

1. DO NOT restate raw indicator numbers. VIX, SPX %, CAPE, MHS score, F&G score --
   these are all already shown in the dashboard tables. The investor sees them before
   reading your briefing. Repeating them is noise.

2. INTERPRET, do not describe. Instead of "VIX is 15 indicating calm markets",
   say what that calm means for a value investor today given everything else --
   e.g. "Low volatility with negative ERP is an unusual combination -- cheap
   protection is available while stocks price in perfection."

3. Look for TENSIONS and CONFIRMATIONS between signals. When two indicators
   point different directions (e.g. credit spreads tight but gold rising),
   name the tension and what it might mean. When multiple signals align
   (e.g. CAPE extreme AND ERP negative AND F&G greed), say what that
   combination historically implies.

4. WHAT TO WATCH: Focus on actionable mean reversion setups. Reference specific
   tickers from high-conviction screens if relevant. Ask what would need to be
   true for the macro to shift -- what are the trip wires.

5. EARNINGS AND EVENTS: Use specific company names, dates, and data points
   from the news sources provided. No generic filler.

6. AI FUN FACT: 1 surprising fact about AI, markets, or investing history
   that is genuinely interesting. Max 25 words. Not about the current data.

7. AI LEARNING: 1 AI/ML concept explained in plain English, relevant to
   investing or data analysis. Max 30 words.

8. Each bullet: dash (-) prefix, max 20 words, no bold, no markdown headers.

DATA (for interpretation -- do NOT repeat these numbers verbatim):

MHS: {mhs['score']}/100 -- {mhs['label']} | Posture: {mhs['action']}
VALUATION: US CAPE={cape_val} (hist avg 17x) | {urth_str} | {efa_str}
MARKET PULSE: {mkt_data['pulse']}

MACRO INDICATORS:
{fred_summary}

HIGH CONVICTION SCREENS (2+ screens overlap):
{', '.join(overlap[:15]) if overlap else 'None today'}

NEWS SOURCES:
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
        "MARKET AND MACRO":    "",
        "EARNINGS AND EVENTS": "",
        "WHAT TO WATCH":       "",
        "AI FUN FACT":         "",
        "AI LEARNING":         "",
    }
    current = None
    for line in text.splitlines():
        up  = line.upper().strip()
        cln = re.sub(r"^\d+[\.\)]\s*", "", up)
        cln = re.sub(r"^#+\s*",        "", cln)
        cln = re.sub(r"^\*+\s*",       "", cln)
        cln = cln.encode("ascii", "ignore").decode().strip()

        if   "MARKET AND MACRO"    in cln: current = "MARKET AND MACRO";    continue
        elif "EARNINGS AND EVENTS" in cln: current = "EARNINGS AND EVENTS"; continue
        elif "WHAT TO WATCH"       in cln: current = "WHAT TO WATCH";       continue
        elif "AI FUN FACT"         in cln: current = "AI FUN FACT";         continue
        elif "AI LEARNING"         in cln: current = "AI LEARNING";         continue
        elif "MARKET SUMMARY" in cln or ("KEY MOVES" in cln and "MACRO" not in cln):
            current = "MARKET AND MACRO"; continue
        elif "EARNINGS CALENDAR"   in cln: current = "EARNINGS AND EVENTS"; continue
        elif "FUN FACT" in cln and "AI" not in cln: current = "AI FUN FACT"; continue

        if current and line.strip():
            secs[current] += line.strip() + "\n"

    for n, c in secs.items():
        icon = "📋" if c.strip() else "⚠️"
        print(f"  {icon} {n}: {len(c)} chars")

    return secs