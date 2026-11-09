# One-order overpayment approval

The numeric support administrator can explicitly approve a verified Ethereum
USDC overpayment for one retail membership invoice. This is not a tolerance
setting: normal verification still requires the exact quoted amount.

## Steps

1. Publish this code update. It uses existing `orders`, `payments` and encrypted
   `metadata` storage; it requires no reseller/notification tables or new schema.
2. In a private bot chat, the configured administrator sends:

   `/approveoverpayment ORDER_ID ETHEREUM_TXID`

3. The bot verifies the original invoice's recipient, official token, network,
   payment window, required confirmations and Ethereum finalization. If the
   provider cannot prove any of those, no preview/approval is permitted.
4. The preview shows the quoted amount, actual received amount, excess, wallet
   and TXID. Check all values before choosing **Approve this order only**.
5. Confirmation performs a fresh blockchain verification and requires the same
   received amount. A single transaction claims the payment, marks the existing
   order paid, records an encrypted administrator audit and consumes the preview.
6. The normal worker provisions the membership and sends its credentials. This
   command does not itself create panel accounts or bypass panel safeguards.

The original quote stays unchanged. The payment proof records the full amount
actually received. **No automatic refund, wallet transfer, transferable balance,
or credit for the excess is created.** Any separate handling of an excess
requires a separate, authorized action.

## Safety

- Only pending retail membership orders using Ethereum USDC are eligible.
  Trial and reseller credit-purchase orders cannot use this exception.
- Previews expire after ten minutes and are bound to one order, hash and received
  amount. New previews replace older ones. Changed invoice terms invalidate them.
- TXIDs already claimed by another order cannot be reused. The payment claim,
  paid status, encrypted audit and preview consumption are atomic.
- A TXID cleared by normal exact-amount rejection can still be inspected by the
  administrator explicitly providing it in the command; clearing is not approval.
- A delayed background verification result cannot clear a newly approved payment
  or overwrite a newer submitted TXID.
- Cancellation leaves the order unchanged. Repeated confirmation does not create
  another payment or another order.
- If the success message fails to arrive, inspect order status before trying
  again; Telegram delivery failure does not mean the database transaction failed.

Tests mock the blockchain and panel. PostgreSQL integration tests run only
against managed development and roll back their writes. Development never
approves real orders or performs production DDL.
