---
name: Trial eligibility
description: The user's one-trial-per-Telegram-user business rule.
---

“Only one telegram user can order one trial not more.”

**Why:** The user explicitly requested one trial per Telegram user, not a
renewing daily allowance.

**How to apply:** Key eligibility to the numeric Telegram account ID, not its
changeable username. Expiry, restarts and repeated requests must not grant a new
trial. Safe recovery can complete the original request, not create a new
entitlement.
