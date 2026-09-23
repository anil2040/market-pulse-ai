# Mean Reversion Macro Insights -- Session Log 12

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
| Claude Routine (market prices / pre-market data) | clauderoutinedata.json |

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

## INFRASTRUCTURE SNAPSHOT

- **Live site:** https://anil2040.github.io/market-pulse-ai
- **Repo:** https://github.com/anil2040/market-pulse-ai (public)
- **Owner:** Anil Abraham -- deep-value mean reversion investor, Boise ID
- **Style:** Greenblatt / Carlisle / Howard Marks / Burry / Pabrai
- **Local:** VS Code on Windows 11 Home (never give Mac instructions or shortcuts)
- **Schedule:** GitHub Actions cron `50 13 * * 1-5` (7:50 AM MT weekdays) + workflow_dispatch
- **Cron drift:** 7:50 AM cron typically starts at 7:58-8:00 AM -- normal GitHub behavior, not a bug
- **Runtime:** ~40-45 seconds, 15/15 indicators, well within free tier limits

**9 GitHub Secrets (all confirmed set):**
GEMINI_API_KEY, ANTHROPIC_API_KEY, YAHOO_EMAIL, YAHOO_APP_PASSWORD,
FRED_API_KEY, MFI_EMAIL, MFI_PASSWORD, AM_EMAIL, AM_PASSWORD

**Pipeline order (main.py) -- runs weekdays only via cron:**
```
Step 0:  load_claude_routine    (clauderoutinedata.json, written 7:44am MT by Claude Routine)
Step 1:  fetch_fred_data
Step 2:  fetch_fear_greed
Step 3:  fetch_market_indicators (uses routine PE as priority 0)
Step 4:  compute_mhs + _append_mhs_history (writes to run_cache.json)
Step 5:  fetch_superinvestor_buys
Step 6:  fetch_magic_formula    (returns ordered list of (ticker, rank) tuples)
Step 7:  fetch_acquirers_multiple (returns ordered list of (ticker, multiple_str) tuples)
Step 8:  scrape_edward_jones
Step 9:  fetch_cnbc_email
Step 10: fetch_yahoo_morning_brief (returns (brief_text, calendar_text) tuple)
Step 11: synthesize_with_ai     (Gemini -> Haiku -> structured fallback)
Step 12: build_html
Step 13: save + commit run_cache.json
```

All steps run every weekday. Fun Fact and AI Learning regenerate fresh each run.
Stale content on weekends is expected (no pipeline run).

---

## MODULE SUMMARY

| File | Lines | Responsibility |
|---|---|---|
| fred.py | ~503 | FRED API, Gold (Yahoo GC=F), CAPE (multpl.com), trend colors, sparklines, interpretive insights |
| market.py | ~320 | Yahoo SPX/RUT/VIX, Claude Routine PE (priority 0), iShares CSV PE, PE_CONFIG fallback, MHS, ERP |
| screens.py | ~350 | Dataroma 13F cache+live, Magic Formula (ordered list+rank), Acquirer's Multiple (ordered list+multiple) |
| news.py | ~282 | Edward Jones scrape, CNBC/Yahoo IMAP email, Yahoo calendar extractor |
| ai_synthesis.py | ~423 | Gemini 3.6 flash -> 3.5 flash -> Haiku -> structured fallback, 4 sections, routine context in prompt |
| html_builder.py | ~1561 | Full dashboard HTML, gauge cards, MHS history chart, 5-day calendar, conviction chips |
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

Routine 2: 7:44am MT -- "Daily Market Warmup" (machine-readable JSON, writes clauderoutinedata.json)
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
- If GitHub hasn't fully propagated the 7:44am routine commit by the time checkout runs,
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

**clauderoutinedata.json schema (written by 7:44am routine):**
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
- PRIMARY: routine_data["market_prices"] (browser-fetched at 7:44am MT, no CORS issue)
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
  20-day SMA appears after ~4 trading weeks of data accumulate from Sep 19 2026.
- mhs_scale text block below card REMOVED (legend is now inside chart bands).

**Market State Detection:**
- marketState taken from SPX (%5EGSPC) only -- VIX marketState is NOT used (unreliable).
- REGULAR -> OPEN, PRE -> PRE, POST -> POST, CLOSED -> CLOSED.
- GitHub Actions IPs blocked by Yahoo for JS/crumb-based API -- only v8 basic fetch works.

