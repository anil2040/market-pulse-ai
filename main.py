# ============================================================
# MarketPulse AI - main.py
# What this file does:
#   1. Scrapes Edward Jones daily market recap
#   2. Reads your CNBC Morning Squawk email via IMAP
#   3. Sends both to Gemini AI for synthesis
#   4. Builds a beautiful HTML dashboard (index.html)
#   5. Emails the briefing to your Yahoo inbox
# ============================================================

# --- IMPORTS: These are Python's toolbox ---
# Think of imports like apps on your phone.
# You don't build a calculator from scratch -- you just open the app.

import os           # Talks to the operating system (reads our secret keys)
import imaplib      # IMAP protocol -- lets Python log into email and READ messages
import smtplib      # SMTP protocol -- lets Python SEND emails
import email        # Helps decode email messages into readable text
from email.mime.multipart import MIMEMultipart   # Builds emails with multiple parts
from email.mime.text import MIMEText             # Adds text/HTML content to emails
from datetime import datetime   # So we can stamp our briefing with today's date
import requests                 # Makes web requests -- how we scrape Edward Jones
from bs4 import BeautifulSoup   # Parses HTML -- finds the text we want in a webpage
import google.generativeai as genai  # The Gemini AI library

# --- CONFIGURATION: Reading our secrets ---
# Remember those secrets we stored in GitHub?
# os.environ.get() reaches into the GitHub vault and retrieves them.
# On your LOCAL computer these would be empty -- they only exist in GitHub's environment.

GEMINI_API_KEY   = os.environ.get("GEMINI_API_KEY")
YAHOO_EMAIL      = os.environ.get("YAHOO_EMAIL")
YAHOO_PASSWORD   = os.environ.get("YAHOO_APP_PASSWORD")

print("✅ Configuration loaded")
print(f"📧 Email configured: {YAHOO_EMAIL}")
# ============================================================
# STEP 1: SCRAPE EDWARD JONES
# ============================================================
# What is scraping? When you visit a website, your browser
# downloads the page's HTML (a text file full of tags like
# <p>, <div>, <h1>) and displays it visually.
# We're doing the same thing but instead of displaying it,
# we extract just the text we want. No browser needed!

def scrape_edward_jones():
    print("\n🔍 Scraping Edward Jones Daily Market Recap...")
    
    url = "https://www.edwardjones.com/us-en/market-news-insights/stock-market-news/daily-market-recap"
    
    # Headers make our request look like a real browser visit.
    # Some websites block requests that don't have these.
    # Think of it as wearing the right outfit to get into a club.
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        # requests.get() = "go fetch this webpage"
        # timeout=15 = "give up if it takes more than 15 seconds"
        response = requests.get(url, headers=headers, timeout=15)
        
        # status_code 200 = success (like HTTP "thumbs up")
        # You've seen 404 before -- that means "not found"
        # 200 means "here's your page!"
        print(f"   Edward Jones status code: {response.status_code}")
        
        # BeautifulSoup parses the raw HTML into something
        # we can search through intelligently
        soup = BeautifulSoup(response.text, "html.parser")
        
        # Remove navigation menus, footers, ads -- junk we don't want
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        
        # .get_text() pulls all visible text from what's left
        # strip=True removes extra whitespace
        text = soup.get_text(separator="\n", strip=True)
        
        # Clean up blank lines
        lines = [line for line in text.splitlines() if line.strip()]
        clean_text = "\n".join(lines[:150])  # First 150 lines is plenty
        
        print(f"   ✅ Edward Jones: captured {len(clean_text)} characters")
        return clean_text
        
    except Exception as e:
        # If ANYTHING goes wrong, we don't crash the whole script.
        # We just return an error message and keep going.
        print(f"   ❌ Edward Jones scrape failed: {e}")
        return "Edward Jones data unavailable today."


# ============================================================
# STEP 2: FETCH CNBC EMAIL VIA IMAP
# ============================================================
# IMAP (Internet Message Access Protocol) lets a program
# LOG INTO your email account and READ messages.
# It's the same protocol your Outlook or Gmail app uses
# behind the scenes -- we're just doing it with Python code!

