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
COMMIT;
