# Simple Replit edition

Run this package in a NEW, empty Python Replit project. Your existing website stays in its current project. This edition runs checkout and the Telegram bot together as one Python app. It does not need Node.js, npm, a gateway, a supervisor, or a website start command.

## Upload and run the demo

1. Download `stream-panel-bot-simple-replit.zip` and extract it on your computer.
2. Create a new Python project in Replit.
3. Upload the CONTENTS of the extracted folder to the new project's root. Include the hidden `.replit` file and the complete `streambot` folder. `run.sh`, `config.json` and `.replit` must sit directly at the project root.
4. In this configured workspace, dependencies are installed in Replit's managed Python environment. Click Run to start the demo workflow. For a fresh import, ask Agent to install `requirements.txt` and configure `bash run.sh` as the run command. See `replit.md` for workspace-specific instructions.
5. Open Preview. The home page is the reseller sign-in; memberships are sold in the Telegram bot. Demo mode creates sample credentials and never accesses your panel or blockchains.

You can also upload the ZIP into the empty project's root and extract it in Shell:

```bash
python3 -m zipfile -e stream-panel-bot-simple-replit.zip .
# Ask Agent to install dependencies and configure the demo workflow before running.
bash run.sh
```

The ZIP contains its files at the root, so it is ONLY for a new empty project. It includes your public receiving wallets, GBP prices and @InterRamit contact link. It includes no private credentials. Do not run the old gateway/supervisor commands with this edition.

## Let Replit Agent finish setup

Paste this after uploading:

```text
This is a NEW project for the uploaded Simple Replit edition of stream-panel-bot.
Read README.md and LIVE_SETUP.md. Install requirements.txt in Replit's managed
Python environment. Use bash run.sh for the Run button.
Ensure Python 3.10+ is available and expose internal port 5000 as external
80. The reseller sign-in is at /, with no gateway, supervisor, Node.js or existing website.
Start in demo mode and verify a simulated checkout. Then help me add the missing
STREAMBOT_* settings in Secrets and a direct PostgreSQL database connection.
Do not print credentials or enable live payments or panel writes during setup.
For publication use Reserved VM, web server, one instance, build bash install.sh,
run bash run.sh. Do not create an Autoscale deployment or duplicate bot pollers.
```

## Try the Telegram bot locally

`python3 preview/telegram_preview.py` opens a Telegram look-alike at http://127.0.0.1:8099
that runs the real bot code in demo mode against a throwaway database under `data/preview/`.
Switch between a customer, the support admin and a reseller applicant from the header, tap
inline buttons, use the Menu command list, reply to messages, and press Reset to start over.
It also serves the website (reseller sign-in and panel) at http://127.0.0.1:8098/ against the
same database, so the bot's **Open web dashboard** link works locally. It never contacts
Telegram, the panel or any blockchain. Per-user rate limits are off unless
`PREVIEW_RATE_LIMITS=1` is set.

## Connect Telegram

Create a bot using Telegram's official @BotFather (`/newbot`). In Replit Secrets, add `STREAMBOT_TELEGRAM_BOT_TOKEN`, then set `STREAMBOT_TELEGRAM_ENABLED=true`. Restart. While logged into @InterRamit, send your bot `/start` and `/myid`. Save the number returned as Secret `STREAMBOT_SUPPORT_ADMIN_ID` and restart. Customers send `/contact`; you use Telegram's Reply action on their incoming support messages to answer them.

## Publish and accept real payments

Follow LIVE_SETUP.md for the settings checklist. Demo needs no Secrets. Live operation needs your bot token, panel credentials, a stable encryption key, PostgreSQL, read-only blockchain endpoints and the published HTTPS origin. Managed database mode uses Replit's runtime connection so production does not connect to development. Prepare `sql/schema.sql` in development; Publish applies the managed production schema.

Choose Reserved VM > Web server, one instance. Use `bash install.sh` for build and `bash run.sh` for run. Port 5000 is configured in this workspace's `.replit`. Check Production app secrets in Publishing before launch. Only one running process may use the bot token; keep Telegram disabled in Preview when production is polling it.

Reserved VM hosting has a cost. Before accepting customers, verify the published health endpoint and perform a controlled live payment/account-delivery test.
