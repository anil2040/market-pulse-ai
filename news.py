# ============================================================
# news.py -- News and email fetchers
# Mean Reversion Macro Insights
# ============================================================
#
# PUBLIC FUNCTIONS (called by main.py). Each returns text + a meta dict:
#   scrape_edward_jones()         -> (text, meta)
#   fetch_cnbc_email()            -> (text, meta)
#   fetch_yahoo_morning_brief()   -> (brief_text, calendar_text, meta)
#   fetch_wsj_email()             -> (text, meta)   WSJ Markets A.M.   (optional source)
#   fetch_axios_email()           -> (text, meta)   Axios Markets      (optional source)
#   fetch_yardeni_email()         -> (text, meta)   Yardeni QuickTakes (optional source)
#
#   meta = {"status": "ok" | "stale" | "missing" | "error",
#           "date":   "YYYY-MM-DD" of the REAL source (email Date header or
#                     the recap date printed on the Edward Jones page),
#           "age_days": int or None,
#           "folder": mail folder the email was found in,
#           "detail": short human text for the dashboard,
#           "words_in" / "words_kept" / "method": the input receipt (new sources),
#           "optional": True for sources whose absence is not a warning}
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
# WORDS, NOT CHARACTERS (Session 15):
#   The old fixed character caps (CNBC 2500, Yahoo 4000, then 1200 again in the
#   prompt) cut stories off at an arbitrary point. Now each newsletter is cut by
#   its SECTIONS: keep the useful part, drop ads, quote tables, sign-offs and
#   footers. If a layout changes and the section markers are not found, the whole
#   email minus its footer is used, up to SOURCE_WORD_CEILING words.
#   Calendar: 6000 chars (was 3000, which cut Friday off mid-sentence)
#
# INPUT RECEIPT:
#   Every run prints, per source, the words kept out of the words found, which
#   cutting method was used, and the first and last few words kept. The raw text
#   is NOT saved anywhere (the repo is public and some newsletters are paid).
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
from timeutil import to_mt

YAHOO_EMAIL    = (os.environ.get("YAHOO_EMAIL") or "").strip()
YAHOO_PASSWORD = (os.environ.get("YAHOO_APP_PASSWORD") or "").strip()

CALENDAR_MAX_CHARS = 6000

# Newsletters arrive on weekdays; 3 days covers a weekend or a holiday Monday.
MAX_AGE_DAYS_EMAIL   = 3
MAX_AGE_DAYS_EJ      = 4
MAX_AGE_DAYS_YARDENI = 7      # Yardeni does not write every day: newest email within a week

# Safety ceiling per source (words). Only bites when a layout changes and the
# section markers are not found, so the whole email is used.
SOURCE_WORD_CEILING = 1500
EJ_MAX_LINES        = 300     # was 120; the 120 line cap may have been cutting the recap

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


# ------------------------------------------------------------
# SECTION CUTTING (used by the newsletters)
# ------------------------------------------------------------

_EMOJI        = re.compile("[\\U0001F000-\\U0001FAFF\\u2600-\\u27BF\\u2B00-\\u2BFF\\uFE0F\\u200d]")
_URLS         = re.compile(r"(<?https?://\S+>?|\[https?://[^\]]*\])")
_NUMERIC_ONLY = re.compile("^[\\s\\u2191\\u2193\\u25b2\\u25bc+\\-\\u2212\\d.,%$()/:]+$")
_GENERIC_NOISE = re.compile(
    r"^(view in (your )?browser|view online|read in browser|read more|sponsored by.*|"
    r"presented by.*|share|unsubscribe.*|advertise.*)$", re.IGNORECASE)
_GENERIC_END  = re.compile(
    r"(unsubscribe|all rights reserved|privacy policy|manage your (email )?preferences|"
    r"update your email preferences)", re.IGNORECASE)

_BLOCK_TAGS = ["p", "div", "li", "tr", "td", "th", "table", "ul", "ol", "blockquote",
               "h1", "h2", "h3", "h4", "h5", "h6", "section", "article"]


