-- Development schema source of truth. Replit Publish applies its schema diff
-- to the managed production database. Never run this from startup or deploy build.
BEGIN;
CREATE SCHEMA IF NOT EXISTS stream_panel_bot_live;
SET LOCAL search_path = stream_panel_bot_live, pg_catalog;

CREATE TABLE IF NOT EXISTS orders (
    id TEXT PRIMARY KEY,
    token_hash TEXT UNIQUE,
    kind TEXT NOT NULL,
    telegram_id BIGINT UNIQUE,
    plan_json TEXT NOT NULL,
    asset_json TEXT NOT NULL,
    amount_units TEXT NOT NULL,
    created_at BIGINT NOT NULL,
    expires_at BIGINT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    txid TEXT,
    message TEXT NOT NULL DEFAULT '',
    credentials TEXT,
    attempts INTEGER NOT NULL DEFAULT 0,
    last_check BIGINT NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS payments (
    network TEXT NOT NULL,
    txid TEXT NOT NULL,
    order_id TEXT NOT NULL UNIQUE REFERENCES orders(id),
    proof TEXT NOT NULL,
    PRIMARY KEY(network, txid)
);
CREATE TABLE IF NOT EXISTS links (
    code_hash TEXT PRIMARY KEY,
    order_id TEXT NOT NULL REFERENCES orders(id),
    expires_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS account_links (
    telegram_id BIGINT NOT NULL,
    order_id TEXT NOT NULL REFERENCES orders(id),
    PRIMARY KEY(telegram_id, order_id),
    UNIQUE(order_id)
);
CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS limits (bucket TEXT NOT NULL, at BIGINT NOT NULL);

CREATE INDEX IF NOT EXISTS limits_bucket ON limits(bucket, at);
CREATE INDEX IF NOT EXISTS orders_state ON orders(status, last_check, created_at);
CREATE INDEX IF NOT EXISTS orders_asset_expiry ON orders ((asset_json::jsonb ->> 'id'), expires_at);
CREATE INDEX IF NOT EXISTS orders_trial_created ON orders(created_at) WHERE kind = 'trial';
CREATE INDEX IF NOT EXISTS links_order ON links(order_id);


-- Support tickets (tickets.py). Message bodies are sealed by the application.
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

-- Legitimate initial app state, not sample customer/payment data. Keep initial
-- development-data copying enabled when creating the first production database.
INSERT INTO metadata(key, value) VALUES ('mode', 'live') ON CONFLICT (key) DO NOTHING;
COMMIT;
