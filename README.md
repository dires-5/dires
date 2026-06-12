# Fayda ID Bot v3 — No-Git Deployment Guide

## Option 1: Render.com (FREE, 24/7, NO Git needed)

### Step 1 — Create a free account
Go to https://render.com and sign up (free).

### Step 2 — Upload your code as a zip
1. Go to https://render.com/deploy
2. Click **"New +"** → **"Background Worker"**
3. Choose **"Deploy from ZIP"** (no Git needed!)
4. Upload the `fayda_bot_v3_fixed.zip` file

### Step 3 — Configure
- **Name:** fayda-id-bot (or anything)
- **Runtime:** Python 3
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `python bot.py`

### Step 4 — Set environment variables
Click **"Environment"** tab and add:
| Key | Value |
|-----|-------|
| BOT_TOKEN | Your token from @BotFather |
| ADMIN_CHAT_ID | Your Telegram numeric user ID |

### Step 5 — Deploy
Click **"Create Background Worker"** — it builds and runs 24/7 for FREE!

---

## Option 2: Railway.app (FREE $5/month credit, NO Git needed)

1. Go to https://railway.app → Sign up free
2. Click **"New Project"** → **"Deploy from ZIP"**
3. Upload `fayda_bot_v3_fixed.zip`
4. Click **"Variables"** tab → Add:
   - `BOT_TOKEN` = your token
   - `ADMIN_CHAT_ID` = your chat id
5. Click **Deploy** ✅

---

## Option 3: Koyeb.com (FREE tier, NO Git needed)

1. Go to https://app.koyeb.com → Sign up free
2. **Create App** → **"Archive"** (ZIP upload)
3. Upload the zip file
4. Build command: `pip install -r requirements.txt`
5. Run command: `python bot.py`
6. Add environment variables:
   - `BOT_TOKEN`
   - `ADMIN_CHAT_ID`
7. Deploy!

---

## How to find your ADMIN_CHAT_ID

1. Open Telegram and message @userinfobot
2. It will reply with your numeric ID (e.g. 123456789)
3. Use that number as ADMIN_CHAT_ID

---

## Changes in v3

- Fix 1: Broadcast works without error after sending
- Fix 2: FCN requires exactly 16 digits only
- Fix 3: Background removal no longer cuts heads
- Fix 4: Users must join t.me/dhtechs before using bot