def fetch_cnbc_email():
    print("\n📬 Connecting to Yahoo Mail via IMAP...")
    
    try:
        mail = imaplib.IMAP4_SSL("imap.mail.yahoo.com", 993)
        mail.login(YAHOO_EMAIL, YAHOO_PASSWORD)
        print("   ✅ Logged into Yahoo Mail")
        
        mail.select("INBOX")
        status, messages = mail.search(None, '(FROM "morningsquawk@response.cnbc.com")')
        
        if status != "OK" or not messages[0]:
            print("   ⚠️ No CNBC emails found")
            return "CNBC Morning Squawk not found in inbox today."
        
        email_ids = messages[0].split()
        latest_id = email_ids[-1]
        print(f"   Found {len(email_ids)} CNBC emails, reading latest...")
        
        status, msg_data = mail.fetch(latest_id, "(RFC822)")
        raw_email = msg_data[0][1]
        msg = email.message_from_bytes(raw_email)
        
        body = ""
        
        # Try plain text first
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                    break
        
        # If no plain text, fall back to HTML and strip tags
        if not body:
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/html":
                        html_body = part.get_payload(decode=True).decode("utf-8", errors="ignore")
                        body = BeautifulSoup(html_body, "html.parser").get_text(separator="\n", strip=True)
                        break
            else:
                raw = msg.get_payload(decode=True).decode("utf-8", errors="ignore")
                body = BeautifulSoup(raw, "html.parser").get_text(separator="\n", strip=True)
        
        body = body[:3000].strip()
        print(f"   ✅ CNBC email captured: {len(body)} characters")
        
        mail.logout()
        return body
        
    except Exception as e:
        print(f"   ❌ IMAP fetch failed: {e}")
        return "CNBC Morning Squawk unavailable today."


# ============================================================
# STEP 3: GEMINI AI SYNTHESIS
# ============================================================
# This is where the magic happens!
# We take both text sources and ask Gemini to synthesize them
# into one clean executive briefing.
# The "prompt" is our instruction to the AI -- like a very
# precise question. Prompt engineering is a real skill!

def synthesize_with_gemini(edward_jones_text, cnbc_text):
    print("\n🤖 Sending to Gemini AI for synthesis...")
    
    try:
        # Initialize Gemini with our API key
        genai.configure(api_key=GEMINI_API_KEY)
        
        # gemini-2.5-flash = fast, capable, free tier friendly
        model = genai.GenerativeModel("gemini-3.6-flash")
        
        # The prompt -- this is our instruction to Gemini.
        # Notice how structured and specific it is.
        # Vague prompts = vague answers. Specific prompts = gold.
        prompt = f"""
You are a sharp financial analyst preparing a pre-market morning briefing 
for a retail investor who makes stock investing decisions.

Synthesize the two sources below into ONE clean, structured briefing.
Be concise, specific, and actionable. No fluff.

Format your response with these exact sections:
1. MARKET SUMMARY (2-3 sentences: what happened yesterday, overall tone)
2. KEY MOVES (bullet points: major index moves, notable sector moves)
3. MACRO & NEWS (bullet points: Fed news, economic data, major headlines)
4. EARNINGS HIGHLIGHTS (bullet points: any notable earnings from either source)
5. MORNING OUTLOOK (2-3 sentences: what to watch today, overall sentiment)

--- SOURCE 1: EDWARD JONES DAILY RECAP ---
{edward_jones_text}

--- SOURCE 2: CNBC MORNING SQUAWK EMAIL ---
{cnbc_text}
"""
        
        response = model.generate_content(prompt)
        briefing = response.text
        
        print(f"   ✅ Gemini synthesis complete: {len(briefing)} characters")
        return briefing
        
    except Exception as e:
        print(f"   ❌ Gemini synthesis failed: {e}")
        return "AI synthesis unavailable today. Please check source data manually."


# ============================================================
# STEP 4: BUILD HTML DASHBOARD
# ============================================================
# index.html is the webpage GitHub Pages will host.
# We're building it programmatically -- Python writes the HTML!
# This is called "templating" -- combining a fixed design
# with dynamic data that changes every day.

