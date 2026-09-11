# Mean Reversion Macro Insights -- Session Log

Paste this file at the start of any new session so Claude has full context.
No need to summarize the previous chat.

---

## HOW TO START A NEW SESSION

1. Paste SESSION_LOG.md as your first message
2. Say which module you are working on and paste ONLY that file
3. State the specific task

Do NOT paste all 7 modules -- that blows the context window immediately.

**Module map (which file to paste for which bug):**

| Issue area | Paste this file |
|---|---|
| Gold / CAPE / any FRED series | fred.py |
| VIX / SPX / PE / MHS / ERP | market.py |
| Dataroma / Magic Formula / AM / cache | screens.py |
| Email / Edward Jones | news.py |
| Gemini / Haiku / AI output / prompt | ai_synthesis.py |
| Dashboard layout / cards / HTML | html_builder.py |
| Pipeline order / imports / new features | main.py |
| run_cache.json / cache fallback | main.py |
| Cron schedule / GitHub Actions / secrets | daily.yml |

---

## INFRASTRUCTURE SNAPSHOT

- **Live site:** https://anil2040.github.io/market-pulse-ai
- **Repo:** https://github.com/anil2040/market-pulse-ai (public)
- **Owner:** Anil Abraham -- deep-value mean reversion investor
- **Style:** Greenblatt / Carlisle / Howard Marks / Burry / Pabrai
- **Local:** VS Code on Windows 11 Home, Boise ID (MDT = UTC-6 summer)
- **Schedule:** GitHub Actions cron `50 13 * * 1-5` (7:50 AM MT weekdays) + workflow_dispatch
- **Runtime:** ~42 seconds, 15/15 indicators, well within free tier limits

**9 GitHub Secrets (all confirmed set):**
GEMINI_API_KEY, ANTHROPIC_API_KEY, YAHOO_EMAIL, YAHOO_APP_PASSWORD,
FRED_API_KEY, MFI_EMAIL, MFI_PASSWORD, AM_EMAIL, AM_PASSWORD

**Pipeline order (main.py):**
fetch_fred_data -> fetch_fear_greed -> fetch_market_indicators -> compute_mhs ->
fetch_superinvestor_buys -> fetch_magic_formula -> fetch_acquirers_multiple ->
scrape_edward_jones -> fetch_cnbc_email -> fetch_yahoo_morning_brief ->
fetch_mcoscillator_email -> synthesize_with_ai -> build_html

---

## MODULE SUMMARY

| File | Lines | Responsibility |
|---|---|---|
| fred.py | 503 | FRED API, Gold (Yahoo GC=F), CAPE (multpl.com), trend colors, sparklines |
| market.py | ~270 | Yahoo SPX/RUT/VIX, iShares CSV PE, PE_CONFIG fallback, MHS, ERP |
| screens.py | 339 | Dataroma 13F cache+live, Magic Formula ASP.NET auth, Acquirer's Multiple |
| news.py | 156 | Edward Jones scrape, CNBC/Yahoo/McClellan IMAP email |
| ai_synthesis.py | 238 | Gemini 3.6 flash -> 1.5 flash -> Haiku -> structured fallback, parse_sections |
| html_builder.py | ~870 | Full dashboard HTML, gauge market view, live JS refresh, SI 3+ filter |
| main.py | 206 | Orchestrator only -- imports all modules, runs pipeline, run log |
| debug_etf_pe.py | 214 | Quarterly diagnostic -- run manually to re-audit PE sources |

---

## KEY ARCHITECTURE DECISIONS (confirmed, do not revisit)

**AAII:** Fully removed. Incapsula CDN blocks GitHub Actions IPs permanently.
Quiet footnote link remains. Check manually at aaii.com every Thursday.

**Gold:** Yahoo Finance GC=F (GOLDAMGBD228NLBM discontinued by FRED in 2025).

**Shiller CAPE:** multpl.com scrape (FRED never hosted this series).
multpl.com updates monthly -- all three columns (3mo, 12mo, today) showing the same
value is expected behaviour when CAPE hasn't moved in 3 months due to 10yr smoothing.

