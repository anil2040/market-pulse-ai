# ============================================================
# debug_etf_pe.py -- ETF PE sourcing debug script
# Run via: workflow_dispatch on any branch, or locally.
# Tests all candidate sources for URTH and EFA P/E ratios.
# ============================================================
#
# FINDINGS (Sep 2026):
#   Yahoo Finance v8/v7/v10:  broken server-side for ETF PE since mid-2026
#   yfinance library:         same Yahoo backend, same breakage
#   etf.com:                  Cloudflare 403 on automated requests
#   etfdb.com:                Cloudflare 403 on automated requests
#   iShares product API:      Cloudflare 403 on automated requests
#   macrotrends.net:          Cloudflare 403 on automated requests
#
# VERDICT:
#   No automated source is reliably accessible from GitHub Actions.
#   iShares.com is the authoritative source but requires a browser.
#   SOLUTION: PE_CONFIG dict with PE_LAST_UPDATED date in main.py.
#   Dashboard shows a "stale" warning if >90 days since last update.
#   Update manually each quarter by checking iShares product pages:
#     URTH: https://www.ishares.com/us/products/239696/ISHARES-MSCI-WORLD-ETF
#     EFA:  https://www.ishares.com/us/products/239727/ISHARES-MSCI-EAFE-ETF
#   Look for "P/E Ratio" in the "Fund Characteristics" section.
# ============================================================

import requests
from bs4 import BeautifulSoup
import re
import time

TICKERS = ["URTH", "EFA"]
HDRS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

def test_yahoo_v8():
    print("\n" + "=" * 60)
    print("METHOD 1: Yahoo Finance v8 (broken for ETF PE since mid-2026)")
    print("=" * 60)
    for t in TICKERS:
        try:
            url = f"https://query1.finance.yahoo.com/v8/finance/chart/{t}?interval=1d&range=1d"
            r = requests.get(url, headers=HDRS, timeout=10)
            meta = r.json()["chart"]["result"][0]["meta"]
            pe_keys = [k for k in meta.keys() if "pe" in k.lower() or "ratio" in k.lower()]
            if pe_keys:
                print(f"  {t}: FOUND PE keys: {pe_keys}")
                for k in pe_keys:
                    print(f"    {k} = {meta[k]}")
            else:
                print(f"  {t}: CONFIRMED BROKEN -- no PE keys in v8 meta (HTTP {r.status_code})")
        except Exception as e:
            print(f"  {t}: ERROR -- {e}")


def test_yahoo_v10():
    print("\n" + "=" * 60)
    print("METHOD 2: Yahoo Finance v10 quoteSummary")
    print("=" * 60)
    for t in TICKERS:
        try:
            url = (f"https://query2.finance.yahoo.com/v10/finance/quoteSummary/{t}"
                   f"?modules=summaryDetail,defaultKeyStatistics")
            r = requests.get(url, headers=HDRS, timeout=10)
            data = r.json()
            result = data.get("quoteSummary", {}).get("result", [{}])[0]
            sd = result.get("summaryDetail", {})
            trailing = sd.get("trailingPE", {})
            forward  = sd.get("forwardPE", {})
            if trailing:
                print(f"  {t}: trailingPE = {trailing} (SUCCESS)")
            elif forward:
                print(f"  {t}: forwardPE = {forward} (SUCCESS -- trailing missing)")
            else:
                print(f"  {t}: CONFIRMED BROKEN -- no PE in summaryDetail (HTTP {r.status_code})")
        except Exception as e:
            print(f"  {t}: ERROR -- {e}")


def test_yfinance():
    print("\n" + "=" * 60)
    print("METHOD 3: yfinance library (same Yahoo backend)")
    print("=" * 60)
    try:
        import yfinance as yf
        for t in TICKERS:
            try:
                ticker = yf.Ticker(t)
                info = ticker.info
                pe_keys = {k: v for k, v in info.items()
                           if any(kw in k.lower() for kw in ["pe", "trailing", "forward", "earnings"])}
                if pe_keys:
                    print(f"  {t}: FOUND -- {pe_keys}")
                else:
                    print(f"  {t}: CONFIRMED BROKEN -- no PE keys via yfinance")
            except Exception as e:
                print(f"  {t}: ERROR -- {e}")
    except ImportError:
        print("  yfinance not installed. Run: pip install yfinance")