def _tidy_line(ln):
    """Remove emoji and links, turn em/en dashes into plain hyphens, collapse spaces."""
    ln = _EMOJI.sub("", ln)
    ln = _URLS.sub("", ln)
    ln = ln.replace("\u2014", " - ").replace("\u2013", "-")
    return re.sub(r"[ \t]+", " ", ln).strip()


def _is_noise_line(ln):
    """True for lines that carry no news: numbers only, short ALL-CAPS labels, menu words."""
    if _NUMERIC_ONLY.match(ln):
        return True
    words = ln.split()
    if (len(words) <= 5 and re.search("[A-Za-z]", ln)
            and ln == ln.upper() and not re.search("[a-z]", ln)):
        return True                                   # labels like "S&P 500 FUTURES", "MARKETS"
    return bool(_GENERIC_NOISE.match(ln))


def _n_words(s):
    return len(s.split())


def _extract_sections(text, start_pats=(), end_pats=(), drop_blocks=(), drop_lines=(),
                      fallback_words=None):
    """
    Keep the useful part of a newsletter.
      start_pats : list of (compiled_regex, offset). First pattern that matches a line
                   wins; offset 0 keeps that line, 1 starts after it.
      end_pats   : compiled regexes. The EARLIEST matching line after the start ends the text.
      drop_blocks: list of (begin_regex, stop_regex, max_words). Skips from a line matching
                   begin_regex up to (not including) a line matching stop_regex, never more
                   than max_words words (sponsor blocks).
      drop_lines : compiled regexes for single lines to drop.
      fallback_words: word limit used when no end marker was found (default ceiling).
    Returns (kept_text, info) with info = {words_in, words_kept, method}.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    words_in = sum(_n_words(l) for l in lines)

    start, start_found = 0, False
    for pat, off in start_pats:
        for i, ln in enumerate(lines):
            if pat.search(ln):
                start, start_found = min(i + off, len(lines)), True
                break
        if start_found:
            break

    end, end_found, generic_end = len(lines), False, False
    for pat in end_pats:
        for i in range(start + 1, len(lines)):
            if pat.search(lines[i]):
                if i < end:
                    end, end_found = i, True
                break
    if not end_found:
        for i in range(start + 1, len(lines)):
            if _GENERIC_END.search(lines[i]):
                end, generic_end = i, True
                break

    kept = []
    skipping, skipped, stop_pat, max_w = False, 0, None, 0
    for ln in lines[start:end]:
        if skipping:
            if stop_pat.search(ln) or skipped > max_w:
                skipping = False
            else:
                skipped += _n_words(ln)
                continue
        began = False
        for begin_pat, stop, mx in drop_blocks:
            if begin_pat.search(ln):
                skipping, stop_pat, max_w, skipped = True, stop, mx, _n_words(ln)
                began = True
                break
        if began:
            continue
        if any(p.search(ln) for p in drop_lines):
            continue
        t = _tidy_line(ln)
        if not t or _is_noise_line(t):
            continue
        if kept and t == kept[-1]:
            continue                                   # CNBC repeats one intro line twice
        kept.append(t)

    limit = SOURCE_WORD_CEILING
    if not end_found and fallback_words:
        limit = min(limit, fallback_words)
    out, total, capped = [], 0, False
    for t in kept:
        w = _n_words(t)
        if total + w > limit:
            capped = True
            break
        out.append(t)
        total += w

    if start_found and end_found:
        method = "sections"
    elif start_found:
        method = "start marker found, no end marker" + (" (footer cut)" if generic_end else "")
    elif end_found:
        method = "no start marker, end marker found"
    else:
        method = "no markers, whole email" + (" (footer cut)" if generic_end else "")
    if capped:
        method += f", capped at {limit} words"
    return "\n".join(out), {"words_in": words_in, "words_kept": total, "method": method}


def _receipt(label, text, info):
    """Print what was kept (counts plus a few first/last words, never the full text)."""
    w = text.split()
    print(f"   🧾 {label}: kept {info['words_kept']} of {info['words_in']} words ({info['method']})")
    if w:
        print(f"      starts: \"{' '.join(w[:8])}\"")
        print(f"      ends:   \"{' '.join(w[-8:])}\"")


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
        lines = raw.splitlines()[:EJ_MAX_LINES]
        text  = _clean_ej("\n".join(lines))

        # Real date of the recap, printed on the page ("Monday 9/28/2026 p.m.")
        m = _EJ_DATE.search(text)
        if not m:
            print(f"   ✅ Edward Jones: {_n_words(text)} words (recap date not found on page)")
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
        print(f"   ✅ Edward Jones: {_n_words(text)} words (recap {date_str})")
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


def _find_latest(mail, sender, subject_contains=None, allow_domain_fallback=True):
    """
    Search INBOX plus any Bulk/Spam/Junk folder for the newest email from sender.
    subject_contains: only emails whose subject contains this text (one sender, many
                      newsletters, such as WSJ). More emails are checked in that case.
    allow_domain_fallback: also search by the sender's domain when the full address finds
                      nothing. Switch OFF for shared domains (ghost.io, wsj.com).
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
            needles = (sender, domain) if allow_domain_fallback else (sender,)
            for needle in needles:
                status, found = mail.search(None, f'(FROM "{needle}")')
                if status == "OK" and found and found[0]:
                    ids = found[0].split()
                    break
            how_many = 15 if subject_contains else 3
            for msg_id in ids[-how_many:]:          # newest few by arrival
                dt, subject = _header_date(mail, msg_id)
                if subject_contains and subject_contains.lower() not in subject.lower():
                    continue
                if dt and (best is None or dt > best["date"]):
                    best = {"folder": folder, "id": msg_id, "date": dt, "subject": subject}
        except Exception as e:
            print(f"   Folder {folder} search failed: {e}")
    return best


