# Mean Reversion Macro Insights -- Session Log 14

Paste this file at the start of any new session so Claude has full context.
No need to summarize the previous chat.

---

## HOW TO START A NEW SESSION

**Option A (recommended -- no file paste needed):**
Send this as your first message:

> Fetch the session log from
> https://raw.githubusercontent.com/anil2040/market-pulse-ai/main/SESSION_LOG.md
> and confirm you have full context before we start.
> I am working on [module name] and the task is [specific task].

Claude will fetch the live file directly from GitHub. No copy-paste, no upload.
This only works if SESSION_LOG.md on main is up to date (commit it at end of each session).

**Option B (fallback -- if GitHub fetch fails):**
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
| Stale data warnings / freshness rules / banner logic | health.py |
| Boise time / daylight saving | timeutil.py |
| Refreshing the quarterly Dataroma 13F file by hand | fetch_cache.py (run on your PC) |
| Claude Routine (market prices / pre-market data) | clauderoutinedata.json |

---

## CODING REQUIREMENTS (permanent, apply every session)

1. **ALWAYS provide full file rewrites** for all modules EXCEPT html_builder.py.
   Never provide partial diffs, find/replace patches, or section snippets.
   Always output the complete file content so Anil can paste and save without merging.
   Partial patches have caused errors and wasted tokens.

2. **html_builder.py exception:** At 1561+ lines, full rewrites are error-prone.
   Use targeted Python string replacement scripts run in bash -- they are safer,
   verifiable with per-change confirmation prints, and syntax-checked after.
   Confirm each replacement succeeded before presenting the output file.

3. **One file at a time.** If multiple files need changes, do them sequentially,
   one complete file (or one replacement script) per response.
   Do not batch multiple files into one response.

4. **Confirm understanding before writing code.** State which file you are about to
   rewrite and what changes you are making, then write the full file.

---

## INFRASTRUCTURE SNAPSHOT

- **Live site:** https://anil2040.github.io/market-pulse-ai
- **Repo:** https://github.com/anil2040/market-pulse-ai (public)
- **Owner:** Anil Abraham -- deep-value mean reversion investor, Boise ID
- **Style:** Greenblatt / Carlisle / Howard Marks / Burry / Pabrai
- **Local:** VS Code on Windows 11 Home (never give Mac instructions or shortcuts)
- **When the pipeline runs (Session 14 continued, Oct 1 2026):** PUSH-TRIGGERED. The Claude Routine pushes
  clauderoutinedata.json (weekdays 7:40 AM MDT, set in the Claude app) and that push starts the workflow within
  a minute (`on: push: paths: clauderoutinedata.json`). Running the routine by hand, or editing that file, also
  starts it. Code pushes do NOT. A single BACKUP schedule (`17 15 * * 1-5`, 9:17 AM MDT / 8:17 AM MST, works in
  both seasons) covers days the routine fails, and skips itself if index.html was already built today (Boise date).
  Manual "Run workflow" always runs. No daylight-saving gate and no second cron any more.
- **Why not cron only:** GitHub's scheduler is best-effort. On Sep 30 2026 both crons fired about 4h45m late
  (platform-wide delays since Aug 26, see GitHub community discussions #156282 / #207346). Push events are not affected.
- **"pages build and deployment"** entries are GitHub's own publisher: one per push to main from anyone (you, the
  routine, the bot). It only publishes files already in the repo; it never rebuilds the HTML. Free and normal.
- **Claude Routine:** "Daily Market Warmup", weekdays 7:40 AM MDT, Sonnet 4.6 Medium (owner's choice: Sonnet 5.5 High
  felt like overthinking), Claude_Code_Remote, commits clauderoutinedata.json. Its schedule text says MDT
  explicitly: check around Nov 2 2026 that it still fires at 7:40 local. If it shifts, nothing breaks, because the
  pipeline now follows its push.
