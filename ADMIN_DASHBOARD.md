# Streamline website administration

The `/admin/` portal uses Replit sign-in, explicitly selected by the user. It is
separate from the original checkout. Signing in or being the first signup never
grants administration. No Telegram administrator ID is required for website access.

## First-owner setup

1. Store `STREAMBOT_WEB_ADMIN_EMAILS` as a Replit Secret with the intended owner's
   email (comma-separated for operational configuration). Do not use shared
   non-secret configuration: that writes the address into `.replit`.
2. Store a unique 20–200 character setup code as the workspace secret
   `STREAMBOT_WEB_BOOTSTRAP_CODE`. Keep a private copy to enter once on the website.
3. Open `/admin/`, choose Sign in, and use the intended Replit account. Its OIDC
   email must match the allowlist. If the provider explicitly marks the email
   unverified it cannot be used for owner setup.
4. Enter the setup code in the website's first-owner form. Both the authenticated
   account and the workspace-held proof are required. The server atomically binds
   ownership to the immutable Replit account ID. Another account cannot replace
   it, even with the same email or setup code.
5. Normal subsequent sign-ins need no setup code. An existing owner cannot be
   replaced through this form. Removing the email from the allowlist denies access
   on subsequent API requests after configuration is applied.

The code is not stored in browser storage. Requests and provider responses
containing credentials, tokens or setup codes must never be logged.

## Publishing

Production needs the same owner email configuration and setup-code secret. Publish
the development schema normally: Replit Auth adds `public.users` and
`public.sessions`. The dashboard does not change existing business schemas or
create production tables at startup. Do not use “overwrite production data.”

Development and published application sessions/data are separate. Complete the
first-owner form on the published site too. Never copy development session rows
to production. The owner binding and recovery drafts/audits use the bot's existing
encrypted metadata store (owner identity itself is a nonsecret subject identifier).

## Operational scope and safeguards

- Overview is actual stored order counts, not revenue or active-subscription estimates.
- Orders are paginated and searchable by ID or exact Telegram ID. Details exclude
  credentials, checkout tokens and raw provider errors.
- Readiness reports configuration and optional-schema availability. It is not an
  upstream panel, blockchain node or Telegram health probe.
- Trial recovery shares the original validator, fingerprint and atomic confirmation
  transaction with Telegram recovery. Drafts bind to the website account and session.
- Preview never queues an account. Explicit operator attestation that creation never
  started is mandatory; missing credentials alone are not proof.
- Confirmation queues the original trial, not a replacement entitlement. Possibly
  submitted creations remain blocked. See `TRIAL_RECOVERY.md`.
- Audits record actor, session digest, timestamp, prior fingerprint and attestation.
  No plaintext session token or account credentials are shown in dashboard responses.

## Gateway and lifecycle

The API service supervises one unchanged Python business backend on a loopback-only
allocated port. Node performs OIDC signature/issuer/audience/PKCE/state/nonce
verification and checks the explicit owner binding on every administrative request.
Opaque session cookies are HttpOnly, Secure and SameSite=Lax; logout deletes the
server-side session. Administrative mutations also require same-origin JSON.

Narrowly allowlisted internal requests are signed with a fresh process-only HMAC
key. Python checks method, path, body, actor, timestamp and one-use nonce. Public
requests cannot reach internal routes or provide privileged actor headers.
Existing checkout requests are streamed before body parsing. Python continues to
own the database, strict financial verification, panel provisioning, worker lease
and Telegram polling. Preview remains demo-only with Telegram/provider writes off.

Tests use isolated temporary state or development data, with mocked providers.
No live trial recovery, payment approval, panel creation or broadcast is required
to verify the dashboard.
