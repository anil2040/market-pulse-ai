# ============================================================
# screens.py -- Value screen fetchers
# Mean Reversion Macro Insights
# ============================================================
#
# PUBLIC FUNCTIONS (called by main.py). Each returns (data, meta):
#   fetch_superinvestor_buys() -> ({ticker: count},            meta)
#   fetch_magic_formula()      -> ([(ticker, rank_int), ...],  meta)
#   fetch_acquirers_multiple() -> ([(ticker, multiple_str)...], meta)
#
#   meta = {"source": "live" | "cache",
#           "as_of":  "YYYY-MM-DD",   (date the data was really fetched)
#           "note":   short human text for the dashboard badge}
#
# Every function RAISES ScreenError when it cannot produce data.
# main.py catches that and falls back to run_cache.json. Nothing here
# ever returns an empty result pretending to be a success.
#
# ONE-TIME BUG FIXED (Sep 29 2026):
#   Old versions caught their own errors and returned {} or [].
#   main.py then saw "success", wrote the EMPTY result over the last
#   good copy in run_cache.json, and its fallback code never ran.
#
# HOW OFTEN EACH SOURCE IS CONTACTED (kept low on purpose, to be a good neighbour):
#   Dataroma 13F       Not at all until a 13F filing deadline has passed since the saved
#                      list was fetched (Feb 14, May 15, Aug 14, Nov 14, plus 3 days grace).
#                      Then ONE try per day until a live fetch works, then silence again
#                      until the next deadline. About four windows a year.
#   Magic Formula and  Once per day. A second run on the same day reuses today's saved copy
#   Acquirer's Multiple (that rule lives in main.py).
#
# CACHE FILES (just two in the whole project):
#   run_cache.json      -- automatic fallback for everything, written by
#                          main.py, committed by the workflow every day.
#   dataroma_cache.json -- Dataroma 13F only. 13F data changes once a
#                          quarter, so this file is used at ANY age.
#                          Refreshed automatically when the live fetch
#                          works, or by hand: python fetch_cache.py
#                          on your PC (Dataroma sometimes blocks GitHub).
#   (am_cache.json is gone -- it duplicated run_cache.json and was never
#    committed, so it never survived a run.)
# ============================================================

import os
import re
import json
import time
from datetime import datetime, timedelta, timezone
import requests
from bs4 import BeautifulSoup

from health import last_13f_deadline, _13F_GRACE_DAYS
from timeutil import now_mt

MFI_EMAIL    = (os.environ.get("MFI_EMAIL")    or "").strip()
MFI_PASSWORD = (os.environ.get("MFI_PASSWORD") or "").strip()
AM_EMAIL     = (os.environ.get("AM_EMAIL")     or "").strip()
AM_PASSWORD  = (os.environ.get("AM_PASSWORD")  or "").strip()

DATAROMA_CACHE_FILE = "dataroma_cache.json"
DATAROMA_URL        = "https://www.dataroma.com/m/g/portfolio_b.php?q=q"


class ScreenError(Exception):
    """Raised when a screen cannot produce usable data."""


def _utc_now():
    return datetime.now(timezone.utc)


def today_str():
    """Today's date in Boise time, as used for every 'as of' stamp."""
    return now_mt().strftime("%Y-%m-%d")


def _parse_utc(s):
    """Parse an ISO timestamp. Old files were written without a timezone; treat as UTC."""
    dt = datetime.fromisoformat(s)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


# ============================================================
# DATAROMA 13F SUPERINVESTOR BUYS
# ============================================================