def _html_to_text(payload_bytes, charset=None):
    html = payload_bytes.decode(charset or "utf-8", errors="ignore")
    return BeautifulSoup(html, "html.parser").get_text("\n", strip=True)


def _html_to_blocks(payload_bytes, charset=None):
    """
    HTML to text keeping paragraphs together: inline pieces (links, bold) stay on
    one line and each block element (paragraph, table cell, heading) starts a new
    line. _html_to_text above splits at EVERY tag and is kept for the Yahoo
    calendar parser, which was built around that format.
    """
    html = payload_bytes.decode(charset or "utf-8", errors="ignore")
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style", "head", "title"]):
        t.decompose()
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for t in soup.find_all(_BLOCK_TAGS):
        t.insert(0, "\n")
        t.append("\n")
    return soup.get_text("")


def _body_from_message(msg, prefer_html, blocks=False):
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
            if ctype == "text/html":
                return _html_to_blocks(payload, cs) if blocks else _html_to_text(payload, cs)
            return payload.decode(cs or "utf-8", errors="ignore")
    return ""


def _posted_label(dt_utc):
    """'Sep 30' in Boise time (the UTC date can be a day later for evening emails)."""
    d = to_mt(dt_utc)
    return f"{d.strftime('%b')} {d.day}"


def _fetch_email_raw(sender, label, max_age_days=MAX_AGE_DAYS_EMAIL,
                     prefer_html=False, char_limit=2500,
                     subject_contains=None, allow_domain_fallback=True, blocks=False):
    """
    Fetch the newest email from sender (any folder) and check its real age.
    prefer_html: use the HTML part (Yahoo Brief's plain-text part is a ~1200
                 char teaser; the full newsletter incl. calendar is HTML).
    char_limit:  truncate AFTER cleaning; None = no truncation.
    subject_contains / allow_domain_fallback: see _find_latest.
    blocks:      HTML to text with paragraphs kept together (_html_to_blocks).
    Returns (text, meta). text is "" when the email is missing or too old.
    """
    print(f"\n📬 Fetching {label}...")
    if not YAHOO_EMAIL or not YAHOO_PASSWORD:
        return "", _meta("error", detail="YAHOO_EMAIL / YAHOO_APP_PASSWORD secrets not set")
    try:
        mail = imaplib.IMAP4_SSL("imap.mail.yahoo.com", 993)
        mail.login(YAHOO_EMAIL, YAHOO_PASSWORD)
        try:
            best = _find_latest(mail, sender, subject_contains, allow_domain_fallback)
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
            body = _clean_text(_body_from_message(msg, prefer_html, blocks)).strip()
            print(f"   ✅ {label}: {len(body)} chars cleaned (html={prefer_html}, "
                  f"{age} days old, folder={best['folder']})")
            if char_limit is not None:
                body = body[:char_limit]
            detail = "" if best["folder"] == "INBOX" else \
                f"arriving in your {best['folder']} folder -- mark it 'Not spam' in Yahoo Mail"
            meta = _meta("ok", dstr, age, best["folder"], detail)
            meta["posted"] = _posted_label(best["date"])
            return body, meta
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



