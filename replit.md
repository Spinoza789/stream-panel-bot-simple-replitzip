# Running the imported demo

This project is the original Python/Flask checkout and Telegram bot, not a Node app.
Keep its existing structure and stack.

- Click **Run** to start the `Start application` workflow, which runs `bash run.sh`.
- Checkout is at `/`, listening on `0.0.0.0:5000`. Health is at `/healthz`.
- Dependencies are installed in Replit's managed Python environment from
  `requirements.txt`. `install.sh` installs the supplied exact lock for builds;
  neither script creates a virtual environment.
- The preview workflow explicitly selects demo mode with Telegram polling enabled;
  live payments and panel writes remain disabled. Telegram uses the bot token and
  support administrator ID stored in Secrets. Run only one poller per bot token.
- Select a plan and currency, create a quote, then use the demo payment button.
  It generates sample account credentials without contacting blockchains or the panel.
- Demo state and its generated encryption key are kept in the ignored `data/`
  directory using SQLite. Do not commit or share that directory.
- The Telegram membership menu selects duration, adult/no-adult content, and
  connection count using buttons, with Back navigation. It displays a selection
  summary only; it does not create an order or take payment.
- `config.json` is the public catalog and must be retained with the project.
  Store credentials only in Secrets, never in that file.
- Run isolated Telegram menu tests with `python3 -m unittest discover -s tests -v`.
- Real-payment setup and publication remain separate from this demo
  setup. Consult `LIVE_SETUP.md` before any live configuration. Do not enable live
  payments or panel writes without the user's explicit request.

The imported README describes the original standalone installer and port 8090.
For this Replit workspace, use the managed environment and port 5000 above.
