# Administrator recovery of an unsubmitted trial

This feature uses the existing orders and encrypted metadata storage. No new
database tables or schema changes are required, and missing reseller/notification
tables do not disable it. Publish the code update before using it in the live bot.

## Use

1. In a **private chat** with the bot, the configured numeric support administrator
   sends `/recovertrial` to list the latest ten retail trials in review. Alternatively,
   send `/recovertrial ORDER_ID` for a specific order.
2. Select the original trial and read the preview. Merely opening a preview does
   not requeue an order or call the panel.
3. Verify provisioning logs/source evidence that no account-creation request was
   submitted. **Empty stored details alone are not proof.** If a request may have
   been submitted, cancel and identify/reconcile the existing account manually.
4. Only after that check, select **I verified creation never started**. Or select
   **Cancel recovery** to leave the order untouched.
5. The original order returns to the worker queue. The worker performs its normal
   fresh panel checks, submits blank username/password/description, and delivers
   confirmed credentials through the existing trial delivery path. The customer
   can check with `/trial`.

## Safeguards

- Only the configured support administrator can list, preview, confirm or cancel.
  Recovery is independent of reseller approval and does not grant reseller access.
- A trial must still be in review and have either no saved details or an explicit
  panel-generated `post_attempted=false` marker. Saved legacy credentials and
  any possibly submitted generation are blocked, even for administrators.
- Missing-details recovery is an **explicit operator override** after investigation,
  not an automatic inference that no account exists.
- Preview expires after ten minutes. A new preview invalidates older buttons.
  Changed order identity/state/details invalidate confirmation.
- Confirmation, queue transition, audit and consumption of the one-use preview
  are one transaction. Repeated or concurrent confirmations cannot requeue twice.
- No new order or entitlement is created. The original numeric Telegram owner and
  lifetime-trial record remain unchanged. Panel creation must be enabled in live mode.
- Encrypted audit metadata records administrator, order, timestamp and explicit
  no-submission attestation. It contains no panel password.
- If Telegram fails to show the confirmation receipt, do not assume it failed:
  inspect `/trial` or open a fresh `/recovertrial` list before taking further action.

Tests use mocked panel clients. The opt-in PostgreSQL integration test uses the
managed development database and rolls back its writes; no live recovery is run
by development tests.