def _C(pattern, flags=0):
    return re.compile(pattern, flags)


def fetch_cnbc_email():
    """
    Returns (CNBC Morning Squawk text, meta).
    Keeps the market line and the five numbered items. Drops the greeting, futures
    labels, "The Daily Dividend" and everything after it (credits, ads, footer).
    """
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
        text, info = _extract_sections(
            text,
            start_pats=[(_C(r"^S&P 500 futures"), 0),
                        (_C(r"five key things", re.I), 0),
                        (_C(r"^1\.\s"), 0)],
            end_pats=[_C(r"^The Daily Dividend"), _C(r"contributed to this report", re.I),
                      _C(r"Morning Squawk recommends", re.I)],
            drop_lines=[_C(r"^Follow live market updates", re.I),
                        _C(r"^Watch live on CNBC", re.I),
                        _C(r"^SEE IT IN CONTEXT", re.I)],
        )
        _receipt("CNBC Morning Squawk", text, info)
        meta.update(info)
    return text, meta


def fetch_yahoo_morning_brief():
    """
    Returns (brief_text, calendar_text, meta).
    brief_text: the opening summary plus the headline list (from "Good morning"
                up to "Market snapshot"). The long featured stories, the quote of
                the day, "Popular on Yahoo Finance" and the rest are left out.
    calendar_text: extracted earnings/economic calendar (up to CALENDAR_MAX_CHARS).
    Monday brief has the full week. Other days have the remainder of the week.
    The dashboard keeps the weekly calendar from Monday (html_builder cache).

    The FULL email is fetched (char_limit=None) because the calendar is at
    the END; the calendar is extracted BEFORE the brief text is cut.
    """
    raw, meta = _fetch_email_raw(
        "finance-morning-brief@newsletters.yahoo.net", "Yahoo Morning Brief",
        prefer_html=True, char_limit=None,
    )
    if not raw:
        print("   ⚠️  Yahoo Brief: no usable email")
        return "", "", meta

    print(f"   📧 Yahoo Brief cleaned body: {_n_words(raw)} words total")
    calendar_text = _extract_calendar(raw)
    brief_text, info = _extract_sections(
        raw,
        start_pats=[(_C(r"^Good morning", re.I), 0)],
        end_pats=[_C(r"^Market snapshot", re.I), _C(r"^Popular on Yahoo Finance", re.I)],
        fallback_words=320,
    )
    if info["words_kept"] < 150:
        # Safety net: if the headline list sits AFTER the "Market snapshot" label in some
        # layout, the first cut is too short. Try the "Powered by" line under the heat map.
        alt, info2 = _extract_sections(
            raw,
            start_pats=[(_C(r"^Good morning", re.I), 0)],
            end_pats=[_C(r"^Powered by", re.I), _C(r"^Popular on Yahoo Finance", re.I)],
            fallback_words=320,
        )
        if info2["words_kept"] > info["words_kept"]:
            brief_text, info = alt, info2
            info["method"] += " (second end marker)"
    _receipt("Yahoo Brief", brief_text, info)
    meta.update(info)
    print(f"   ✅ Yahoo Brief: {info['words_kept']} words main | {len(calendar_text)} chars calendar")
    return brief_text, calendar_text, meta


