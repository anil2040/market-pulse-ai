# ============================================================
# news.py -- News and email fetchers
# Mean Reversion Macro Insights
# ============================================================
#
# PUBLIC FUNCTIONS (called by main.py):
#   scrape_edward_jones()         -> str
#   fetch_cnbc_email()            -> str
#   fetch_yahoo_morning_brief()   -> (brief_str, calendar_str)
#
# WHAT THIS COVERS:
#   - Edward Jones daily market recap (web scrape)
#   - CNBC Morning Squawk (Yahoo IMAP SSL)
#   - Yahoo Finance Morning Brief (Yahoo IMAP SSL)
#     Returns TWO values: the main brief text AND the extracted
#     earnings/economic calendar section.
#     Monday brief has the full week Mon-Fri.
#     Tue-Fri briefs have that day onward.
#     Calendar shown in its own "Week Ahead" card in the dashboard.
#
# NOTE: McClellan Oscillator removed Sep 2026 -- paid teaser only.
#
# CHAR LIMITS:
#   Yahoo brief: 4000 chars (raised from 2000)
#   CNBC: 2500 chars (unchanged)
#   Calendar: up to 3000 chars (separate from brief limit)
#
# All IMAP fetches use Yahoo Mail (imap.mail.yahoo.com:993).
# Credentials from env: YAHOO_EMAIL, YAHOO_APP_PASSWORD.
# ============================================================

import os
import re
import imaplib
import email
import requests
from bs4 import BeautifulSoup

YAHOO_EMAIL    = os.environ.get("YAHOO_EMAIL")
YAHOO_PASSWORD = os.environ.get("YAHOO_APP_PASSWORD")


def scrape_edward_jones():
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


def _fetch_email_raw(sender, label, char_limit=2500, prefer_html=False):
    """
    Fetch the latest email from sender via IMAP.
    char_limit: truncate body to this many chars. Pass None to return the full body.
    prefer_html: always parse the HTML MIME part instead of text/plain.
                 Yahoo Brief has a ~1200-char plain-text teaser for spam filters;
                 the full newsletter content (including calendar) is HTML-only.
    Returns the body string, or an error string starting with label name on failure.
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

        if prefer_html:
            # Yahoo Brief: plain-text part is a ~1200-char teaser only.
            # Full content including the calendar section is in text/html.
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
        else:
            # Default: prefer plain text, fall back to HTML
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                        break

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
        body = body.strip()
        print(f"   ✅ {label}: {len(body)} chars (full body, html={prefer_html})")
        # Apply char limit AFTER logging full size -- None means no truncation
        if char_limit is not None:
            body = body[:char_limit]
        return body

    except Exception as e:
        print(f"   ❌ {label} IMAP failed: {e}")
        return f"{label} unavailable today."


def _extract_calendar(body_text):
    """
    Extract the earnings/economic calendar section from Yahoo Morning Brief.
    Monday has full week Mon-Fri. Tue-Fri have that day onward.
    Returns up to 3000 chars of calendar text, or empty string.

    Yahoo varies its header phrasing. Patterns tried in order:
      - "Earnings and economic calendar" (most common)
      - "Earnings & economic calendar"   (ampersand variant)
      - "Economic and earnings calendar" (reversed order)
      - "Economic calendar"             (economy-only weeks)
      - "Earnings calendar"             (earnings-only weeks)
      - "The week ahead"                (narrative opener)
      - "Week ahead"                    (shorter form)
      - Bare weekday names at line start (last resort: Mon/Tue etc.)
    """
    start_patterns = [
        r"Earnings and economic calendar",
        r"Earnings\s*&\s*economic calendar",
        r"Economic and earnings calendar",
        r"Economic calendar",
        r"Earnings calendar",
        r"The week ahead",
        r"Week ahead",
    ]
    end_patterns = [
        r"If you like what we do",
        r"Privacy Policy",
        r"Unsubscribe",
        r"Yahoo Finance App",
        r"Download now",
        r"sign up right here",
        r"Follow Yahoo Finance",
        r"Get the latest",
    ]

    start_idx = None
    matched_pattern = None
    for pattern in start_patterns:
        m = re.search(pattern, body_text, re.IGNORECASE)
        if m:
            start_idx = m.start()
            matched_pattern = pattern
            break

    if start_idx is None:
        # Last resort: look for a bare weekday line that suggests a calendar block
        m = re.search(r"(?m)^(Monday|Tuesday|Wednesday|Thursday|Friday)\b", body_text)
        if m:
            # Only use this if there's at least 200 chars of content after it
            candidate = m.start()
            if len(body_text) - candidate > 200:
                start_idx = candidate
                matched_pattern = "weekday line fallback"

    if start_idx is None:
        print("   📅 Calendar: no section header found in brief")
        # Debug: show the last 500 chars so we can see what the brief ends with
        tail = body_text[-500:].replace("\n", " | ")
        print(f"   📅 Brief tail (500 chars): ...{tail}")
        return ""

    print(f"   📅 Calendar: matched pattern '{matched_pattern}' at char {start_idx}")

    end_idx = len(body_text)
    for pattern in end_patterns:
        m = re.search(pattern, body_text[start_idx:], re.IGNORECASE)
        if m:
            candidate = start_idx + m.start()
            if candidate < end_idx:
                end_idx = candidate

    calendar_text = body_text[start_idx:end_idx].strip()
    calendar_text = re.sub(r"\n{3,}", "\n\n", calendar_text)
    print(f"   📅 Calendar extracted: {len(calendar_text)} chars")
    if len(calendar_text) < 80:
        # Print it so we can see what went wrong
        print(f"   📅 Calendar content (short): {repr(calendar_text)}")
    return calendar_text[:3000]


def fetch_cnbc_email():
    """Returns CNBC Morning Squawk text."""
    return _fetch_email_raw(
        "morningsquawk@response.cnbc.com",
        "CNBC Morning Squawk",
        char_limit=2500,
    )


def fetch_yahoo_morning_brief():
    """
    Returns (brief_text, calendar_text) tuple.
    brief_text: first 4000 chars of the morning brief body.
    calendar_text: extracted earnings/economic calendar section (up to 3000 chars).
    Monday brief has full week. Other days have remainder of week.

    IMPORTANT: fetch with char_limit=None so the FULL email body is retrieved.
    The calendar section is at the END of the email -- any char limit applied
    before extraction would silently cut it off.
    brief_text is truncated to 4000 chars AFTER calendar extraction.
    """
    raw = _fetch_email_raw(
        "finance-morning-brief@newsletters.yahoo.net",
        "Yahoo Morning Brief",
        char_limit=None,    # fetch full body -- calendar is at the END
        prefer_html=True,   # plain-text part is a ~1200-char teaser only;
                            # full newsletter (incl. calendar) is in text/html
    )

    # Detect IMAP failure: _fetch_email_raw returns an error string starting
    # with the label name when no email is found or login fails.
    if not raw or raw.startswith("Yahoo Morning Brief unavailable") \
               or raw.startswith("Yahoo Morning Brief not found"):
        print("   ⚠️  Yahoo Brief: fetch failed or no email found")
        return "", ""

    print(f"   📧 Yahoo Brief raw body: {len(raw)} chars total")

    # Extract calendar from FULL body first, then truncate brief separately
    calendar_text = _extract_calendar(raw)
    brief_text    = raw[:4000].strip()

    print(f"   ✅ Yahoo Brief: {len(brief_text)} chars main | {len(calendar_text)} chars calendar")
    return brief_text, calendar_text