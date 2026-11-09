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

The observed blank-field creation response contains only a redirect to the account
list, not a new account ID or credentials. Empty descriptions are rendered by the
panel as a dash placeholder.

**Why:** One explicitly approved zero-credit test submitted all three fields empty.
Its native AJAX response did not identify the new account. Read-only inspection
also showed that an edit form contains username/password but no package selector,
so those fields alone do not identify a login page.

**How to apply:** Require an acknowledged creation and an unambiguous complete
before/after account-ID comparison, then verify the new record through its edit
form. Never choose the first row or assume the listing is sorted newest-first.
Unknown post-submit identity requires manual review, not an automatic second POST.

Treat the panel's browser submission logic as the contract, not merely the raw
HTML form or package JSON. The hidden current_bouquets field is populated by the
browser as comma-separated bouquet IDs, not a JSON array.

**Why:** Read-only login, package inspection and creation preflight all succeeded,
but the first real trial entered review. Inspecting the panel's submission script
exposed a serialization mismatch not covered by those checks.

**How to apply:** Test exact submitted payloads against the observed browser
behavior when modifying this connector. Do not equate authentication or a guarded
preflight with successful live account delivery.

