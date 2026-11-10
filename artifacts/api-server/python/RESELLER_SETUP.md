# Credit-based resellers

The existing Telegram bot now has a **Reseller area**. Send `/reseller` to open it.
This is a Telegram interface backed by the existing Replit application/database,
not a separate website or payment service.

## Access and administration

- Your existing numeric `SUPPORT_ADMIN_ID` is the reseller/financial administrator.
  Telegram usernames never grant account ownership or administrative authority.
- Anyone can apply with one tap from **Become A Reseller**. The administrator is
  messaged immediately with an **Approve** button, and can also open
  **Administration → Reseller accounts**. Applicants are told in Telegram when they
  are approved or suspended, and approved resellers land on a dashboard showing
  available credits and active / expiring / trial subscription counts.
- **Administration** also lists purchases, pending/failed operations, the audit log
  and current configuration, and explains all administrative commands.
- `/rsapprove TELEGRAM_ID reason` approves or resumes an account.
- `/rssuspend TELEGRAM_ID reason` blocks new purchases, creation, trials and
  extensions. Queued requests remain reserved and pause. An operation already
  submitted to the provider must still be reconciled; suspension cannot cancel a
  remote request already in flight.
- `/rsbalance TELEGRAM_ID` and `/rshistory TELEGRAM_ID [page]` show balances/history
  privately to the administrator, never to another reseller.
- `/rscredits TELEGRAM_ID signed_credits reason` is an audited adjustment.
  Negative adjustments cannot consume reserved credits.
- `/rspayment ORDER_ID network:TXID_or_bank:reference reason` manually confirms an
  actual payment. The reference must be unique and consistent with the real receipt.
  Repeating confirmation does not grant credits twice.

## Initial pricing

| Price | Credits |
| --- | --- |
| £100 | 34 |
| £200 | 75 |
| £300 | 129 |
| £400 | 192 |

Money is integer pence; credit quantities are integers. Purchases accumulate.
Existing crypto quotes and blockchain verification are reused; entering a TXID or
pressing “I've paid” never grants credits.

| Months | 1 connection | 2 connections | 3 connections |
| --- | --- | --- | --- |
| 1 | 1 | 2 | 3 |
| 3 | 3 | 4 | 5 |
| 6 | 6 | 7 | 8 |
| 9 | 9 | 10 | 11 |
| 12 | 12 | 15 | 20 |

Adult/no-adult prices are equal. Administrator changes affect future requests,
not the price/cost already captured on a purchase or confirmed operation.

- `/rspackage PACKAGE_ID PRICE_PENCE CREDITS ACTIVE_0_OR_1 reason`
- `/rscost MONTHS CONNECTIONS CREDITS reason`
- `/rstrials DAILY_LIMIT ACTIVE_LIMIT reason`

The initial reseller limits are **one customer trial per rolling 24 hours and one
active/pending trial**. Administrators can raise them or set zero to disable new
trials. Reseller trials are separate from ordinary customers' one lifetime trial.
Expired trials stay in history. References are stored in this application only;
they are never written into the provider's description/notes.

## Provider safety

- All new panel accounts still submit blank username, password and description.
  The panel generates credentials.
- Nine-month packages were verified read-only: no-adult 119–121, adult 122–124.
  Other paid mappings reuse the existing verified membership configuration.
- Trial package 275 is one connection, 24 hours. Its adult profile is the native
  package profile; no-adult removes the verified adult-only bouquet difference
  between the native monthly profiles. Unsupported profiles fail explicitly.
- Renewal uses the observed native POST form `/lines/extend/{id}` and its
  read-only `/lines/packages` preview, including both native identity parameters.
- The provider defines 12 months as **12 calendar months** (owner confirmed).
  Actual expiry always comes from the provider; London times include GMT/BST.
- “Recorded start” is when this application confirmed activation, not a claim
  that the panel supplied an otherwise-unavailable creation timestamp.
- On 2026-11-08, an owner-approved live test created one one-month, one-connection,
  no-adult account and extended that same account once. Read-back confirmed
  generated credentials, blank notes, unchanged credentials/content/connections,
  retained existing time and two provider credits spent in total. The ledger
  test used an isolated encrypted local database; production reseller balances
  and existing customer accounts were not changed.
- Further paid provider tests require fresh permission; the approved two-credit
  test budget has been exhausted. The test account remains in the panel.
- No simulated provider is selected in live mode. The demo is explicitly
  labelled and keeps simulated accounts in its own encrypted demo state.

## Reservations and uncertain results

Confirmation creates a unique request and atomically holds credits. A successful
provider read-back commits the subscription, debit, ledger and extension history
in one database transaction. Definite pre-submit failures release the hold.

A timeout after submission is **not** proof of failure. Credits remain reserved;
the account operation is not submitted again automatically. **My Balance →
Requests** shows the reseller's requests. Another request with the same customer
reference is blocked while the previous request is unresolved; an empty reference
also permits only one unresolved request of that type.

The administrator can use **Pending / failed operations → Reconcile**, or
`/rsreconcile OPERATION_ID [PROVIDER_ID]`. This only reads the panel, verifies the
account/profile/expiry, and completes the existing ledger entry. For ambiguous
new-account identification, supply a positively identified provider ID. Existing
pre-request accounts and accounts already attached to other completed operations
cannot be silently reused. Unknown results are never automatically refunded.

## Schema and publishing

The additive schema source is `streambot/reseller_schema.py`. It is applied to
local SQLite during local initialization. The new tables have also been applied
to the **managed development PostgreSQL** schema, without modifying production.

Publish the app normally so Replit applies the development schema additions to
the managed production database. Do **not** overwrite production data, run custom
production migration scripts, or add DDL to startup/build commands.

There is no automatic conversion of existing retail customers into approved
resellers, no transfer of existing customer accounts, and no automatic credit
grant. New accounts start pending with zero balance.