def fetch_dataroma_live():
    """
    Live fetch from Dataroma. Returns dict {ticker: buy_count}.
    Raises ScreenError on any failure (including too few rows parsed).
    Retries twice for the temporary errors Dataroma throws at automated
    traffic (409, 429, 5xx). Also used by fetch_cache.py on your PC.
    """
    hdrs = {
        "User-Agent":      ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
        "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer":         "https://www.dataroma.com/m/home.php",
    }
    sess = requests.Session()
    sess.headers.update(hdrs)
    resp = None
    last_err = ""
    for attempt in (1, 2, 3):
        try:
            resp = sess.get(DATAROMA_URL, timeout=20)
            print(f"   Status: {resp.status_code} (attempt {attempt})")
            if resp.status_code == 200:
                break
            last_err = f"HTTP {resp.status_code}"
        except Exception as e:
            last_err = f"{type(e).__name__}: {str(e)[:80]}"
            resp = None
        if attempt < 3:
            time.sleep(4 * attempt)
    if resp is None or resp.status_code != 200:
        raise ScreenError(f"Dataroma live fetch failed ({last_err})")

    soup  = BeautifulSoup(resp.text, "html.parser")
    buys  = {}
    table = soup.find("table", {"id": "grid"})
    if not table:
        for t in soup.find_all("table"):
            if len(t.find_all("tr")) > 5:
                table = t
                break
    if not table:
        raise ScreenError("Dataroma page had no data table")

    rows    = table.find_all("tr")
    headers = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]
    sym_idx = next((i for i, h in enumerate(headers)
                    if any(k in h for k in ["Symbol", "Ticker"])), 0)
    buy_idx = next((i for i, h in enumerate(headers)
                    if any(k in h for k in ["Buy", "Count"])), 3)
    print(f"   Using: Symbol col={sym_idx}, Buys col={buy_idx}")
    for row in rows[1:]:
        cells = row.find_all("td")
        if len(cells) > max(sym_idx, buy_idx):
            ticker = re.sub(r"[^A-Z.]", "", cells[sym_idx].get_text(strip=True).upper())[:6]
            if not ticker:
                continue
            try:
                count = int(cells[buy_idx].get_text(strip=True).replace(",", ""))
            except Exception:
                count = 1
            buys[ticker] = count

    if len(buys) < 20:
        raise ScreenError(f"Dataroma parsed only {len(buys)} rows (expected ~100)")
    return buys


