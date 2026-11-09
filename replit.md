# Streamline

## Website administration

The owner-only portal is served at `/admin/`; see `ADMIN_DASHBOARD.md`.
The user selected Replit sign-in after managed Clerk provisioning rejected the
imported project name. Do not switch providers without asking.
Use `STREAMBOT_WEB_ADMIN_EMAILS` for the explicit owner email allowlist.
Store it as a Replit Secret, not a shared non-secret setting that commits personal
email addresses to `.replit`.
First owner setup additionally requires `STREAMBOT_WEB_BOOTSTRAP_CODE` (20–200
characters) entered on the website. The backend atomically binds the owner to the
immutable OIDC subject; the code cannot replace an existing owner.
Do not grant admin to the first signup, trust browser role headers, or tie website
access to the Telegram administrator ID. Existing Python provisioning remains
authoritative; the API gateway supervises one loopback-only Python backend.

Streamline is an existing Python Flask/Waitress checkout and Telegram subscription
service, preserved in a pnpm workspace. This port does not introduce admin features.

## Run and verify

- Start managed `artifacts/api-server: API Server`, then `artifacts/streamline: web`.
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
