# Streamline website administration

The `/admin/` portal uses the owner's own username/email and password. The user
explicitly requested removal of Replit sign-in. No Replit or Telegram account is
needed for website administration. There is no public registration.

## First-owner setup

1. Store `STREAMBOT_WEB_ADMIN_EMAILS` as a Replit Secret with the approved setup
   email. Do not put personal email addresses into shared `.replit` configuration.
2. Store a unique 20–200 character `STREAMBOT_WEB_BOOTSTRAP_CODE` secret and keep a
   private copy to enter once in the website.
3. Visit `/admin/sign-in`. If no local owner exists, follow **Setup required** to
   `/admin/setup`. Choose a username and password, and enter the approved email
   and setup code. Passwords must have 12–128 characters; usernames have 3–32.
4. Setup atomically creates a single local owner. Both approved email and workspace
   proof are mandatory; being the first visitor never grants access. If an old
   Replit owner exists, this explicitly authorized auth migration preserves its
   identity in an encrypted audit before binding the new local account.
5. Thereafter use username or email plus password. The setup form cannot overwrite
   a local owner. Legacy login/callback links remain local; they never start OIDC.

The secret is consumed only by server-side code; no passwords or setup codes are
logged or placed in URLs/browser storage. Do not ask for the password in chat.

## Account settings and sessions

Settings → Owner login edits username and email, and optionally the password.
Every save requires the current password. A blank new password means leave it
unchanged. Account changes increment a credential version atomically; old sessions
fail authentication immediately, and the current session is rotated after saving.
Logout revokes its server-side session. Cookies are HttpOnly, Secure and SameSite=Lax.
Sign-in/setup/account mutations require same-origin JSON.
Empty mutations such as logout also declare an empty JSON request body in OpenAPI,
so generated hooks send the required JSON media type rather than a bodyless POST.
Legacy GET logout links only redirect; they do not mutate a session.

Passwords use unique salted scrypt hashes (N=32768, r=8, p=3), encrypted at rest in
the bot's existing metadata store. Private rate limits are persistent across API
processes. Password hashing has a bounded concurrency limit to protect workers.
No plaintext password, password hash, setup code or credential version is sent to
the browser. Email here is an account login identifier; editing it does not enable
email notifications or imply verified delivery.

Old OIDC sessions are deliberately rejected. Historical profile rows and business
audits are retained rather than deleted. A server-only bootstrap code cannot reset
an already configured local password; no password-reset mechanism is currently exposed.

## Publishing

Production needs the same privately configured setup email and bootstrap secret.
Keep the website `public.sessions` table. If the previous dashboard release has
not yet been published, Publish must apply that existing development schema first.
This provider change adds no further tables or columns and runs no production DDL:
local ownership/credentials/audits use existing business metadata. Retaining that
store avoids another production-schema migration for the provider change.

Development and published application data are separate. Create the owner's
password on the published website too if it has no local owner yet. Do not overwrite
production data with demo state or copy development sessions into production.

## Operational scope and safeguards

- Overview is stored order counts, not revenue or active-subscription estimates.
- Orders are paginated/searchable by ID, exact Telegram ID, exact Telegram @username or
  the full transaction ID. An order's page shows its TXID with a link to the public
  block explorer, marked verified once the order is paid or fulfilled.
  Details show the delivered login (username, password, server, expiry) at the owner's
  request; checkout tokens, payment proofs and raw provider errors are still excluded.
- Readiness shows configuration and optional-schema availability, not an upstream
  panel, blockchain or Telegram health probe.
- Recovery shares the original validator/fingerprint/atomic confirmation with
  Telegram recovery; drafts bind to the local website account and session.
- Preview never queues an account. Operator attestation that creation never started
  is mandatory. Missing credentials alone are not evidence of that.
- Confirmation queues the original trial without resetting its lifetime entitlement.
  Possibly submitted creations remain blocked. See `TRIAL_RECOVERY.md`.
- Recovery audits record actor/session digest/time/fingerprint/attestation. Auth
  migration/update audits never contain plaintext passwords or setup codes.

## Gateway and verification

