# Mean Reversion Macro Insights -- Session Log 5

Paste this file at the start of any new session so Claude has full context.
No need to summarize the previous chat.

---

## HOW TO START A NEW SESSION

1. Paste SESSION_LOG.md as your first message
2. Say which module you are working on and paste ONLY that file
3. State the specific task

Do NOT paste all modules at once -- that blows the context window immediately.

**Module map (which file to paste for which bug):**

| Issue area | Paste this file |
|---|---|
| Gold / CAPE / any FRED series | fred.py |
| VIX / SPX / PE / MHS / ERP | market.py |
| Dataroma / Magic Formula / AM / cache | screens.py |
| Email / Edward Jones / Yahoo calendar | news.py |
| Gemini / Haiku / AI output / prompt | ai_synthesis.py |
| Dashboard layout / cards / HTML | html_builder.py |
| Pipeline order / imports / new features | main.py |
| run_cache.json / cache fallback / MHS history | main.py |
| Cron schedule / GitHub Actions / secrets | daily.yml |
| Claude Routine (market prices / pre-market data) | clauderoutinedata.json |

---

## INFRASTRUCTURE SNAPSHOT

- **Live site:** https://anil2040.github.io/market-pulse-ai
- **Repo:** https://github.com/anil2040/market-pulse-ai (public)
- **Owner:** Anil Abraham -- deep-value mean reversion investor
- **Style:** Greenblatt / Carlisle / Howard Marks / Burry / Pabrai
- **Local:** VS Code on Windows 11 Home, Boise ID (MDT = UTC-6 summer)
- **Schedule:** GitHub Actions cron `50 13 * * 1-5` (7:50 AM MT weekdays) + workflow_dispatch
- **Runtime:** ~40-45 seconds, 15/15 indicators, well within free tier limits

**9 GitHub Secrets (all confirmed set):**
GEMINI_API_KEY, ANTHROPIC_API_KEY, YAHOO_EMAIL, YAHOO_APP_PASSWORD,
FRED_API_KEY, MFI_EMAIL, MFI_PASSWORD, AM_EMAIL, AM_PASSWORD

**Pipeline order (main.py) -- runs weekdays only via cron:**
Step 0: load_claude_routine (clauderoutinedata.json, written 7:44am MT by Claude Routine)
Step 1: fetch_fred_data
Step 2: fetch_fear_greed
Step 3: fetch_market_indicators (uses routine PE as priority 0)
Step 4: compute_mhs + _append_mhs_history (writes to run_cache.json)
Step 5: fetch_superinvestor_buys
Step 6: fetch_magic_formula (returns ordered list of (ticker, rank) tuples)
Step 7: fetch_acquirers_multiple (returns ordered list of (ticker, multiple_str) tuples)
Step 8: scrape_edward_jones
Step 9: fetch_cnbc_email
Step 10: fetch_yahoo_morning_brief (returns (brief_text, calendar_text) tuple)
Step 11: synthesize_with_ai (Gemini -> Haiku -> structured fallback)
Step 12: build_html
Step 13: save + commit run_cache.json

All steps including AI synthesis run every weekday. Fun Fact and AI Learning
regenerate fresh each run -- stale content on weekends is expected (no pipeline run).

---

## MODULE SUMMARY

| File | Lines | Responsibility |
|---|---|---|
| fred.py | ~503 | FRED API, Gold (Yahoo GC=F), CAPE (multpl.com), trend colors, sparklines, interpretive insights |
| market.py | ~320 | Yahoo SPX/RUT/VIX, Claude Routine PE (priority 0), iShares CSV PE, PE_CONFIG fallback, MHS, ERP |
| screens.py | ~350 | Dataroma 13F cache+live, Magic Formula (ordered list+rank), Acquirer's Multiple (ordered list+multiple) |
| news.py | ~282 | Edward Jones scrape, CNBC/Yahoo IMAP email, Yahoo calendar extractor |
| ai_synthesis.py | ~280 | Gemini 3.6 flash -> 1.5 flash -> Haiku -> structured fallback, 4 sections, routine context in prompt |
| html_builder.py | ~1650 | Full dashboard HTML, market card (routine-sourced), MHS history chart, 5-day calendar, conviction chips |
| main.py | ~580 | Orchestrator -- imports all modules, runs pipeline, MHS history append, weekly calendar cache |
| debug_etf_pe.py | 214 | Quarterly diagnostic -- run manually to re-audit PE sources |

