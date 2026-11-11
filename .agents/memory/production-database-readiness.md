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
that initialized development state will be included, not just empty tables.
Initialize legitimate application metadata, never fake customer orders or
payments, before the first live publish. If production does not
exist, report that setup blocker rather than recommending repeated unchanged
publishes or pointing real orders at the development database. Keep production
schema changes within the Publish flow.

Do not reject a platform-managed connection solely from its hostname.

**Why:** Private managed proxies can use aliases whose names alone do not establish
database identity or reachability. A guessed hostname restriction can itself
prevent startup before the driver has attempted a connection.

**How to apply:** Honor the runtime-managed connection and verify actual production
provisioning and connectivity; keep errors secret-safe and avoid copied development
connection strings.

Compare actual table catalogs when a schema readiness error contradicts the
Publish schema-diff report.

**Why:** The schema-diff helper reported no changes while read-only catalog queries
showed reseller and notification tables present in development but absent from
managed production. A no-diff result alone did not establish schema parity;
a subsequent successful republish also left required columns absent.

**How to apply:** Check both environments in the application's private schema.
If the Publish dialog also omits the missing tables, investigate the migration
failure rather than promising that another unchanged publish will fix it. Do not
bypass the managed production migration rules or overwrite production data.