# ------------------------------------------------------------
# OPTIONAL NEWSLETTERS (WSJ, Axios, Yardeni)
# Missing or old = quietly skipped (no warning on the dashboard).
# ------------------------------------------------------------

def _fetch_optional_email(label, sender, subject_contains=None,
                          max_age_days=MAX_AGE_DAYS_EMAIL, start_pats=(), end_pats=(),
                          drop_blocks=(), drop_lines=(), fallback_words=None,
                          add_posted_label=False):
    raw, meta = _fetch_email_raw(
        sender, label, max_age_days=max_age_days, prefer_html=True, char_limit=None,
        subject_contains=subject_contains, allow_domain_fallback=False, blocks=True,
    )
    meta["optional"] = True
    if not raw:
        return "", meta
    text, info = _extract_sections(raw, start_pats, end_pats, drop_blocks, drop_lines,
                                   fallback_words)
    _receipt(label, text, info)
    meta.update(info)
    if info["words_kept"] < 40:
        print(f"   ⚠️ {label}: almost no readable text found -- not used")
        meta["status"] = "missing"
        meta["detail"] = f"{label} email found but it had almost no readable text"
        return "", meta
    if add_posted_label and meta.get("posted"):
        text = f"(Posted {meta['posted']})\n{text}"
    return text, meta


def fetch_wsj_email():
    """WSJ Markets A.M. (Spencer Jakab): the opening paragraph and the main essay."""
    return _fetch_optional_email(
        "WSJ Markets A.M.", "access@interactive.wsj.com", subject_contains="Markets A.M.",
        start_pats=[(_C(r"^Sponsored by", re.I), 1), (_C(r"^Markets A\.M\.$"), 1)],
        end_pats=[_C(r"^This is an edition of the Markets A\.M\."),
                  _C(r"^Stocks I.m Watching", re.I), _C(r"^One Big Chart", re.I)],
        drop_lines=[_C(r"^Is this email difficult to read", re.I),
                    _C(r"^Follow our live markets", re.I),
                    _C(r"^[-\s]*Last\s+Chg", re.I),
                    _C(r"^\d{1,2}/\d{1,2}/\d{4},\s*\d"),
                    _C(r"^Spencer Jakab$"),
                    _C(r"^On Second Thought", re.I),
                    _C(r"^Market-implied", re.I),
                    _C(r"^Source: CME", re.I)],
    )


def fetch_axios_email():
    """Axios Markets: the numbered stories. Sponsor blocks and the sign-off are removed."""
    return _fetch_optional_email(
        "Axios Markets", "markets@axios.com",
        start_pats=[(_C(r"^1 big thing", re.I), 0),
                    (_C(r"^By .+ and .+ \u00b7 "), 1)],
        end_pats=[_C(r"^Thanks for reading", re.I), _C(r"^Tell your friends", re.I),
                  _C(r"^Why stop here", re.I)],
        drop_blocks=[(_C(r"^A\s*M\s*E\s*S\s*S\s*A\s*G\s*E\s*F\s*R\s*O\s*M", re.I),
                      _C(r"^\d+\.\s+\S"), 140)],
        drop_lines=[_C(r"^Data:", re.I), _C(r"^Note:", re.I), _C(r"^Chart:", re.I),
                    _C(r"^By [A-Z][a-z]+ [A-Z][a-z]+$")],
    )


def fetch_yardeni_email():
    """Yardeni QuickTakes: the free part, up to the paywall. Newest email within 7 days."""
    return _fetch_optional_email(
        "Yardeni QuickTakes", "yardeni-research@ghost.io",
        max_age_days=MAX_AGE_DAYS_YARDENI,
        start_pats=[(_C(r"^YARDENI QUICKTAKES$", re.I), 1)],
        end_pats=[_C(r"upgrade to continue reading", re.I), _C(r"become a paid member", re.I)],
        drop_lines=[_C(r"^By .*\d{4}$"), _C(r"^View in browser$", re.I), _C(r"^Photo by", re.I)],
        add_posted_label=True,
    )