**AI Synthesis fallback chain (confirmed working Sep 23 2026):**
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

**AI Synthesis -- 4 sections (Earnings & Events removed Sep 2026):**
```
MARKET AND MACRO | WHAT TO WATCH | AI FUN FACT | AI LEARNING
```
- MARKET AND MACRO and WHAT TO WATCH shown as true 2-column CSS grid.
  Left col: "Macro Interpretation" (blue label). Right col: "What to Watch" (green label).
- No data regurgitation -- interpretive macro implications only.
- Yahoo calendar injected as WEEK AHEAD block in prompt for date-specific events.
- Claude Routine pre-market intelligence injected as PRE-MARKET INTELLIGENCE block (once only).
- Fun Fact and AI Learning regenerate fresh every weekday run.

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
- ⚠️ in Insights column = fred.py interpretive sig text prefix (separate from amber badge)
  Stripped with re.sub() in td rendering. Subtitle clarifies the difference.

**McClellan Oscillator:** Fully removed Sep 2026. Paid teaser only.

**Dashboard layout (confirmed working Sep 23 2026) -- DO NOT CHANGE WIDTH/LAYOUT:**
```
1.  Fun Fact + AI Learning        -- display:grid 1fr 1fr (same width as all cards)
2.  Earnings & Economic Calendar  -- full width single card
3.  MHS score + history SVG chart -- full width single card
4.  Market Performance + Market Sentiment -- display:grid 1fr 1fr (always side by side)
5.  Global Market Valuation       -- full width (CAPE + URTH + EFA + ERP)
6.  Market & Macro                -- full width (2-col grid INSIDE card: Macro / What to Watch)
7.  Value Screens                 -- full width (All-3, 2-of-3, SI-only, MF-only, AM-only)
8.  Macro Indicators table        -- full width (15 indicators, sparklines, insights)
9.  Run log                       -- collapsed button, expands to show all pipeline steps
10. Hidden #market-context div    -- for Chrome extension
```

**VIX placement (changed Session 11):**
- VIX moved OUT of Market Performance card INTO Market Sentiment table
- Sentiment table now has 3 rows: VIX | Fear & Greed | Consumer Sentiment
- VIX note: "CBOE Volatility · fear gauge · <15=calm · 20-25=cautious · >30=panic"
- Pulse line (⚡ S&P +X% · Russell +X% · VIX X.X ...) remains at bottom of Market Performance

**Header:**
- URL removed (redundant with address bar)
- Date and "Updated HH:MM MT" merged onto one .sub line. .ts row removed entirely.

