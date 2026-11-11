"""Support ticket tables. SQLite creates them on start; PostgreSQL gets them through sql/schema.sql and Publish."""
SCHEMA = """
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
"""
