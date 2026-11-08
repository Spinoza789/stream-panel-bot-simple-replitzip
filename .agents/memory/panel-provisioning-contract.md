---
name: Panel provisioning contract
description: External panel submission behavior and safe recovery after uncertain creation.
---

Treat the panel's browser submission logic as the contract, not merely the raw
HTML form or package JSON. The hidden current_bouquets field is populated by the
browser as comma-separated bouquet IDs, not a JSON array.

**Why:** Read-only login, package inspection and creation preflight all succeeded,
but the first real trial entered review. Inspecting the panel's submission script
exposed a serialization mismatch not covered by those checks.

**How to apply:** Test exact submitted payloads against the observed browser
behavior when modifying this connector. Do not equate authentication or a guarded
preflight with successful live account delivery.

