# Zack.ai — LinkedIn Commenting Agent

Comments on up to 90 posts daily in your exact voice. While you sleep.

Built by Clinton Okhai (https://www.linkedin.com/in/clinton-okhai/)

---

## What it does

Zack visits posts from people on your engagement list, reads
each post, identifies the type (funny, emotional, intellectual,
achievement, opinion), and drops a comment that matches the
energy — written in your voice, not a template.

It runs on your Windows laptop. Uses your LinkedIn session.
Posts comments automatically. You do nothing.

---

## This is not a public download

Access is for registered users only.

If you have a key — follow the steps below.
If you don't — you were sent a registration link by email.

---

## What you need before starting

- Windows 10 or 11
- Python 3.10+  →  python.org (check "Add Python to PATH")
- Google Chrome  →  chrome.google.com
- ChromeDriver  →  must match your Chrome version
- A free Groq API key  →  console.groq.com
- A Google Sheet  →  for logging comments

---

## Installation

**Step 1 — Download these files**

Click the green Code button above → Download ZIP

Unzip it. Create a folder on your Desktop called:
`Zacharia Lead Agent`

Put all the files inside it.

**Step 2 — Get ChromeDriver**

Open Chrome → go to `chrome://settings/help`

Note your version number (e.g. 147.0.7727)

Go to: googlechromelabs.github.io/chrome-for-testing

Download the matching version. Unzip it.
Put `chromedriver.exe` inside your Zacharia Lead Agent folder.

**Step 3 — Put google_credentials.json in the folder**

This file was attached to your access email.
Place it in the Zacharia Lead Agent folder.

**Step 4 — Open Command Prompt in your folder**

Open your Zacharia Lead Agent folder.
Hold Shift + right-click inside the folder.
Click "Open PowerShell window here" or "Open Command window here".

**Step 5 — Run the setup wizard**

---

## python zack_setup.py

Enter your licence key when asked.
Answer the questions. Takes 2 minutes.
Your personalised zack_config.py is created automatically.

**Step 6 — Run the installer**

Right-click `zack_install.bat`
Select "Run as administrator"
Wait for it to finish.
Desktop shortcuts appear.

**Step 7 — Add people to your engagement list**

Open your Google Sheet.
Find the tab called "Zacharia Engagement List".
Add people like this:

| A — Name | B — LinkedIn URL | C — Notes |
|---|---|---|
| Alex Hormozi | https://linkedin.com/in/alexhormozi | Posts about business |

**Step 8 — Run Zack**

Double-click "Zack – Engage (Comments)" on your Desktop.
Log into LinkedIn when Chrome opens.
Zack starts commenting automatically.

---

## Stuck?

Post in the Zack community on Telegram.
Link was shown on your registration confirmation page.

---

## Want the full system?

The commenting agent is the free tier.
The full Zack suite (lead scraper, messaging, reply agent) is available separately.

Contact Clinton Okhai on LinkedIn.
