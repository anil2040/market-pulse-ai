# ============================================================
# health.py -- Data health checks ("never be blindsided")
# Mean Reversion Macro Insights
# ============================================================
#
# WHY THIS EXISTS (Sep 29 2026):
#   Several problems ran for days or weeks with no visible sign:
#   a 26-day-old CNBC email, a one-month-old 10Y yield, an empty
#   super-investor list, a CAPE trend that never moved, a calendar
#   cut off mid-sentence. Each source now reports the age of its REAL
#   content, and this module turns that into a single list of items
#   that the dashboard shows as a banner and as badges on each card.
#
# ITEM FORMAT (a plain dict):
#   {"source": "Dataroma 13F",
#    "level":  "ok" | "warn" | "bad",     ok = fine, warn = amber, bad = red
#    "detail": "short human sentence",
#    "as_of":  "YYYY-MM-DD" or "",
#    "notify": True/False}   True = a "bad" item also turns the GitHub
#                            run red, which makes GitHub email you.
#
# ONE SYMBOL: the warning triangle (amber for warn, red for bad) is used
# only for data problems. Everything else on the page is plain text.
#
# All functions here are pure (no network, no files) so they are easy to test.
# ============================================================

from datetime import date, datetime, timedelta

OK, WARN, BAD = "ok", "warn", "bad"

# Oldest acceptable observation date, in days, before a FRED-style series is "late".
# Monthly and quarterly numbers are published weeks after the period ends, so
# their limits are long. Daily series allow a long weekend.
MAX_AGE_DAYS = {
    "daily":          6,
    "calendar_daily": 4,
    "weekly":         14,
    "monthly":        100,
    "quarterly":      215,   # Q2 GDP (dated Apr 1) is replaced ~Oct 29 = 211 days
}


def max_age_for(row):
    """
    Oldest acceptable observation for one indicator row, in days.
    A row can carry its own "max_age_days" (set in fred.py); otherwise the limit
    comes from its frequency. Example: the Fed's broad dollar index has a value for
    every day, but FRED only receives it once a week (Mondays, through the previous
    Friday), so it may legitimately be up to 10-11 days old.
    """
    own = row.get("max_age_days")
    if isinstance(own, (int, float)) and own > 0:
        return own
    return MAX_AGE_DAYS.get(row.get("freq", "monthly"), 100)


def item(source, level, detail="", as_of="", notify=False):
    return {"source": source, "level": level, "detail": detail,
            "as_of": as_of, "notify": notify}


def _to_date(s):
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


# ------------------------------------------------------------
# MACRO INDICATORS (FRED, Yahoo, multpl)
# ------------------------------------------------------------

def check_indicators(rows, today):
    """
    One item per problem row; a single OK item if everything is fine.
    Problems: no data, cached copy, observation older than expected,
    fallback source used, CAPE history unavailable.
    """
    items = []
    total = len(rows)
    good  = 0
    for r in rows:
        label = r.get("label", "?")
        if r.get("current") == "N/A":
            items.append(item(label, BAD, "no data returned", notify=True))
            continue
        problem = False
        if r.get("cached"):
            cd  = _to_date(r.get("cached_date", ""))
            age = (today - cd).days if cd else 99
            items.append(item(label, BAD if age > 3 else WARN,
                              f"live fetch failed; showing cached value from {r.get('cached_date', '?')}",
                              r.get("cached_date", ""), notify=age > 3))
            problem = True
        else:
            od  = _to_date(r.get("obs_date", ""))
            lim = max_age_for(r)
            if od is not None:
                age = (today - od).days
                if age > lim:
                    items.append(item(label, BAD if age > 2 * lim else WARN,
                                      f"latest reading is {age} days old (expected within {lim})",
                                      r.get("obs_date", ""), notify=age > 2 * lim))
                    problem = True
        if r.get("source_note"):
            items.append(item(label, WARN, r["source_note"], r.get("obs_date", "")))
            problem = True
        if label.startswith("Shiller CAPE") and (r.get("mo3") == "N/A" or r.get("mo12") == "N/A"):
            items.append(item(label, WARN, "3mo / 12mo history unavailable (table not readable)"))
            problem = True
        if not problem:
            good += 1
    if not items:
        items.append(item("Macro indicators", OK, f"all {total} indicators fresh"))
    elif good:
        items.append(item("Macro indicators", OK, f"{good} of {total} indicators fresh"))
    return items


