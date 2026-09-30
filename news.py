# ============================================================
# news.py -- News and email fetchers
# Mean Reversion Macro Insights
# ============================================================
#
# PUBLIC FUNCTIONS (called by main.py). Each returns text + a meta dict:
#   scrape_edward_jones()         -> (text, meta)
#   fetch_cnbc_email()            -> (text, meta)
#   fetch_yahoo_morning_brief()   -> (brief_text, calendar_text, meta)
#
#   meta = {"status": "ok" | "stale" | "missing" | "error",
#           "date":   "YYYY-MM-DD" of the REAL source (email Date header or
#                     the recap date printed on the Edward Jones page),
#           "age_days": int or None,
#           "folder": mail folder the email was found in,
#           "detail": short human text for the dashboard}
#
# WHY META EXISTS (Sep 2026 blind spot):
#   The CNBC email on the dashboard was 26 days old and nothing said so:
#   the fetch "worked" (it downloaded the newest email it could find), so
#   the run date was recorded as if the NEWS were fresh. Now every source
#   reports the date of the content itself. Stale content is NOT sent to
#   the AI (text comes back empty) and is flagged on the dashboard.
#
# EMAIL SEARCH:
#   Looks in INBOX and in any Bulk/Spam/Junk folder, picks the newest by
#   the email's own Date header, and opens folders read-only so your
#   emails are not marked as read.
#
# TEXT CLEANING (saves AI tokens, sends real news instead of filler):
#   Removes invisible spacer characters (Yahoo), site menu lines (Edward
#   Jones), "view in browser" boilerplate (CNBC), and legal footers.
#
# CHAR LIMITS:
#   Yahoo brief: 4000 | CNBC: 2500 | Edward Jones: 120 lines
#   Calendar: 6000 (was 3000, which cut Friday off mid-sentence)
#
# All IMAP fetches use Yahoo Mail (imap.mail.yahoo.com:993).
# Credentials from env: YAHOO_EMAIL, YAHOO_APP_PASSWORD.
# ============================================================

import os
import re
import imaplib
import email
import requests
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from bs4 import BeautifulSoup

YAHOO_EMAIL    = (os.environ.get("YAHOO_EMAIL") or "").strip()
YAHOO_PASSWORD = (os.environ.get("YAHOO_APP_PASSWORD") or "").strip()

CALENDAR_MAX_CHARS = 6000

# Newsletters arrive on weekdays; 3 days covers a weekend or a holiday Monday.
MAX_AGE_DAYS_EMAIL = 3
MAX_AGE_DAYS_EJ    = 4

# Characters newsletters use as invisible padding
_INVISIBLE = re.compile(
    "[\u034f\u200b\u200c\u200d\u200e\u200f\u2028\u2029\u2060\u2061\u2062\u2063\u2064\u00ad\ufeff]")
_SPACEY    = re.compile("[\u00a0\u2007\u2009\u202f]")


def _meta(status, date_str="", age_days=None, folder="", detail=""):
    return {"status": status, "date": date_str, "age_days": age_days,
            "folder": folder, "detail": detail}


def _clean_text(text):
    """Strip invisible characters, tidy spaces, drop blank lines."""
    text = _INVISIBLE.sub("", text)
    text = _SPACEY.sub(" ", text)
    lines = []
    for ln in text.splitlines():
        ln = re.sub(r"[ \t]+", " ", ln).strip()
        if ln:
            lines.append(ln)
    return "\n".join(lines)


# ============================================================
# EDWARD JONES
# ============================================================

