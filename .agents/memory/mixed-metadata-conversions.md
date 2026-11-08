---
name: Mixed metadata conversions
description: PostgreSQL evaluation order makes numeric casts on mixed text/encrypted metadata unsafe without an expression-level guard.
---

Do not assume an AND condition on a metadata key protects a numeric cast of its
value. Guard the conversion inside CASE, including bigint overflow, rather than
relying on predicate order.

**Why:** A fulfilled trial's notification query repeatedly failed in production by
casting unrelated text settings to bigint. A small rollback-only development
notification fixture passed, but the actual read-only production query reproduced
the conversion error. The guarded query succeeded against the same production
state, without deleting or rewriting any legitimate metadata.

**How to apply:** Metadata intentionally mixes timestamps, text settings and
encrypted routing/session state. Validate numeric shape and bounds inside the cast
expression. Include direct nonnumeric/overflow cases in PostgreSQL tests; do not
treat a passing small-fixture query plan as proof that a cast is safe in production.
