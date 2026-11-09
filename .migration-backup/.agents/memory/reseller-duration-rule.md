---
name: Reseller duration rule
description: The user-confirmed meaning of a provider's 12-month term.
---

The provider defines a 12-month subscription as **12 calendar months**.

**Why:** The user explicitly confirmed “12 calendar months” when asked to
distinguish it from 365 days.

**How to apply:** Do not hardcode a 365-day renewal. Use the provider's quoted and
confirmed expiry, preserving existing time on active subscriptions, and display
the result in Europe/London. Leap years and timezone transitions must not be
converted into a fixed number of days.
