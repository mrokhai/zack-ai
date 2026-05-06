## Zack.ai — LinkedIn Commenting Agent
Comments on 2up to 100 posts daily in your exact voice. While you sleep.
Built by Clinton Okhai

---

## What it does
Zack visits people on your engagement list, reads their latest post,
identifies what kind of post it is — funny, emotional, intellectual,
achievement, opinion — and drops a comment that matches the energy.
In your voice. Not a template. Not a generic response.
It runs on your Windows laptop. Uses your LinkedIn session.
You do nothing after setup.

---

## You need a licence key to use this
This is not a public download. Access is for registered Zack users only.
If you came here from your access email — your key is in that email.
Scroll down to Installation.
If you don't have access yet — join the waitlist:
→ Join the WhatsApp community to get access
Members get the registration link pinned in the group.
Registration takes 2 minutes. Your key arrives by email automatically.

---

## What you need before starting
RequirementWhere to get itWindows 10 or 11—Python 3.10 or newerpython.org — check "Add Python to PATH"Google Chromechrome.google.comChromeDrivergooglechromelabs.github.io/chrome-for-testingGroq API key (free)console.groq.com → API KeysGoogle SheetAny sheet you own — you'll paste the ID during setupgoogle_credentials.jsonAttached to your access emailYour licence keyIn your access email

---

## Installation

Step 1 — Download your files
Click the green Code button at the top of this page → Download ZIP
Unzip it. Create a folder on your Desktop called:
Zacharia Lead Agent
Place all the files from the ZIP inside it.

Step 2 — Get ChromeDriver
Open Chrome and go to chrome://settings/help
Note your version number — e.g. 147.0.7727.102
Go to: googlechromelabs.github.io/chrome-for-testing
Download the version that matches yours. Unzip it.
Put chromedriver.exe inside your Zacharia Lead Agent folder.

⚠️ The version must match exactly. If Chrome updates, you'll need to
update ChromeDriver too.

Step 3 — Add your credentials file
Your access email has google_credentials.json attached to it.
Place it inside your Zacharia Lead Agent folder.

Step 4 — Open Command Prompt in your folder
Open your Zacharia Lead Agent folder in Windows Explorer.
Hold Shift + right-click anywhere inside the folder.
Click "Open PowerShell window here" or "Open Command window here".

Step 5 — Run the setup wizard
python zack_setup.py
The wizard will ask you for:

Your licence key
Your name, title, company, LinkedIn URL
Your Google Sheet ID and Groq API key
Your target audience and regions
Your tone — warm, sharp, thoughtful, or witty
Your gender — affects how Zack phrases comments naturally
Phrases you never use — Zack hard-bans these
2–3 real LinkedIn comments you've written — your voice reference

Takes 2 minutes. Your personalised zack_config.py is created automatically.

Step 6 — Run the installer
Right-click zack_install.bat → Run as administrator
Wait for it to finish. You will see:
[1/5] Python found. Installing required packages...
[2/5] Packages installed.
[3/5] Setting up environment variables...
[4/5] Creating desktop shortcuts...
[5/5] Scheduling automatic runs...

INSTALLATION COMPLETE
Desktop shortcuts appear automatically.

Step 7 — Add people to your engagement list
Open your Google Sheet.
Find the tab called "Zacharia Engagement List"
(Zack creates this tab automatically on first run if it doesn't exist).
Add people like this:
Column A — NameColumn B — LinkedIn URLColumn C — NotesAlex Hormozihttps://linkedin.com/in/alexhormoziPosts about business and salesJasmin Alichttps://linkedin.com/in/jasmin-alicLinkedIn writing coach, posts dailyAdedeji Olowehttps://linkedin.com/in/adedeji-oloweAfrican fintech founder and investor
Add anyone whose posts you want Zack to comment on.
The note in Column C helps Zack write better-targeted comments.

Step 8 — Run Zack
Double-click Zack – Engage (Comments) on your Desktop.
Chrome opens. Log into LinkedIn if prompted.
Zack detects your session and starts running automatically.
You will see output like this:
📋 Processing engagement list...
───────────────────────────────────────────────────────
   Alex Hormozi
   → Checking for recent posts...
   → Post found (18hrs ago) | 312 words
   → Generating comment...
   → Comment: 'The part about compounding your own reputation before...'
   → Opening comment editor...
   → Typing comment...
   → Posting comment...
   ✅ Posted (1/25)

Automatic schedule
After installation, Zack runs automatically on weekdays:
TimeWhat happens7:00 AMZack comments on your engagement list posts1:00 PMZack runs again for posts published since morning
LinkedIn must be logged in on Chrome for the scheduled runs to work.
If the session expires, log in manually — Zack continues immediately.

---

## Troubleshooting
"Chrome opens and closes immediately"
ChromeDriver version mismatch. Check your Chrome version at
chrome://settings/help and download the exact matching ChromeDriver.
"No module named gspread" or similar
Open Command Prompt in your folder and run:
pip install selenium gspread google-auth groq requests
"Comment box not found"
LinkedIn updated its interface. This happens every 2–4 months.
Post in the Telegram community — an updated file will be shared.
Rate limit error from Groq
The free Groq tier allows 100,000 tokens per day. Zack automatically
waits and retries. To remove the limit, upgrade at
console.groq.com/settings/billing
"Invalid session" or browser crashes mid-run
Zack restarts the browser automatically and continues.
If it keeps happening, close other applications to free up memory.

---

## What Zack will not do

Send more than 25 comments per run
Comment on the same post twice
Access your LinkedIn password
Run on any account other than the one logged into Chrome
Work on Mac or Linux (Windows only for now)

---

## Community
Every registered Zack user gets access to the private Telegram community.

Installation help and troubleshooting
Share your results and screenshots
Early access to new features
Updates when LinkedIn changes break selectors

Your Telegram invite link is in your access email.
The link is private — please do not share it publicly.

The full Zack suite
The commenting agent is the free community tier.
The full system includes:

LinkedIn lead scraper (search-based)
Automated first messaging + 2-message new connections sequence
Connections scanner and messaging
Reply agent — reads threads and continues conversations
Reignite agent — follows up cold conversations after 7 days

Contact Clinton Okhai on LinkedIn to discuss the full suite.

Built by
Clinton Okhai
Founder, Mathetes — Venture Architecture for African Founders
LinkedIn ·
Newsletter — The Founder's Odyssey

Zack.ai — your LinkedIn outreach engine.