**ETF PE (URTH/EFA):**
- Priority 1: iShares fund characteristics CSV (free, no auth, "P/E Ratio" row)
- Priority 2: PE_CONFIG dict in market.py (hardcoded quarterly fallback)
- Yahoo v8/v10 broken for ETFs since mid-2026. etf.com/etfdb.com blocked by Cloudflare.
- Playwright considered but rejected: overkill for quarterly PE, adds 45-60s per run.
- Update PE_LAST_UPDATED in market.py each quarter from iShares.com product pages.
- Current values: URTH=22.57x, EFA=18.35x (Sep 10 2026)

**MHS (Macro Heat Score):** Inverted 0-100 composite.
- 0-33 DEPLOY | 34-65 SELECTIVE | 66-85 OVERHEATED | 86-100 EXTREME OVERHEATED
- Base = 50. Components: Core PCE, VIX, Fear&Greed, HY Credit, Yield Curve,
  Fed Posture, Shiller CAPE, Gold Signal.
- EXTREME OVERHEATED posture: quality and patience, not panic. Left Leg 0-2, MoS >30%.

**Market State Detection:**
- marketState taken from SPX (%5EGSPC) only -- VIX marketState is NOT used (unreliable).
- REGULAR -> OPEN, PRE -> PRE, POST -> POST, CLOSED -> CLOSED.
- GitHub Actions IPs blocked by Yahoo for JS/crumb-based API -- only v8 basic fetch works.
- Browser-side JS fetch works fine (not blocked) -- live refresh handled in html_builder.py.

**Live Market Refresh (html_builder.py):**
- Gauge section has embedded JavaScript that calls Yahoo Finance v8 from the browser.
- Runs on page load + every 60s while market is open (Mon-Fri 7:30-16:05 MT).
- Updates SPX, RUT, VIX values, pills, gauge dot positions, and pulse line in real time.
- No backend changes needed -- this is purely client-side.
- Timestamp shown next to "Market Performance" heading after each refresh.

**AI Synthesis fallback chain:**
gemini-3.6-flash (free, 20 RPD resets midnight UTC = 6 PM MT) ->
gemini-1.5-flash (free, separate pool) ->
claude-haiku-4-5 (paid ~$0.003/run, shown in log) ->
structured text (always works)

**Value Screens:**
- SI-only: filtered to >= 3 superinvestor managers (removes 1-2 SI noise)
- MF-only: capped at 25 (Greenblatt daily)
- AM-only: capped at 25 (Carlisle daily)
- Dataroma cache: 20hr TTL, written by fetch_cache.py, read by screens.py
- AM cache: 48hr TTL, written on success, read on failure

**McClellan Oscillator:**
- Card removed. Email is a paid article teaser with no usable data.
- fetch_mcoscillator_email() still runs in pipeline (harmless, ~3s).
- Can remove from news.py + main.py in a future cleanup session.

**Dashboard layout:**
- Gauge-style market performance with live JS refresh
- AI briefing: 2-column grid (Market & Macro + Earnings & Events)
- Valuation block: Shiller CAPE (US) + URTH + EFA + ERP row
- Hidden #market-context div for Chrome extension (compact data string)
- Fun Fact + AI Learning: AI-generated by Gemini synthesis step

---

## SESSION HISTORY

---

### Sessions 1-3 (pre-modularization)
**Date:** Pre Sep 2026
**Status:** Pipeline built. All 15 indicators working.
**Key fixes:** AAII removed (CDN blocks), Gold -> Yahoo GC=F,
CAPE -> multpl.com, ANTHROPIC_API_KEY added to daily.yml.

---

### Session 4
**Date:** Sep 7 2026
**Files changed:** main.py (monolith), daily.yml
**Done:**
- Fixed Gold (GOLDAMGBD228NLBM discontinued -- now Yahoo GC=F)
- Fixed CAPE (SHILLER_CAPE invalid -- now multpl.com)
- Fixed URTH/EFA PE (Yahoo broken -- hardcoded PE_CONFIG)
- Fixed ANTHROPIC_API_KEY missing from daily.yml env block
- Confirmed 15/15 indicators working, 39s runtime

