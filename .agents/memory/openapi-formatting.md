---
name: Generated source formatting
description: Formatting is part of the generated-source contract, not optional polish.
---

Generated source must be formatted explicitly as part of code generation.

**Why:** The gateway's whitespace validation also applies to generated files;
optional generator formatting settings are not a reliable guarantee.

**How to apply:** Preserve formatting in the generation command when replacing or
upgrading code-generation tools.
