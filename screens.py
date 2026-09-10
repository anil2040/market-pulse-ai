# ============================================================
# screens.py -- Value screen fetchers
# Mean Reversion Macro Insights
# ============================================================
#
# PUBLIC FUNCTIONS (called by main.py):
#   fetch_superinvestor_buys() -> dict  {ticker: count}
#   fetch_magic_formula()      -> set   {ticker, ...}
#   fetch_acquirers_multiple() -> set   {ticker, ...}
#
# WHAT THIS COVERS:
#   - Dataroma 13F superinvestor buys (cache-first, 20hr TTL)
#   - Magic Formula (Greenblatt) -- ASP.NET 4-step auth scrape
#   - Acquirer's Multiple (Carlisle) -- RCP WordPress login + table
#     Cache: am_cache.json, 48hr TTL, written on success, read on failure
#
# CACHE FILES (committed to repo, persist across ephemeral GH Actions runners):
#   dataroma_cache.json -- written by fetch_cache.py, read here
#   am_cache.json       -- written here on success, read on timeout/fail
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
    Fetch Magic Formula top 30 stocks from magicformulainvesting.com.
    Uses ASP.NET 4-step auth: GET login page -> extract CSRF token ->
    POST credentials -> GET screener page -> extract CSRF -> POST screen.
    Returns set of ticker strings.
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

        # Step 4: POST screen parameters
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

        tickers = list(dict.fromkeys(tickers))
        print(f"   ✅ Magic Formula: {len(tickers)} tickers")
        if tickers:
            print(f"   Sample: {tickers[:8]}")
        return set(tickers)

    except Exception as e:
        print(f"   ❌ Magic Formula failed: {e}")
        return set()


# ============================================================
# ACQUIRER'S MULTIPLE (Carlisle)
# ============================================================

def fetch_acquirers_multiple():
    """
    Fetch Acquirer's Multiple large-cap screen from acquirersmultiple.com.
    Uses RCP WordPress login flow. Writes am_cache.json on success.
    Falls back to am_cache.json on failure (48hr TTL).
    Returns set of ticker strings.
    """
    AM_CACHE_FILE    = "am_cache.json"
    AM_CACHE_TTL_HRS = 48

    print("\n📐 Fetching Acquirer's Multiple large-cap stocks...")

    def _read_am_cache():
        try:
            with open(AM_CACHE_FILE, "r") as f:
                cached = json.load(f)
            fetched_at = datetime.fromisoformat(
                cached.get("fetched_at", "2000-01-01T00:00:00"))
            age_hours = (datetime.now() - fetched_at).total_seconds() / 3600
            if age_hours < AM_CACHE_TTL_HRS and cached.get("tickers"):
                return set(cached["tickers"]), age_hours
        except Exception:
            pass
        return None, None

    def _write_am_cache(tickers_set):
        try:
            with open(AM_CACHE_FILE, "w") as f:
                json.dump({
                    "fetched_at": datetime.now().isoformat(),
                    "tickers":    sorted(tickers_set),
                }, f, indent=2)
            print(f"   ✅ AM cache written ({len(tickers_set)} tickers)")
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

        tickers = []
        for t in soup2.find_all("table"):
            rows = t.find_all("tr")
            if len(rows) < 3:
                continue
            hdrs = [c.get_text(strip=True) for c in rows[0].find_all(["th", "td"])]
            print(f"   Table: {len(rows)} rows | headers: {hdrs[:4]}")
            if hdrs and hdrs[0].strip().lower() == "ticker":
                for row in rows[1:]:
                    cells = row.find_all("td")
                    if cells:
                        ticker = re.sub(r"[^A-Z.]", "",
                                        cells[0].get_text(strip=True).upper())
                        if re.match(r"^[A-Z]{1,5}$", ticker):
                            tickers.append(ticker)
                break

        tickers = list(dict.fromkeys(tickers))

        if tickers:
            print(f"   ✅ Acquirer's Multiple: {len(tickers)} tickers (live)")
            if tickers:
                print(f"   Sample: {tickers[:8]}")
            _write_am_cache(set(tickers))
            return set(tickers)
        else:
            raise Exception("Live scrape returned 0 tickers")

    except Exception as e:
        print(f"   ❌ Acquirer's Multiple live fetch failed: {e}")
        cached_set, age_h = _read_am_cache()
        if cached_set:
            print(f"   ⚠️ Using AM cache fallback ({age_h:.1f}h old, {len(cached_set)} stocks)")
            return cached_set
        print("   ❌ No AM cache available")
        return set()
