"""Additive, portable reseller schema. PostgreSQL is applied to development only."""

SCHEMA = """
CREATE TABLE IF NOT EXISTS rs_resellers (
 id TEXT PRIMARY KEY, telegram_id BIGINT NOT NULL UNIQUE CHECK(telegram_id>0),
 username TEXT NOT NULL DEFAULT '', status TEXT NOT NULL CHECK(status IN ('pending','active','suspended')),
 created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS rs_accounts (
 reseller_id TEXT PRIMARY KEY REFERENCES rs_resellers(id),
 balance BIGINT NOT NULL DEFAULT 0, reserved BIGINT NOT NULL DEFAULT 0,
 CHECK(balance>=0 AND reserved>=0 AND balance>=reserved)
);
CREATE TABLE IF NOT EXISTS rs_packages (
 id TEXT PRIMARY KEY, price_pence BIGINT NOT NULL CHECK(price_pence>0),
 credits BIGINT NOT NULL CHECK(credits>0), active BIGINT NOT NULL CHECK(active IN (0,1)),
 updated_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS rs_costs (
 months BIGINT NOT NULL CHECK(months IN (1,3,6,9,12)),
 connections BIGINT NOT NULL CHECK(connections BETWEEN 1 AND 3),
 credits BIGINT NOT NULL CHECK(credits>0), updated_at BIGINT NOT NULL,
 PRIMARY KEY(months,connections)
);
CREATE TABLE IF NOT EXISTS rs_purchases (
 id TEXT PRIMARY KEY REFERENCES orders(id), reseller_id TEXT NOT NULL REFERENCES rs_resellers(id),
 package_snapshot TEXT NOT NULL, amount_pence BIGINT NOT NULL CHECK(amount_pence>0),
 credits BIGINT NOT NULL CHECK(credits>0), payment_reference TEXT UNIQUE,
 status TEXT NOT NULL CHECK(status IN ('pending','granted')),
 created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS rs_operations (
 id TEXT PRIMARY KEY, request_key TEXT NOT NULL UNIQUE, reseller_id TEXT NOT NULL REFERENCES rs_resellers(id),
 operation_type TEXT NOT NULL CHECK(operation_type IN ('create','trial','extend')),
 target_id TEXT, months BIGINT NOT NULL, connections BIGINT NOT NULL CHECK(connections BETWEEN 1 AND 3),
 adult BIGINT NOT NULL CHECK(adult IN (0,1)), customer_ref TEXT NOT NULL,
 credit_cost BIGINT NOT NULL CHECK(credit_cost>=0),
 reservation TEXT NOT NULL CHECK(reservation IN ('held','charged','released')),
 status TEXT NOT NULL CHECK(status IN ('queued','preparing','processing','uncertain','succeeded','failed')),
 package_id TEXT NOT NULL, provider_context TEXT, result_id TEXT, error TEXT NOT NULL DEFAULT '',
 created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS rs_subscriptions (
 id TEXT PRIMARY KEY, reseller_id TEXT NOT NULL REFERENCES rs_resellers(id), provider_id TEXT NOT NULL UNIQUE,
 customer_ref TEXT NOT NULL, kind TEXT NOT NULL CHECK(kind IN ('trial','paid')),
 connections BIGINT NOT NULL CHECK(connections BETWEEN 1 AND 3), adult BIGINT NOT NULL CHECK(adult IN (0,1)),
 starts_at BIGINT NOT NULL, expires_at BIGINT NOT NULL, status TEXT NOT NULL,
 credentials TEXT NOT NULL, confirmed_at BIGINT NOT NULL, created_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS rs_extensions (
 id TEXT PRIMARY KEY, subscription_id TEXT NOT NULL REFERENCES rs_subscriptions(id),
 reseller_id TEXT NOT NULL REFERENCES rs_resellers(id), operation_id TEXT NOT NULL UNIQUE REFERENCES rs_operations(id),
 months BIGINT NOT NULL, credits BIGINT NOT NULL, previous_expiry BIGINT NOT NULL,
 confirmed_expiry BIGINT NOT NULL, created_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS rs_ledger (
 id TEXT PRIMARY KEY, reseller_id TEXT NOT NULL REFERENCES rs_resellers(id), movement BIGINT NOT NULL,
 reason TEXT NOT NULL, reference TEXT NOT NULL UNIQUE, administrator BIGINT, created_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS rs_settings (
 key TEXT PRIMARY KEY, value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rs_audit (
 id TEXT PRIMARY KEY, administrator BIGINT NOT NULL, action TEXT NOT NULL, subject TEXT NOT NULL,
 reason TEXT NOT NULL, details TEXT NOT NULL, created_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS rs_logins (
 reseller_id TEXT PRIMARY KEY REFERENCES rs_resellers(id),
 email TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, updated_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS rs_web_codes (
 code_hash TEXT PRIMARY KEY, reseller_id TEXT NOT NULL REFERENCES rs_resellers(id), expires_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS rs_login_requests (
 poll_hash TEXT PRIMARY KEY, code_hash TEXT NOT NULL UNIQUE, reseller_id TEXT REFERENCES rs_resellers(id),
 created_at BIGINT NOT NULL, expires_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS rs_web_sessions (
 token_hash TEXT PRIMARY KEY, reseller_id TEXT NOT NULL REFERENCES rs_resellers(id),
 created_at BIGINT NOT NULL, expires_at BIGINT NOT NULL, last_seen BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS rs_operations_state ON rs_operations(status,created_at);
CREATE INDEX IF NOT EXISTS rs_subscriptions_owner ON rs_subscriptions(reseller_id,expires_at);
CREATE INDEX IF NOT EXISTS rs_ledger_owner ON rs_ledger(reseller_id,created_at);
"""

# Columns added after the first release. Each statement is applied on its own and a
# "duplicate column" error is ignored, so SQLite databases upgrade in place. PostgreSQL
# never receives DDL from the application: run these by hand on development, then Publish.
MIGRATIONS = [
    "ALTER TABLE rs_subscriptions ADD COLUMN contact TEXT NOT NULL DEFAULT ''",
    "ALTER TABLE rs_subscriptions ADD COLUMN converted_at BIGINT",
    "ALTER TABLE rs_subscriptions ADD COLUMN deleted_at BIGINT",
]
