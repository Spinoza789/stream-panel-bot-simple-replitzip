---
name: Trial eligibility
description: The user's one-trial-per-Telegram-user business rule.
---

Ordinary retail customers: “Only one telegram user can order one trial not more.”

**Why:** The user explicitly requested one ordinary trial per Telegram user, then
separately specified administrator-approved resellers creating customer trials
under configurable daily and active-trial limits.

**How to apply:** Key eligibility to the numeric Telegram account ID, not its
changeable username. Expiry, restarts and repeated requests must not grant a new
trial. Safe recovery can complete the original request, not create a new
entitlement. Approved reseller customer trials are a separate entitlement with
administrator-configured limits; they must not reset or reuse the ordinary
customer's lifetime eligibility record.
