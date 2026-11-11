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
- Orders are paginated/searchable by ID or exact Telegram ID. Details exclude
  credentials, checkout tokens and raw provider errors.
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