---

## KEY ARCHITECTURE DECISIONS (confirmed, do not revisit)

**AAII:** Fully removed. Incapsula CDN blocks GitHub Actions IPs permanently.
Quiet footnote link remains. Check manually at aaii.com every Thursday.

**Gold:** Yahoo Finance GC=F (GOLDAMGBD228NLBM discontinued by FRED in 2025).

**Shiller CAPE:** multpl.com scrape (FRED never hosted this series).
multpl.com updates monthly -- all three columns (3mo, 12mo, today) showing the same
value is expected behaviour when CAPE hasn't moved in 3 months due to 10yr smoothing.

**ETF PE (URTH/EFA) -- 3-priority system:**
- Priority 0: Claude Routine JSON (clauderoutinedata.json, fresh = today's date)
  Source label shows "Claude Routine" with no timestamp. Always fresh by 7:50am MT.
- Priority 1: iShares fund characteristics CSV (free, no auth, "P/E Ratio" row)
- Priority 2: PE_CONFIG dict in market.py (hardcoded quarterly fallback)
  Shows amber "UPDATE NEEDED" warning if >90 days stale.
- Yahoo v8/v10 broken for ETFs since mid-2026. etf.com/etfdb.com blocked by Cloudflare.
- Current PE_CONFIG values: URTH=22.57x, EFA=18.35x (Sep 10 2026)

**Claude Routine -- TWO separate routines:**

Routine 1: 4:00am MT -- "Pre-Market Briefing" (personal reading only, no file output)
- Outputs formatted pre-market text briefing for Anil to read
- Covers: futures, overnight macro (3 events), global markets, rates/oil, what to watch
- Format: emoji-headed sections (OVERNIGHT / GLOBAL MARKETS / FUTURES / RATES & OIL / WATCH TODAY)
- NO GitHub commit, NO clauderoutinedata.json write

Routine 2: 7:44am MT -- "Market Data" (machine-readable JSON, writes clauderoutinedata.json)
- 5-minute gap before 7:50am pipeline is sufficient (JSON commit only, no build step)
- Contains sections A-G: futures, ETF PE, macro/rates, sector movers, global markets,
  open_focus, AND market_prices (new in Session 9)
- ETF PE from routine used as priority 0 in market.py _yq_pe()
- market_prices block used as PRIMARY source for Market Performance card
- Injected into AI synthesis prompt as PRE-MARKET INTELLIGENCE block
- Staleness: if routine date != today MT, amber banner shown in valuation block

**clauderoutinedata.json schema (written by 7:44am routine):**
```json
{
  "date": "YYYY-MM-DD",
  "time_collected_utc": "HH:MM",
  "futures": {
    "sp500": {"change_pct": 0.00, "direction": "up"},
    "nasdaq100": {"change_pct": 0.00, "direction": "up"},
    "dow": {"change_pct": 0.00, "direction": "up"},
    "sentiment": "bullish"
  },
  "etf_pe": {
    "URTH": {"pe_ttm": 0.00, "proxy_for": "MSCI World", "source": "stockanalysis.com"},
    "EFA":  {"pe_ttm": 0.00, "proxy_for": "MSCI EAFE ex-US Developed", "source": "stockanalysis.com"}
  },
  "rates_commodities": {
    "treasury_10yr_pct": 0.00,
    "crude_oil_usd": 0.00,
    "crude_oil_type": "WTI"
  },
  "macro_events": ["event1", "event2", "event3"],
  "sector_movers": {
    "leading": [{"sector": "...", "change_pct": 0.00, "reason": "..."}],
    "lagging":  [{"sector": "...", "change_pct": 0.00, "reason": "..."}]
  },
  "global_markets": {
    "europe": {"index": "STOXX600", "direction": "up", "change_pct": 0.00},
    "asia":   {"index": "Nikkei",   "direction": "up", "change_pct": 0.00}
  },
  "open_focus": "One sentence on what traders are watching at the open.",
  "market_prices": {
    "sp500": {"prev_close": 0.00, "current": 0.00, "change_pct": 0.00, "source_time_et": "07:44"},
    "rut":   {"prev_close": 0.00, "current": 0.00, "change_pct": 0.00, "source_time_et": "07:44"},
    "vix":   {"prev_close": 0.00, "current": 0.00}
  }
}
```

**Market Performance Card -- data source changed Session 9:**
- PRIMARY: routine_data["market_prices"] (browser-fetched at 7:44am MT, no CORS issue)
- FALLBACK: mkt_data from market.py pipeline fetch (server-side, may show stale after close)
- NO live JS fetch -- removed entirely. Yahoo Finance CORS-blocks requests from github.io.
  Chrome extension works because extensions bypass CORS via host_permissions in manifest.
  github.io static pages cannot bypass CORS -- all browser fetch attempts return ERR_FAILED.
- Card header shows "as of HH:MM ET · via Claude Routine" when routine data present
- All classify/color/label logic is now Python-side (_classify_idx, _classify_vix, etc.)
- routine_fresh_prices flag: True if market_prices present and sp500.current > 0

**MHS (Macro Heat Score):** Inverted 0-100 composite. FRAMEWORK LOCKED AT V1.0.
- 0-33 DEPLOY | 34-65 SELECTIVE | 66-85 OVERHEATED | 86-100 EXTREME OVERHEATED
- Base = 50. Components: Core PCE, VIX, Fear&Greed, HY Credit, Yield Curve,
  Fed Posture, Shiller CAPE, Gold Signal.
- EXTREME OVERHEATED posture text: "Macro is at its most stretched since dot-com."
  (macro observation only -- no stock-picking prescription, no behavioral advice)
- History stored in run_cache.json under "mhs_history" key as array of
  {date, score, label} objects. Appended once per weekday run. Capped at 252 entries.
- Chart: inline SVG W=680px, zone labels overlaid INSIDE chart bands (not separate panel).
  Zones top-to-bottom: EXTREME (86-100), OVERHEATED (66-85), SELECTIVE (34-65), DEPLOY (0-33).
  Daily score = blue line. 20-day SMA = amber line. Zone labels right-aligned inside bands.
  20-day SMA appears after ~4 trading weeks of data from Sep 19 2026.
- DO NOT change thresholds or component weights -- breaks historical comparability.
- mhs_scale text block below card REMOVED (legend is now inside chart bands).

**Market State Detection:**
- marketState taken from SPX (%5EGSPC) only -- VIX marketState is NOT used (unreliable).
- REGULAR -> OPEN, PRE -> PRE, POST -> POST, CLOSED -> CLOSED.
- GitHub Actions IPs blocked by Yahoo for JS/crumb-based API -- only v8 basic fetch works.
- Live JS browser fetch REMOVED from html_builder.py (CORS blocked from github.io).

**AI Synthesis fallback chain:**
gemini-3.6-flash (free, 1,500 RPD, resets daily) ->
gemini-2.5-flash (free, separate pool, stable) ->
claude-haiku-4-5 (paid, ~$0.01-0.02/run depending on prompt size, shown in log) ->
structured text (always works)

Note: gemini-1.5-flash is dead/removed from free tier. Replaced with gemini-2.5-flash.
Note: gemini-3.6-flash is the correct model ID (stable since July 21 2026).

**AI Synthesis -- 4 sections (Earnings & Events removed Sep 2026):**
MARKET AND MACRO | WHAT TO WATCH | AI FUN FACT | AI LEARNING
- MARKET AND MACRO and WHAT TO WATCH shown as true 2-column CSS grid layout.
  Left col: "Macro Interpretation" (blue label). Right col: "What to Watch" (green label).
  No --- sentinel merge. _merge_macro_sections() still exists but is no longer called.
- No data regurgitation -- interpretive macro implications only.
- Yahoo calendar injected as WEEK AHEAD block in prompt for date-specific events.
- Claude Routine pre-market intelligence injected as PRE-MARKET INTELLIGENCE block.
- Fun Fact and AI Learning regenerate fresh every weekday run. Stale on weekends is expected.

**Value Screens -- return types changed Sep 2026:**
- SI: dict {ticker: count} -- unchanged
- MF: ordered list of (ticker, rank_int) tuples -- rank 1 = highest conviction
- AM: ordered list of (ticker, multiple_str) tuples -- position 1 = lowest multiple
- Both preserve site rank order (set() destroyed it before)
- Conviction chips: all3/two3 chips show enriched tags e.g. (4SI,MF#12,AM 8.00x)
- MF-only chips show rank: ANF #1, ADBE #2
- AM-only chips show multiple: SYF (2.50x), EQNR (3.40x)
- SI-only: filtered to >= 3 managers (removes 1-2 SI noise)
- two3 sorted by conviction: MF rank asc, then AM multiple asc, then SI count desc, then alpha

**Weekly Economic Calendar:**
- Yahoo Morning Brief IMAP fetch returns (brief_text, calendar_text) tuple
- Monday brief has full week Mon-Fri calendar
- Stored in run_cache.json under "weekly_calendar" key on Monday: {week_of: "YYYY-MM-DD", text: "..."}
- Tue-Fri: reads from cache if same week's Monday date matches
- Monday storage guard: _is_real_calendar() validates text contains a weekday name before storing.
  If extraction invalid: keeps existing cache rather than overwriting with garbage.
- Renders as 5-day box grid with TODAY badge and blue border
- Day labels show actual date: MON 9/22, TUE 9/23, etc.
- Economic items split on semicolons and rendered as individual bullets
- Earnings items: BS4 inserts newlines inside <a> tags; _parse_calendar_into_days() uses
  earn_buffer state machine to reconstruct "Company (TICKER)" from fragmented lines
- Section header: "Earnings & Economic Calendar for the Week"

**Amber Badge (FRED Macro Indicators table):**
- Fires only on weekdays (pipeline and FRED don't update on weekends)
- Fires only when fetched date is strictly older than yesterday (2+ days old)
- Monday: Friday's data correctly shows as stale until pipeline runs at 7:50am MT
- Weekends: no badges shown (expected -- no weekend runs)
- Determined by comparing cache["fred_{label}"]["fetched"] date to today UTC
- ⚠️ in Insights column = fred.py interpretive sig text prefix (separate from amber badge)
  Stripped with re.sub() in td rendering. Subtitle clarifies the difference.

**McClellan Oscillator:** Fully removed Sep 2026. Paid teaser only.

**Dashboard layout (current -- Sep 2026):**
1. Fun Fact + AI Learning: gradient cards at top
2. Earnings & Economic Calendar for the Week (5-day box grid, stored from Monday's brief)
3. MHS score card with h2 header + history SVG chart below (W=680, inline zone labels)
4. Market Performance (gauge, routine-sourced) + Market Sentiment (2-col grid)
5. Global Market Valuation (CAPE + URTH + EFA + ERP)
6. Market & Macro (true 2-column CSS grid: Macro Interpretation / What to Watch)
7. Value Screens (All-3, 2-of-3 by conviction, SI-only, MF-only ranked, AM-only ranked)
8. Macro Indicators table (15 indicators, interpretive insights column)
9. Run log (collapsed, shows all pipeline steps with timing)
10. Hidden #market-context div for Chrome extension

**Header (simplified Session 9):**
- URL removed (redundant with address bar)
- Date and "Updated HH:MM MT" merged onto one .sub line. .ts row removed entirely.

**run_cache.json structure:**
- fred_{label}: per FRED indicator fallback, includes "fetched" date
- fear_greed: CNN Fear & Greed
- market_indicators: SPX/RUT/VIX/PE block
- screens_si: {ticker: count} dict
- screens_mf: [[ticker, rank], ...] list of pairs
- screens_am: [[ticker, multiple_str], ...] list of pairs
- news_ej / news_cnbc / news_yahoo / news_yahoo_calendar: email caches
- weekly_calendar: {week_of, text} -- stored Monday, used all week
- mhs_history: [{date, score, label}, ...] -- up to 252 entries, appended daily

**Yahoo Morning Brief -- email fetch architecture (fixed Session 9):**
- Yahoo email has TWO MIME parts: tiny text/plain (~1200 chars, spam-filter teaser only)
  and full newsletter in text/html. Code MUST use prefer_html=True to get full content.
- Calendar section is at the END of the email (~char 7,874 in clean text, ~20,000+ in raw HTML).
  char_limit must be None to avoid truncating before the calendar section.
- _fetch_email_raw(prefer_html=True, char_limit=None) for Yahoo Brief only.
- CNBC Morning Squawk: default (prefer_html=False, char_limit=2500) -- plain text works fine.

---

## GITHUB ACTIONS NOTES

- ubuntu-latest PINNED to ubuntu-24.04 as of Sep 20 2026 (migrates to Ubuntu 26 on Oct 19 2026).
- actions/checkout bumped to @v5, actions/setup-python bumped to @v6 (Node.js 22, clears warnings).
- The github-pages Bot "pages build and deployment" workflow is GitHub-internal -- its ubuntu-latest
  warning cannot be fixed by you. Not your workflow, ignore it.
- Canceling/superseded Pages deployments are normal when two commits happen close together.
- "Run job" = "trigger the workflow" = click Run workflow in Actions tab.
- Workflow dispatch (manual trigger): repo -> Actions -> MarketPulse Daily Briefing -> Run workflow

---

## SESSION HISTORY

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
- html_builder.py: SI-only filter changed to >= 3 managers (removes 1-2 SI noise)
- html_builder.py: AI briefing changed to 2-column grid
- SESSION_LOG.md: created

---

### Session 6
**Date:** Sep 11 2026
**Files changed:** market.py, main.py, html_builder.py, ai_synthesis.py, daily.yml
**Done:**
- PE_CONFIG confirmed permanent solution (all live sources blocked by GitHub Actions IPs)
- PE_CONFIG updated: URTH=22.57x, EFA=18.35x (Sep 10 2026, from Yahoo Finance browser)
- MHS EXTREME OVERHEATED threshold lowered from 90 to 86 (tighter top tier)
- MHS scale: 0-33 DEPLOY | 34-65 SELECTIVE | 66-85 OVERHEATED | 86-100 EXTREME
- run_cache.json implemented: per-indicator persistent fallback
- daily.yml: git add index.html run_cache.json added to final commit step
- Gauge market performance: exact Chrome extension style
- Dir column removed from FRED macro table
- AI prompt rewritten: no data regurgitation, interpret combinations and tensions

**Confirmed working:** Sep 11 2026 run, 74s, 15/15 indicators, Gemini succeeded
MHS: 94/100 EXTREME OVERHEATED

---

### Session 7
**Date:** Sep 17 2026
**Files changed:** market.py, html_builder.py, daily.yml, SESSION_LOG.md
**Done:**
- market.py: Market state detection fixed -- SPX marketState as single source of truth
- html_builder.py: Gauge section rebuilt with individual element IDs
- daily.yml: Cron changed from 6:55 AM MT to 7:50 AM MT

---

### Session 8 -- Claude Routine Integration + Major UX Overhaul
**Date:** Sep 19-22 2026
**Files changed:** ALL 7 modules + run_cache.json + daily.yml

**Claude Routine integration (clauderoutinedata.json):**
- 4am Claude Routine writes pre-market JSON to repo before 7:50am pipeline
- ETF PE from routine used as priority 0 in market.py (above iShares CSV)
- Routine pre-market data injected into AI synthesis prompt as PRE-MARKET INTELLIGENCE block
- Staleness detection: amber banner if routine date != today MT
- routine_data and routine_fresh passed through entire pipeline

**daily.yml:**
- ubuntu-latest pinned to ubuntu-24.04 (Oct 19 deadline, committed Sep 20)
- actions/checkout@v4 -> @v5, actions/setup-python@v5 -> @v6

**market.py:**
- _yq() chg fix: always compute manually, never trust Yahoo's field
- _yq_pe(): priority 0 = Claude Routine, priority 1 = iShares CSV, priority 2 = PE_CONFIG
- MHS EXTREME OVERHEATED posture trimmed to macro observation only

**screens.py:**
- fetch_magic_formula() now returns ordered list of (ticker, rank) tuples
- fetch_acquirers_multiple() now returns ordered list of (ticker, multiple_str) tuples
- am_cache.json updated to store pairs format (backward compatible)

**news.py:**
- McClellan removed entirely
- fetch_yahoo_morning_brief() returns (brief_text, calendar_text) tuple
- Yahoo Brief char limit raised from 2000 to 4000
- _extract_calendar() added: extracts Earnings and economic calendar section

**main.py:**
- load_claude_routine() added as step 0
- _append_mhs_history() added: writes one entry per day to mhs_history in cache
- _wrap_screens() updated for ordered list return types
- _wrap_news() restructured for Yahoo tuple return + separate calendar cache key

**ai_synthesis.py:**
- Earnings & Events section removed (was showing stale Nvidia/HuggingFace for weeks)
- Now 4 sections: MARKET AND MACRO | WHAT TO WATCH | AI FUN FACT | AI LEARNING
- routine_data and routine_fresh params added
- Yahoo calendar injected as WEEK AHEAD block in prompt

**html_builder.py:**
- Amber badge: now weekday-only, fires only when data is 2+ days old
- two3 chips sorted by conviction: MF rank asc, AM multiple asc, SI count desc, then alpha
- Calendar header: "Earnings & Economic Calendar for the Week"
- Calendar day labels: now show actual date (MON 9/15, TUE 9/16, etc.)
- Calendar items: semicolons split into individual bullets
- Market & Macro: true 2-column CSS grid (Macro Interpretation / What to Watch)
- Page sequence reordered: Calendar -> MHS -> Market -> Valuation -> Macro -> Screens -> Indicators
- MHS card: added h2 blue section header matching all other cards
- All card h2 font size bumped .62rem -> .76rem for easier section scanning
- Macro Indicators subtitle: removed FRED/Yahoo/multpl source details

**run_cache.json:**
- mhs_history backfilled: Sep 12-18 = 86, Sep 19 = 91 (7 entries)
- weekly_calendar seeded with Sep 14-18 data for layout preview
- screens_mf and screens_am updated to [[ticker, value], ...] format

**Confirmed working:** Sep 19-22 2026
MHS: 91/100 EXTREME OVERHEATED

---

### Session 9 -- Yahoo Calendar, MHS Legend, Market Performance, CORS Resolution
**Date:** Sep 22 2026
**Files changed:** news.py, html_builder.py

**Issue 1: Yahoo calendar not populating -- 3-layer root cause fixed**
- Layer 1: char_limit=12000 truncated body before calendar section
- Layer 2 (real root cause): text/plain MIME part (~1200 chars teaser) found first,
  code stopped there, never read text/html which has full content including calendar
- Layer 3: _build_weekly_calendar guard overwrote good cache with bad extraction
  ("The week ahead" false-positive matched at char 124 in intro, stored 756 chars garbage)
- Fix news.py: prefer_html=True parameter on _fetch_email_raw(), char_limit=None
- Fix html_builder.py: _is_real_calendar() validates weekday name present before storing;
  keeps existing cache if new extraction is invalid
- Fix news.py: removed broken regex from _extract_calendar() (was collapsing day boundaries)

**Issue 2: Earnings clunky display -- fixed**
- Root cause: BS4 get_text("\n") inserts newlines inside <a> tags, splitting
  "THOR Industries (THO)" into 4 separate lines: "THOR Industries" / "(" / "THO" / ")"
- Attempted regex fix collapsed day boundaries (all data merged into Tuesday column)
- Final fix: complete rewrite of _parse_calendar_into_days() with earn_buffer state machine
  Detects "Company (" -> buffer; bare "TICKER" -> appends; ")," -> flushes, starts next
  Day headers always flush buffer first -- boundaries never corrupted
  Tested against real Yahoo email: all 5 days correct, all tickers clean as "Company (TICKER)"

**Issue 3: Amber/sig text confusion -- fixed**
- ⚠️ was part of fred.py sig string prefix, not the amber cache badge (two separate things)
- Stripped leading ⚠️ and ⚡ from sig strings with re.sub(chr(9888)...) in td rendering
- Subtitle updated to clarify the difference

**Issue 4: MHS chart legend -- fixed**
- Old: separate 160px right panel (TOTAL_W=720)
- New: zone labels overlaid INSIDE chart bands, right-aligned, vertically centred per band
- Width W=680, no TOTAL_W/LEGEND_W
- Zones ordered EXTREME top, DEPLOY bottom (matches y-axis -- high score = top)
- mhs_scale text block below card removed entirely

**Issue 5: Market Performance +0.00% FLAT -- root cause found, architecture changed**
- Root cause: Yahoo Finance CORS-blocks browser fetches from github.io (ERR_FAILED every time)
  Chrome extension worked because extensions have host_permissions that bypass CORS.
  github.io static pages cannot bypass CORS. All JS fix attempts were irrelevant.
- Removed entire JS fetch block from html_builder.py
- Solution: Claude Routine fetches SPX/RUT/VIX at 7:44am MT (browser, no CORS)
  writes market_prices to clauderoutinedata.json; pipeline reads and bakes into HTML
- routine_fresh_prices flag gates logic; fallback to mkt_data if routine missing
- Card header shows "as of HH:MM ET · via Claude Routine"
- All classify/color/label logic moved to Python side

**Issue 6: Header cleanup -- fixed**
- URL removed from hero, date + updated time merged onto single .sub line

**Claude Routine restructured:**
- 4:00am MT: personal pre-market briefing only (no file output, no JSON)
- 7:44am MT: writes full clauderoutinedata.json including new market_prices block

**Confirmed working Sep 22 2026:**
- Calendar: populating correctly, 5-day grid rendering
- Earnings: clean "Company (TICKER)" format, correct day separation
- MHS chart: inline legend, EXTREME top / DEPLOY bottom
- Market Performance: showing correct values from routine (SPX +0.19%, RUT -0.03%)
- Header: URL removed, one-line date+time

---

## CODING REQUIREMENTS (permanent, apply every session)

1. **ALWAYS provide full file rewrites.** Never provide partial diffs, find/replace patches,
   or section snippets. Always output the complete file content so Anil can paste and save
   without any manual merging. Partial patches have caused errors and wasted tokens.

2. **One file at a time.** If multiple files need changes, do them sequentially, one complete
   file per response. Do not batch multiple files into one response.

3. **Confirm understanding before writing code.** State which file you are about to rewrite
   and what changes you are making, then write the full file.

---

## OPEN ITEMS / NEXT SESSION

1. **MHS 20-day SMA** -- will appear ~4 weeks from Sep 19 2026. No action needed.

2. **Calendar persistence** -- verify calendar stays populated Tue-Fri from Monday cache.

3. **Market Performance accuracy** -- verify 7:44am routine values match Chrome extension
   each morning. If routine runs late or fails, card falls back to pipeline mkt_data (stale).

4. **Future: SEC EDGAR 13F API as Dataroma backup**
   Dataroma working fine. EDGAR full-text search provides same 13F data if it goes down.

5. **Future: Chrome extension #market-context div compression (~60% reduction possible)**
   Low priority.

6. **ai_synthesis.py** -- needs these confirmed fixes (Sep 22 2026):
   a. Replace gemini-1.5-flash with gemini-2.5-flash in models_to_try list
   b. Update Haiku cost display to use dynamic token counts from the message object
   c. Remove duplicate {routine_block} in prompt (appears twice)
   d. Update comment block at top of file to match new model names and cost

---

### Session 10 -- Model fixes, cost math, coding requirements
**Date:** Sep 22 2026
**Files changed:** ai_synthesis.py (pending), SESSION_LOG.md

**Token math (confirmed from Anthropic dashboard):**
- Haiku 4.5 pricing: $1.00/M input tokens, $5.00/M output tokens
- 30-day dashboard: 10,743 in + 2,454 out = $0.023 total across 2 Haiku runs
- Today's run: 3,753 in + 953 out = $0.0085
- Yesterday's run: 6,990 in + 1,522 out = $0.0146 (larger because longer news email / calendar)
- Token count variation run-to-run: driven by prompt size (news text, calendar text lengths vary)
- Safe per-run estimate for display: ~$0.02 (worst case observed * 1.25 buffer)
- Code fix: use dynamic token count from message.usage object instead of hardcoded guess

**GitHub Actions cron drift:** 8-minute delay (7:50 -> 7:58) is normal documented behavior.
GitHub schedule events can be delayed under high load. Not a bug. No fix needed.

**Gemini model IDs confirmed:**
- gemini-3.6-flash: stable production model (released July 21 2026), correct ID confirmed
- gemini-1.5-flash: DEAD, removed from free tier -- replaced with gemini-2.5-flash
- gemini-2.5-flash: stable, free tier, correct replacement

**HTML width observation:** The top rows appear narrower because they use grid-2 (2-column)
layout. Cards from Global Valuation onward are full-width single cards. This is intentional,
not a bug. No width fix needed.

**GSD (Git. Ship. Done.):** Anil is exploring GSD for future projects. GSD uses fresh
sub-agents + .planning/ files instead of session logs. Not needed for this project.
For new projects: npx @opengsd/gsd-core@latest --claude --local in Claude Code.

**Coding requirement added:** Always provide full file rewrites, never partial diffs.

---

## PLAYWRIGHT REFERENCE (for future use)

When you need to scrape JavaScript-rendered pages, Playwright is the tool.

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
- No repeated news stories across days (e.g. same Nvidia headline daily)
- No em dashes, no en dashes in Claude responses
- Windows 11 Home -- never give Mac instructions or shortcuts