_EJ_NAV = re.compile(r"(\| English$|\| French$|^Stock Market News Today \| Edward Jones$)")
_EJ_DATE = re.compile(
    r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+(\d{1,2})/(\d{1,2})/(\d{4})")


def _clean_ej(text):
    """Drop site-menu lines and cut the legal footer."""
    out = []
    for ln in text.splitlines():
        if _EJ_NAV.search(ln):
            continue
        if re.match(r"^(Investment Strategy|Diversification does not|Past performance|Back to Top)", ln):
            break
        out.append(ln)
    return "\n".join(out)


def scrape_edward_jones():
    print("\n🔍 Scraping Edward Jones...")
    url  = ("https://www.edwardjones.com/us-en/market-news-insights"
            "/stock-market-news/daily-market-recap")
    hdrs = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        resp = requests.get(url, headers=hdrs, timeout=15)
        print(f"   Status: {resp.status_code}")
        if resp.status_code != 200:
            return "", _meta("error", detail=f"Edward Jones page returned HTTP {resp.status_code}")
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        raw   = _clean_text(soup.get_text("\n", strip=True))
        lines = raw.splitlines()[:120]
        text  = _clean_ej("\n".join(lines))

        # Real date of the recap, printed on the page ("Monday 9/28/2026 p.m.")
        m = _EJ_DATE.search(text)
        if not m:
            print(f"   ✅ Edward Jones: {len(text)} chars (recap date not found on page)")
            return text, _meta("ok", detail="recap date not found on page")
        try:
            d = datetime(int(m.group(4)), int(m.group(2)), int(m.group(3)), tzinfo=timezone.utc)
        except ValueError:
            return text, _meta("ok", detail="recap date unreadable")
        age = (datetime.now(timezone.utc) - d).days
        date_str = d.strftime("%Y-%m-%d")
        if age > MAX_AGE_DAYS_EJ:
            print(f"   ⚠️ Edward Jones recap is {age} days old ({date_str})")
            return "", _meta("stale", date_str, age,
                             detail=f"latest recap on the page is from {d.strftime('%b %d')} ({age} days old)")
        print(f"   ✅ Edward Jones: {len(text)} chars (recap {date_str})")
        return text, _meta("ok", date_str, age)
    except Exception as e:
        print(f"   ❌ Edward Jones failed: {e}")
        return "", _meta("error", detail=f"Edward Jones failed: {str(e)[:80]}")


# ============================================================
# EMAIL (Yahoo IMAP)
# ============================================================

def _folder_names(mail):
    """Return all mail folder names on the account (used to find Bulk/Spam)."""
    names = []
    try:
        status, data = mail.list()
        if status != "OK":
            return names
        for raw in data:
            if not raw:
                continue
            line = raw.decode("utf-8", errors="ignore") if isinstance(raw, bytes) else str(raw)
            m = re.match(r'\((?P<flags>[^)]*)\)\s+"?(?P<delim>[^"\s]+)"?\s+(?P<name>.+)$', line)
            if m:
                names.append(m.group("name").strip().strip('"'))
    except Exception as e:
        print(f"   Folder list failed: {e}")
    return names


def _select(mail, name):
    """Open a folder READ-ONLY so emails are not marked as read."""
    arg = "INBOX" if name == "INBOX" else '"' + name.replace('"', "") + '"'
    status, _ = mail.select(arg, readonly=True)
    return status == "OK"


def _header_date(mail, msg_id):
    """Return (aware UTC datetime or None, subject) from an email's headers."""
    try:
        _, hdr = mail.fetch(msg_id, "(BODY.PEEK[HEADER.FIELDS (DATE SUBJECT)])")
        raw = hdr[0][1].decode("utf-8", errors="ignore")
        msg = email.message_from_string(raw)
        dt = parsedate_to_datetime(msg.get("Date", ""))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        subject = email.header.decode_header(msg.get("Subject", ""))[0]
        subject = subject[0].decode(subject[1] or "utf-8", errors="ignore") \
            if isinstance(subject[0], bytes) else str(subject[0])
        return dt.astimezone(timezone.utc), subject
    except Exception:
        return None, ""


def _find_latest(mail, sender):
    """
    Search INBOX plus any Bulk/Spam/Junk folder for the newest email from sender.
    Returns dict {folder, id, date, subject} or None.
    """
    names = _folder_names(mail)
    if names:
        print(f"   Mail folders: {names}")
    folders = ["INBOX"] + [n for n in names
                           if re.search(r"bulk|spam|junk", n, re.IGNORECASE)]
    domain = sender.split("@")[-1] if "@" in sender else sender
    best = None
    for folder in folders:
        try:
            if not _select(mail, folder):
                continue
            ids = []
            for needle in (sender, domain):
                status, found = mail.search(None, f'(FROM "{needle}")')
                if status == "OK" and found and found[0]:
                    ids = found[0].split()
                    break
            for msg_id in ids[-3:]:                 # newest few by arrival
                dt, subject = _header_date(mail, msg_id)
                if dt and (best is None or dt > best["date"]):
                    best = {"folder": folder, "id": msg_id, "date": dt, "subject": subject}
        except Exception as e:
            print(f"   Folder {folder} search failed: {e}")
    return best


def _html_to_text(payload_bytes, charset=None):
    html = payload_bytes.decode(charset or "utf-8", errors="ignore")
    return BeautifulSoup(html, "html.parser").get_text("\n", strip=True)


def _body_from_message(msg, prefer_html):
    """Extract readable text from an email message."""
    parts = list(msg.walk()) if msg.is_multipart() else [msg]

    def first(ctype):
        for p in parts:
            if p.get_content_type() == ctype:
                payload = p.get_payload(decode=True)
                if payload:
                    return payload, p.get_content_charset()
        return None, None

    order = ["text/html", "text/plain"] if prefer_html else ["text/plain", "text/html"]
    for ctype in order:
        payload, cs = first(ctype)
        if payload:
            return _html_to_text(payload, cs) if ctype == "text/html" \
                else payload.decode(cs or "utf-8", errors="ignore")
    return ""


def _fetch_email_raw(sender, label, max_age_days=MAX_AGE_DAYS_EMAIL,
                     prefer_html=False, char_limit=2500):
    """
    Fetch the newest email from sender (any folder) and check its real age.
    prefer_html: use the HTML part (Yahoo Brief's plain-text part is a ~1200
                 char teaser; the full newsletter incl. calendar is HTML).
    char_limit:  truncate AFTER cleaning; None = no truncation.
    Returns (text, meta). text is "" when the email is missing or too old.
    """
    print(f"\n📬 Fetching {label}...")
    if not YAHOO_EMAIL or not YAHOO_PASSWORD:
        return "", _meta("error", detail="YAHOO_EMAIL / YAHOO_APP_PASSWORD secrets not set")
    try:
        mail = imaplib.IMAP4_SSL("imap.mail.yahoo.com", 993)
        mail.login(YAHOO_EMAIL, YAHOO_PASSWORD)
        try:
            best = _find_latest(mail, sender)
            if not best:
                print(f"   ❌ No {label} emails found in any folder")
                return "", _meta("missing", detail=f"no {label} email found in any folder")

            age  = (datetime.now(timezone.utc) - best["date"]).days
            dstr = best["date"].strftime("%Y-%m-%d")
            print(f"   Newest: {best['date'].strftime('%a %d %b %Y %H:%M')} UTC | "
                  f"folder={best['folder']} | subject={best['subject'][:60]}")

            if age > max_age_days:
                print(f"   ⚠️ {label} is {age} days old -- NOT used")
                return "", _meta("stale", dstr, age, best["folder"],
                                 f"newest {label} email is from {best['date'].strftime('%b %d')} "
                                 f"({age} days old)")

            _select(mail, best["folder"])
            _, msg_data = mail.fetch(best["id"], "(BODY.PEEK[])")
            msg  = email.message_from_bytes(msg_data[0][1])
            body = _clean_text(_body_from_message(msg, prefer_html)).strip()
            print(f"   ✅ {label}: {len(body)} chars cleaned (html={prefer_html}, "
                  f"{age} days old, folder={best['folder']})")
            if char_limit is not None:
                body = body[:char_limit]
            detail = "" if best["folder"] == "INBOX" else \
                f"arriving in your {best['folder']} folder -- mark it 'Not spam' in Yahoo Mail"
            return body, _meta("ok", dstr, age, best["folder"], detail)
        finally:
            try:
                mail.logout()
            except Exception:
                pass
    except Exception as e:
        print(f"   ❌ {label} IMAP failed: {e}")
        return "", _meta("error", detail=f"{label} mail login/search failed: {str(e)[:80]}")


def _extract_calendar(body_text):
    """
    Extract the earnings/economic calendar section from Yahoo Morning Brief.
    Monday has full week Mon-Fri. Tue-Fri have that day onward.
    Returns up to CALENDAR_MAX_CHARS of calendar text, or empty string.

    Yahoo varies its header phrasing. Patterns tried in order:
      - "Earnings and economic calendar" (most common)
      - "Earnings & economic calendar"   (ampersand variant)
      - "Economic and earnings calendar" (reversed order)
      - "Economic calendar"             (economy-only weeks)
      - "Earnings calendar"             (earnings-only weeks)
      - "The week ahead"                (narrative opener)
      - "Week ahead"                    (shorter form)
      - Bare weekday names at line start (last resort: Mon/Tue etc.)

    IMPORTANT -- use LAST match, not first:
      Yahoo sometimes uses the calendar header phrase as an article title earlier
      in the email (e.g. "The earnings and economic calendar is back in the
      driver's seat"). re.search() would latch onto that early occurrence and
      start extracting article body text, missing the actual Mon-Fri data
      which is always near the END of the email.
      Using re.finditer() + [-1] ensures we always anchor to the actual section.
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
        # Use the LAST match -- the actual calendar section is always at the END
        # of the email. Earlier matches are article titles, not data.
        matches = list(re.finditer(pattern, body_text, re.IGNORECASE))
        if matches:
            m = matches[-1]
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
    # Note: BeautifulSoup inserts newlines inside <a> tags so earnings entries
    # are fragmented across lines. _parse_calendar_into_days handles this
    # directly -- do NOT pre-process with regex here as it corrupts day boundaries.
    calendar_text = re.sub(r"\n{3,}", "\n\n", calendar_text)
    print(f"   📅 Calendar extracted: {len(calendar_text)} chars")
    if len(calendar_text) < 80:
        # Print it so we can see what went wrong
        print(f"   📅 Calendar content (short): {repr(calendar_text)}")
    return calendar_text[:CALENDAR_MAX_CHARS]



def fetch_cnbc_email():
    """Returns (CNBC Morning Squawk text, meta)."""
    text, meta = _fetch_email_raw(
        "morningsquawk@response.cnbc.com", "CNBC Morning Squawk",
        char_limit=None,
    )
    if text:
        drop = re.compile(
            r"^(VIEW IN BROWSER|\||CNBC NEWSLETTERS|Data as of .*|Think a friend.*|Share|this link|"
            r"with them to sign up\.|DOW|S&P 500|NASDAQ 100|FUTURES|[+-]?\d+\.\d+%)$",
            re.IGNORECASE)
        text = "\n".join(ln for ln in text.splitlines() if not drop.match(ln.strip()))
        text = text[:2500]
    return text, meta


def fetch_yahoo_morning_brief():
    """
    Returns (brief_text, calendar_text, meta).
    brief_text: first 4000 chars of the cleaned brief.
    calendar_text: extracted earnings/economic calendar (up to CALENDAR_MAX_CHARS).
    Monday brief has the full week. Other days have the remainder of the week.

    The FULL email is fetched (char_limit=None) because the calendar is at
    the END; brief_text is truncated only AFTER calendar extraction.
    """
    raw, meta = _fetch_email_raw(
        "finance-morning-brief@newsletters.yahoo.net", "Yahoo Morning Brief",
        prefer_html=True, char_limit=None,
    )
    if not raw:
        print("   ⚠️  Yahoo Brief: no usable email")
        return "", "", meta

    print(f"   📧 Yahoo Brief cleaned body: {len(raw)} chars total")
    calendar_text = _extract_calendar(raw)
    brief_text    = raw[:4000].strip()
    print(f"   ✅ Yahoo Brief: {len(brief_text)} chars main | {len(calendar_text)} chars calendar")
    return brief_text, calendar_text, meta