Speed: the backend keeps up to six PostgreSQL connections open and reuses them (each
block is still one transaction, committed or rolled back before the connection is
reused; idle ones are probed, and replaced if the server dropped them). The gateway
remembers the owner's sign-in profile for 10 seconds and a confirmed owner session for
15 seconds; every sign-in change (setup, password, username, two-factor) goes through
the gateway and clears both at once, and logout deletes the session row, which is read
on every request. Bridge replay protection keeps its one-use nonces in memory instead
of a database row per request, and bridge requests skip the shared web rate-limit bucket.

In the browser, once a page has loaded the dashboard fetches the screens most often
opened next (Orders, Subscriptions, Trials, Resellers, Tickets) one at a time in the
background, and fetches any other screen when its sidebar link is hovered, so the
first click shows data at once. Copies live in memory only (never browser storage),
are dropped after five minutes unused, and each screen still refreshes itself when
opened and every 30 seconds.

Node supervises one loopback-only Python backend. Narrow internal requests use a
fresh process-only HMAC key, binding method/path/body/actor/timestamp/one-use nonce.
External requests cannot reach those routes or forge role headers. Only server
auth code can retrieve encrypted credential material for hash verification.

Python retains database ownership, financial verification, panel provisioning,
worker leases and Telegram polling. Preview remains demo-only with live writes off.

Python tests isolate stores and use mocked providers. Node tests cover hashes and
bootstrap checks. The opt-in development-only `src/admin-http.test.ts` exercises
local login, secure cookies, legacy-session rejection, account changes, session
revocation/logout and recovery preview/cancel using temporary demo fixtures; it
refuses to overwrite an actual local owner and restores the old binding. Never
use production data or actual passwords for these tests.

## Resellers, reports, rate card and two-factor sign-in

- **Resellers**: every reseller with status, available and reserved credits, active/all
  customers, credits bought and last activity. Opening one shows this-month and all-time
  statistics, recent credit history, and lets the owner suspend/reactivate or adjust
  credits. Each action needs a reason and is written to `rs_audit` with the website
  actor (administrator column 0, actor string in the details).
- **Reports**: revenue per month from verified payments only (retail memberships at GBP
  price, credit packs at pack price), credits sold and used, tests and conversions, plus
  per-reseller totals. Both tables export as CSV from the browser.
- **Settings › Rate card**: credit pack prices and credits, subscription costs in
  credits per duration and device count, and trial limits. Changes apply to new orders
  and are audited with the reason given.
- **Settings › Two-factor sign-in**: TOTP (Google Authenticator, Authy, 1Password).
  Enrolment keeps the secret in the session until a live code confirms it; it is then
  stored in the sealed owner profile. Sign-in asks for the code after the password.
  Turning it off needs the password and a current code. Both changes sign out other
  sessions.
- The admin has a light/dark toggle in the top bar, remembered per browser.

## Prices, credit costs and packs

Settings → Rate card is the one place for pricing. Every save needs a reason, which
goes into the audit log, and changes apply to new orders only.

- **Subscription prices**: the pound price customers pay for each plan in the bot and
  on the website, plus an on-sale switch. Hidden plans leave the menus; existing
  customers keep what they bought. At least one plan must stay on sale. Prices are
  stored in the database as overrides on top of `config.json`, so a redeploy keeps them.
- **Credit packs**: edit price and credits, hide a pack, remove one, or add a new one.
  Removed packs stay on past purchases as a snapshot. At least one pack must stay on sale.
- **Subscription cost in credits**: the credits a reseller spends per duration and
  device count.
- **Reseller free trial limits**: the default for every reseller, counted per reseller:
  per day (rolling 24 hours), per week (7 days), per month (30 days) and running at
  once. Each is unlimited or a number; 0 switches trials off.

## Subscriptions, account details and Telegram usernames

- **Subscriptions** lists every delivered account in one place: direct customers'
  subscriptions and trials, and the ones resellers created. Each row shows the account
  username and password; filter by direct/reseller, subscription/trial and
  active/expired, or search by account username, Telegram ID, @username or the
  reseller's customer note. Renewals and trial upgrades are shown once, as the login
  they extend.
- **Trials and Subscriptions pages** share one layout that keeps your own customers
  and resellers' customers visibly apart: filters for All / Your customers / Resellers /
  Expired, a search box, a green "Direct customers" section, then one violet section per
  reseller (folded by default when there are several, with Expand all), then a grey
  Expired section. Rows in mixed lists carry a Direct or Reseller badge in the same
  colours, which the logs use too. Trial orders that never produced a login (queued or
  in review) stay under Orders, filtered to trials.
