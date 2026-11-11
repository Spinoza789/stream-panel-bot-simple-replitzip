# Streamline

## Website administration

The owner-only portal is served at `/admin/`; see `ADMIN_DASHBOARD.md`.
The user explicitly requested normal username/email-and-password login instead
of Replit sign-in. Keep the website login independent of Replit accounts.
Use `STREAMBOT_WEB_ADMIN_EMAILS` for the approved first-owner setup email.
Store it as a Replit Secret, not a shared non-secret setting that commits personal
email addresses to `.replit`.
First owner setup additionally requires `STREAMBOT_WEB_BOOTSTRAP_CODE` (20–200
characters) entered on the website. It creates one local owner, not public signup.
The setup code cannot overwrite an existing local password account. It may migrate
the previous Replit owner binding once while preserving its audit history.
Passwords are salted scrypt hashes inside the existing encrypted business metadata;
normal login uses secure opaque server-side sessions. Settings changes require the
current password and revoke other sessions. Prior OIDC sessions are rejected.
Do not grant admin to the first signup, trust browser role headers, or tie website
access to the Telegram administrator ID. Existing Python provisioning remains
authoritative; the API gateway supervises one loopback-only Python backend.

Streamline is an existing Python Flask/Waitress checkout and Telegram subscription
service, preserved in a pnpm workspace, with a separate owner administration portal.

## Run and verify

- Start managed `artifacts/api-server: API Server`, then `artifacts/streamline: web`.
- Start `artifacts/streamline-admin: web` for the owner portal at `/admin/`.
- Install workspace dependencies with `pnpm install --frozen-lockfile` and Python
  dependencies from the root `requirements.txt` using Replit's package manager.
- The API development command forces demo mode and disables Telegram polling,
  live payments, and panel writes, regardless of saved production settings.
- Run existing tests from `artifacts/api-server/python`:
  `python3 -m unittest discover -s tests -v`.
- PostgreSQL integration tests are opt-in only against development. Never enable
  them against production or use the live namespaced database secret for tests.
- Python requirements are retained at the root for Replit dependency installation.
- The original ignored demo database and key are restored together when available;
  existing destination state is never overwritten. No live data is copied.

## Structure

- `artifacts/api-server/python/`: authoritative Python package, original config,
  operational documentation, and tests.
- `artifacts/streamline/checkout/`: original HTML, CSS, and browser JavaScript.
- `artifacts/streamline/gateway.mjs`: transparent HTTP gateway to Flask; no
  financial, provisioning, authentication, or worker logic.
- Existing generated TypeScript/Drizzle scaffold packages are not the source of
  truth for Streamline data and must not be pushed over its database.
- `.migration-backup/` retains the original source and local state, is not needed
  at runtime, and is excluded from deployment.

## Preservation constraints

- Keep Python authoritative for crypto verification, provisioning, Telegram,
  worker leadership, and existing checkout behavior. Do not rewrite in JavaScript.
- Preserve the dedicated VM target and single exclusive worker leader.
- Never replace the existing database, change encryption keys, run production
  DDL, or run scaffold DB push commands. Managed production schema changes use
  Publish, not custom migration scripts or new startup DDL.
- Production settings are preserved; preview is always demo-only.
- All new panel accounts must use blank username, password, and description.
- Verification must not create live accounts, approve payments, recover live
  trials, broadcast messages, or start a second Telegram polling worker.
- Preserve checkout security headers, same-origin POST checks, limits, order
  tokens, and base-path handling. Do not weaken iframe protections for preview.
- The original custom fetch layer is retained; do not replace it with generated
  hooks as part of this preservation task.
- `artifacts/api-server/python/LEGACY_NOTES.md` retains the earlier operational
  notes. Its standalone paths and ports are historical; use the managed services
  above. Other domain rules and safety constraints remain in effect.