def check_rate_crosscheck(rows, routine_data, routine_fresh):
    """FRED's daily 10Y should be within ~0.25 of the routine's live reading."""
    if not routine_data or not routine_fresh:
        return []
    live = (routine_data.get("rates_commodities") or {}).get("treasury_10yr_pct")
    row  = next((r for r in rows if r.get("label") == "10Y Treasury"), None)
    if live is None or not row or row.get("current") == "N/A":
        return []
    try:
        fred_v = float(str(row["current"]).replace("%", ""))
        live_v = float(live)
    except Exception:
        return []
    if abs(fred_v - live_v) > 0.25:
        return [item("10Y cross-check", WARN,
                     f"FRED shows {fred_v:.2f}% but the routine reports {live_v:.2f}% -- one source is off")]
    return []


# ------------------------------------------------------------
# PRE-MARKET ROUTINE (clauderoutinedata.json)
# ------------------------------------------------------------

def check_routine(routine_data, fresh, commit_time_mt=None):
    """commit_time_mt: 'HH:MM' from git history (the real time), or None."""
    if not routine_data:
        return [item("Claude Routine", BAD,
                     "clauderoutinedata.json missing or unreadable -- no pre-market data today",
                     notify=True)]
    if not fresh:
        return [item("Claude Routine", BAD,
                     f"data is from {routine_data.get('date', 'unknown')}, not today -- "
                     f"today's routine did not run or did not commit",
                     routine_data.get("date", ""), notify=True)]
    detail = f"committed {commit_time_mt} MT" if commit_time_mt else "fresh"
    return [item("Claude Routine", OK, detail, routine_data.get("date", ""))]


def check_pe_sanity(mkt_data, pe_config, pe_ref_date, tolerance=0.12):
    """
    Warn when a routine P/E is far from the last manual reference (PE_CONFIG).
    A 16% overnight change in a broad index P/E almost always means the
    source or the measure changed, not the market.
    """
    out = []
    for tk, key, srcs in (("URTH", "urth_pe", "urth_pe_source"), ("EFA", "efa_pe", "efa_pe_source")):
        pe  = mkt_data.get(key)
        src = mkt_data.get(srcs, "") or ""
        ref = (pe_config.get(tk) or {}).get("pe")
        if pe and ref and "Routine" in src:
            diff = (pe - ref) / ref
            if abs(diff) > tolerance:
                out.append(item(f"{tk} P/E", WARN,
                                f"{pe:.1f}x is {abs(diff) * 100:.0f}% "
                                f"{'below' if diff < 0 else 'above'} your {pe_ref_date} reference "
                                f"of {ref:.1f}x -- check the routine's data source"))
    return out


# ------------------------------------------------------------
# NEWS AND EMAIL
# ------------------------------------------------------------

def check_news(name, meta):
    """meta comes from news.py: status ok / stale / missing / error."""
    status = meta.get("status")
    if status == "ok":
        if meta.get("detail"):                       # e.g. arriving in Bulk folder
            return item(name, WARN, meta["detail"], meta.get("date", ""))
        return item(name, OK, "fresh", meta.get("date", ""))
    if status == "stale":
        age = meta.get("age_days") or 0
        return item(name, BAD if age > 10 else WARN, meta.get("detail", "content is old"),
                    meta.get("date", ""))
    return item(name, BAD, meta.get("detail", "unavailable"))


# ------------------------------------------------------------
# VALUE SCREENS
# ------------------------------------------------------------

_13F_DEADLINES = ((2, 14), (5, 15), (8, 14), (11, 14))   # 45 days after quarter end
_13F_GRACE_DAYS = 3


def last_13f_deadline(today):
    c = [date(y, m, d) for y in (today.year - 1, today.year) for m, d in _13F_DEADLINES
         if date(y, m, d) <= today]
    return max(c)


def next_13f_deadline(today):
    c = [date(y, m, d) for y in (today.year, today.year + 1) for m, d in _13F_DEADLINES
         if date(y, m, d) > today]
    return min(c)


