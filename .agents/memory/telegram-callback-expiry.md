---
name: Telegram callback expiry
description: Prevent expired inline-button acknowledgements from stalling the polling queue.
---

Telegram callback acknowledgements expire quickly. A 400 from acknowledging an old inline-button click must not cause indefinite replay of the same update. Continue safe handling and let the polling offset advance; do not suppress errors from unrelated API operations.

**Why:** After a restart, retrying an expired acknowledgement blocked all later bot messages even though the web application was healthy.

**How to apply:** Handle acknowledgement expiry separately from send failures, rate limits, authorization errors, and other failures that still need explicit retry or reporting.
