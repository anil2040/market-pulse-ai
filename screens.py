# ============================================================
# screens.py -- Value screen fetchers
# Mean Reversion Macro Insights
# ============================================================
#
# PUBLIC FUNCTIONS (called by main.py):
#   fetch_superinvestor_buys() -> dict  {ticker: count}
#   fetch_magic_formula()      -> list  [(ticker, rank_int), ...]
#   fetch_acquirers_multiple() -> list  [(ticker, multiple_str), ...]
#
# RETURN TYPE CHANGE (Sep 2026):
#   fetch_magic_formula() now returns an ORDERED LIST of (ticker, rank)
#   tuples rather than a set. Rank 1 = highest conviction per Greenblatt.
#   fetch_acquirers_multiple() now returns an ORDERED LIST of
#   (ticker, multiple_str) tuples. Position 1 = lowest multiple =
#   highest conviction. multiple_str is the raw EV/EBIT-style value
#   from the table, e.g. "4.2" or "-" if not available.
#   Both lists preserve the site's rank order (set destroyed it).
#
# IMPORTANT for main.py / html_builder.py:
#   - mf_tickers: use set(t for t,_ in mf_list) for membership tests
#   - am_tickers: use dict(am_list) for multiple lookup, set() for membership
#   - SI tickers dict is unchanged: {ticker: count}
#
# CACHE FILES (committed to repo, persist across ephemeral GH Actions runners):
#   dataroma_cache.json -- written by fetch_cache.py, read here
#   am_cache.json       -- written here on success, read on timeout/fail
#                          Now stores list of [ticker, multiple] pairs
#                          to preserve order and multiple values.
# ============================================================

import os
import re
import json
from datetime import datetime
import requests
from bs4 import BeautifulSoup

MFI_EMAIL    = os.environ.get("MFI_EMAIL")
MFI_PASSWORD = os.environ.get("MFI_PASSWORD")
AM_EMAIL     = os.environ.get("AM_EMAIL")
AM_PASSWORD  = os.environ.get("AM_PASSWORD")


# ============================================================
# DATAROMA 13F SUPERINVESTOR BUYS
# ============================================================

def fetch_superinvestor_buys():
    """
    Fetch superinvestor 13F quarterly buys from Dataroma.
    Reads dataroma_cache.json first (written by fetch_cache.py).
    Falls back to live fetch if cache is missing or stale (>20hr).
    Returns dict {ticker: buy_count}.
    """
    CACHE_FILE    = "dataroma_cache.json"
    CACHE_TTL_HRS = 20

    print("\n👑 Fetching Dataroma superinvestor quarterly buys...")

    # Try cache first
    try:
        with open(CACHE_FILE, "r") as f:
            cached = json.load(f)
        fetched_at = datetime.fromisoformat(cached.get("fetched_at", "2000-01-01T00:00:00"))
        age_hours  = (datetime.now() - fetched_at).total_seconds() / 3600
        if age_hours < CACHE_TTL_HRS and cached.get("buys"):
            buys = cached["buys"]
            top3 = sorted(buys.items(), key=lambda x: -x[1])[:3]
            print(f"   ✅ Dataroma (cache {age_hours:.1f}h old): {len(buys)} stocks | Top: {top3}")
            return buys
        else:
            print(f"   Cache stale ({age_hours:.1f}h > {CACHE_TTL_HRS}h) -- fetching live")
    except FileNotFoundError:
        print("   No cache file -- fetching live")
    except Exception as e:
        print(f"   Cache error: {e} -- fetching live")

    # Live fetch
    try:
        url  = "https://www.dataroma.com/m/g/portfolio_b.php?q=q"
        hdrs = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept":     "text/html,application/xhtml+xml",
            "Referer":    "https://www.dataroma.com/",
        }
        resp = requests.get(url, headers=hdrs, timeout=15)
        print(f"   Status: {resp.status_code}")
        if resp.status_code != 200:
            raise Exception(f"HTTP {resp.status_code}")

        soup  = BeautifulSoup(resp.text, "html.parser")
        buys  = {}
        table = soup.find("table", {"id": "grid"})
        if not table:
            for t in soup.find_all("table"):
                if len(t.find_all("tr")) > 5:
                    table = t
                    break

        if table:
            rows    = table.find_all("tr")
            headers = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]
            print(f"   Columns: {headers}")
            sym_idx = next((i for i, h in enumerate(headers)
                            if any(k in h for k in ["Symbol", "Ticker"])), 0)
            buy_idx = next((i for i, h in enumerate(headers)
                            if any(k in h for k in ["Buy", "Count"])), 3)
            print(f"   Using: Symbol col={sym_idx}, Buys col={buy_idx}")
            for row in rows[1:]:
                cells = row.find_all("td")
                if len(cells) > max(sym_idx, buy_idx):
                    ticker = re.sub(r"[^A-Z.]", "",
                                    cells[sym_idx].get_text(strip=True).upper())[:6]
                    if not ticker:
                        continue
                    try:
                        count = int(cells[buy_idx].get_text(strip=True).replace(",", ""))
                    except Exception:
                        count = 1
                    buys[ticker] = count

        top3 = sorted(buys.items(), key=lambda x: -x[1])[:3]
        print(f"   ✅ Dataroma: {len(buys)} stocks (live) | Top: {top3}")
        return buys

    except Exception as e:
        print(f"   ❌ Dataroma failed: {e}")
        return {}


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
    print("\n🔮 Fetching Magic Formula top 30 stocks...")
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
        print(f"   ✅ Magic Formula: {len(result)} tickers (ranked)")
        if result:
            print(f"   Sample: {result[:5]}")
        return result

    except Exception as e:
        print(f"   ❌ Magic Formula failed: {e}")
        return []


