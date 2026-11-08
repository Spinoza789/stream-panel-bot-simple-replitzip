# Simple Replit edition

Run this package in a NEW, empty Python Replit project. Your existing website stays in its current project. This edition runs checkout and the Telegram bot together as one Python app. It does not need Node.js, npm, a gateway, a supervisor, or a website start command.

## Upload and run the demo

1. Download `stream-panel-bot-simple-replit.zip` and extract it on your computer.
2. Create a new Python project in Replit.
3. Upload the CONTENTS of the extracted folder to the new project's root. Include the hidden `.replit` file and the complete `streambot` folder. `run.sh`, `config.json` and `.replit` must sit directly at the project root.
4. Click Run. The first run installs dependencies automatically; subsequent runs reuse them. If the Run button still uses the template command, set its command to `bash run.sh` or ask Agent using the instruction below.
5. Open Preview. Checkout is at `/`. Select a plan and simulate a successful payment. Demo mode creates sample credentials and never accesses your panel or blockchains.

You can also upload the ZIP into the empty project's root and extract it in Shell:

```bash
python3 -m zipfile -e stream-panel-bot-simple-replit.zip .
bash run.sh
```

The ZIP contains its files at the root, so it is ONLY for a new empty project. It includes your public receiving wallets, GBP prices and @InterRamit contact link. It includes no private credentials. Do not run the old gateway/supervisor commands with this edition.

## Let Replit Agent finish setup

Paste this after uploading:

```text
This is a NEW project for the uploaded Simple Replit edition of stream-panel-bot.
Read README.md and LIVE_SETUP.md. Run bash run.sh; use that command for the Run
button. Ensure Python 3.10+ is available and expose internal port 8090 as external
80. Checkout is at /, with no gateway, supervisor, Node.js or existing website.
Start in demo mode and verify a simulated checkout. Then help me add the missing
STREAMBOT_* settings in Secrets and a direct PostgreSQL database connection.
Do not print credentials or enable live payments or panel writes during setup.
For publication use Reserved VM, web server, one instance, build bash install.sh,
run bash run.sh. Do not create an Autoscale deployment or duplicate bot pollers.
```

## Connect Telegram

Create a bot using Telegram's official @BotFather (`/newbot`). In Replit Secrets, add `STREAMBOT_TELEGRAM_BOT_TOKEN`, then set `STREAMBOT_TELEGRAM_ENABLED=true`. Restart. While logged into @InterRamit, send your bot `/start` and `/myid`. Save the number returned as Secret `STREAMBOT_SUPPORT_ADMIN_ID` and restart. Customers send `/contact`; you use Telegram's Reply action on their incoming support messages to answer them.

## Publish and accept real payments

Follow LIVE_SETUP.md for the settings checklist. Demo needs no Secrets. Live operation needs your bot token, panel credentials, a stable encryption key, a direct PostgreSQL connection, read-only blockchain endpoints and the published HTTPS origin.

Choose Reserved VM > Web server, one instance. Use `bash install.sh` for build and `bash run.sh` for run. Port 8090 is already configured in `.replit`. Check Production app secrets in Publishing before launch. Only one running process may use the bot token; keep Telegram disabled in Preview when production is polling it.

Reserved VM hosting has a cost. The package has been tested locally; it has not been deployed into your Replit account, and real payment/account delivery still needs a controlled live test.
