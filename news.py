# ============================================================
# news.py -- News and email fetchers
# Mean Reversion Macro Insights
# ============================================================
#
# PUBLIC FUNCTIONS (called by main.py):
#   scrape_edward_jones()      -> str
#   fetch_cnbc_email()         -> str
#   fetch_yahoo_morning_brief()-> str
#   fetch_mcoscillator_email() -> str
#
# WHAT THIS COVERS:
#   - Edward Jones daily market recap (web scrape)
#   - CNBC Morning Squawk (Yahoo IMAP SSL)
#   - Yahoo Finance Morning Brief (Yahoo IMAP SSL)
#   - McClellan Oscillator weekly (Yahoo IMAP SSL)
#
# All IMAP fetches use Yahoo Mail (imap.mail.yahoo.com:993).
# Credentials from env: YAHOO_EMAIL, YAHOO_APP_PASSWORD.
# ============================================================

import os
import imaplib
import email
import requests
from bs4 import BeautifulSoup

YAHOO_EMAIL    = os.environ.get("YAHOO_EMAIL")
YAHOO_PASSWORD = os.environ.get("YAHOO_APP_PASSWORD")


# ============================================================
# EDWARD JONES WEB SCRAPE
# ============================================================

def scrape_edward_jones():
    """
    Scrape the Edward Jones daily market recap page.
    Returns plain text (up to ~120 lines worth).
    """
    print("\n🔍 Scraping Edward Jones...")
    url  = ("https://www.edwardjones.com/us-en/market-news-insights"
            "/stock-market-news/daily-market-recap")
    hdrs = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.get(url, headers=hdrs, timeout=15)
        print(f"   Status: {resp.status_code}")
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        lines = [l.strip() for l in soup.get_text("\n", strip=True).splitlines()
                 if l.strip()]
        text  = "\n".join(lines[:120])
        print(f"   ✅ Edward Jones: {len(text)} chars")
        return text
    except Exception as e:
        print(f"   ❌ Edward Jones failed: {e}")
        return "Edward Jones data unavailable today."


# ============================================================
# YAHOO IMAP EMAIL FETCHER
# ============================================================

def _fetch_email(sender, label, char_limit=2500):
    """
    Fetch the latest email from a specific sender via Yahoo IMAP SSL.
    Falls back to domain search if exact sender address yields nothing.
    Returns plain text body up to char_limit characters.
    """
    print(f"\n📬 Fetching {label}...")
    try:
        mail = imaplib.IMAP4_SSL("imap.mail.yahoo.com", 993)
        mail.login(YAHOO_EMAIL, YAHOO_PASSWORD)
        mail.select("INBOX")

        status, messages = mail.search(None, f'(FROM "{sender}")')
        if status != "OK" or not messages[0]:
            domain = sender.split("@")[-1] if "@" in sender else sender
            status, messages = mail.search(None, f'(FROM "{domain}")')
        if status != "OK" or not messages[0]:
            print(f"   ❌ No {label} emails found")
            mail.logout()
            return f"{label} not found today."

        latest = messages[0].split()[-1]

        _, hdr = mail.fetch(latest, "(BODY[HEADER.FIELDS (FROM SUBJECT DATE)])")
        if hdr and hdr[0] and hdr[0][1]:
            for line in hdr[0][1].decode("utf-8", errors="ignore").strip().splitlines()[:4]:
                if line.strip():
                    print(f"   {line.strip()}")

        _, msg_data = mail.fetch(latest, "(RFC822)")
        msg  = email.message_from_bytes(msg_data[0][1])
        body = ""

        # Prefer plain text part
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                    break

        # Fall back to HTML -> text
        if not body:
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/html":
                        body = BeautifulSoup(
                            part.get_payload(decode=True).decode("utf-8", errors="ignore"),
                            "html.parser"
                        ).get_text("\n", strip=True)
                        break
            else:
                body = BeautifulSoup(
                    msg.get_payload(decode=True).decode("utf-8", errors="ignore"),
                    "html.parser"
                ).get_text("\n", strip=True)

        mail.logout()
        body = body[:char_limit].strip()
        print(f"   ✅ {label}: {len(body)} chars")
        return body

    except Exception as e:
        print(f"   ❌ {label} IMAP failed: {e}")
        return f"{label} unavailable today."


# ============================================================
# PUBLIC EMAIL WRAPPERS
# ============================================================

def fetch_cnbc_email():
    return _fetch_email(
        "morningsquawk@response.cnbc.com",
        "CNBC Morning Squawk",
        char_limit=2500,
    )


def fetch_yahoo_morning_brief():
    return _fetch_email(
        "finance-morning-brief@newsletters.yahoo.net",
        "Yahoo Morning Brief",
        char_limit=2000,
    )


def fetch_mcoscillator_email():
    return _fetch_email(
        "admin@mcoscillator.com",
        "McClellan Oscillator",
        char_limit=1500,
    )