- **Screen sizes**: below 1024px the sidebar is a slide-in drawer (with order search
  inside it on phones); below 768px every list (orders, accounts, resellers, tickets,
  both logs) is shown as cards instead of a table; page actions wrap onto their own row.
- **A reseller is a full page** (`/resellers/<telegram id>`): credits, activity, trial
  usage and limits, credit adjustment, suspend, recent credit history, and their own
  Subscriptions and Trials lists with search and an Expired section.
- **Telegram usernames**: the bot records a customer's current @username whenever they
  message it or tap a button (`tg_username:<id>` in metadata). For customers who have
  not used the bot since, it asks Telegram (`getChat`) in small background batches, so
  existing customers fill in within minutes of the bot starting. "No username set"
  means the person has no @username on Telegram or never started the bot; those are
  re-checked weekly. The numeric Telegram ID remains the identity.
- **Add subscription** gives a Telegram user a membership without payment: pick the
  plan and give a reason. The normal worker creates a real panel line and the bot
  sends the login. It is not counted as revenue, and the customer can renew it later
  by paying. Refused while panel account creation is switched off.
- **Delete** asks for confirmation and a reason. It removes the account from the
  dashboard list and, for a direct subscription, from the customer's bot; a reseller's
  account also leaves the reseller's list. It never cancels the line on the IPTV panel,
  refunds no credits, and keeps the order for reports. A deleted trial still counts as
  the customer's one free trial.
- **Resellers → open a reseller** shows that reseller's subscriptions and trials, how
  many trials they have used in each window, and lets the owner give that one reseller
  its own limits (or leave any window on the default).
- **Logs** has two tabs, both built from this system's own records (nothing is read
  from the IPTV panel) and both filterable by reseller:
  - *Activity log*: every line created or extended, by a reseller or as a direct sale,
    with the account username and password, the package, and the reseller's credits
    before and after.
  - *Credit log*: every change to a reseller's balance. It opens on top-ups and manual
    adjustments (who made them and why); "Credits used" and "Everything" add the
    deductions. Balances are replayed from the reseller ledger.
  Each reseller's page links straight to their activity and credit logs.
- **Creating things as the owner** (each needs a reason where money or accounts are
  involved, and is audited):
  - *Resellers → Add reseller*: makes a Telegram user an active reseller without a
    pack purchase, optionally with starting credits (recorded as a manual adjustment).
    Refused if they are already active or suspended.
  - *Subscriptions → Add trial or subscription*: besides paid plans, the owner can
    start a customer's 24-hour trial. The one-trial-per-Telegram-user rule still
    applies; the public daily trial allowance does not.
  - *Tickets → New ticket* (also on a reseller's page and on an order): opens a ticket
    addressed to a customer or reseller and sends the message in Telegram. Their reply
    lands on the same ticket. Telegram only delivers to people who have started the
    bot; the dashboard says when delivery failed.
- None of this adds tables or columns: usernames, deletions and per-reseller limits
  live in the existing `metadata` and `rs_settings` tables, so Publish has no schema
  change to apply.

## Support tickets

Tickets replace the old support chat relay. A customer or reseller taps Contact support
in the bot (or opens Support in the reseller panel), picks a topic and writes one
message; the owner receives a Telegram notification and the ticket appears under
Tickets in the dashboard with a "Needs reply" badge in the sidebar.

- Answer from the dashboard (Tickets → open a row → Send reply) or by replying to the
  Telegram notification. Both store the answer on the ticket and send it to the
  customer in Telegram with Reply / Close buttons. `/close TICKET` closes one from Telegram.
- Statuses: open (needs reply), answered, closed. A customer reply reopens a ticket.
- Bodies are sealed at rest; the bridge only ever exposes them to the verified owner.
- Tables `tk_tickets` and `tk_messages` are in `sql/schema.sql`; create them on
  PostgreSQL before publishing (see RESELLER_SETUP.md).

## Bot FAQ

Settings → Bot FAQ holds the questions and answers customers see under FAQ in the Telegram
bot. Add, reorder, edit or remove entries and press Save FAQ; changes show in the bot
straight away. Up to 30 entries, questions up to 120 characters, answers up to 1500. While
the list is empty the bot hides the FAQ button and offers Support in its place.
