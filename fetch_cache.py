# ============================================================
# fetch_cache.py  (UPDATED -- adds Acquirer's Multiple caching)
# Runs BEFORE main.py in the GitHub Actions workflow.
# Fetches slow/rate-limited data sources and writes JSON cache
# files that main.py reads. Cache files are committed to the
# repo so they persist across ephemeral GitHub Actions runners.
#
# Current sources cached:
#   dataroma_cache.json -- 13F superinvestor quarterly buys
#     Dataroma rate-limits repeat requests (HTTP 409).
#     Data updates quarterly -- daily cache is more than enough.
#
#   am_cache.json -- Acquirer's Multiple large-cap screener tickers
#     AM site can be slow/timeout in GitHub Actions.
#     Pre-fetching here means main.py always has a warm fallback.
#     Data updates daily after market close.
#
# To add more cached sources later:
#   1. Add a fetch function here
#   2. Write output to a new *_cache.json file
#   3. main.py reads the file with the same TTL pattern
# ============================================================
import json
import time
import re
import sys
import os
from datetime import datetime
import requests
from bs4 import BeautifulSoup

DATAROMA_CACHE_FILE = "dataroma_cache.json"
AM_CACHE_FILE       = "am_cache.json"

AM_EMAIL    = os.environ.get("AM_EMAIL")
AM_PASSWORD = os.environ.get("AM_PASSWORD")


# ============================================================
# DATAROMA -- 13F superinvestor quarterly buys
# ============================================================

def fetch_dataroma():
    print("👑 Fetching Dataroma superinvestor quarterly buys...")
    url = "https://www.dataroma.com/m/g/portfolio_b.php?q=q"
    hdrs = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept":     "text/html,application/xhtml+xml",
        "Referer":    "https://www.dataroma.com/",
    }
    resp = requests.get(url, headers=hdrs, timeout=20)
    print(f"   Status: {resp.status_code}")
    if resp.status_code != 200:
        raise Exception(f"HTTP {resp.status_code}")

    soup = BeautifulSoup(resp.text, "html.parser")
    buys = {}
    table = soup.find("table", {"id": "grid"})
    if not table:
        for t in soup.find_all("table"):
            if len(t.find_all("tr")) > 5:
                table = t
                break

    if not table:
        raise Exception("No table found in Dataroma response")

    rows = table.find_all("tr")
    headers = [th.get_text(strip=True) for th in rows[0].find_all(["th", "td"])]
    print(f"   Columns: {headers}")
    sym_idx = next((i for i, h in enumerate(headers)
                    if any(k in h for k in ["Symbol","Ticker","symbol","ticker"])), 0)
    buy_idx = next((i for i, h in enumerate(headers)
                    if any(k in h for k in ["Buy","buy","Count","count"])), 3)
    print(f"   Using: Symbol col={sym_idx}, Buys col={buy_idx}")

    for row in rows[1:]:
        cells = row.find_all("td")
        if len(cells) > max(sym_idx, buy_idx):
            ticker = re.sub(r"[^A-Z.]", "", cells[sym_idx].get_text(strip=True).upper())[:6]
            if not ticker:
                continue
            try:
                count = int(cells[buy_idx].get_text(strip=True).replace(",", ""))
            except:
                count = 1
            buys[ticker] = count

    print(f"   ✅ {len(buys)} stocks fetched")
    if buys:
        top3 = sorted(buys.items(), key=lambda x: -x[1])[:3]
        print(f"   Top: {top3}")
    return buys


# ============================================================
# ACQUIRER'S MULTIPLE -- large-cap screener
# ============================================================

