# Running the imported demo

This project is the original Python/Flask checkout and Telegram bot, not a Node app.
Keep its existing structure and stack.

- Click **Run** to start the `Start application` workflow, which runs `bash run.sh`.
- Checkout is at `/`, listening on `0.0.0.0:5000`. Health is at `/healthz`.
- Dependencies are installed in Replit's managed Python environment from
  `requirements.txt`. `install.sh` installs the supplied exact lock for builds;
  neither script creates a virtual environment.
- The preview workflow explicitly selects demo mode and disables Telegram,
  live payments, and panel writes. No additional secrets are needed for the demo.
- Select a plan and currency, create a quote, then use the demo payment button.
  It generates sample account credentials without contacting blockchains or the panel.
- Demo state and its generated encryption key are kept in the ignored `data/`
  directory using SQLite. Do not commit or share that directory.
- Real-payment setup, Telegram connection, and publication are outside this demo
  setup. Consult `LIVE_SETUP.md` before any live configuration. Do not enable live
  payments or panel writes without the user's explicit request.

The imported README describes the original standalone installer and port 8090.
For this Replit workspace, use the managed environment and port 5000 above.