**Last known good run:** Sep 7 2026, 3:17 PM MT
MHS: 94/100 EXTREME OVERHEATED
SPX: 7,719 | RUT: 2,976 | VIX: 15.3 | CAPE: 41.4x | Gold: $4,477
SCREENS_ALL3: CTSH | SCREENS_2OF3: BBY, BMY, CI, CVS, FOXA, HPQ, LDOS, MO, OMC, TEL, ZTS

---

### Session 5 (Part 1) -- Modularization
**Date:** Sep 10 2026
**Files changed:** All 7 modules created + debug_etf_pe.py
**Done:**
- Modularized main.py (1967 lines) into 7 self-contained modules
- PATCH 1: PE_CONFIG with PE_LAST_UPDATED + stale warning (>90 days)
- PATCH 2: Label "US Shiller CAPE" -> "Shiller CAPE (US)"
- PATCH 3: MHS 90+ = EXTREME OVERHEATED (darker red #7f1d1d, 4-tier scale)
- PATCH 4: Equity Risk Premium row (ERP = CAPE yield - 10Y, currently -2.24%)
- debug_etf_pe.py: full audit of all ETF PE sources, all blocked/broken

**Confirmed working:** Sep 10 2026 run, 39s, 15/15 indicators
ERP: -2.24% (bonds yield more than stocks, last seen ~2002)

---

### Session 5 (Part 2) -- UX Improvements
**Date:** Sep 10 2026
**Files changed:** market.py, html_builder.py + SESSION_LOG.md created
**Done:**
- market.py: iShares CSV PE fetch added (tries live first, PE_CONFIG fallback)
- market.py: EXTREME OVERHEATED posture text softened (quality + patience, not panic)
- html_builder.py: Gauge-style market performance (cloned from Chrome extension)
- html_builder.py: "What to Watch" card removed (was restating value screens)
- html_builder.py: McClellan Oscillator "Market Breadth" card added in its place
- html_builder.py: SI-only filter changed to >= 3 managers (removes 1-2 SI noise)
- html_builder.py: AI briefing changed to 2-column grid
- SESSION_LOG.md: created (this file)

---

### Session 6
**Date:** Sep 11 2026
**Files changed:** market.py, main.py, html_builder.py, ai_synthesis.py, daily.yml
**Done:**
- Yahoo PE fetch attempted (HTML + API) -- both blocked by GitHub Actions
  (no JS rendering for HTML, no crumb for API v10). PE_CONFIG confirmed permanent solution.
- PE_CONFIG updated: URTH=22.57x, EFA=18.35x (Sep 10 2026, from Yahoo Finance browser)
- MHS EXTREME OVERHEATED threshold lowered from 90 to 86 (tighter top tier)
- MHS scale: 0-33 DEPLOY | 34-65 SELECTIVE | 66-85 OVERHEATED | 86-100 EXTREME
- run_cache.json implemented: per-indicator persistent fallback
  Each fetch writes on success, reads stale on failure, shows amber cached badge
  Committed back to repo after every run via _commit_cache()
- daily.yml: git add index.html run_cache.json added to final commit step
- Gauge market performance: exact Chrome extension style
  (gradient bar, SELLOFF/DOWN/FLAT/UP/RALLY band labels, no closed/prev language)
- Dir column removed from FRED macro table
- McClellan Oscillator card removed (email is paid article teaser, no value)
- AI prompt rewritten: no data regurgitation, interpret combinations and tensions
- test_pe_fetch.yml added for future PE source debugging

**Confirmed working:** Sep 11 2026 run, 74s, 15/15 indicators, Gemini succeeded
MHS: 94/100 EXTREME OVERHEATED
SPX: 7,670 | RUT: 2,910 | VIX: 15.87 | CAPE: 40.7x | Gold: $4,426 | WTI: $97.3
run_cache.json: committed and pushed successfully on first run

---

### Session 7
**Date:** Sep 11 2026
**Files changed:** market.py, html_builder.py, daily.yml, SESSION_LOG.md
**Done:**
- market.py: Market state detection fixed -- now uses SPX marketState as single
  source of truth (VIX marketState is unreliable and was causing FLAT/+0.00% bug).
  REGULAR->OPEN, PRE->PRE, POST->POST, CLOSED->CLOSED. Defaults to OPEN if unknown.
- market.py: POST/CLOSED now still shows the day's % change (not zeroed out).
  Only PRE-MKT shows "Pre-Market" text instead of a % change.
- market.py: Dead Yahoo PE HTML/API fetch comments cleaned up (code was already
  removed in session 6 but comment noise remained).
- market.py: PE_CONFIG confirmed at URTH=22.57x, EFA=18.35x, date=Sep 10 2026.
- market.py: MHS threshold confirmed at 86 for EXTREME OVERHEATED.
- html_builder.py: Gauge section rebuilt with individual element IDs (spx-val,
  spx-chg, spx-pill, spx-dot, rut-*, vix-*, pulse-line, mkt-refresh-ts).
- html_builder.py: Live JS refresh block added -- calls Yahoo Finance v8 directly
  from the browser on page load and every 60s during market hours (7:30-16:05 MT).
  This mirrors the Chrome extension behaviour. No backend changes needed.
- html_builder.py: Refresh timestamp shown next to "Market Performance" heading.
- daily.yml: Cron changed from `55 12` (6:55 AM MT) to `50 13` (7:50 AM MT).
  Market opens 7:30 AM MT -- pipeline now runs 20 min after open for live prices.
- SESSION_LOG.md: Module map updated (added daily.yml row). Session 7 documented.

**Open items / next session:**
- Remove fetch_mcoscillator_email() from news.py and its call in main.py (dead code,
  wastes ~3s per run, McClellan card already removed from dashboard)
- Verify live JS refresh works correctly on first load after deploy
- Consider future: SEC EDGAR 13F API as Dataroma replacement
- Consider future: Chrome extension token optimization (~60% reduction possible)

---

## PLAYWRIGHT REFERENCE (for future use)

When you need to scrape JavaScript-rendered pages, Playwright is the tool.
It runs a real headless browser and can execute JS, wait for elements, click buttons.

**Install in daily.yml** (add before pip install step):
```yaml
- name: Install Playwright
  run: |
    pip install playwright --break-system-packages
    playwright install chromium --with-deps
```

**Python usage pattern:**
```python
from playwright.sync_api import sync_playwright

def scrape_with_playwright(url, selector):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page    = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=30000)
        text    = page.locator(selector).text_content()
        browser.close()
        return text
```

**When to use:** Any page that returns blank/incomplete HTML with regular requests
because the content loads via JavaScript after page load.
**Tradeoff:** Adds 45-60 seconds per page to pipeline runtime.
**Current status:** Not in pipeline. Evaluated for iShares PE -- rejected (quarterly data,
overhead not worth it). Ready to implement if a daily JS-rendered source is needed.

---

## NOTES ON INVESTING STYLE (for AI prompt context)

- Deep value, mean reversion framework
- Greenblatt (Magic Formula), Carlisle (Acquirer's Multiple), Howard Marks, Burry, Pabrai
- US-focused, holds international ADRs (EQNR, PBR, SNY, NVO, SHEL, BP etc.)
- Long-term holder, not a trader
- Key metrics: Left Leg score, Margin of Safety (MoS >25%)
- MHS is the macro backdrop gauge -- it sets the bar, not a buy/sell trigger
- EXTREME OVERHEATED (86+): raise bar, not panic. Quality and patience above all.
- Loves the value screens (All-3 = highest conviction, 2-of-3 = strong convergence)
- Does NOT want prescriptive rule-based instructions hardcoded in the AI prompt
- Prefers genuine insights over data regurgitation
- Frustrated by repeated news stories across days (e.g. same Nvidia headline daily)