# ============================================================
# ACQUIRER'S MULTIPLE (Carlisle)
# ============================================================

def fetch_acquirers_multiple():
    """
    Fetch Acquirer's Multiple large-cap screen from acquirersmultiple.com.
    Uses RCP WordPress login flow. Writes am_cache.json on success.
    Falls back to am_cache.json on failure (48hr TTL).
    Returns ORDERED LIST of (ticker, multiple_str) tuples.
    Position 1 = lowest EV/EBIT-style multiple = highest conviction.
    multiple_str is the raw value from the table (e.g. "4.2") or "-".
    """
    AM_CACHE_FILE    = "am_cache.json"
    AM_CACHE_TTL_HRS = 48

    print("\n📐 Fetching Acquirer's Multiple large-cap stocks...")

    def _read_am_cache():
        """Returns (ordered_list_of_tuples, age_hours) or (None, None)."""
        try:
            with open(AM_CACHE_FILE, "r") as f:
                cached = json.load(f)
            fetched_at = datetime.fromisoformat(
                cached.get("fetched_at", "2000-01-01T00:00:00"))
            age_hours = (datetime.now() - fetched_at).total_seconds() / 3600
            if age_hours < AM_CACHE_TTL_HRS:
                # Support both old format (list of strings) and new (list of pairs)
                raw = cached.get("tickers_with_multiples") or cached.get("tickers")
                if raw:
                    if raw and isinstance(raw[0], list):
                        return [tuple(x) for x in raw], age_hours
                    else:
                        # Old format: list of strings, no multiples
                        return [(t, "-") for t in raw], age_hours
        except Exception:
            pass
        return None, None

    def _write_am_cache(ordered_pairs):
        """ordered_pairs: list of (ticker, multiple_str) tuples."""
        try:
            with open(AM_CACHE_FILE, "w") as f:
                json.dump({
                    "fetched_at":            datetime.now().isoformat(),
                    "tickers_with_multiples": [list(p) for p in ordered_pairs],
                    # Legacy key for any old readers
                    "tickers":               [t for t, _ in ordered_pairs],
                }, f, indent=2)
            print(f"   ✅ AM cache written ({len(ordered_pairs)} tickers with multiples)")
        except Exception as e:
            print(f"   ⚠️ Could not write AM cache: {e}")

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
            _write_am_cache(ordered_pairs)
            return ordered_pairs
        else:
            raise Exception("Live scrape returned 0 tickers")

    except Exception as e:
        print(f"   ❌ Acquirer's Multiple live fetch failed: {e}")
        cached_list, age_h = _read_am_cache()
        if cached_list:
            print(f"   ⚠️ Using AM cache fallback ({age_h:.1f}h old, {len(cached_list)} stocks)")
            return cached_list
        print("   ❌ No AM cache available")
        return []