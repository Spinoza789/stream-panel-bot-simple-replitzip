---
name: Panel provisioning contract
description: External panel submission behavior and safe recovery after uncertain creation.
---

All account generation, including trials and paid memberships, must leave
username and password empty so the panel generates random credentials. Leave the
description empty; the user does not want any notes at all.

**Why:** The user explicitly requested this after seeing a trial with a
bot-assigned username and an order-reference note.

**How to apply:** Do not insert bot branding, order references or tracking markers
into panel account notes or credential fields. Keep internal order association
inside the bot's own storage.

Treat the panel's browser submission logic as the contract, not merely the raw
HTML form or package JSON. The hidden current_bouquets field is populated by the
browser as comma-separated bouquet IDs, not a JSON array.

**Why:** Read-only login, package inspection and creation preflight all succeeded,
but the first real trial entered review. Inspecting the panel's submission script
exposed a serialization mismatch not covered by those checks.

**How to apply:** Test exact submitted payloads against the observed browser
behavior when modifying this connector. Do not equate authentication or a guarded
preflight with successful live account delivery.