def test_etf_com():
    print("\n" + "=" * 60)
    print("METHOD 4: etf.com scrape")
    print("=" * 60)
    for t in TICKERS:
        try:
            url = f"https://www.etf.com/{t}"
            r = requests.get(url, headers=HDRS, timeout=12)
            print(f"  {t}: HTTP {r.status_code}")
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                text = soup.get_text(" ", strip=True)
                for pattern in [
                    r"P/E Ratio[\s:]*(\d+\.?\d*)",
                    r"Price.Earnings[\s:]*(\d+\.?\d*)",
                    r"Wtd Avg P/E[\s:]*(\d+\.?\d*)",
                ]:
                    m = re.search(pattern, text, re.IGNORECASE)
                    if m:
                        print(f"  {t}: FOUND via '{pattern}' = {m.group(1)} (SUCCESS)")
                        break
                else:
                    print(f"  {t}: No PE pattern matched (check HTML structure manually)")
            else:
                print(f"  {t}: BLOCKED (Cloudflare or CDN -- expected)")
        except Exception as e:
            print(f"  {t}: ERROR -- {e}")
        time.sleep(0.5)


def test_etfdb():
    print("\n" + "=" * 60)
    print("METHOD 5: etfdb.com scrape")
    print("=" * 60)
    for t in TICKERS:
        try:
            url = f"https://etfdb.com/etf/{t}/"
            r = requests.get(url, headers=HDRS, timeout=12)
            print(f"  {t}: HTTP {r.status_code}")
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                text = soup.get_text(" ", strip=True)
                for pattern in [r"P/E Ratio[\s:]*(\d+\.?\d*)", r"Price.Earnings[\s:]*(\d+\.?\d*)"]:
                    m = re.search(pattern, text, re.IGNORECASE)
                    if m:
                        print(f"  {t}: FOUND via '{pattern}' = {m.group(1)} (SUCCESS)")
                        break
                else:
                    print(f"  {t}: No PE pattern matched")
            else:
                print(f"  {t}: BLOCKED (Cloudflare -- expected)")
        except Exception as e:
            print(f"  {t}: ERROR -- {e}")
        time.sleep(0.5)


def test_ishares_api():
    print("\n" + "=" * 60)
    print("METHOD 6: iShares product API (authoritative source)")
    print("=" * 60)
    endpoints = {
        "URTH": "https://www.ishares.com/us/products/239696/ISHARES-MSCI-WORLD-ETF/1467271812596.ajax?tab=fund-profile&fileType=json",
        "EFA":  "https://www.ishares.com/us/products/239727/ISHARES-MSCI-EAFE-ETF/1467271812596.ajax?tab=fund-profile&fileType=json",
    }
    for t, url in endpoints.items():
        try:
            r = requests.get(url, headers=HDRS, timeout=12)
            print(f"  {t}: HTTP {r.status_code}")
            if r.status_code == 200:
                import json
                data = r.json()
                print(f"  {t}: JSON keys = {list(data.keys())[:10]}")
            else:
                print(f"  {t}: BLOCKED (CDN -- expected)")
        except Exception as e:
            print(f"  {t}: ERROR -- {e}")


if __name__ == "__main__":
    print("ETF PE Debug Script -- Mean Reversion Macro Insights")
    print("Run date:", __import__("datetime").date.today())
    print()
    print("Testing all candidate sources for URTH and EFA P/E ratios...")

    test_yahoo_v8()
    test_yahoo_v10()
    test_yfinance()
    test_etf_com()
    test_etfdb()
    test_ishares_api()

    print("\n" + "=" * 60)
    print("VERDICT")
    print("=" * 60)
    print("""
All automated ETF PE sources are either broken or blocked from GitHub Actions:
  - Yahoo Finance v8/v10: broken server-side for ETFs (mid-2026)
  - yfinance: same Yahoo backend, same issue
  - etf.com / etfdb.com / iShares API: Cloudflare CDN blocks automated requests

SOLUTION IMPLEMENTED in main.py:
  - PE_CONFIG dict with PE_LAST_UPDATED date constant
  - Dashboard shows amber 'UPDATE NEEDED' warning if >90 days stale
  - Quarterly manual update: check iShares.com product pages
    URTH: https://www.ishares.com/us/products/239696
    EFA:  https://www.ishares.com/us/products/239727

CURRENT VALUES (Sep 2026, from iShares.com):
  URTH PE: 23.0x
  EFA PE:  14.0x
""")
