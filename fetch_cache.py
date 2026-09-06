# ============================================================
# fetch_cache.py
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
# To add more cached sources later (MF, AM, etc.):
#   1. Add a fetch function here
#   2. Write output to a new *_cache.json file
#   3. main.py reads the file with the same TTL pattern
# ============================================================

import json
import time
import re
import sys
from datetime import datetime
import requests
from bs4 import BeautifulSoup

CACHE_FILE = "dataroma_cache.json"

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


def main():
    print("="*50)
    print("🗄️  fetch_cache.py -- pre-run data cache")
    print("="*50)

    success = False
    try:
        buys = fetch_dataroma()
        cache = {
            "fetched_at": datetime.now().isoformat(),
            "buys": buys,
        }
        with open(CACHE_FILE, "w") as f:
            json.dump(cache, f, indent=2)
        print(f"\n✅ Wrote {CACHE_FILE} ({len(buys)} tickers)")
        success = True
    except Exception as e:
        print(f"\n❌ Dataroma fetch failed: {e}")
        print("   main.py will attempt live fetch as fallback")
        # Don't exit with error -- main.py has its own fallback
        # If old cache exists, main.py will use it

    print("="*50)
    print("🗄️  fetch_cache.py complete")
    print("="*50)
    return 0  # Always exit 0 -- cache failure is non-fatal


if __name__ == "__main__":
    sys.exit(main())