def write_dataroma_cache(buys):
    """Save a successful Dataroma result. Both timestamps are UTC."""
    now = _utc_now().isoformat()
    with open(DATAROMA_CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump({"fetched_at": now, "last_attempt": now, "buys": buys}, f, indent=2)


def mark_dataroma_attempt():
    """Record that a live fetch was tried (and failed) now, keeping the saved list unchanged."""
    try:
        with open(DATAROMA_CACHE_FILE, "r", encoding="utf-8") as f:
            cached = json.load(f)
        cached["last_attempt"] = _utc_now().isoformat()
        with open(DATAROMA_CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cached, f, indent=2)
    except Exception as e:
        print(f"   Could not record the attempt: {e}")


def read_dataroma_full():
    """Returns (buys, fetched_utc, last_attempt_utc_or_None), or (None, None, None)."""
    try:
        with open(DATAROMA_CACHE_FILE, "r", encoding="utf-8") as f:
            cached = json.load(f)
        buys = cached.get("buys") or {}
        if not buys:
            return None, None, None
        fetched = _parse_utc(cached.get("fetched_at", "2000-01-01T00:00:00"))
        la = cached.get("last_attempt")
        return buys, fetched, (_parse_utc(la) if la else None)
    except FileNotFoundError:
        return None, None, None
    except Exception as e:
        print(f"   Cache read problem: {e}")
        return None, None, None


def read_dataroma_cache():
    """Returns (buys_dict, fetched_datetime_utc) or (None, None). Age does not matter."""
    buys, fetched, _ = read_dataroma_full()
    return buys, fetched


def refresh_due(fetched, today):
    """
    True when a 13F deadline (plus grace) has passed since the saved list was fetched,
    meaning new filings should now be on Dataroma.
    """
    ready = last_13f_deadline(today) + timedelta(days=_13F_GRACE_DAYS)
    return today >= ready and fetched.date() < ready


def _cache_result(buys, fetched, note):
    return buys, {"source": "cache", "as_of": fetched.strftime("%Y-%m-%d"), "note": note}


def fetch_superinvestor_buys():
    """
    Dataroma 13F buys, contacting Dataroma as rarely as possible:
      1. A saved list exists and no new 13F deadline has passed since it was fetched:
         use it, no network call at all.
      2. A deadline has passed (new filings should be out): try live, but only ONCE PER DAY.
         On success dataroma_cache.json is refreshed (the workflow commits it).
         On failure the attempt is recorded and the saved list is used, with the
         dashboard showing an amber reminder.
      3. No saved list at all: try live.
    Raises ScreenError if nothing works; main.py then tries run_cache.json.
    """
    print("\n👑 Dataroma superinvestor quarterly buys...")
    today = now_mt().date()
    buys, fetched, last_attempt = read_dataroma_full()

    if buys:
        if not refresh_due(fetched, today):
            print(f"   ♻️ Using saved list from {fetched.strftime('%Y-%m-%d')}: no new 13F deadline "
                  f"since then, so Dataroma is not contacted")
            return _cache_result(buys, fetched,
                                 f"saved list from {fetched.strftime('%b %d')}; next refresh after the next 13F deadline")
        if last_attempt is not None and now_mt().tzinfo is not None and \
                last_attempt.astimezone(now_mt().tzinfo).date() == today:
            print("   ♻️ New filings are due but Dataroma was already tried today; using saved list")
            return _cache_result(buys, fetched,
                                 f"saved list from {fetched.strftime('%b %d')}; already tried today, retrying tomorrow")
        print("   A new 13F deadline has passed: trying Dataroma live (one try per day)")

    live_err = ""
    try:
        live = fetch_dataroma_live()
        top3 = sorted(live.items(), key=lambda x: -x[1])[:3]
        print(f"   ✅ Dataroma (live): {len(live)} stocks | Top: {top3}")
        try:
            write_dataroma_cache(live)
        except Exception as e:
            print(f"   Could not refresh cache file: {e}")
        return live, {"source": "live", "as_of": today_str(), "note": "live"}
    except Exception as e:                     # ScreenError, or anything unexpected (never crash the run)
        live_err = str(e) if isinstance(e, ScreenError) else f"{type(e).__name__}: {str(e)[:80]}"
        print(f"   ⚠️ {live_err} -- using dataroma_cache.json")
        if buys:
            mark_dataroma_attempt()

    if buys:
        age_days = (_utc_now() - fetched).days
        print(f"   ♻️ Dataroma from dataroma_cache.json: {len(buys)} stocks, {age_days} days old")
        return _cache_result(buys, fetched, f"cache from {fetched.strftime('%b %d')} (live fetch failed)")
    raise ScreenError(f"Dataroma unavailable: {live_err}; no dataroma_cache.json")


# ============================================================
# MAGIC FORMULA (Greenblatt)
# ============================================================

def fetch_magic_formula():
    """
    Fetch Magic Formula top stocks from magicformulainvesting.com.
    Uses ASP.NET 4-step auth: GET login -> extract CSRF -> POST creds
    -> GET screener -> extract CSRF -> POST screen.
    Returns ORDERED LIST of (ticker, rank) tuples.
    Rank 1 = highest conviction (Greenblatt's composite score of
    earnings yield + ROIC; no raw score published, rank is the signal).
    """
    print("\n🔮 Fetching Magic Formula stocks...")
    try:
        sess = requests.Session()
        sess.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept":     "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

        # Step 1: GET login page, extract CSRF token
        login_url   = "https://www.magicformulainvesting.com/Account/LogOn"
        resp        = sess.get(login_url, timeout=15)
        soup        = BeautifulSoup(resp.text, "html.parser")
        token_input = soup.find("input", {"name": "__RequestVerificationToken"})
        if not token_input:
            raise Exception("Login token not found -- site may have changed")
        token = token_input.get("value", "")
        print(f"   Got anti-forgery token: {token[:20]}...")

        # Step 2: POST credentials
        resp = sess.post(login_url, data={
            "Email":    MFI_EMAIL,
            "Password": MFI_PASSWORD,
            "__RequestVerificationToken": token,
        }, timeout=15)
        if any(kw in resp.text for kw in ["Welcome", "LogOff", "Log Off", "Screening"]):
            print("   ✅ Logged into Magic Formula")
        elif any(kw in resp.text.lower() for kw in ["invalid", "incorrect"]):
            raise Exception("Login failed -- check MFI_EMAIL / MFI_PASSWORD secrets")
        else:
            print(f"   Login submitted (status {resp.status_code})")

        # Step 3: GET screener page, extract second CSRF token
        screener_url = "https://www.magicformulainvesting.com/Screening/StockScreening"
        resp         = sess.get(screener_url, timeout=15)
        soup         = BeautifulSoup(resp.text, "html.parser")
        st_input     = soup.find("input", {"name": "__RequestVerificationToken"})
        if not st_input:
            raise Exception("Screener token not found")
        screen_token = st_input.get("value", "")

        # Step 4: POST screen parameters (30 stocks, $2B+ market cap)
        resp   = sess.post(screener_url, data={
            "MinimumMarketCap":            "2000",
            "NumberOfStocks":              "30",
            "__RequestVerificationToken":  screen_token,
        }, timeout=20)
        soup   = BeautifulSoup(resp.text, "html.parser")
        tables = soup.find_all("table")
        print(f"   Tables found: {len(tables)}")

        tickers    = []
        ticker_col = None
        for t in tables:
            rows = t.find_all("tr")
            if len(rows) < 3:
                continue
            hdrs = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]
            print(f"   Table headers: {hdrs}")
            for ci, h in enumerate(hdrs):
                if any(k in h.lower() for k in ["ticker", "symbol"]):
                    ticker_col = ci
                    print(f"   Ticker column at index {ci}: '{h}'")
                    break
            if ticker_col is None and len(rows) > 1:
                for ci, cell in enumerate(rows[1].find_all("td")):
                    txt = cell.get_text(strip=True).upper()
                    if re.match(r"^[A-Z]{1,5}$", txt):
                        ticker_col = ci
                        print(f"   Ticker auto-detected at col {ci}: '{txt}'")
                        break
            if ticker_col is not None:
                for row in rows[1:]:
                    cells = row.find_all("td")
                    if ticker_col < len(cells):
                        clean = re.sub(r"[^A-Z.]", "",
                                       cells[ticker_col].get_text(strip=True).upper())
                        if re.match(r"^[A-Z]{1,5}$", clean):
                            tickers.append(clean)
                break

        # Dedupe preserving order
        seen = set()
        ordered = []
        for t in tickers:
            if t not in seen:
                seen.add(t)
                ordered.append(t)

        # Return as (ticker, rank) tuples -- rank = position in list (1-based)
        result = [(t, i + 1) for i, t in enumerate(ordered)]
        if len(result) < 10:
            raise ScreenError(f"Magic Formula returned only {len(result)} tickers")
        print(f"   ✅ Magic Formula: {len(result)} tickers (ranked)")
        print(f"   Sample: {result[:5]}")
        return result, {"source": "live", "as_of": today_str(),
                        "note": "live"}

    except ScreenError:
        raise
    except Exception as e:
        print(f"   ❌ Magic Formula failed: {e}")
        raise ScreenError(f"Magic Formula failed: {str(e)[:100]}")


