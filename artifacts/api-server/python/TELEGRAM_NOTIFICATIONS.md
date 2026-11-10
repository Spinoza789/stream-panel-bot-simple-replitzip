# Telegram reminders and deals

Publish the update and its additive development database schema before these
features appear in the live bot. No production database writes or real
announcements are performed during development verification.

## Customer controls

Open **More → Notifications & deals** or send `/notifications`. The option is also
on the reseller menu.

- Expiry reminders default to on.
- Paid subscriptions receive reminders in the 7-day, 3-day and 1-day windows.
- Trials and subscriptions receive an expired alert within 24 hours of expiry.
  Older expired accounts are not backfilled with stale messages.
- Deals default to off and require each recipient to opt in.
- `/stopdeals` disables deals. `/stop` disables both reminders and deals.
  Starting the bot again does not silently change those preferences.
- Reseller customer reminders go to the reseller who owns the record, not to
  an unverified customer contact.

Expiry is checked against the panel using read-only requests. Messages show
Europe/London time and never include passwords. Unreachable or unverifiable
provider status defers reminders; a renewal or ownership change invalidates
queued reminders for the old expiry.

## Administrator announcements

Only the configured numeric support/financial administrator may send offers.

1. Send `/announce Your offer text here` (up to 2,500 UTF-16 characters).
2. Choose all opted-in users, retail users, or approved resellers.
3. Review the text, audience and recipient count.
4. Press **Confirm send**, or **Discard draft**.

Each preview lasts 15 minutes and is bound to the exact audience snapshot.
New opt-ins after the preview are not silently added. Subsequent opt-outs and
blocked/suspended recipients are respected before delivery.

Use `/announcements` or **Manage announcements** in notification settings to see
the last five campaigns and sent/retry/failed/blocked/unknown counts. Pending
campaigns can be cancelled; already delivered messages cannot be recalled.
An announcement can contain a deal, service update or other approved message.
It does not automatically alter membership prices, grant credits or charge users.

## Reliability

- The existing Telegram worker sends bounded batches; no second poller is created.
- Campaigns, recipient preferences and individual delivery states survive restarts.
- Each account/expiry/reminder window has a unique delivery key.
- Telegram rate limits postpone sends, and blocked chats stop future attempts.
- Ambiguous network results or a crash after submission are recorded as
  `uncertain`, not automatically replayed. Telegram does not provide an
  idempotency key for `sendMessage`, so exactly-once remote delivery cannot be
  guaranteed. This deliberately avoids blind duplicate broadcasts.
- The delivery ledger contains no customer login credentials.