def fetch_acquirers_multiple():
    print("\n📐 Fetching Acquirer's Multiple large-cap stocks...")

    if not AM_EMAIL or not AM_PASSWORD:
        raise Exception("AM_EMAIL or AM_PASSWORD secrets not set")

    sess = requests.Session()
    sess.headers.update({
        "User-Agent":    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept":        "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    })

    # Step 1: Get login page + nonce
    r0    = sess.get("https://acquirersmultiple.com/login/", timeout=30)
    soup0 = BeautifulSoup(r0.text, "html.parser")
    print(f"   Login page: {r0.status_code} | Cookies: {len(sess.cookies)}")

    nonce_tag = soup0.find("input", {"name": "rcp_login_nonce"})
    nonce     = nonce_tag["value"] if nonce_tag else ""
    print(f"   Nonce: {nonce[:12]}..." if nonce else "   ⚠️ No nonce found")

    # Step 2: Login POST
    r1 = sess.post(
        "https://acquirersmultiple.com/login/",
        data={
            "rcp_user_login":  AM_EMAIL,
            "rcp_user_pass":   AM_PASSWORD,
            "rcp_action":      "login",
            "rcp_redirect":    "https://acquirersmultiple.com/login/",
            "rcp_login_nonce": nonce,
        },
        timeout=30,
        allow_redirects=True,
    )
    print(f"   Login POST: {r1.status_code} | URL: {r1.url}")

    logged_in = "logout" in r1.text.lower() or "log-out" in r1.text.lower()
    print(f"   Logged in: {logged_in}")
    if not logged_in:
        soup_err = BeautifulSoup(r1.text, "html.parser")
        err = soup_err.find(class_=re.compile(r"rcp.error|rcp.notice|error"))
        if err:
            print(f"   Error: {err.get_text(strip=True)[:120]}")

    # Step 3: Screener page
    r2    = sess.get("https://acquirersmultiple.com/screener/large-cap/", timeout=30)
    soup2 = BeautifulSoup(r2.text, "html.parser")
    title = soup2.find("title")
    print(f"   Screener: {r2.status_code} | Title: {title.get_text(strip=True)[:50] if title else 'none'}")

    # Step 4: Parse ticker table
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
                    ticker = re.sub(r"[^A-Z.]", "", cells[0].get_text(strip=True).upper())
                    if re.match(r"^[A-Z]{1,5}$", ticker):
                        tickers.append(ticker)
            break

    tickers = list(dict.fromkeys(tickers))

    if not tickers:
        raise Exception("No tickers found in AM screener table")

    print(f"   ✅ AM: {len(tickers)} tickers fetched")
    if tickers:
        print(f"   Sample: {tickers[:8]}")
    return tickers


# ============================================================
# MAIN
# ============================================================

def main():
    print("=" * 50)
    print("🗄️  fetch_cache.py -- pre-run data cache")
    print("=" * 50)

    # --- DATAROMA ---
    try:
        buys = fetch_dataroma()
        cache = {
            "fetched_at": datetime.now().isoformat(),
            "buys": buys,
        }
        with open(DATAROMA_CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
        print(f"\n✅ Wrote {DATAROMA_CACHE_FILE} ({len(buys)} tickers)")
    except Exception as e:
        print(f"\n❌ Dataroma fetch failed: {e}")
        print("   main.py will attempt live fetch as fallback")

    # --- ACQUIRER'S MULTIPLE ---
    try:
        tickers = fetch_acquirers_multiple()
        cache_am = {
            "fetched_at": datetime.now().isoformat(),
            "tickers": tickers,
        }
        with open(AM_CACHE_FILE, "w") as f:
            json.dump(cache_am, f, indent=2)
        print(f"\n✅ Wrote {AM_CACHE_FILE} ({len(tickers)} tickers)")
    except Exception as e:
        print(f"\n❌ Acquirer's Multiple cache fetch failed: {e}")
        print("   main.py will use existing cache or return empty set")
        # Non-fatal -- existing am_cache.json (if any) will be used by main.py

    print("=" * 50)
    print("🗄️  fetch_cache.py complete")
    print("=" * 50)
    return 0  # Always exit 0 -- cache failures are non-fatal


if __name__ == "__main__":
    sys.exit(main())