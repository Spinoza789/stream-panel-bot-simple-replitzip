---
name: Production database readiness
description: Why successful workspace checks alone cannot establish live publishing readiness.
---

Validate production database provisioning separately from development connectivity
before declaring the live bot ready. Presence of a managed connection variable is
not evidence that a separate production database exists.

**Why:** Live configuration and rollback-only PostgreSQL tests passed in the
workspace, but the published VM failed during database initialization while the
database service reported no production database. Workspace-only connectivity did
not test the published hosting environment.

**How to apply:** Confirm production database creation is enabled in Publishing and
that the prepared development schema will be included. If production does not
exist, report that setup blocker rather than recommending repeated unchanged
publishes or pointing real orders at the development database. Keep production
schema changes within the Publish flow.