def check_13f(meta, count, today):
    """
    Dataroma 13F list. Data only changes quarterly, so a saved copy is normal.
    It is only a problem when new filings are out and the copy predates them.
    """
    if not count:
        return item("Dataroma 13F", BAD, "no super-investor data at all", notify=True)
    as_of = _to_date(meta.get("as_of", ""))
    if meta.get("source") == "run_cache":
        return item("Dataroma 13F", WARN,
                    f"live fetch and dataroma_cache.json both failed; using older copy from {meta.get('as_of', '?')}",
                    meta.get("as_of", ""))
    due_since = None
    dl = last_13f_deadline(today)
    if today >= dl + timedelta(days=_13F_GRACE_DAYS):
        due_since = dl
    if as_of and due_since and as_of < dl + timedelta(days=_13F_GRACE_DAYS):
        overdue = (today - dl).days
        return item("Dataroma 13F", BAD if overdue > 45 else WARN,
                    f"new 13F filings have been out since {dl.strftime('%b %d')}; the pipeline retries "
                    f"once a day, or run python fetch_cache.py on your PC and commit dataroma_cache.json",
                    meta.get("as_of", ""), notify=overdue > 45)
    nxt = next_13f_deadline(today)
    if meta.get("source") == "cache":
        return item("Dataroma 13F", OK,
                    f"saved list from {as_of.strftime('%b %d') if as_of else '?'}; "
                    f"next refresh due after {nxt.strftime('%b %d')}",
                    meta.get("as_of", ""))
    return item("Dataroma 13F", OK, "live", meta.get("as_of", ""))


def check_screen(name, meta, count, today):
    """
    Magic Formula / Acquirer's Multiple: fetched live once a day; a second run the same
    day reuses that copy ("today_saved"); fallback when live fails = run_cache.json.
    """
    if not count:
        return item(name, BAD, "no data (live fetch failed and no saved copy)", notify=True)
    if meta.get("source") == "today_saved":
        return item(name, OK, "saved earlier today", meta.get("as_of", ""))
    if meta.get("source") == "run_cache":
        as_of = _to_date(meta.get("as_of", ""))
        age = (today - as_of).days if as_of else 99
        return item(name, BAD if age > 7 else WARN,
                    f"live fetch failed; using saved copy from {meta.get('as_of', '?')}",
                    meta.get("as_of", ""), notify=age > 7)
    return item(name, OK, "live", meta.get("as_of", ""))


# ------------------------------------------------------------
# CALENDAR, MARKET, SENTIMENT, AI
# ------------------------------------------------------------

def check_calendar(week_of, this_monday, text_len=0):
    if not week_of:
        return item("Weekly calendar", BAD, "no calendar stored for this week")
    if week_of != this_monday:
        return item("Weekly calendar", WARN, f"showing the calendar for the week of {week_of}", week_of)
    return item("Weekly calendar", OK, f"week of {week_of}", week_of)


def check_market(mkt_cached, cached_date=""):
    if mkt_cached:
        return item("Market prices", WARN, f"live fetch failed; cached values from {cached_date}",
                    cached_date)
    return item("Market prices", OK, "live")


def check_sentiment(fg_data):
    if fg_data.get("label") == "Unavailable":
        return item("Fear & Greed", BAD, "no data and no cached copy")
    if fg_data.get("cached"):
        return item("Fear & Greed", WARN, f"cached from {fg_data.get('cached_date', '?')}",
                    fg_data.get("cached_date", ""))
    return item("Fear & Greed", OK, "live")


def check_ai(ai_failed, ai_info):
    """AI problems are shown but never turn the run red (notify False)."""
    ai_info = ai_info or {}
    if ai_failed:
        return item("AI briefing", BAD, "all models failed -- fallback text shown")
    attempts = ai_info.get("attempts") or []
    if attempts:
        return item("AI briefing", WARN,
                    f"{ai_info.get('model', '?')} used after: " +
                    "; ".join(f"{a['model']} {a['error']}" for a in attempts))
    return item("AI briefing", OK, ai_info.get("model", ""))


# ------------------------------------------------------------
# SUMMARIES
# ------------------------------------------------------------

def problems(items):
    return [i for i in items if i["level"] != OK]


def needs_notification(items):
    """True if any item is red AND flagged notify (turns the GitHub run red -> email)."""
    return any(i["level"] == BAD and i.get("notify") for i in items)


def context_line(items):
    """One line for the hidden Chrome-extension block so its analysis knows about stale inputs."""
    p = problems(items)
    if not p:
        return "DATA_HEALTH:all_sources_fresh"
    parts = [f"{i['source']}[{i['level']}]:{i['detail']}" for i in p]
    return "DATA_HEALTH:" + " | ".join(parts)


def stale_notes_for_ai(items):
    """Short caveats for the AI prompt (data problems only; the AI item itself is excluded)."""
    return [f"{i['source']}: {i['detail']}" for i in problems(items) if i["source"] != "AI briefing"]