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

---

## INFRASTRUCTURE SNAPSHOT

- **Live site:** https://anil2040.github.io/market-pulse-ai
- **Repo:** https://github.com/anil2040/market-pulse-ai (public)
- **Owner:** Anil Abraham -- deep-value mean reversion investor
- **Style:** Greenblatt / Carlisle / Howard Marks / Burry / Pabrai
- **Local:** VS Code on Windows 11 Home, Boise ID (MDT = UTC-6 summer)
- **Schedule:** GitHub Actions cron `55 12 * * 1-5` (6:55 AM MT weekdays) + workflow_dispatch
- **Runtime:** ~39 seconds, 15/15 indicators, well within free tier limits

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
| market.py | 449 | Yahoo SPX/RUT/VIX, iShares CSV PE, PE_CONFIG fallback, MHS, ERP |
| screens.py | 339 | Dataroma 13F cache+live, Magic Formula ASP.NET auth, Acquirer's Multiple |
| news.py | 156 | Edward Jones scrape, CNBC/Yahoo/McClellan IMAP email |
| ai_synthesis.py | 238 | Gemini 3.6 flash -> 1.5 flash -> Haiku -> structured fallback, parse_sections |
| html_builder.py | 834 | Full dashboard HTML, gauge market view, breadth card, SI 3+ filter |
| main.py | 206 | Orchestrator only -- imports all modules, runs pipeline, run log |
| debug_etf_pe.py | 214 | Quarterly diagnostic -- run manually to re-audit PE sources |

---

## KEY ARCHITECTURE DECISIONS (confirmed, do not revisit)

**AAII:** Fully removed. Incapsula CDN blocks GitHub Actions IPs permanently.
Quiet footnote link remains. Check manually at aaii.com every Thursday.

**Gold:** Yahoo Finance GC=F (GOLDAMGBD228NLBM discontinued by FRED in 2025).

**Shiller CAPE:** multpl.com scrape (FRED never hosted this series).

**ETF PE (URTH/EFA):**
- Priority 1: iShares fund characteristics CSV (free, no auth, "P/E Ratio" row)
- Priority 2: PE_CONFIG dict in market.py (hardcoded quarterly fallback)
- Yahoo v8/v10 broken for ETFs since mid-2026. etf.com/etfdb.com blocked by Cloudflare.
- Playwright considered but rejected: overkill for quarterly PE, adds 45-60s per run.
- Update PE_LAST_UPDATED in market.py each quarter from iShares.com product pages.

**MHS (Macro Heat Score):** Inverted 0-100 composite.
- 0-33 DEPLOY | 34-65 SELECTIVE | 66-89 OVERHEATED | 90-100 EXTREME OVERHEATED
- Base = 50. Components: Core PCE, VIX, Fear&Greed, HY Credit, Yield Curve,
  Fed Posture, Shiller CAPE, Gold Signal.
- EXTREME OVERHEATED posture: quality and patience, not panic. Left Leg 0-2, MoS >30%.

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

**Dashboard layout:**
- Gauge-style market performance (cloned from Chrome extension view)
- Market Breadth card using McClellan Oscillator email (replaces "What to Watch")
- AI briefing: 2-column grid (Market & Macro + Earnings & Events)
- Valuation block: Shiller CAPE (US) + URTH + EFA + ERP row
- Hidden #market-context div for Chrome extension (compact data string)

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

**Open items / next session:**
- Playwright: documented but not implemented (overkill for quarterly PE)
- run_cache.json fallback: if any fetch fails, serve last known good data (future)
- SEC EDGAR 13F API: future replacement for Dataroma scraping
- Chrome extension token optimization: ~60% reduction possible (future)

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

**Open items / next session:**
- Remove Yahoo PE HTML/API fetch code from market.py (dead code, adds noise to logs)
- SESSION_LOG module map: add run_cache.json -> main.py entry
- Consider replacing McClellan card space with something useful
  (e.g. AAII reminder, or a simple What to Watch card from AI briefing section)

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
- EXTREME OVERHEATED (90+): raise bar, not panic. Quality and patience above all.
- Loves the value screens (All-3 = highest conviction, 2-of-3 = strong convergence)
- Does NOT want prescriptive rule-based instructions hardcoded in the AI prompt
- Prefers genuine insights over data regurgitation
- Frustrated by repeated news stories across days (e.g. same Nvidia headline daily)
