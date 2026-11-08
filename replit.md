# Running the imported demo

This project is the original Python/Flask checkout and Telegram bot, not a Node app.
Keep its existing structure and stack.

- Click **Run** to start the `Start application` workflow, which runs `bash run.sh`.
- Checkout is at `/`, listening on `0.0.0.0:5000`. Health is at `/healthz`.
- Dependencies are installed in Replit's managed Python environment from
  `requirements.txt` before Build. `install.sh` checks imports and compiles Python;
  it must not run pip against the immutable Nix system directory.
- The preview workflow explicitly selects demo mode with Telegram polling disabled;
  live payments and panel writes remain disabled. Publishing enables Telegram
  using the bot token and support administrator ID in Secrets.
  Run only one poller per bot token.
- Select a plan and currency, create a quote, then use the demo payment button.
  It generates sample account credentials without contacting blockchains or the panel.
- Demo state and its generated encryption key are kept in the ignored `data/`
  directory using SQLite. Do not commit or share that directory. The Replit demo
  launcher deliberately ignores the live PostgreSQL URL and live encryption key:
  adding production Secrets must not move demo data or invalidate its credentials.
- The Telegram membership menu selects duration, adult/no-adult content, and
  connection count using buttons, with Back navigation. Choose payment crypto
  continues to a crypto/network selection and a wallet invoice with a USD
  reference value, exact crypto amount, and expiry.
- Tap the TXID button to submit a hash, or use `/txid ORDER_ID HASH`.
  The backend worker verifies payment; a submitted hash alone never marks it paid.
  My orders or `/orders` returns to invoices. Quotes, ownership, TXID entry, and
  delivery receipts persist in the existing store. No new database schema is required.
- A trial in review offers Check / retry trial, also available as `/retrytrial`.
  Recovery looks up the existing panel username first and verifies saved credentials.
  Matching accounts are delivered without another creation; confirmed absence queues
  the same trial order with the same credentials. Ownership, atomic state checks,
  cooldowns and rate limits prevent duplicate queued requests.
- Never automatically retry uncertain panel creation. Preserve the review state
  until an explicit recovery action checks the existing account.
- The current demo uses simulated exchange rates and nonpayable wallets. Its
  simulation button is explicitly labeled and unavailable in live mode.
- Telegram requires Stars for digital-goods sales in bots. The requested custom
  crypto flow is not an exception to that rule; do not describe it as Telegram-approved.
- `config.json` is the public catalog and must be retained with the project.
  Store credentials only in Secrets, never in that file.
- Run isolated menu and payment tests with `python3 -m unittest discover -s tests -v`.
- PostgreSQL schema source is `sql/schema.sql`. Apply changes in development;
  Replit Publish migrates managed production. Store startup only validates schema,
  never runs DDL. Opt-in PostgreSQL tests run with `STREAMBOT_TEST_POSTGRES=true`;
  sample writes are rolled back and panel/blockchain providers are mocked.
- Production uses `STREAMBOT_DATABASE_SOURCE=managed`, selecting Replit's runtime
  `DATABASE_URL` rather than a copied development URL in Secrets. Explicit external
  database connections remain available with `STREAMBOT_DATABASE_SOURCE=external`.
- The prepared Reserved VM publishing settings enable live payments, Telegram
  polling and panel writes on the next publish. The preview remains a separate demo.
- Real-payment setup and publication remain separate from this demo
  setup. Consult `LIVE_SETUP.md` before any live configuration. Do not enable live
  payments or panel writes without the user's explicit request.

The imported README describes the original standalone installer and port 8090.
For this Replit workspace, use the managed environment and port 5000 above.
