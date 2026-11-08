# Live settings for the Simple Replit edition

Start with the demo in README.md. Add sensitive values individually in Replit's Secrets tool, preserving any other settings. Public settings/flags can go in its Configurations section. Wallets and prices are already set in `config.json`.

| Name | Value |
| --- | --- |
| STREAMBOT_MODE | demo initially, live when ready |
| STREAMBOT_PUBLIC_URL | Exact HTTPS published origin, such as https://your-bot.replit.app, with no path |
| STREAMBOT_TELEGRAM_BOT_TOKEN | Token from official @BotFather |
| STREAMBOT_TELEGRAM_ENABLED | false initially, true to connect Telegram |
| STREAMBOT_SUPPORT_ADMIN_ID | Your numeric ID from /myid, sent from your @InterRamit account |
| STREAMBOT_PANEL_USERNAME | Reseller panel username |
| STREAMBOT_PANEL_PASSWORD | Reseller panel password |
| STREAMBOT_CREDENTIAL_KEY | Stable encryption key generated below |
| STREAMBOT_DATABASE_SOURCE | managed for Replit's database; external for your own connection |
| STREAMBOT_DATABASE_URL | Direct/session PostgreSQL URL when using external mode |
| STREAMBOT_ETHEREUM_RPC_URL | Ethereum mainnet RPC supporting finalized blocks |
| STREAMBOT_SOLANA_RPC_URL | Solana mainnet RPC supporting finalized transaction history |
| STREAMBOT_BITCOIN_ESPLORA_URL | https://blockstream.info/api or your mainnet Esplora service |
| STREAMBOT_PANEL_WRITE_ENABLED | false initially; true for real account creation |
| STREAMBOT_LIVE_PAYMENTS_ENABLED | false initially; true for real payments |

Do not set STREAMBOT_BASE_PATH: this edition serves checkout at `/`. Leave STREAMBOT_PORT unset to use port 5000. Demo automatically uses Replit's Preview origin when REPLIT_DEV_DOMAIN is available. Use the verified published origin for STREAMBOT_PUBLIC_URL in production.

## Encryption key

After the first demo run, generate a key in Shell:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Save the output as STREAMBOT_CREDENTIAL_KEY, keep a private backup, and never change it while using the same database. Never send it in chat or put it in a public source file.

## Database

Live Replit operation requires PostgreSQL; local SQLite is for the demo only. For Replit's database, set STREAMBOT_DATABASE_SOURCE=managed: the launcher uses the runtime DATABASE_URL, which points to production after publishing. Do not pin production to a copied development connection string. External databases use STREAMBOT_DATABASE_SOURCE=external and STREAMBOT_DATABASE_URL. Do not use a transaction pooler: the app holds a session advisory lock to prevent two instances processing the same state. A session-pooled endpoint is suitable only if session semantics are guaranteed.

The schema source of truth is `sql/schema.sql`. Apply it in development using the database tools; Publish applies the schema diff to managed production. Do not run schema mutations in the deploy build or at runtime. Store startup validates the six required tables and fails closed if they are absent. External database owners must prepare their schema separately through their authorized migration process.

PostgreSQL requires a stable encryption key. The Replit launcher isolates demo mode on its existing SQLite database and local demo key, even after live Secrets have been added. No demo orders or account credentials are migrated into the live database.

Keep the database and encryption key across republishes. Replacing the database loses order history, used-TXID protection and trial limits. Local demo data is not automatically migrated.

## Check before activation

```bash
bash run.sh check
bash run.sh inspect-panel
```

The second command logs in and lists packages without creating an account. It requires panel credentials. Verify all adult/no-adult packages, wallets and prices in config.json.

## Publish

Select Reserved VM > Web server with one instance, use build `bash install.sh` and run `bash run.sh`. Replit installs requirements before Build; the build script validates imports instead of running pip into the immutable system directory. Expose only port 5000 as external 80. Review Production secrets and use the verified published HTTPS origin for STREAMBOT_PUBLIC_URL. Production settings are prepared for live mode on the next publish; the preview remains demo with Telegram disabled. The Telegram long poller needs always-on hosting. Do not run Preview and production against the same bot token or live schema. If reusing a bot token with a webhook, remove its webhook before enabling long polling.

After every required live setting is present, set STREAMBOT_MODE=live, STREAMBOT_TELEGRAM_ENABLED=true, STREAMBOT_PANEL_WRITE_ENABLED=true and STREAMBOT_LIVE_PAYMENTS_ENABLED=true, then republish. Request one `/trial` and verify its real account in the panel. Test a controlled paid order and verify delivery before accepting customers. Paid provisioning spends panel credits. Live payment/account delivery has not been tested in the delivered package.

## Support and operations

Customers send `/contact` or `/support` to open a 24-hour support session. They consent to share their message and Telegram identity with you. You reply using Telegram's Reply action on the forwarded message or support header. `/cancel` stops new forwarding. Reply routes last 30 days and survive database-backed restarts. Your numeric admin ID is the authorization check; a matching username does not grant access. Message contents are copied through Telegram rather than stored as text in the database; encrypted delivery/routing metadata is stored. Telegram retains the chat copies. Protected/service messages cannot be copied; a crash after a successful API send but before its receipt is saved can cause a repeated message.

```bash
bash run.sh orders
bash run.sh reconcile ORDER_ID
```

An ambiguous panel creation result moves the order to `review` and stops automatic retries. Reconcile looks for the stored credentials without submitting creation again. If it confirms a match, the order is fulfilled. Only after verifying absence manually, `bash run.sh retry ORDER_ID --confirm-absent` queues one new attempt after another absence lookup.

The custom Telegram checkout now continues from membership selection to coin/network buttons. It freezes a rate snapshot, displays the USD equivalent and exact crypto amount, then accepts a TXID through the order's button or `/txid ORDER_ID HASH`. The backend verifies chain, recipient, token, amount, time window and confirmations before marking an order paid. Used transactions cannot pay another order. Account delivery and payment status are sent privately to the order owner; `/orders` returns to invoices.

Demo mode uses simulated rates, nonpayable wallets and an explicit simulation button. It does not perform real-chain verification. Live verification requires the read-only RPC endpoints above and a controlled real-payment test. Notification retries are persistent; a crash after sending but before recording a delivery receipt can repeat a notification.

Telegram's published policy requires Stars for digital goods sold through bots and does not exempt custom wallet/TXID backends. This custom flow is not Telegram-approved. See https://core.telegram.org/bots/payments-stars#can-i-accept-payment-in-cryptocurrency-instead-of-telegram-stars before operating it.

## Official Replit references

- https://docs.replit.com/features/project-setup/configuration
- https://docs.replit.com/features/publishing/deployment-types
- https://docs.replit.com/core-concepts/project-editor/app-setup/secrets