# ============================================================
# ACQUIRER'S MULTIPLE (Carlisle)
# ============================================================

def fetch_acquirers_multiple():
    """
    Fetch Acquirer's Multiple large-cap screen from acquirersmultiple.com.
    Uses RCP WordPress login flow.
    Returns (ordered list of (ticker, multiple_str) tuples, meta).
    Raises ScreenError on failure; main.py falls back to run_cache.json.
    Position 1 = lowest EV/EBIT-style multiple = highest conviction.
    multiple_str is the raw value from the table (e.g. "4.2") or "-".
    """
    print("\n📐 Fetching Acquirer's Multiple large-cap stocks...")

    try:
        sess = requests.Session()
        sess.headers.update({
            "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        })

        r0    = sess.get("https://acquirersmultiple.com/login/", timeout=30)
        soup0 = BeautifulSoup(r0.text, "html.parser")
        print(f"   Login page: {r0.status_code} | Cookies: {len(sess.cookies)}")

        nonce_tag = soup0.find("input", {"name": "rcp_login_nonce"})
        nonce     = nonce_tag["value"] if nonce_tag else ""
        print(f"   Nonce: {nonce[:12]}..." if nonce
              else "   ⚠️ No nonce found -- login may fail")

        r1 = sess.post("https://acquirersmultiple.com/login/", data={
            "rcp_user_login": AM_EMAIL,
            "rcp_user_pass":  AM_PASSWORD,
            "rcp_action":     "login",
            "rcp_redirect":   "https://acquirersmultiple.com/login/",
            "rcp_login_nonce": nonce,
        }, timeout=30, allow_redirects=True)
        print(f"   Login POST: {r1.status_code} | URL: {r1.url}")

        logged_in = "logout" in r1.text.lower() or "log-out" in r1.text.lower()
        print(f"   Logged in: {logged_in}")
        if not logged_in:
            soup_err = BeautifulSoup(r1.text, "html.parser")
            err = soup_err.find(class_=re.compile(r"rcp.error|rcp.notice|error"))
            if err:
                print(f"   Error: {err.get_text(strip=True)[:120]}")

        r2    = sess.get("https://acquirersmultiple.com/screener/large-cap/", timeout=30)
        soup2 = BeautifulSoup(r2.text, "html.parser")
        title = soup2.find("title")
        print(f"   Screener: {r2.status_code} | Title: "
              f"{title.get_text(strip=True)[:50] if title else 'none'}")

        ordered_pairs = []
        for t in soup2.find_all("table"):
            rows = t.find_all("tr")
            if len(rows) < 3:
                continue
            hdrs = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
            print(f"   Table: {len(rows)} rows | headers: {hdrs[:6]}")

            # Find ticker column and multiple column
            ticker_col   = None
            multiple_col = None
            for ci, h in enumerate(hdrs):
                hl = h.lower()
                if hl == "ticker" or hl == "symbol":
                    ticker_col = ci
                # Look for the multiple value column -- typically "Acquirer's Multiple"
                # or just "Multiple" or "EV/EBIT" style header
                if any(k in hl for k in ["multiple", "ev/ebit", "ev / ebit",
                                          "acquirer", "value"]):
                    multiple_col = ci

            if ticker_col is None and hdrs and hdrs[0].strip().lower() == "ticker":
                ticker_col = 0

            print(f"   ticker_col={ticker_col}, multiple_col={multiple_col}")

            if ticker_col is not None:
                seen = set()
                for row in rows[1:]:
                    cells = row.find_all("td")
                    if len(cells) <= ticker_col:
                        continue
                    ticker = re.sub(r"[^A-Z.]", "",
                                    cells[ticker_col].get_text(strip=True).upper())
                    if not re.match(r"^[A-Z]{1,5}$", ticker):
                        continue
                    if ticker in seen:
                        continue
                    seen.add(ticker)

                    # Try to extract the multiple value
                    multiple_str = "-"
                    if multiple_col is not None and multiple_col < len(cells):
                        raw_val = cells[multiple_col].get_text(strip=True)
                        # Clean to numeric
                        cleaned = re.sub(r"[^0-9.\-]", "", raw_val)
                        if cleaned and cleaned not in ("", "-", "."):
                            try:
                                float(cleaned)
                                multiple_str = cleaned
                            except ValueError:
                                pass

                    ordered_pairs.append((ticker, multiple_str))
                break

        if ordered_pairs:
            print(f"   ✅ Acquirer's Multiple: {len(ordered_pairs)} tickers (ranked, with multiples)")
            print(f"   Top 5: {ordered_pairs[:5]}")
            if len(ordered_pairs) < 10:
                raise ScreenError(f"Acquirer's Multiple returned only {len(ordered_pairs)} tickers")
            return ordered_pairs, {"source": "live",
                                   "as_of": today_str(),
                                   "note": "live"}
        else:
            raise ScreenError("Acquirer's Multiple live scrape returned 0 tickers")

    except ScreenError:
        raise
    except Exception as e:
        print(f"   ❌ Acquirer's Multiple failed: {e}")
        raise ScreenError(f"Acquirer's Multiple failed: {str(e)[:100]}")