**run_cache.json structure:**
```
fred_{label}:         per FRED indicator fallback, includes "fetched" date
fear_greed:           CNN Fear & Greed
market_indicators:    SPX/RUT/VIX/PE block
screens_si:           {ticker: count} dict
screens_mf:           [[ticker, rank], ...] list of pairs
screens_am:           [[ticker, multiple_str], ...] list of pairs
news_ej / news_cnbc / news_yahoo / news_yahoo_calendar: email caches
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

---

## GITHUB ACTIONS NOTES

- ubuntu-latest PINNED to ubuntu-24.04 as of Sep 20 2026 (migrates to Ubuntu 26 on Oct 19 2026).
- actions/checkout bumped to @v5, actions/setup-python bumped to @v6 (Node.js 22, clears warnings).
- The github-pages Bot "pages build and deployment" workflow is GitHub-internal -- its ubuntu-latest
  warning cannot be fixed by you. Not your workflow, ignore it.
- Canceling/superseded Pages deployments are normal when two commits happen close together.
- "Run job" = "trigger the workflow" = click Run workflow in Actions tab.
- Workflow dispatch (manual trigger): repo -> Actions -> MarketPulse Daily Briefing -> Run workflow
- Manual trigger re-runs the FULL pipeline every time -- all steps, all modules. No partial runs.
  For fast HTML iteration, test locally with `python main.py` in VS Code terminal before pushing.

---

## OPEN ITEMS / NEXT SESSION

1. **Verify Session 12 fixes on Sep 24 2026 scheduled run:**
   - clauderoutinedata.json shows date = 2026-09-24 on main, no side branch created
   - Pipeline run log shows no stale routine warning
   - Dashboard Market Performance shows "via Claude Routine" label
   - Routine completes in under 90 seconds with no red failure lines

2. **MHS 20-day SMA** -- will appear ~4 trading weeks from Sep 19 2026 (~Oct 17).
   No action needed, just wait for data to accumulate.

3. **Calendar persistence** -- verify calendar stays populated Tue-Fri from Monday cache.
   Working as of Sep 23 2026. Monitor on a Tuesday to confirm.

4. **ubuntu-24.04 deadline** -- Oct 19 2026, GitHub migrates ubuntu-latest to Ubuntu 26.
   If any pip packages break after that date, check Ubuntu 26 compatibility.

5. **Future: SEC EDGAR 13F API as Dataroma backup.**
   Dataroma working fine. EDGAR full-text search provides same 13F data if it goes down.

6. **Future: Chrome extension #market-context div compression (~60% reduction possible).**
   Low priority. Current div works fine.

7. **Future: Claude Code CLI setup** for direct repo read/write without paste workflow.
   Install in VS Code terminal: `npm install -g @anthropic-ai/claude-code` then `claude`

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

**market.py:**
- _yq() chg fix: always compute manually, never trust Yahoo's field
- _yq_pe(): 3-priority system (Routine -> iShares CSV -> PE_CONFIG)
- MHS EXTREME OVERHEATED posture trimmed to macro observation only

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

**GSD noted:** Framework for agentic coding with sub-agents + .planning/ files.
Not needed for this project. Relevant for new projects started from scratch in Claude Code.

---

### Session 11 -- Gemini timeout fix, width fix, VIX to Sentiment
**Date:** Sep 23 2026
**Files changed:** ai_synthesis.py, html_builder.py, SESSION_LOG.md

**Gemini timeout root cause found and fixed:**
- _call_gemini() was using client.interactions.create() -- new Interactions API
  causes 90s+ timeout under free-tier load due to stateful session overhead
- Fixed to client.models.generate_content() -- stateless, fast, fully supported
- gemini-2.5-flash -> corrected to gemini-3.5-flash (gemini-2.5-flash is not a valid ID)

**HTML width fixed (confirmed working Sep 23 2026):**
- Fun Fact + AI Learning: changed from class="grid-2" to display:grid;grid-template-columns:1fr 1fr
- Market Performance + Sentiment: same treatment
- All top-level layout sections now use identical grid or full-width -- consistent width throughout
- DO NOT change this layout -- it is confirmed working

**VIX moved to Sentiment card:**
- Removed VIX block from gauge_section (Market Performance card)
- Added VIX as first row in Sentiment table: VIX | Fear & Greed | Consumer Sentiment
- Pulse line (⚡) kept at bottom of Market Performance card for index context

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
- This is the only change to daily.yml

**Issue 2: Routine pushing to side branch instead of main**
- Claude Code Remote initializes every session on a new branch by default
- "Push to main branch" was ambiguous -- Claude committed locally then failed to push main
- Root cause of 4+ minute runtime: stash/rebase/conflict retry loop (4 failures observed)
- Fix: Step 3 of routine instructions replaced with explicit git command sequence
  (see clauderoutinedata.json schema section above for full sequence)
- After fix: routine completes in under 90 seconds, 2 commands, zero failures

**Other routine improvements in Session 12:**
- Model changed from Opus 5.5 to Sonnet 4.6 (faster, lower cost, same output quality)
- Treasury yield cross-check added: if yield differs >0.5% from prior day, verify second source
- source_time_et now records actual ET collection time (was using template placeholder)
- Hard stop after push: do not respond to hook prompts, no further commands or branches
- ETF PE source field now records whichever source was actually used

**AFC warning (confirmed non-issue):**
- Google SDK emits advisory warning for Models.generate_content -- not an error
- Appears as "Direct use of AFC in Models.generate_content is not recommended" in run log
- Gemini still falls through correctly to Haiku when 503 occurs. No code change needed.

**Session start improvement:**
- Old method: paste SESSION_LOG.md as file upload every session
- New method: "Fetch the session log from
  https://raw.githubusercontent.com/anil2040/market-pulse-ai/main/SESSION_LOG.md"
- Claude fetches live file from GitHub raw URL -- no file management needed
- Requires SESSION_LOG.md to be committed to main at end of each session

**Verification checklist for Sep 24 2026 scheduled run:**
1. clauderoutinedata.json date = 2026-09-24 on main, no side branch
2. Pipeline run log: no stale routine warning
3. Dashboard: Market Performance shows "via Claude Routine" label
4. Routine runtime: under 90 seconds, no red failure lines

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