def build_html(briefing_text, ej_text, cnbc_text):
    print("\n🎨 Building HTML dashboard...")

    today     = datetime.now().strftime("%A, %B %d, %Y")
    now       = datetime.now().strftime("%I:%M %p UTC")

    sections = {
        "MARKET SUMMARY":   "",
        "KEY MOVES":        "",
        "MACRO & NEWS":     "",
        "EARNINGS":         "",
        "MORNING OUTLOOK":  "",
    }
    current = None
    for line in briefing_text.splitlines():
        upper = line.upper()
        if "MARKET SUMMARY"  in upper: current = "MARKET SUMMARY";  continue
        if "KEY MOVES"       in upper: current = "KEY MOVES";        continue
        if "MACRO"           in upper: current = "MACRO & NEWS";     continue
        if "EARNINGS"        in upper: current = "EARNINGS";         continue
        if "MORNING OUTLOOK" in upper: current = "MORNING OUTLOOK";  continue
        if current:
            sections[current] += line + "\n"

    def fmt(raw):
        import re
        html = ""
        for line in raw.strip().splitlines():
            line = line.strip()
            if not line:
                continue
            line = re.sub(r"^\*+\s*", "", line)
            line = re.sub(r"^-+\s*",  "", line)
            line = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", line)
            if ":" in line[:60]:
                parts = line.split(":", 1)
                html += f'<div class="bullet"><span class="label">{parts[0].strip()}:</span>{parts[1]}</div>'
            else:
                html += f'<div class="bullet">{line}</div>'
        return html or "<p>No data available.</p>"

    def plain(raw):
        lines = [l.strip() for l in raw.strip().splitlines() if l.strip()]
        return " ".join(lines[:60])

    s  = sections
    ej = plain(ej_text[:1200])
    cb = plain(cnbc_text[:1200])

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>MarketPulse AI · {today}</title>
<style>
  :root {{
    --blue:   #1a56db;
    --green:  #057a55;
    --red:    #c81e1e;
    --amber:  #b45309;
    --ink:    #111928;
    --muted:  #6b7280;
    --border: #e5e7eb;
    --bg:     #f9fafb;
    --card:   #ffffff;
  }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{
    font-family: 'Segoe UI', system-ui, sans-serif;
    background: var(--bg);
    color: var(--ink);
    padding: 0 0 60px;
  }}
  .hero {{
    background: linear-gradient(135deg, #1e3a5f 0%, #1a56db 100%);
    color: #fff;
    padding: 36px 24px 28px;
    text-align: center;
  }}
  .hero h1 {{ font-size:2rem; letter-spacing:3px; font-weight:800; }}
  .hero .sub {{ opacity:.85; margin-top:6px; font-size:.95rem; }}
  .hero .ts  {{ opacity:.65; margin-top:4px; font-size:.8rem; }}
  .ticker {{
    background:#1e3a5f;
    color:#93c5fd;
    font-size:.78rem;
    padding:7px 20px;
    letter-spacing:.5px;
    display:flex;
    gap:28px;
    flex-wrap:wrap;
    justify-content:center;
  }}
  .ticker span {{ color:#fff; font-weight:600; }}
  .container {{ max-width:1100px; margin:32px auto; padding:0 20px; }}
  .grid-2 {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; }}
  .card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 22px 24px;
    box-shadow: 0 1px 4px rgba(0,0,0,.06);
  }}
  .card h2 {{
    font-size: .7rem;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: var(--blue);
    margin-bottom: 14px;
    padding-bottom: 10px;
    border-bottom: 2px solid var(--border);
  }}
  .card.accent-green {{ border-left: 4px solid var(--green); }}
  .card.accent-blue  {{ border-left: 4px solid var(--blue);  }}
  .card.accent-amber {{ border-left: 4px solid var(--amber); }}
  .card.accent-red   {{ border-left: 4px solid var(--red);   }}
  .bullet {{
    padding: 7px 0;
    border-bottom: 1px solid #f3f4f6;
    font-size: .88rem;
    line-height: 1.55;
    color: #374151;
  }}
  .bullet:last-child {{ border-bottom:none; }}
  .label {{ font-weight:700; color: var(--ink); margin-right:4px; }}
  .prose {{
    font-size: .92rem;
    line-height: 1.75;
    color: #374151;
  }}
  .source-text {{
    font-size:.78rem;
    color:var(--muted);
    line-height:1.6;
    max-height:130px;
    overflow-y:auto;
  }}
  .footer {{
    text-align:center;
    color:var(--muted);
    font-size:.75rem;
    margin-top:40px;
  }}
  @media(max-width:640px){{
    .grid-2{{ grid-template-columns:1fr; }}
    .hero h1{{ font-size:1.4rem; }}
  }}
</style>
</head>
<body>

<div class="hero">
  <h1>📈 MARKETPULSE AI</h1>
  <div class="sub">{today}</div>
  <div class="ts">Last updated {now} · Powered by Gemini AI & GitHub Actions</div>
