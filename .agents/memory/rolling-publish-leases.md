---
name: Rolling-publish leases
description: Avoid mistaking a previous published version's worker lease for a stale database lock.
---

A busy application-instance advisory lock during republishing is not evidence
of a corrupt database or an unmanaged duplicate bot.

**Why:** The first live publish succeeded, but the next version repeatedly exited
with “Another application instance is already running for this database schema.”
The previous published version still held the legitimate session lease. Requiring
the replacement to own that lease before responding to its startup probe prevented
the replacement from becoming live.

**How to apply:** Check for old/new revision overlap before proposing stale-lock
cleanup, terminating database sessions or resetting state. Keep the exclusive
worker safety guarantee and support a safe application-level handoff instead.
Successful publishing alone is not proof that standby has finished and the bot's
workers are active.
