"""Additive notification tables; PostgreSQL schema changes go through Publish."""
SCHEMA = """
CREATE TABLE IF NOT EXISTS nt_contacts (
 telegram_id BIGINT PRIMARY KEY CHECK(telegram_id>0),
 alerts BIGINT NOT NULL DEFAULT 1 CHECK(alerts IN (0,1)),
 deals BIGINT NOT NULL DEFAULT 0 CHECK(deals IN (0,1)),
 blocked BIGINT NOT NULL DEFAULT 0 CHECK(blocked IN (0,1)),
 updated_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS nt_campaigns (
 id TEXT PRIMARY KEY, administrator BIGINT NOT NULL, body TEXT NOT NULL,
 audience TEXT NOT NULL, status TEXT NOT NULL, created_at BIGINT NOT NULL
);
CREATE TABLE IF NOT EXISTS nt_deliveries (
 id TEXT PRIMARY KEY, telegram_id BIGINT NOT NULL REFERENCES nt_contacts(telegram_id),
 kind TEXT NOT NULL, subject TEXT NOT NULL, campaign_id TEXT REFERENCES nt_campaigns(id),
 status TEXT NOT NULL, due_at BIGINT NOT NULL, attempts BIGINT NOT NULL DEFAULT 0,
 created_at BIGINT NOT NULL, updated_at BIGINT NOT NULL
);
CREATE INDEX IF NOT EXISTS nt_delivery_due ON nt_deliveries(status,due_at);
CREATE INDEX IF NOT EXISTS nt_campaign_deliveries ON nt_deliveries(campaign_id,status);
"""