- **Python:** GitHub workflow uses 3.13 (same as the owner's laptop, 3.13.15). Latest stable is 3.14; 3.15 is due
  Oct 1 2026; 3.11 is supported until Oct 2027. Test on the workflow's version before delivering.
- **Runtime:** about 40 to 70 seconds, 17/17 indicators (Sep 30 2026)

**9 GitHub Secrets (all confirmed set):**
GEMINI_API_KEY, ANTHROPIC_API_KEY, YAHOO_EMAIL, YAHOO_APP_PASSWORD,
FRED_API_KEY, MFI_EMAIL, MFI_PASSWORD, AM_EMAIL, AM_PASSWORD

**Pipeline order (main.py) -- runs after each routine push (Session 14 continued):**
```
Step 0:  load_claude_routine    (clauderoutinedata.json + REAL commit time from git history)
Step 1:  fetch_fred_data        (17 indicators, DAILY rates, per-indicator cache fallback)
Step 2:  fetch_fear_greed
Step 3:  fetch_market_indicators (uses routine PE as priority 0)
Step 4:  compute_mhs + _append_mhs_history (writes to run_cache.json)
Step 5:  value screens          (Dataroma: saved list, contacted only after a 13F deadline, one try/day;
                                 Magic Formula and Acquirer's Multiple: today's saved copy -> live -> run_cache.json)
Step 6:  news                   (Edward Jones, CNBC, Yahoo Brief; real dates checked; no cache)
Step 7:  health checks          (health.py: one list of ok/warn/bad items)
Step 8:  synthesize_with_ai     (Claude Sonnet 5.5 -> [10 s wait, only after a temporary failure] -> Claude Haiku 4.5 -> Gemini 3.6 Flash (free) -> fallback text; ONE try each)
Step 9:  build_html             (one-line status at the top, badges, all cards)
Step 10: save run_cache.json    (workflow commits index.html + run_cache.json + dataroma_cache.json in ONE commit)
Step 11: exit code 1 if a red item needs attention (GitHub then emails you); NOTIFY_ON_FAILURE in main.py
```

One normal run per weekday (plus the skip-if-built backup). Fun Fact and AI Learning regenerate each run.
Stale content on weekends is expected (no routine, no run).

---

## MODULE SUMMARY

| File | Lines | Responsibility |
|---|---|---|
| fred.py | ~800 | Macro series (daily rates DGS10/DGS2/DFF), Yahoo gold and WTI (FRED oil fallback), CAPE from multpl by-month table, ICSA, GDPC1, lookback windows by frequency, trend colors, sparklines, interpretive insights (no symbols) |
| market.py | ~330 | Yahoo SPX/RUT/VIX (previous close from bars), Claude Routine PE (priority 0), iShares CSV PE, PE_CONFIG fallback, MHS, ERP |
| screens.py | ~400 | Dataroma (saved list, live only after a 13F deadline, one try/day, last_attempt stored in dataroma_cache.json), Magic Formula, Acquirer's Multiple. Every function returns (data, meta) and raises ScreenError on failure. |
| news.py | ~430 | Edward Jones scrape, CNBC/Yahoo IMAP (INBOX + Bulk/Spam, real Date header, read-only), text cleaning, calendar extractor (6000 chars). Returns (text, meta). |
| ai_synthesis.py | ~500 | Sonnet 5.5 -> Haiku 4.5 -> Gemini 3.6 Flash (free) -> fallback text. One try each, no retries; 10 s wait only between Sonnet and Haiku after a temporary error; 1500 max tokens. Returns (briefing, failed, ai_info). Prompt has as-of dates, data caveats, calendar from today. |
| health.py | ~270 | All freshness rules and health items (ok/warn/bad), per-row age limits (max_age_for), 13F deadline helpers. Pure functions, no network. |
| timeutil.py | ~70 | NEW. Boise time with daylight saving (zoneinfo, with a built-in fallback for Windows without tzdata). |
| html_builder.py | ~1680 | Full dashboard HTML, one-line status at the top, warning-triangle badges, gauge cards, MHS history chart, 5-day calendar, conviction chips, collapsed screens card (badges in header) |
| main.py | ~690 | Orchestrator, per-source cache fallback, same-day reuse for Magic Formula / Acquirer's Multiple, health assembly, step summary, exit code |
| fetch_cache.py | ~60 | Local tool only (not in the workflow). Refreshes dataroma_cache.json from your PC. |
| debug_etf_pe.py | 214 | Quarterly diagnostic -- run manually to re-audit PE sources |

---

## KEY ARCHITECTURE DECISIONS (confirmed, do not revisit)

**AAII:** Fully removed. Incapsula CDN blocks GitHub Actions IPs permanently.
Quiet footnote link remains. Check manually at aaii.com every Thursday.

**Gold:** Yahoo Finance GC=F (GOLDAMGBD228NLBM discontinued by FRED in 2025).

**Shiller CAPE:** multpl.com scrape (FRED never hosted this series).
multpl.com updates monthly -- all three columns (3mo, 12mo, today) showing the same
value is expected behaviour when CAPE hasn't moved in 3 months due to 10yr smoothing.

**ISM Manufacturing PMI -- permanently dropped:**
- ISM asked FRED to remove ALL 22 ISM series in June 2016. NAPM is deleted from FRED.
- No reliable free alternative found. S&P Global PMI (formerly Markit) data is proprietary.
- ICSA (jobless claims) already covers the labor/cycle signal faster and for free.
- Do NOT try to add ISM PMI again without a confirmed working FRED series ID.

**ETF PE (URTH/EFA) -- 3-priority system:**
- Priority 0: Claude Routine JSON (clauderoutinedata.json, fresh = today's date).
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

Routine 2: 7:40am MT -- "Daily Market Warmup" (machine-readable JSON, writes clauderoutinedata.json)
- 6-minute gap before 7:50am pipeline
- Model: Sonnet 4.6 (changed from Opus 5.5 in Session 12 -- same output, lower cost)
- Contains sections A-G: futures, ETF PE, macro/rates, sector movers, global markets,
  open_focus, AND market_prices
- ETF PE from routine used as priority 0 in market.py _yq_pe()
- market_prices block used as PRIMARY source for Market Performance card in html_builder.py
- Injected into AI synthesis prompt as PRE-MARKET INTELLIGENCE block (once only)
- Staleness: if routine date != today MT, amber banner shown in valuation block
- Commits directly to main branch using explicit git command sequence (fixed Session 12)

**Stale routine warning root cause (confirmed Sep 23 2026, fixed Session 12):**
- Pipeline reads clauderoutinedata.json right after actions/checkout
- If GitHub hasn't fully propagated the 7:40am routine commit by the time checkout runs,
  the pipeline sees yesterday's file and flags it stale
- Fix: added `git pull origin main` step in daily.yml immediately after actions/checkout

**Claude Routine branch issue (confirmed Sep 23 2026, fixed Session 12):**
- Claude Code Remote always initializes sessions on a new branch, not main
- Vague "push to main" instruction caused commit to land on side branch
- Fix: Step 3 of routine instructions now uses explicit git command sequence:
    git checkout main
    git pull origin main
    git add clauderoutinedata.json
    git commit -m "Auto-update: claude routine data YYYY-MM-DD"
    git push origin main
  Fallback: if checkout fails due to uncommitted changes, run git checkout -- . then retry
- After push succeeds, hard stop: do not respond to hook prompts, no further commands

**clauderoutinedata.json schema (written by 7:40am routine):**
```json
{
  "date": "YYYY-MM-DD",
  "time_collected_utc": "HH:MM",
  "futures": {
    "sp500":     {"change_pct": 0.00, "direction": "up"},
    "nasdaq100": {"change_pct": 0.00, "direction": "up"},
    "dow":       {"change_pct": 0.00, "direction": "up"},
    "sentiment": "bullish"
  },
  "etf_pe": {
    "URTH": {"pe_ttm": 0.00, "proxy_for": "MSCI World",           "source": "stockanalysis.com"},
    "EFA":  {"pe_ttm": 0.00, "proxy_for": "MSCI EAFE ex-US Developed", "source": "stockanalysis.com"}
  },
  "rates_commodities": {
    "treasury_10yr_pct": 0.00,
    "crude_oil_usd":     0.00,
    "crude_oil_type":    "WTI"
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

**Market Performance Card -- data source priority:**
- PRIMARY: routine_data["market_prices"] (browser-fetched at 7:40am MT, no CORS issue)
- FALLBACK: mkt_data from market.py pipeline fetch (server-side, may show stale after close)
- NO live JS fetch -- removed entirely. Yahoo Finance CORS-blocks requests from github.io.
  Chrome extension works because extensions bypass CORS via host_permissions in manifest.
  github.io static pages cannot bypass CORS -- all browser fetch attempts return ERR_FAILED.
- Card header shows "as of HH:MM ET · via Claude Routine" when routine data present
- All classify/color/label logic is Python-side (_classify_idx, _classify_vix, etc.)
- routine_fresh_prices flag: True if market_prices present and sp500.current > 0

**MHS (Macro Heat Score):** FRAMEWORK LOCKED AT V1.0 -- do not change thresholds or weights.
- 0-33 DEPLOY | 34-65 SELECTIVE | 66-85 OVERHEATED | 86-100 EXTREME OVERHEATED
- Base = 50. Components: Core PCE, VIX, Fear & Greed, HY Credit, Yield Curve,
  Fed Posture, Shiller CAPE, Gold Signal.
- EXTREME OVERHEATED posture text: "Macro is at its most stretched since dot-com."
  (macro observation only -- no stock-picking prescription, no behavioral advice)
- History stored in run_cache.json under "mhs_history" key as array of
  {date, score, label} objects. Appended once per weekday run. Capped at 252 entries.
- Chart: inline SVG W=680px, zone labels overlaid INSIDE chart bands (not separate panel).
  Zones top-to-bottom: EXTREME (86-100), OVERHEATED (66-85), SELECTIVE (34-65), DEPLOY (0-33).
  Daily score = blue line. 20-day SMA = amber line. Zone labels right-aligned inside bands.
  20-day SMA appears ~Oct 17 2026 (4 trading weeks from Sep 19 2026 start).
- mhs_scale text block below card REMOVED (legend is now inside chart bands).
- Card h2 display: "🌡 Macro Heat Score" (no MHS acronym -- removed Session 14)
- Chart legend: "Trend ({days}d)" (no MHS prefix -- removed Session 14)

**Market State Detection:**
- marketState taken from SPX (%5EGSPC) only -- VIX marketState is NOT used (unreliable).
- REGULAR -> OPEN, PRE -> PRE, POST -> POST, CLOSED -> CLOSED.
- GitHub Actions IPs blocked by Yahoo for JS/crumb-based API -- only v8 basic fetch works.

**AI Synthesis fallback chain (confirmed working Sep 28 2026):**
```
gemini-3.6-flash  (free, ~20 RPD confirmed from AI Studio dashboard, resets daily)
  -> gemini-3.5-flash  (free, 1,500 RPD, confirmed stable model ID)
  -> claude-haiku-4-5  (paid, ~$0.01-0.02/run depending on prompt size)
  -> structured text   (always works, no AI narrative)
```

**Critical Gemini notes:**
- _call_gemini() uses client.models.generate_content() NOT client.interactions.create()
  interactions.create is the new Interactions API (GA June 2026) but causes 90s+ timeouts
  under free-tier load. generate_content is stateless, fast, and fully supported.
- gemini-2.5-flash does NOT exist as a valid API model string -- causes 404. Use gemini-3.5-flash.
- gemini-1.5-flash is dead/removed from free tier.
- gemini-3.6-flash free tier limit: ~20 RPD (confirmed from AI Studio rate limit dashboard).
  If RPD exceeded, falls through to gemini-3.5-flash, then Haiku.
- AFC warning from Google SDK is advisory only -- not an error. No code change needed.
  Appears as "Direct use of AFC in Models.generate_content is not recommended" in run log.
- Do NOT set up Gemini billing -- Haiku fallback costs less and produces better output.

**Haiku cost math (confirmed from Anthropic dashboard Sep 2026):**
- Haiku 4.5 pricing: $1.00/M input tokens, $5.00/M output tokens
- Observed runs: 3,753 in + 953 out = $0.0085 | 6,990 in + 1,522 out = $0.0146
- Token count varies because prompt includes news email text + calendar + FRED block (all variable)
- Cost logged dynamically from message.usage object -- no hardcoded estimate

**AI Synthesis -- 4 sections (Earnings & Events removed Sep 2026, VALUE SCREENS removed Session 14):**
```
MARKET AND MACRO | WHAT TO WATCH | AI FUN FACT | AI LEARNING
```
- MARKET AND MACRO and WHAT TO WATCH shown as true 2-column CSS grid.
  Left col: "Macro Interpretation" (blue label). Right col: "What to Watch" (green label).
- Both columns: max 5 bullets each (was 6-8 left / 3-4 right -- balanced in Session 14).
- VALUE SCREENS intentionally NOT in AI prompt (removed Session 14):
  si_tickers, mf_list, am_list accepted as parameters for signature compat but NOT sent to AI.
  Saves ~200-250 input tokens/run. Prevents AI generating ticker-specific commentary in briefing.
  Screen data belongs in dashboard chips and Chrome extension div, not the macro briefing.
- No data regurgitation -- interpretive macro implications only.
- Yahoo calendar injected as WEEK AHEAD block in prompt for date-specific events.
- Claude Routine pre-market intelligence injected as PRE-MARKET INTELLIGENCE block (once only).
- Fun Fact and AI Learning regenerate fresh every weekday run.
- Text limits (raised Session 14): EJ 1500 chars, CNBC 1200 chars, Yahoo Brief 1200 chars.
  Log line prints when any source is truncated (visible in GitHub Actions run log).

**Value Screens -- return types (Sep 2026):**
- SI: dict {ticker: count} -- unchanged
- MF: ordered list of (ticker, rank_int) tuples -- rank 1 = highest conviction
- AM: ordered list of (ticker, multiple_str) tuples -- position 1 = lowest multiple
- Both preserve site rank order (set() destroyed it before)
- Conviction chips: all3/two3 chips show enriched tags e.g. (4SI,MF#12,AM 8.00x)
- MF-only chips show rank: ANF #1, ADBE #2
- AM-only chips show multiple: SYF (2.50x), EQNR (3.40x)
- SI-only: filtered to >= 3 managers (removes 1-2 SI noise)
- two3 sorted by conviction: MF rank asc, then AM multiple asc, then SI count desc, then alpha
- **Value Screens card: collapsed by default** (Session 14). Click header to expand.
  ID: screens-body (content div), screens-tog (button label). Toggle JS inline onclick.

**Chrome extension #market-context div (updated Session 14):**
- Now contains three full ranked lists for stock-specific analysis:
  MAGIC_FORMULA_FULL(all_ranked,Greenblatt_earnings_yield_plus_ROIC): ANF #1|ADBE #2|...
  ACQUIRERS_MULTIPLE_FULL(all_by_multiple,Carlisle_EV_over_EBIT): SYF 2.40x|EQNR 3.30x|...
  SUPER_INVESTORS_FULL(all_by_count,Dataroma_13F_quarterly): MSFT 18|META 14|V 14|...
- Screen labels renamed: SCREENS_SUPER_INVESTORS_ONLY, SCREENS_MAGIC_FORMULA_ONLY,
  SCREENS_ACQUIRERS_MULTIPLE_ONLY (spelled out, no abbreviations)
- Helper functions added: _tlist_mf_full(), _tlist_am_full(), _tlist_si_full() in html_builder.py
- _build_market_context() signature updated: mf_list, am_list now passed in (before mf_only, am_only)

**FRED Macro Indicators table (17 rows as of Sep 28 2026):**

| Group | Icon | Indicators |
|---|---|---|
| Inflation | 🔥 | CPI, Core CPI, PCE, Core PCE |
| Interest Rates | 📊 | 10Y, 2Y, Yield Curve, Fed Funds |
| Credit | 💳 | HY Spread |
| Labor | 👷 | Unemployment, Jobless Claims (ICSA) |
| Commodities | 🛢 | WTI Crude, Gold |
| Currency | 💵 | US Dollar Index (Broad) -- Fed DTWEXBGS, NOT the ICE DXY |
| Consumer Sentiment | 🎭 | U of Michigan |
| Valuation | 📐 | Shiller CAPE |
| Economic Growth | 📈 | GDP Growth YoY |

**ICSA (Jobless Claims) -- LABOR group:**
- FRED series: ICSA (weekly initial claims, seasonally adjusted)
- Placed in LABOR alongside Unemployment. ICSA leads unemployment by 6-8 weeks.
- 4-week moving average computed and prepended to the insight string.
- Thresholds: <250K=healthy, >300K=stress emerging, >400K=recession territory
- Weekly so `is_daily=True` path applies (13-week = 3mo, 52-week = 12mo comparison)
- Sep 28 2026 reading: 197,000 ▼ (very healthy)

**GDPC1 (GDP Growth YoY) -- GROWTH group:**
- FRED series: GDPC1 (real GDP, quarterly, chained 2017 dollars)
- Special handling in _fetch_one_fred: YoY % = (obs[0] - obs[4]) / obs[4] * 100
  (obs[4] = same quarter 1 year ago, i.e., 4 quarterly periods back)
- 3mo col = prior quarter's YoY (obs[1] vs obs[5])
- 12mo col = 2-year-ago YoY (obs[4] vs obs[8]) -- requires 9+ quarterly obs
- Date shown as "Q2 2026" format (quarter label, not day-level)
- FRED window extended 460 -> 1200 days to get 13+ quarterly obs (bug: 460 days only gave
  ~5 obs, obs[8] fell back to obs[4], numerator = 0, 12mo column showed "0.0%" incorrectly)
- Sep 28 2026 reading: 2.1% ▲ (Q2 2026 YoY vs Q2 2025)

**Monthly FRED date format (changed Session 14):**
- Monthly series (PCE, CPI etc.): "Jul 2026" (no day -- monthly precision only)
- Daily series (10Y, 2Y, Fed Funds, WTI, gold, dollar, HY, CAPE): "Sep 26 2026" (day-level)
- Weekly (ICSA): "Sep 19 2026". Each row also carries obs_date (ISO) used by health.py.
- Quarterly GDPC1: "Q2 2026" (custom quarter label)

**Valuation section (updated Session 14):**
- h2 header: "📐 Global Market Valuation" (subtitle removed -- was showing source notes)
- Box labels renamed: "US Market P/E (Shiller CAPE)", "MSCI World P/E (URTH)", "ex-US Dev. P/E (EFA)"
- CAPE box: added "(dot-com peak: Dec 1999 at 44.2x)" below "Hist avg 17x · 2nd highest ever"
- Shiller CAPE _insight: 40x+ branch now says "dot-com peak (44.2x, Dec 1999)" in context

**Amber badge / Macro Indicators legend (updated Session 14):**
- Note text: "sparkline = 12mo → 3mo → today · green = good for equities · red = bad ·
  ⚠️ = interpretive insight · 🟡 = cached (2+ days old)"
- Was: "amber pill = cached (live FRED fetch failed)" -- now uses emoji for clarity

**Weekly Economic Calendar:**
- Yahoo Morning Brief IMAP fetch returns (brief_text, calendar_text) tuple
- Monday brief has full week Mon-Fri calendar
- Stored in run_cache.json under "weekly_calendar": {week_of: "YYYY-MM-DD", text: "..."}
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
- Warning in Insights column = fred.py interpretive sig text prefix (separate from amber badge)
  Stripped with re.sub() in td rendering. Subtitle clarifies the difference.

**McClellan Oscillator:** Fully removed Sep 2026. Paid teaser only.

**Dashboard layout (DO NOT CHANGE WIDTH/LAYOUT):**
```
1.  Fun Fact + AI Learning        -- display:grid 1fr 1fr (same width as all cards)
2.  Earnings & Economic Calendar  -- full width single card
3.  MHS score + history SVG chart -- full width single card
4.  Market Performance + Market Sentiment -- display:grid 1fr 1fr (always side by side)
5.  Global Market Valuation       -- full width (CAPE + URTH + EFA + ERP)
6.  Market & Macro                -- full width (2-col grid INSIDE card: Macro / What to Watch)
7.  Value Screens                 -- full width, COLLAPSED by default (click header to expand)
8.  Macro Indicators table        -- full width (17 rows: 15 original + ICSA + GDPC1)
9.  Run log                       -- collapsed button, expands to show all pipeline steps
10. Hidden #market-context div    -- for Chrome extension (now includes 3 full ranked lists)
```

**run_cache.json structure:**
```
Every entry is {"value", "fetched", "as_of"}. Empty values are never written.
fred_{label}:         per indicator fallback (used per indicator, not only on total failure)
fear_greed:           CNN Fear & Greed
market_indicators:    SPX/RUT/VIX/PE block
screens_si:           {ticker: count} dict
screens_mf:           [[ticker, rank], ...] list of pairs
screens_am:           [[ticker, multiple_str], ...] list of pairs
(news_* keys REMOVED (Session 14 continued): old news is worse than none; main.py deletes them)
weekly_calendar:      {week_of, text} -- stored Monday, used all week
mhs_history:          [{date, score, label}, ...] -- up to 252 entries, appended daily
```

**Yahoo Morning Brief -- email fetch architecture:**
- Yahoo email has TWO MIME parts: tiny text/plain (~1200 chars, spam-filter teaser only)
  and full newsletter in text/html. Code MUST use prefer_html=True to get full content.
- Calendar section is at the END of the email (~char 7,874 in clean text, ~20,000+ in raw HTML).
  char_limit must be None to avoid truncating before the calendar section.
- _fetch_email_raw(prefer_html=True, char_limit=None) for Yahoo Brief only.
- CNBC Morning Squawk: default (prefer_html=False, char_limit=2500) -- plain text works fine.

**fetch_cache.py (RESOLVED Session 14 continued):**
- It is no longer part of the workflow and no longer touches Acquirer's Multiple (that was the old
  AM_EMAIL problem, now moot). It only refreshes dataroma_cache.json from YOUR PC: `python fetch_cache.py`,
  then commit. Needed after each 13F deadline (Feb 14, May 15, Aug 14, Nov 14). The dashboard turns amber
  3 days after a deadline if the file predates it, and red after 45 days.

**SESSION 14 (CONTINUED) ARCHITECTURE RULES (confirmed):**
- Warning triangle = DATA problem only. Amber = cached or later than expected. Red = missing. Nothing else uses it.
- Every source reports the date of its REAL content. Freshness rules live in health.py (MAX_AGE_DAYS by frequency).
- Failure never becomes an empty success. Live -> saved copy -> visible flag. Never overwrite a good copy with empty.
- The top of the page has ONE quiet line: "Data health OK · Briefing by Gemini 3.8 Flash" (plain grey text). It becomes an
  amber or red box, listing each problem, only when something is wrong. There is no separate AI banner any more.
- Red items marked notify=True end the run with exit code 1 (after publishing) so GitHub emails you.
  AI and news problems never trigger the email. Switch: NOTIFY_ON_FAILURE in main.py.
- No routine time is shown on the page (owner decision Oct 1: the pipeline now starts right after the routine push, so the
  single "Updated" time is enough). The routine's git commit time is still used for freshness checks and the health detail.
- Routine PRICES are used only when the routine data is from today.
- Dataroma: the saved list is used at ANY age. No contact at all until a 13F deadline (Feb 14, May 15, Aug 14, Nov 14, +3 days
  grace) has passed since it was fetched, then ONE try per day until success. Magic Formula and Acquirer's Multiple: a second
  run on the same Boise day reuses today's saved copy. FRED, prices, Fear & Greed, emails and Edward Jones stay live every run
  (tiny requests; caching news would bring back stale-news risk).
- All-3 and 2-of-3 accept any SI count >= 1; SI-only needs 3+.
- Boise time: never hard-code a UTC offset. Use timeutil.now_mt().
- Insight text has no leading symbols. MHS framework v1.0 thresholds are UNCHANGED.
- Owner rule: HUMAN IN THE LOOP. Ask before coding or deciding; propose any change that was not asked for BEFORE making it.
  When coding: deliver full files, list every change, and summarize at the end.
- Dollar row: Fed broad index DTWEXBGS has a value for every day but FRED receives it weekly (Mondays, through the prior
  Friday), so it may be up to 10-11 days old: max_age_days = 11 in fred.py (health.max_age_for). Note text kept to 2 lines.
- AI model chain (owner's design, Oct 1 2026): ONE try per model, NO retries (the owner does not want the assistant to
  choose retry counts: ask before changing any of this). Order: Claude Sonnet 5.5 (about $0.02 to $0.03 per run, about $0.50
  a month) -> Claude Haiku 4.5 -> Gemini 3.6 Flash (free tier, a different vendor) -> fallback text. The only wait in the
  chain is SECONDS_BEFORE_HAIKU = 10 s, and only after a TEMPORARY Sonnet failure (503/529 overload, 429, timeout, network).
  A PERMANENT error (404 model name not found or changed, 401 key rejected, 403 no access, 400 bad request) or a blank answer
  skips the wait and goes straight to Haiku, and the top line of the page says so with a hint, for example
  "Sonnet 5.5 HTTP 404, model not found, check the name". The Gemini-first order and the alias were dropped because the free
  tier answered 503 and hit RPM limits. Gemini now runs only if both Claude models fail. Output limit 1500 tokens; all text
  blocks are joined (a "thinking" block first is skipped). Evaluate Sonnet 5.5 after about a week (about Oct 8): if the
  briefings are not better than Haiku, change the first entry back.
- Haiku 4.5 retirement: Anthropic lists it Active with "tentative retirement not sooner than Oct 15 2026" (a floor, not a date)
  and promises at least 60 days notice by email. Third-party sites that call Oct 15 a firm date are wrong. When Anthropic
  deprecates it, move the second slot to the replacement.
- Pricing reference (Sep 30 2026): Haiku 4.5 $1/$5, Sonnet 5.5 $2/$10 (released Sep 28), Opus 5.5 $4/$20, Gemini 3.8 Flash
  $0.75/$3.75 (doubles Jan 1 2027; thinking tokens bill as output). Gemini free tier: rate limited, data may be used by Google.
  Real Haiku cost from the Anthropic dashboard: $0.008 to $0.015 per run.
- TEST ON THE WORKFLOW'S PYTHON (3.13 since Oct 1 2026; was 3.11). The Sep 30 outage came from testing on a newer Python
  than the workflow used (3.11 forbids backslashes inside f-string {...}). Keep the laptop and the workflow on the same version.
- ROUTINE = SEARCH ONLY: the Claude Code routine environment blocks page fetching (proxy allowlist; every fetch fails).
  Only web SEARCH works. Never write routine instructions that open URLs. Old instructions finished in ~1 minute by
  using only searches; a version that told it to open Yahoo/CNBC/MarketWatch/iShares pages took 12 minutes and
  produced 21 failed fetches. Routine instructions are the ORIGINAL ones restored Sep 30 plus small fixes (S&P INDEX wording,
  separate "Europe stock markets today" / "Asia stock markets today" searches, EFA fallback "EFA P/E ratio iShares", HH:MM
  time placeholder, no hook prompts, no pull request). Do NOT add dates to queries, scripts or validators: that version
  returned almost empty data. The pipeline no longer races the routine (it starts from the routine's push).

---

## TOOLING NOTES: Claude Chat vs Claude Code CLI vs GSD

**Why repo file timestamps don't mean stale data:**
- "X days ago" on a Python module file = last code change, not last data refresh
- index.html and run_cache.json update every weekday run
- Python modules only change when you edit and push code

**Claude Chat (this interface) -- current setup:**
- Can read GitHub files via raw URL fetch (Option A session start above)
- Cannot write to GitHub directly -- no repo connector available in chat sessions
- Produces full file rewrites you paste into VS Code and commit manually
- Best for: code review, bug diagnosis, full module rewrites, architecture decisions

**Claude Code CLI -- what it adds:**
- Native read/write access to your entire repo without pasting any files
- Can open fred.py, understand it, fix it, and commit directly in one step
- You say "fix the stale routine warning" and it reads daily.yml, edits it, commits, done
- No copy-paste workflow at all -- the AI works directly in your codebase
- Install: open VS Code terminal, run `npm install -g @anthropic-ai/claude-code`
  then `claude` to start a session in your repo directory
- Best for: iterative code fixes, multi-file changes, anything where you are currently
  doing paste-save-commit manually

**GSD (Git. Ship. Done.) -- what it is:**
- A framework for agentic coding with fresh sub-agents + .planning/ coordination files
- Solves the same "AI loses context" problem as SESSION_LOG.md but differently:
  instead of one long log file, each task gets its own short planning file
- Sub-agents read only what they need, stay focused, don't blow context window
- SESSION_LOG.md is your current manual version of the same idea
- For new projects: `npx @opengsd/gsd-core@latest --claude --local` in Claude Code
- Not needed for this project -- SESSION_LOG.md is working well and the project is mature
- Worth evaluating if you start a new larger project from scratch

**Read/write in Claude Chat future:**
- Anthropic will likely add GitHub connector support to Claude chat over time
- For now: raw URL fetch for reading works today (Option A above)
- Writing still requires Claude Code CLI or manual paste-commit

**Claude Skills (claude.ai) vs Cowork plugins:**
- Skills in claude.ai: add them from the tools menu in this interface. No Cowork needed.
  They trigger automatically when you describe a task that matches their description.
  Good for: repeatable workflows, house style, specialized domain tasks.
- Cowork plugins: bundle skills + connectors + commands together for agentic desktop automation.
  More powerful but require Cowork mode to be active.
- For the learning session demo: triggering a skill naturally by describing a task
  (without naming the skill) is a good talking point about how the system works.

---

## GITHUB ACTIONS NOTES

- ubuntu-latest PINNED to ubuntu-24.04 as of Sep 20 2026 (migrates to Ubuntu 26 on Oct 19 2026).
- actions/checkout bumped to @v5, actions/setup-python bumped to @v6 (Node.js 22, clears warnings).
- The github-pages Bot "pages build and deployment" workflow is GitHub-internal -- its ubuntu-latest
  warning cannot be fixed by you. Not your workflow, ignore it.
- Canceling/superseded Pages deployments are normal when two commits happen close together.
- "Run job" = "trigger the workflow" = click Run workflow in Actions tab.
- Workflow dispatch (manual trigger): repo -> Actions -> MarketPulse Daily Briefing -> Run workflow
- Triggers: routine push (normal), backup schedule 15:17 UTC (skips if built today), manual button. See daily.yml header.
- Scheduled runs are best-effort and were hours late on Sep 30 2026 (platform-wide since Aug 26): never depend on cron timing.
- Manual trigger re-runs the FULL pipeline every time -- all steps, all modules. No partial runs (but screens reuse today's copy).
  For fast HTML iteration, test locally with `python main.py` in VS Code terminal before pushing.

---

## OPEN ITEMS / NEXT SESSION

1. **Verify the first push-triggered run after the Oct 1 2026 deployment:**
   - After the routine's push, a "MarketPulse Daily Briefing" run starts within about a minute (event shows "push").
   - Top of page: one grey line, e.g. "Data health OK · Briefing by Gemini 3.x Flash" (the alias shows the model it picked).
   - Market Performance card has no "as of" time; the S&P / Russell line has none either.
   - Dollar row note is two lines; no false amber on Friday.
   - No "Not financial advice" in the footer; the AAII reminder is still there.
   - The backup schedule run appears around 9:17 AM and is a quick green "already built today" skip.
   - Actions list: no more "skipped twin" runs.

   - Briefing line says "Briefing by Claude Sonnet 5.5" and the Actions log shows a "Cost: ~$0.02" line. If it says Haiku with
     "(Sonnet 5.5 HTTP 404)", the API key has no access to the new model: tell the assistant (not a code bug).
   - First Sonnet run time: watch that the whole pipeline stays near 1 to 2 minutes.
   - If the top line says "Sonnet 5.5 HTTP 404, model not found, check the name", the model name in ai_synthesis.py (or the
     account's access) needs attention; Haiku wrote that day's briefing.

   **To-dos for the owner:** (a) after Nov 2, glance at the routine time (should still be 7:40 local); (b) after Nov 17,
   watch for the amber 13F reminder, the pipeline retries daily, else run `python fetch_cache.py` on the PC and commit
   dataroma_cache.json; (c) optional cleanup when convenient: delete test_haiku.py and validate_routine.py (not used by the
   restored routine); (d) when a real Axios Markets / WSJ Markets A.M. issue arrives, copy the sender address so it can be
   added to news.py; (f) about Oct 8: judge the Sonnet 5.5 briefings; (g) newsletters: Axios Markets arrives in the morning (add to the pipeline),
   Axios Macro (Neil Irwin, around lunchtime ET) and Closer (after the close) arrive later in the day, so they suit personal
   reading, not the 7:45 AM run; AM/PM/Finish Line are the general-news Daily Essentials bundle (Finish Line is wellness);
   (h) try Claude Code in VS Code for a small task (Manual permission mode first); (e) decide later whether to keep the routine's stockanalysis.com / Robinhood P/E or switch to an
   iShares reference (both give the same URTH vs EFA discount of about 27%; absolute levels differ about 6%).

2. **MHS 20-day SMA** -- will appear ~Oct 17 2026 (4 trading weeks from Sep 19 2026 start).
   No action needed, just wait for data to accumulate.

3. **ubuntu-24.04 deadline** -- Oct 19 2026, GitHub migrates ubuntu-latest to Ubuntu 26.
   If any pip packages break after that date, check Ubuntu 26 compatibility.

4. **fetch_cache.py AM fix** -- OBSOLETE. fetch_cache.py is a local Dataroma-only tool.

5. **Future: SEC EDGAR 13F API as Dataroma backup.**
   Dataroma working fine. EDGAR full-text search provides same 13F data if it goes down.

6. **Future: Chrome extension for stock-specific mean reversion analysis.**
   Extension reads #market-context div (macro) + stock-specific page data (valuation,
   52-week range, revenue trend, balance sheet, insider buying).
   Combined context fed to Claude for buy/hold/avoid analysis.
   Key stock metrics needed: trailing P/E, P/B, EV/EBIT, EV/FCF, debt/equity,
   interest coverage, return on capital, 52-week range position, insider activity.
   Full ranked lists (MF, AM, SI) now in #market-context div and ready for the extension.

7. **Future: Claude Code in VS Code** (or the CLI) for direct repo read/write without copy and paste. Two of the three
   Sep 29-30 outages came from copy/paste or a Python version mismatch that it avoids. Try it on a small task first and add a
   CLAUDE.md with the standing rules (ask before coding, no dashes, Windows only, test on the workflow's Python).
   Install docs: https://code.claude.com/docs/en/vs-code

8. **Future: read more newsletters in the pipeline** (WSJ Markets A.M., Axios Markets; Daily Upside optional; Yardeni is weekly
   and teaser-length so it is not worth a special freshness rule). Needs each sender address from a real issue.

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
- PE_CONFIG with PE_LAST_UPDATED + stale warning (>90 days)
- Label "US Shiller CAPE" -> "Shiller CAPE (US)"
- MHS 90+ = EXTREME OVERHEATED (darker red #7f1d1d, 4-tier scale)
- Equity Risk Premium row added (ERP = CAPE yield - 10Y, was -2.24%)
- debug_etf_pe.py: full audit of all ETF PE sources (all blocked/broken)

**Confirmed working:** Sep 10 2026 run, 39s, 15/15 indicators

---

### Session 5 (Part 2) -- UX Improvements
**Date:** Sep 10 2026
**Files changed:** market.py, html_builder.py, SESSION_LOG.md created
**Done:**
- iShares CSV PE fetch added (tries live first, PE_CONFIG fallback)
- EXTREME OVERHEATED posture text softened (quality + patience, not panic)
- Gauge-style market performance card (cloned from Chrome extension)
- SI-only filter changed to >= 3 managers (removes 1-2 SI noise)
- AI briefing changed to 2-column grid

---

### Session 6
**Date:** Sep 11 2026
**Files changed:** market.py, main.py, html_builder.py, ai_synthesis.py, daily.yml
**Done:**
- PE_CONFIG confirmed permanent solution (all live sources blocked by GitHub Actions IPs)
- PE_CONFIG updated: URTH=22.57x, EFA=18.35x (Sep 10 2026, from Yahoo Finance browser)
- MHS EXTREME OVERHEATED threshold lowered from 90 to 86 (tighter top tier)
- MHS scale locked: 0-33 DEPLOY | 34-65 SELECTIVE | 66-85 OVERHEATED | 86-100 EXTREME
- run_cache.json implemented: per-indicator persistent fallback
- daily.yml: git add index.html run_cache.json added to final commit step
- Dir column removed from FRED macro table
- AI prompt rewritten: no data regurgitation, interpret combinations and tensions

**Confirmed working:** Sep 11 2026 run, 74s, 15/15 indicators, Gemini succeeded

---

### Session 7
**Date:** Sep 17 2026
**Files changed:** market.py, html_builder.py, daily.yml
**Done:**
- Market state detection fixed -- SPX marketState as single source of truth
- Gauge section rebuilt with individual element IDs
- Cron changed from 6:55 AM MT to 7:50 AM MT

---

### Session 8 -- Claude Routine Integration + Major UX Overhaul
**Date:** Sep 19-22 2026
**Files changed:** ALL 7 modules + run_cache.json + daily.yml

**Claude Routine integration (clauderoutinedata.json):**
- 7:44am routine writes pre-market JSON to repo before 7:50am pipeline
- ETF PE from routine used as priority 0 in market.py (above iShares CSV)
- Routine pre-market data injected into AI synthesis prompt as PRE-MARKET INTELLIGENCE block
- Staleness detection: amber banner if routine date != today MT
- routine_data and routine_fresh passed through entire pipeline

**daily.yml:** ubuntu-24.04 pinned, checkout@v5, setup-python@v6

**screens.py:**
- fetch_magic_formula() returns ordered list of (ticker, rank) tuples
- fetch_acquirers_multiple() returns ordered list of (ticker, multiple_str) tuples

**news.py:**
- McClellan removed entirely
- fetch_yahoo_morning_brief() returns (brief_text, calendar_text) tuple
- Yahoo Brief char limit raised from 2000 to 4000

**ai_synthesis.py:**
- Earnings & Events section removed
- 4 sections: MARKET AND MACRO | WHAT TO WATCH | AI FUN FACT | AI LEARNING
- routine_data and routine_fresh params added

**html_builder.py:**
- Amber badge: weekday-only, fires only when data is 2+ days old
- two3 chips sorted by conviction: MF rank asc, AM multiple asc, SI count desc
- Calendar: 5-day grid, TODAY badge, actual date labels
- Market & Macro: true 2-column CSS grid (Macro Interpretation / What to Watch)
- Page sequence reordered: Calendar -> MHS -> Market -> Valuation -> Macro -> Screens -> Indicators

**Confirmed working:** Sep 19-22 2026, MHS: 91/100 EXTREME OVERHEATED

---

### Session 9 -- Yahoo Calendar, MHS Legend, Market Performance, CORS Resolution
**Date:** Sep 22 2026
**Files changed:** news.py, html_builder.py

**Issue 1: Yahoo calendar not populating -- 3-layer root cause fixed**
- char_limit=12000 truncated body before calendar section
- text/plain MIME part (~1200 chars teaser) found first -- never read text/html (full content)
- _build_weekly_calendar guard overwrote good cache with bad extraction
- Fix: prefer_html=True, char_limit=None in _fetch_email_raw() for Yahoo Brief only
- Fix: _is_real_calendar() validates weekday name present before storing
- Fix: removed broken regex from _extract_calendar()

**Issue 2: Earnings clunky display -- fixed**
- BS4 get_text() splits "THOR Industries (THO)" into 4 lines
- Complete rewrite of _parse_calendar_into_days() with earn_buffer state machine

**Issue 3: MHS chart legend -- fixed**
- Zone labels now overlaid INSIDE chart bands, right-aligned, vertically centred
- Width W=680, mhs_scale text block below removed

**Issue 4: Market Performance +0.00% FLAT -- CORS root cause found**
- Yahoo Finance CORS-blocks all browser fetches from github.io (ERR_FAILED every time)
- Solution: Claude Routine fetches SPX/RUT/VIX at 7:44am MT, writes to clauderoutinedata.json
- Pipeline reads and bakes values into HTML -- no live JS needed

**Confirmed working:** Sep 22 2026 run

---

### Session 10 -- Model fixes, cost math, coding requirements
**Date:** Sep 22 2026
**Files changed:** ai_synthesis.py, SESSION_LOG.md

**Gemini model fixes:**
- gemini-1.5-flash dead -> replaced with gemini-3.5-flash (gemini-2.5-flash is not a valid ID)
- Haiku cost display updated to use dynamic token counts from message.usage

**Token math confirmed:** 10,743 in + 2,454 out = $0.023 total across 2 Haiku runs
**Coding requirement added:** Always full file rewrites, never partial diffs.

---

### Session 11 -- Gemini timeout fix, width fix, VIX to Sentiment
**Date:** Sep 23 2026
**Files changed:** ai_synthesis.py, html_builder.py, SESSION_LOG.md

**Gemini timeout root cause found and fixed:**
- _call_gemini() was using client.interactions.create() -- new Interactions API
  causes 90s+ timeout under free-tier load due to stateful session overhead
- Fixed to client.models.generate_content() -- stateless, fast, fully supported

**HTML width fixed:**
- Fun Fact + AI Learning: changed from class="grid-2" to display:grid;grid-template-columns:1fr 1fr
- Market Performance + Sentiment: same treatment
- All top-level layout sections now use identical grid or full-width -- consistent width throughout
- DO NOT change this layout -- it is confirmed working

**VIX moved to Sentiment card:**
- Removed VIX block from gauge_section (Market Performance card)
- Added VIX as first row in Sentiment table: VIX | Fear & Greed | Consumer Sentiment
- Pulse line kept at bottom of Market Performance card for index context

**Confirmed working:** Sep 23 2026 run
MHS: 99/100 EXTREME OVERHEATED
SPX: 7,779 | RUT: 2,875 | VIX: 14.93 | CAPE: 41.6x
AI synthesis: Haiku fallback, $0.0074 (3,371 in + 804 out tokens)

---

### Session 12 -- Claude Routine Branch Fix + daily.yml git pull
**Date:** Sep 23 2026
**Files changed:** daily.yml, Claude Routine instructions (in-app, not a repo file)

**Issue 1: Stale Claude Routine warning (root cause confirmed)**
- Pipeline reads clauderoutinedata.json right after actions/checkout
- If GitHub hasn't propagated the 7:44am routine commit before checkout runs,
  pipeline sees yesterday's file and flags stale
- Fix: added `git pull origin main` step in daily.yml after actions/checkout@v5

**Issue 2: Routine pushing to side branch instead of main**
- Claude Code Remote initializes every session on a new branch by default
- Fix: Step 3 of routine instructions replaced with explicit git command sequence
- After fix: routine completes in under 90 seconds, 2 commands, zero failures

**Other routine improvements:**
- Model changed from Opus 5.5 to Sonnet 4.6 (faster, lower cost, same output quality)
- Treasury yield cross-check added
- source_time_et now records actual ET collection time
- Hard stop after push: do not respond to hook prompts

**AFC warning (confirmed non-issue):**
- Advisory only. Gemini still falls through correctly to Haiku. No code change needed.

---

### Session 13 -- Architecture visualization, PPTX slide, macro gap analysis
**Date:** Sep 24 2026
**Files changed:** SESSION_LOG.md only (no code changes this session)

**Sep 24 2026 run verification (confirmed):**
- Session 12 fixes working. Routine date = 2026-09-24 on main, no side branch
- No stale routine warning in pipeline log
- Dashboard shows "via Claude Routine" label on Market Performance

**Architecture visualization (for learning session):**
- Built interactive SVG flowchart + compact 7-box PPTX slide (16:9)
- Stat strip: ~3,000 lines | 8 modules | 3 AI models | $0-$3/month | 9 API secrets
- Agency cost estimate: $25-50K build, $2-5K/month retainer

**Macro coverage gap analysis:**
- Gap identified: no cycle direction indicator
- Three additions agreed: ICSA (Priority 1), ISM PMI (Priority 2), GDPC1 (Priority 3)
- None touch MHS (framework locked V1.0)

---

### Session 14 -- Leading Indicators + UI Overhaul + Prompt Cleanup
**Date:** Sep 28-29 2026
**Files changed:** ai_synthesis.py, fred.py, html_builder.py

**ICSA + GDPC1 added to Macro Indicators table:**
- ICSA (Initial Jobless Claims, weekly): placed in LABOR group alongside Unemployment
  4-week moving average prepended to insight string. Sep 28 reading: 197K ▼ (healthy)
- GDPC1 (Real GDP YoY, quarterly): placed in new GROWTH group (📈, #059669)
  Special quarterly YoY handling: obs[0] vs obs[4] = 4 quarters back = 1 year
  Sep 28 reading: 2.1% ▲ (Q2 2026 vs Q2 2025)
- Monthly series date format changed: "Jul 2026" not "Jul 01 2026"
- FRED window: 460 -> 1200 days (GDPC1 needed 9+ quarterly obs for valid 12mo column;
  460 days gave only ~5 obs, making obs[8] fall back to obs[4], showing 0% as bug)
- max_workers: 15 -> 17

**ISM Manufacturing PMI -- permanently dropped:**
- Investigated NAPM: ISM asked FRED to remove ALL 22 ISM series in June 2016. Series dead.
- Tried USAMFGPMISMMT (S&P Global US Mfg PMI): unconfirmed series ID, fragile
- Decision: drop PMI entirely. ICSA already covers labor/cycle direction faster.
- Do NOT attempt to add PMI without a verified working FRED series ID

**AI synthesis prompt cleanup:**
- HIGH CONVICTION SCREENS block removed (~200-250 input tokens/run saved)
- Rationale: AI was generating ticker-specific lines in macro briefing (wrong format)
  Screen data belongs in chips and Chrome extension div, not the macro briefing
- si_tickers, mf_list, am_list still accepted as function parameters (main.py unchanged)
- Both columns: "max 5 bullets each" (was 6-8 left / 3-4 right)
- Text limits raised: EJ 1500, CNBC 1200, Yahoo 1200 chars. Log prints when truncated.

**html_builder.py UI changes (20 changes, all verified):**
- MHS acronym removed from h2 ("🌡 Macro Heat Score", not "MHS · Macro Heat Score")
- Chart legend: "Trend ({days}d)" not "MHS TREND ({days}d)"
- Valuation boxes renamed: "US Market P/E (Shiller CAPE)", "MSCI World P/E (URTH)", "ex-US Dev. P/E (EFA)"
- CAPE box: added "(dot-com peak: Dec 1999 at 44.2x)" below "Hist avg 17x · 2nd highest ever"
- Global Valuation header subtitle removed (was showing source notes)
- Amber legend: "⚠️ = interpretive insight · 🟡 = cached (2+ days old)"
- Value Screens card: collapsed by default; clickable header shows "▶ Expand / ▼ Collapse"
- group_order: "LEADING" replaced with "GROWTH" (bug fix: ICSA and GDPC1 were not rendering
  because group_order in html_builder.py had hardcoded list that never included LEADING/GROWTH)
- Chrome extension div: three full ranked lists added (MF with ranks, AM with multiples,
  SI with counts). Screen labels spelled out in full. Helper functions added.

**Confirmed working:** Sep 28 2026 run (manual trigger)
MHS: 86/100 EXTREME OVERHEATED
17/17 indicators | Gemini 3.6 Flash (1749 chars) | 36s runtime
SPX: 7,684 | RUT: 2,818 | VIX: 16.07 | CAPE: 41.2 | Gold: $4,165

---

### Session 14 (continued), part 1 -- "Never be blindsided" overhaul
**Date:** Sep 29-30 2026
**Files changed:** main.py, screens.py, news.py, fred.py, market.py, ai_synthesis.py, html_builder.py,
fetch_cache.py, daily.yml. NEW: health.py, timeutil.py. Deleted (by you): test_pe_fetch.yml, am_cache.json.

**Problems found (all confirmed from files and logs):**
1. Empty-overwrite bug: screens.py swallowed its own errors and returned {} or []; main.py saw "success" and wrote
   the EMPTY result over the good run_cache.json copy, so its fallback never ran. Dataroma showed 0 stocks.
   Dataroma returned HTTP 409 to GitHub's IPs (worked from your PC).
2. Three overlapping cache files; am_cache.json was never committed so it never survived a run; fetch_cache.py had
   no AM secrets. Freshness stamps recorded the RUN date, not the source date. Error strings were cached as news.
3. CNBC email on the page was really Sep 3 (26 days old) with nothing saying so. Cause of no new mail: you had
   unsubscribed; resubscribed since. Search now also covers Bulk/Spam.
4. Rates came from FRED MONTHLY averages (GS10, GS2, FEDFUNDS): dashboard 10Y 4.68% (Aug) vs real 5.24%;
   "Fed on hold 3.63%" after the Sep 16 hike. Now DGS10, DGS2, DFF. WTI via Yahoo CL=F (FRED fallback).
5. ICSA 3mo/12mo columns looked back 65/260 WEEKS (weekly series treated as daily). CAPE 3mo/12mo silently equalled
   the current value (41.2 all three) because the scraped page has no history. Gold insight showed "++13%".
6. market.py _yq read a field that does not exist, so % change was stuck at +0.00% FLAT.
7. Routine timestamps inside the JSON are the model's guess (said 12:15 UTC; real run 7:45 AM MDT). Real time now
   comes from git commit time.
8. Hard-coded UTC-6 offset in main.py and html_builder.py; on Nov 1 the single cron would fire at 6:50 AM MST.
9. html_builder used %-m/%-d (Linux only; crashes local Windows runs). Calendar was capped at 3000 chars (Friday cut).
10. Routine prices were used whenever a file had prices, even when stale (silent staleness).
11. Legend said the warning triangle meant "interpretive insight" (never true; the column already hid it).
12. Haiku fallback on Sep 29: 503 "credential validation failed" (a bad key gives 401). test_haiku.py returned 200
    from your PC with a 108-character key. Unresolved; treated as transient plus possible secret mismatch.
    Gemini 503 "high demand" is Google capacity, NOT quota (the old banner claimed quota exhausted).

**What was built:** see the pipeline and rules above. Key additions: health.py (all freshness rules), the health
banner and one-symbol badges, per-indicator cache fallback, Dataroma cache used at any age with a 13F refresh
reminder, real source dates for news, calendar repair (merges saved Monday with fresh Tue-Fri), DST-proof two-cron
workflow with a gate, single commit with push retry, red-X email on critical failures, ai_info explaining exactly
why models failed, Haiku retries temporary errors (503/529/429/timeouts) at most 2 extra times with exponential backoff (5 s then 10 s); bad-key and bad-request errors fail at once; SDK auto-retry is off. Set by the owner: HAIKU_RETRIES / HAIKU_BASE_DELAY in ai_synthesis.py. RULE: tell the owner BEFORE making any change he did not ask for.

**Dollar explained (for future sessions):** ICE DXY = dollar vs 6 currencies (euro about 58%), base 100 in 1973,
usual range 90-110, Yahoo ticker DX-Y.NYB. Our row is the Fed Nominal Broad Dollar Index (DTWEXBGS): 26 currencies,
base 100 in Jan 2006, about 120 today. They move together most days. Direction matters more than level: a falling
index is a tailwind for international ADRs (EQNR, PBR, SNY, NVO, SHEL, BP). Thresholds re-based (>=125 = strong).

**Tested offline (fake network, real code):** good day, Gemini down, everything broken at once, all AI down, total
blackout. All published a page, none crashed. DST gate tested across Nov 1 2026 and Mar 14 2027.

**Known limits:** monthly and quarterly macro data lag by nature (CPI, PCE, unemployment, sentiment, GDP); they are
labelled with their real as-of month. ISM PMI stays excluded. A Friday calendar cut before this overhaul is repaired the
first Tue-Fri run that has a fuller brief.

---

### Session 14 (continued), part 2 -- Sep 30 2026 (same day)
**Files delivered later:** html_builder.py (Python 3.11 fix), ai_synthesis.py (Haiku retries), routine instructions (later restored to the original, see rules).

1. **Outage 1: ImportError on market.** The delivered market.py was fine; the copy in the repo was not the delivered file
   (copy/paste or partial overwrite). Lesson: verify file size/line count after copying, or stop copy-pasting (see below).
2. **Outage 2: SyntaxError in html_builder.py** (backslash inside an f-string expression). Invisible on Python 3.12, fatal on
   3.11. Fixed; every file now checked with python3.11 before delivery.
3. **Routine v2 took 12 minutes** with 21 failed page fetches (see rule above). Fixed in v3: search only, budget of 14 searches,
   no URLs anywhere in the text, all-or-nothing prices (market_prices = {} falls back to the pipeline's own Yahoo feed).
   Routine schedule is now 7:40 AM MDT (owner changed it); pipeline stays 7:50.
4. **ETF P/E finding:** the same fund (EFA) showed P/E 16.6, 19.5, 32.1, "-" and 0 on different sites via search results.
   The routine had been mixing gurufocus (URTH 18.86) with ishares (EFA 18.71). iShares' own figure for URTH is about 26.4x
   (BlackRock page, as of Sep 24 2026). Search results rarely show iShares' EFA figure, so the routine now tries once per fund,
   accepts only ishares.com/blackrock.com with an as-of date, and otherwise leaves null. PLAN (owner to confirm): update
   PE_CONFIG in market.py monthly from the iShares fact sheets, using iShares for BOTH funds. Until then the dashboard shows
   the amber "verify source" badge and a possibly wrong EFA-versus-URTH label.
5. **README:** not needed. SESSION_LOG.md is the project memory. (Optional later: a CLAUDE.md file so Claude Code loads the
   standing rules automatically.)
6. **Live page check (Sep 29 evening):** the deployed page was still the 8:02 AM Sep 29 build (old labels, empty 13F, old 10Y)
   right after manual run #77 (success, 1m 0s; summary showed only CNBC red). Expect it to update within minutes; if not,
   inspect the "Commit and push dashboard" step of the run.
7. **Known stale comments (harmless, fix next time those files change):** main.py, html_builder.py and daily.yml still say the
   routine runs at 7:44/7:45; fred.py comments say "18 series" (there are 17).

**LESSONS LEARNED**
- Copy/paste of multi-file changes through a chat window caused two of the three outages. A coding agent that works inside the
  repo (Claude Code) removes the copy step, can run the same Python version as the workflow, and can run the tests itself.
- Test where the code will run: same Python version, same network limits (the routine cannot fetch pages).
- Every change to something that already worked (routine instructions especially) needs a before/after time or output check.
- Do not add complexity without evidence it is needed; prefer the smallest change that fixes the observed problem.
- Watch the first real scheduled run after any deployment: read the health banner and the Actions run summary.

---

### Session 14 (continued), part 3 -- Oct 1 2026: push-triggered pipeline and polish
**Files changed:** daily.yml, main.py, screens.py, health.py, fred.py, ai_synthesis.py, html_builder.py, fetch_cache.py, SESSION_LOG.md.
Unchanged: news.py, market.py, timeutil.py. Everything tested on Python 3.13 (five failure scenarios plus same-day reuse and
a date-simulated Dataroma test).

**Why:** on Sep 30 GitHub started both scheduled runs about 4h45m late, so the page stayed stale until 12:37 PM MT.
The earlier assumption that a manual run had caused the 12:37 build was WRONG (both runs said "Scheduled").

**Changes (all approved by the owner before coding):**
1. daily.yml: runs when the routine pushes clauderoutinedata.json; one backup schedule (15:17 UTC) that skips if today's
   page exists; manual button; Python 3.13. Daylight-saving gate and second cron removed.
2. ai_synthesis.py: model order alias first (gemini-flash-latest), then gemini-3.6-flash, gemini-3.5-flash, Haiku. The page
   shows the model Google reports (response.model_version). Fixed the stray ". ." in the notice.
3. fred.py / health.py: dollar row max_age_days = 11 via health.max_age_for(); dollar note shortened to fit two lines
   ("Fed broad dollar index · 26 currencies · Jan 2006 = 100 · above 100 = stronger than 2006 · falling helps intl ADRs").
   Comment fixes (17 series, routine time 7:40).
4. html_builder.py: removed the "as of ... via Claude Routine" labels (card heading and S&P line); replaced the top banner and
   AI banner with one status line; removed the duplicate "Trend colors" line (legend header now says trend colors: green /
   red / amber = depends, and the warning triangle = data problem); kept the AAII reminder; removed "Not financial advice";
   footer lists the new model order.
5. screens.py / main.py: Dataroma only after a 13F deadline and once a day (last_attempt in dataroma_cache.json);
   Magic Formula / Acquirer's Multiple reuse today's saved copy on a second run; cache dates now use the Boise day.
6. Session log renumbered: this work is folded under Session 14 (continued).

**Decisions and explanations recorded for the owner:**
- Pages build vs MarketPulse run: see INFRASTRUCTURE. Code commits do not start the pipeline any more.
- 13F deadlines are fixed dates, 45 days after quarter end; Nov 14 2026 is a Saturday so filings are due Mon Nov 16.
- FRED's dollar index is daily data delivered weekly. ICSA = Initial Claims, Seasonally Adjusted (weekly, Thursdays 8:30 ET).
- AAII (not "AI") = American Association of Individual Investors sentiment survey; blocks automated access.
- Dollar index 120.3 = about 20% stronger than Jan 2006 against a 26-currency basket; it is not an exchange rate.
- Emails and Edward Jones are NOT cached (tiny requests; stale-news risk). A one-time CNBC welcome email counted as a real
  issue; owner chose not to build a check for it.
- Both the URTH/EFA P/E sources (stockanalysis.com and Robinhood) and iShares give about a 27% ex-US discount.

---

### Session 14 (continued), part 4 -- Oct 1 2026 (evening): AI order and tooling answers
**Files changed:** ai_synthesis.py, html_builder.py (footer and status-line wording), main.py (comments only), SESSION_LOG.md.
Tested on Python 3.13 (eight scenarios including Sonnet down, no access to Sonnet, Claude both down, everything down) and 3.14.

**Change (owner approved):** Claude Sonnet 5.5 first, Haiku 4.5 second, one free Gemini 3.5 Flash try third. See the rules above for
the reasons and costs. The page line now reads "Data health OK · Briefing by Claude Sonnet 5.5".
REVISED the same evening at the owner's request: no retries at all (one try per model), a single 10 s wait between Sonnet and
Haiku only after a temporary error, permanent errors go straight to Haiku with a visible hint, and the last-resort Gemini is
3.6 Flash (the owner's choice; note 3.6 answered 503 on some days while 3.5 answered, and the free tier allows few requests).

**Answers recorded for the owner:**
- Does a failed Gemini call count toward limits? Google does not say (not found). The dashboard showed RPM warnings, so quick
  repeated calls are a plausible cause.
- Seeing the screen: Claude in Chrome (extension side panel, Chrome only) reads and clicks pages; Claude Desktop computer use works
  with desktop apps and asks permission per app. Images cost about width x height / 750 tokens (roughly 1,000 to 1,500 per screenshot).
- VS Code Source Control: Commit = local snapshot; Commit & Push = save and upload; Commit & Sync = save, pull others' changes
  (the routine and bot commit daily), then upload (best default); Amend = rewrite the last commit (avoid). Undo: Discard Changes
  before committing; Undo Last Commit before pushing; after pushing git history still holds every version.
- Claude Code in VS Code: with extension v2.1.283 or later the starting permission mode is Auto (edits most files without asking).
  For a first try switch the mode chip at the bottom of the prompt box to Manual ("Ask before edits"). To use a newer model such as
  Sonnet 5.5 the extension must be updated: Extensions view (Ctrl+Shift+X), find Claude Code, Update, then reload the window.

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
- MHS is the macro backdrop gauge -- sets the bar, not a buy/sell trigger
- EXTREME OVERHEATED (86+): raise bar, not panic. Quality and patience above all.
- Loves the value screens (All-3 = highest conviction, 2-of-3 = strong convergence)
- Does NOT want prescriptive rule-based instructions hardcoded in the AI prompt
- Prefers genuine insights over data regurgitation
- No repeated news stories across days (e.g. same Nvidia headline daily)
- No em dashes, no en dashes in Claude responses
- Windows 11 Home -- never give Mac instructions or shortcuts
- US stocks primary focus, mean reversion style, NOT interested in FOMO or growth stocks