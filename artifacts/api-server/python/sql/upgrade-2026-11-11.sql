-- Streamline: additive schema upgrade for PostgreSQL (safe to run more than once).
-- Run against the DEVELOPMENT database in Replit, then Publish so the schema reaches production.
-- Covers: reseller web portal, Log in with Telegram, customer notes/conversion/delete, support tickets.
BEGIN;
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
ALTER TABLE rs_subscriptions ADD COLUMN IF NOT EXISTS contact TEXT NOT NULL DEFAULT '';
ALTER TABLE rs_subscriptions ADD COLUMN IF NOT EXISTS converted_at BIGINT;
ALTER TABLE rs_subscriptions ADD COLUMN IF NOT EXISTS deleted_at BIGINT;
CREATE TABLE IF NOT EXISTS tk_tickets (
 id TEXT PRIMARY KEY, telegram_id BIGINT NOT NULL CHECK(telegram_id>0), username TEXT NOT NULL DEFAULT '',
 topic TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('open','answered','closed')),
 channel TEXT NOT NULL, reseller BIGINT NOT NULL DEFAULT 0 CHECK(reseller IN (0,1)),
 created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL, closed_at BIGINT
);
CREATE TABLE IF NOT EXISTS tk_messages (
 id TEXT PRIMARY KEY, ticket_id TEXT NOT NULL REFERENCES tk_tickets(id),
 sender TEXT NOT NULL CHECK(sender IN ('customer','support')), body TEXT NOT NULL,
 actor TEXT NOT NULL DEFAULT '', created_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS tk_tickets_owner ON tk_tickets(telegram_id,updated_at);
CREATE INDEX IF NOT EXISTS tk_tickets_status ON tk_tickets(status,updated_at);
CREATE INDEX IF NOT EXISTS tk_messages_ticket ON tk_messages(ticket_id,created_at);
COMMIT;