</div>

<div class="ticker">
  📰 Edward Jones + CNBC Morning Squawk &nbsp;|&nbsp;
  🤖 Gemini 3.6 Flash &nbsp;|&nbsp;
  ⏱ Auto-updated weekdays 6:30 AM EST
</div>

<div class="container">

  <div class="grid-2">
    <div class="card accent-blue">
      <h2>📊 Market Summary</h2>
      <div class="prose">{fmt(s["MARKET SUMMARY"])}</div>
    </div>
    <div class="card accent-green">
      <h2>🌅 Morning Outlook</h2>
      <div class="prose">{fmt(s["MORNING OUTLOOK"])}</div>
    </div>
  </div>

  <div class="grid-2" style="margin-top:20px">
    <div class="card accent-amber">
      <h2>⚡ Key Moves</h2>
      {fmt(s["KEY MOVES"])}
    </div>
    <div class="card accent-red">
      <h2>🌐 Macro & News</h2>
      {fmt(s["MACRO & NEWS"])}
    </div>
  </div>

  <div style="margin-top:20px">
    <div class="card accent-green">
      <h2>💰 Earnings Highlights</h2>
      {fmt(s["EARNINGS"])}
    </div>
  </div>

  <div class="grid-2" style="margin-top:20px">
    <div class="card">
      <h2>📰 Edward Jones Source</h2>
      <div class="source-text">{ej}</div>
    </div>
    <div class="card">
      <h2>📧 CNBC Squawk Source</h2>
      <div class="source-text">{cb}</div>
    </div>
  </div>

  <div class="footer">
    MarketPulse AI &nbsp;·&nbsp; Built by anil2040 &nbsp;·&nbsp;
    Not financial advice.
  </div>

</div>
</body>
</html>"""

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)
    print("   ✅ index.html written successfully")


# ============================================================
# STEP 5: SEND EMAIL BACKUP VIA SMTP
# ============================================================
# SMTP = Simple Mail Transfer Protocol
# While IMAP reads email, SMTP SENDS email.
# Same concept -- we connect to Yahoo's mail server
# and hand it a message to deliver.

def send_email(briefing_text):
    print("\n📤 Sending email backup via SMTP...")
    
    try:
        # Build the email object
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"📈 MarketPulse AI Briefing - {datetime.now().strftime('%b %d, %Y')}"
        msg["From"]    = YAHOO_EMAIL
        msg["To"]      = YAHOO_EMAIL  # Sending to yourself!
        
        # Plain text version (fallback for basic email clients)
        text_part = MIMEText(briefing_text, "plain")
        
        # HTML version (rich formatted version)
        html_body = f"<pre style='font-family:sans-serif;'>{briefing_text}</pre>"
        html_part = MIMEText(html_body, "html")
        
        msg.attach(text_part)
        msg.attach(html_part)
        
        # Connect to Yahoo's SMTP server
        # Port 587 = STARTTLS (secure sending port)
        with smtplib.SMTP("smtp.mail.yahoo.com", 587) as server:
            server.starttls()  # Upgrade to encrypted connection
            server.login(YAHOO_EMAIL, YAHOO_PASSWORD)
            server.sendmail(YAHOO_EMAIL, YAHOO_EMAIL, msg.as_string())
        
        print("   ✅ Email sent successfully!")
        
    except Exception as e:
        print(f"   ❌ Email send failed: {e}")
        print("   (Dashboard will still be updated -- email is backup only)")


# ============================================================
# MAIN RUNNER -- This is where everything kicks off
# ============================================================
# In Python, this pattern:
#   if __name__ == "__main__":
# means "only run this block if THIS file was called directly"
# It's a Python best practice -- prevents accidental execution
# when another file imports this one.

if __name__ == "__main__":
    print("🚀 MarketPulse AI Starting...")
    print("=" * 50)
    
    # Run all steps in sequence
    ej_text    = scrape_edward_jones()
    cnbc_text  = fetch_cnbc_email()
    briefing   = synthesize_with_gemini(ej_text, cnbc_text)
    build_html(briefing, ej_text, cnbc_text)
    send_email(briefing)
    
    print("\n" + "=" * 50)
    print("✅ MarketPulse AI Complete!")
    print(f"🌐 Dashboard: https://anil2040.github.io/market-pulse-ai")
    print("=" * 50)
