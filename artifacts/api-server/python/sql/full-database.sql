--
-- PostgreSQL database dump
--


-- Dumped from database version 18.6 (Ubuntu 18.6-1.pgdg22.04+2)
-- Dumped by pg_dump version 18.6 (Ubuntu 18.6-1.pgdg22.04+2)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: stream_panel_bot_live; Type: SCHEMA; Schema: -; Owner: -
--

CREATE SCHEMA stream_panel_bot_live;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: sessions; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.sessions (
    sid character varying NOT NULL,
    sess jsonb NOT NULL,
    expire timestamp without time zone NOT NULL
);


--
-- Name: users; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.users (
    id character varying DEFAULT gen_random_uuid() NOT NULL,
    email character varying,
    first_name character varying,
    last_name character varying,
    profile_image_url character varying,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: account_links; Type: TABLE; Schema: stream_panel_bot_live; Owner: -
--

CREATE TABLE stream_panel_bot_live.account_links (
    telegram_id bigint NOT NULL,
    order_id text NOT NULL
);


--
-- Name: limits; Type: TABLE; Schema: stream_panel_bot_live; Owner: -
--

CREATE TABLE stream_panel_bot_live.limits (
    bucket text NOT NULL,
    at bigint NOT NULL
);


--
-- Name: links; Type: TABLE; Schema: stream_panel_bot_live; Owner: -
--

CREATE TABLE stream_panel_bot_live.links (
    code_hash text NOT NULL,
    order_id text NOT NULL,
    expires_at bigint NOT NULL
);


--
-- Name: metadata; Type: TABLE; Schema: stream_panel_bot_live; Owner: -
--

CREATE TABLE stream_panel_bot_live.metadata (
    key text NOT NULL,
    value text NOT NULL
);


--
-- Name: nt_campaigns; Type: TABLE; Schema: stream_panel_bot_live; Owner: -
--

CREATE TABLE stream_panel_bot_live.nt_campaigns (
    id text NOT NULL,
    administrator bigint NOT NULL,
    body text NOT NULL,
    audience text NOT NULL,
    status text NOT NULL,
    created_at bigint NOT NULL
);


--
-- Name: nt_contacts; Type: TABLE; Schema: stream_panel_bot_live; Owner: -
--

CREATE TABLE stream_panel_bot_live.nt_contacts (
    telegram_id bigint NOT NULL,
    alerts bigint DEFAULT 1 NOT NULL,
    deals bigint DEFAULT 0 NOT NULL,
    blocked bigint DEFAULT 0 NOT NULL,
    updated_at bigint NOT NULL,
    CONSTRAINT nt_contacts_alerts_check CHECK ((alerts = ANY (ARRAY[(0)::bigint, (1)::bigint]))),
    CONSTRAINT nt_contacts_blocked_check CHECK ((blocked = ANY (ARRAY[(0)::bigint, (1)::bigint]))),
    CONSTRAINT nt_contacts_deals_check CHECK ((deals = ANY (ARRAY[(0)::bigint, (1)::bigint]))),
    CONSTRAINT nt_contacts_telegram_id_check CHECK ((telegram_id > 0))
);


--
-- Name: nt_deliveries; Type: TABLE; Schema: stream_panel_bot_live; Owner: -
--

CREATE TABLE stream_panel_bot_live.nt_deliveries (
    id text NOT NULL,
    telegram_id bigint NOT NULL,
    kind text NOT NULL,
    subject text NOT NULL,
    campaign_id text,
    status text NOT NULL,
    due_at bigint NOT NULL,
    attempts bigint DEFAULT 0 NOT NULL,
    created_at bigint NOT NULL,
    updated_at bigint NOT NULL
);


--
-- Name: orders; Type: TABLE; Schema: stream_panel_bot_live; Owner: -
--

CREATE TABLE stream_panel_bot_live.orders (
    id text NOT NULL,
    token_hash text,
    kind text NOT NULL,
    telegram_id bigint,
    plan_json text NOT NULL,
    asset_json text NOT NULL,
    amount_units text NOT NULL,
    created_at bigint NOT NULL,
    expires_at bigint NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    txid text,
    message text DEFAULT ''::text NOT NULL,
    credentials text,
    attempts integer DEFAULT 0 NOT NULL,
    last_check bigint DEFAULT 0 NOT NULL
);


--
-- Name: payments; Type: TABLE; Schema: stream_panel_bot_live; Owner: -
--

CREATE TABLE stream_panel_bot_live.payments (
    network text NOT NULL,
    txid text NOT NULL,
    order_id text NOT NULL,
    proof text NOT NULL
);


--
-- Name: rs_accounts; Type: TABLE; Schema: stream_panel_bot_live; Owner: -
--

CREATE TABLE stream_panel_bot_live.rs_accounts (
    reseller_id text NOT NULL,
    balance bigint DEFAULT 0 NOT NULL,
    reserved bigint DEFAULT 0 NOT NULL,
    CONSTRAINT rs_accounts_check CHECK (((balance >= 0) AND (reserved >= 0) AND (balance >= reserved)))
);


--
-- Name: rs_audit; Type: TABLE; Schema: stream_panel_bot_live; Owner: -
--

CREATE TABLE stream_panel_bot_live.rs_audit (
    id text NOT NULL,
    administrator bigint NOT NULL,
    action text NOT NULL,
    subject text NOT NULL,
    reason text NOT NULL,
    details text NOT NULL,
    created_at bigint NOT NULL
);


--
-- Name: rs_costs; Type: TABLE; Schema: stream_panel_bot_live; Owner: -
--

CREATE TABLE stream_panel_bot_live.rs_costs (
    months bigint NOT NULL,
    connections bigint NOT NULL,
    credits bigint NOT NULL,
    updated_at bigint NOT NULL,
    CONSTRAINT rs_costs_connections_check CHECK (((connections >= 1) AND (connections <= 3))),
    CONSTRAINT rs_costs_credits_check CHECK ((credits > 0)),
    CONSTRAINT rs_costs_months_check CHECK ((months = ANY (ARRAY[(1)::bigint, (3)::bigint, (6)::bigint, (9)::bigint, (12)::bigint])))
);


--
-- Name: rs_extensions; Type: TABLE; Schema: stream_panel_bot_live; Owner: -
--

CREATE TABLE stream_panel_bot_live.rs_extensions (
    id text NOT NULL,
    subscription_id text NOT NULL,
    reseller_id text NOT NULL,
    operation_id text NOT NULL,
    months bigint NOT NULL,
    credits bigint NOT NULL,
    previous_expiry bigint NOT NULL,
    confirmed_expiry bigint NOT NULL,
    created_at bigint NOT NULL
);


--
-- Name: rs_ledger; Type: TABLE; Schema: stream_panel_bot_live; Owner: -
--

CREATE TABLE stream_panel_bot_live.rs_ledger (
    id text NOT NULL,
    reseller_id text NOT NULL,
    movement bigint NOT NULL,
    reason text NOT NULL,
    reference text NOT NULL,
    administrator bigint,
    created_at bigint NOT NULL
);


--
-- Name: rs_login_requests; Type: TABLE; Schema: stream_panel_bot_live; Owner: -
--

CREATE TABLE stream_panel_bot_live.rs_login_requests (
    poll_hash text NOT NULL,
    code_hash text NOT NULL,
    reseller_id text,
    created_at bigint NOT NULL,
    expires_at bigint NOT NULL
);


--
-- Name: rs_logins; Type: TABLE; Schema: stream_panel_bot_live; Owner: -
--

CREATE TABLE stream_panel_bot_live.rs_logins (
    reseller_id text NOT NULL,
    email text NOT NULL,
    password_hash text NOT NULL,
    updated_at bigint NOT NULL
);


--
-- Name: rs_operations; Type: TABLE; Schema: stream_panel_bot_live; Owner: -
--

CREATE TABLE stream_panel_bot_live.rs_operations (
    id text NOT NULL,
    request_key text NOT NULL,
    reseller_id text NOT NULL,
    operation_type text NOT NULL,
    target_id text,
    months bigint NOT NULL,
    connections bigint NOT NULL,
    adult bigint NOT NULL,
    customer_ref text NOT NULL,
    credit_cost bigint NOT NULL,
    reservation text NOT NULL,
    status text NOT NULL,
    package_id text NOT NULL,
    provider_context text,
    result_id text,
    error text DEFAULT ''::text NOT NULL,
    created_at bigint NOT NULL,
    updated_at bigint NOT NULL,
    CONSTRAINT rs_operations_adult_check CHECK ((adult = ANY (ARRAY[(0)::bigint, (1)::bigint]))),
    CONSTRAINT rs_operations_connections_check CHECK (((connections >= 1) AND (connections <= 3))),
    CONSTRAINT rs_operations_credit_cost_check CHECK ((credit_cost >= 0)),
    CONSTRAINT rs_operations_operation_type_check CHECK ((operation_type = ANY (ARRAY['create'::text, 'trial'::text, 'extend'::text]))),
    CONSTRAINT rs_operations_reservation_check CHECK ((reservation = ANY (ARRAY['held'::text, 'charged'::text, 'released'::text]))),
    CONSTRAINT rs_operations_status_check CHECK ((status = ANY (ARRAY['queued'::text, 'preparing'::text, 'processing'::text, 'uncertain'::text, 'succeeded'::text, 'failed'::text])))
);


--
-- Name: rs_packages; Type: TABLE; Schema: stream_panel_bot_live; Owner: -
--

CREATE TABLE stream_panel_bot_live.rs_packages (
    id text NOT NULL,
    price_pence bigint NOT NULL,
    credits bigint NOT NULL,
    active bigint NOT NULL,
    updated_at bigint NOT NULL,
    CONSTRAINT rs_packages_active_check CHECK ((active = ANY (ARRAY[(0)::bigint, (1)::bigint]))),
    CONSTRAINT rs_packages_credits_check CHECK ((credits > 0)),
    CONSTRAINT rs_packages_price_pence_check CHECK ((price_pence > 0))
);


--
-- Name: rs_purchases; Type: TABLE; Schema: stream_panel_bot_live; Owner: -
--

CREATE TABLE stream_panel_bot_live.rs_purchases (
    id text NOT NULL,
    reseller_id text NOT NULL,
    package_snapshot text NOT NULL,
    amount_pence bigint NOT NULL,
    credits bigint NOT NULL,
    payment_reference text,
    status text NOT NULL,
    created_at bigint NOT NULL,
    updated_at bigint NOT NULL,
    CONSTRAINT rs_purchases_amount_pence_check CHECK ((amount_pence > 0)),
    CONSTRAINT rs_purchases_credits_check CHECK ((credits > 0)),
    CONSTRAINT rs_purchases_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'granted'::text])))
);


--
-- Name: rs_resellers; Type: TABLE; Schema: stream_panel_bot_live; Owner: -
--

CREATE TABLE stream_panel_bot_live.rs_resellers (
    id text NOT NULL,
    telegram_id bigint NOT NULL,
    username text DEFAULT ''::text NOT NULL,
    status text NOT NULL,
    created_at bigint NOT NULL,
    updated_at bigint NOT NULL,
    CONSTRAINT rs_resellers_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'active'::text, 'suspended'::text]))),
    CONSTRAINT rs_resellers_telegram_id_check CHECK ((telegram_id > 0))
);


--
-- Name: rs_settings; Type: TABLE; Schema: stream_panel_bot_live; Owner: -
--

CREATE TABLE stream_panel_bot_live.rs_settings (
    key text NOT NULL,
    value text NOT NULL
);


--
-- Name: rs_subscriptions; Type: TABLE; Schema: stream_panel_bot_live; Owner: -
--

CREATE TABLE stream_panel_bot_live.rs_subscriptions (
    id text NOT NULL,
    reseller_id text NOT NULL,
    provider_id text NOT NULL,
    customer_ref text NOT NULL,
    kind text NOT NULL,
    connections bigint NOT NULL,
    adult bigint NOT NULL,
    starts_at bigint NOT NULL,
    expires_at bigint NOT NULL,
    status text NOT NULL,
    credentials text NOT NULL,
    confirmed_at bigint NOT NULL,
    created_at bigint NOT NULL,
    contact text DEFAULT ''::text NOT NULL,
    converted_at bigint,
    deleted_at bigint,
    CONSTRAINT rs_subscriptions_adult_check CHECK ((adult = ANY (ARRAY[(0)::bigint, (1)::bigint]))),
    CONSTRAINT rs_subscriptions_connections_check CHECK (((connections >= 1) AND (connections <= 3))),
    CONSTRAINT rs_subscriptions_kind_check CHECK ((kind = ANY (ARRAY['trial'::text, 'paid'::text])))
);


--
-- Name: rs_web_codes; Type: TABLE; Schema: stream_panel_bot_live; Owner: -
--

CREATE TABLE stream_panel_bot_live.rs_web_codes (
    code_hash text NOT NULL,
    reseller_id text NOT NULL,
    expires_at bigint NOT NULL
);


--
-- Name: rs_web_sessions; Type: TABLE; Schema: stream_panel_bot_live; Owner: -
--

CREATE TABLE stream_panel_bot_live.rs_web_sessions (
    token_hash text NOT NULL,
    reseller_id text NOT NULL,
    created_at bigint NOT NULL,
    expires_at bigint NOT NULL,
    last_seen bigint NOT NULL
);


--
-- Name: tk_messages; Type: TABLE; Schema: stream_panel_bot_live; Owner: -
--

CREATE TABLE stream_panel_bot_live.tk_messages (
    id text NOT NULL,
    ticket_id text NOT NULL,
    sender text NOT NULL,
    body text NOT NULL,
    actor text DEFAULT ''::text NOT NULL,
    created_at bigint NOT NULL,
    CONSTRAINT tk_messages_sender_check CHECK ((sender = ANY (ARRAY['customer'::text, 'support'::text])))
);


--
-- Name: tk_tickets; Type: TABLE; Schema: stream_panel_bot_live; Owner: -
--

CREATE TABLE stream_panel_bot_live.tk_tickets (
    id text NOT NULL,
    telegram_id bigint NOT NULL,
    username text DEFAULT ''::text NOT NULL,
    topic text NOT NULL,
    status text NOT NULL,
    channel text NOT NULL,
    reseller bigint DEFAULT 0 NOT NULL,
    created_at bigint NOT NULL,
    updated_at bigint NOT NULL,
    closed_at bigint,
    CONSTRAINT tk_tickets_reseller_check CHECK ((reseller = ANY (ARRAY[(0)::bigint, (1)::bigint]))),
    CONSTRAINT tk_tickets_status_check CHECK ((status = ANY (ARRAY['open'::text, 'answered'::text, 'closed'::text]))),
    CONSTRAINT tk_tickets_telegram_id_check CHECK ((telegram_id > 0))
);


--
-- Data for Name: sessions; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.sessions (sid, sess, expire) FROM stdin;
\.


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: -
--

COPY public.users (id, email, first_name, last_name, profile_image_url, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: account_links; Type: TABLE DATA; Schema: stream_panel_bot_live; Owner: -
--

COPY stream_panel_bot_live.account_links (telegram_id, order_id) FROM stdin;
\.


--
-- Data for Name: limits; Type: TABLE DATA; Schema: stream_panel_bot_live; Owner: -
--

COPY stream_panel_bot_live.limits (bucket, at) FROM stdin;
\.


--
-- Data for Name: links; Type: TABLE DATA; Schema: stream_panel_bot_live; Owner: -
--

COPY stream_panel_bot_live.links (code_hash, order_id, expires_at) FROM stdin;
\.


--
-- Data for Name: metadata; Type: TABLE DATA; Schema: stream_panel_bot_live; Owner: -
--

COPY stream_panel_bot_live.metadata (key, value) FROM stdin;
mode	live
\.


--
-- Data for Name: nt_campaigns; Type: TABLE DATA; Schema: stream_panel_bot_live; Owner: -
--

COPY stream_panel_bot_live.nt_campaigns (id, administrator, body, audience, status, created_at) FROM stdin;
\.


--
-- Data for Name: nt_contacts; Type: TABLE DATA; Schema: stream_panel_bot_live; Owner: -
--

COPY stream_panel_bot_live.nt_contacts (telegram_id, alerts, deals, blocked, updated_at) FROM stdin;
\.


--
-- Data for Name: nt_deliveries; Type: TABLE DATA; Schema: stream_panel_bot_live; Owner: -
--

COPY stream_panel_bot_live.nt_deliveries (id, telegram_id, kind, subject, campaign_id, status, due_at, attempts, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: orders; Type: TABLE DATA; Schema: stream_panel_bot_live; Owner: -
--

COPY stream_panel_bot_live.orders (id, token_hash, kind, telegram_id, plan_json, asset_json, amount_units, created_at, expires_at, status, txid, message, credentials, attempts, last_check) FROM stdin;
\.


--
-- Data for Name: payments; Type: TABLE DATA; Schema: stream_panel_bot_live; Owner: -
--

COPY stream_panel_bot_live.payments (network, txid, order_id, proof) FROM stdin;
\.


--
-- Data for Name: rs_accounts; Type: TABLE DATA; Schema: stream_panel_bot_live; Owner: -
--

COPY stream_panel_bot_live.rs_accounts (reseller_id, balance, reserved) FROM stdin;
\.


--
-- Data for Name: rs_audit; Type: TABLE DATA; Schema: stream_panel_bot_live; Owner: -
--

COPY stream_panel_bot_live.rs_audit (id, administrator, action, subject, reason, details, created_at) FROM stdin;
\.


--
-- Data for Name: rs_costs; Type: TABLE DATA; Schema: stream_panel_bot_live; Owner: -
--

COPY stream_panel_bot_live.rs_costs (months, connections, credits, updated_at) FROM stdin;
\.


--
-- Data for Name: rs_extensions; Type: TABLE DATA; Schema: stream_panel_bot_live; Owner: -
--

COPY stream_panel_bot_live.rs_extensions (id, subscription_id, reseller_id, operation_id, months, credits, previous_expiry, confirmed_expiry, created_at) FROM stdin;
\.


--
-- Data for Name: rs_ledger; Type: TABLE DATA; Schema: stream_panel_bot_live; Owner: -
--

COPY stream_panel_bot_live.rs_ledger (id, reseller_id, movement, reason, reference, administrator, created_at) FROM stdin;
\.


--
-- Data for Name: rs_login_requests; Type: TABLE DATA; Schema: stream_panel_bot_live; Owner: -
--

COPY stream_panel_bot_live.rs_login_requests (poll_hash, code_hash, reseller_id, created_at, expires_at) FROM stdin;
\.


--
-- Data for Name: rs_logins; Type: TABLE DATA; Schema: stream_panel_bot_live; Owner: -
--

COPY stream_panel_bot_live.rs_logins (reseller_id, email, password_hash, updated_at) FROM stdin;
\.


--
-- Data for Name: rs_operations; Type: TABLE DATA; Schema: stream_panel_bot_live; Owner: -
--

COPY stream_panel_bot_live.rs_operations (id, request_key, reseller_id, operation_type, target_id, months, connections, adult, customer_ref, credit_cost, reservation, status, package_id, provider_context, result_id, error, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: rs_packages; Type: TABLE DATA; Schema: stream_panel_bot_live; Owner: -
--

COPY stream_panel_bot_live.rs_packages (id, price_pence, credits, active, updated_at) FROM stdin;
\.


--
-- Data for Name: rs_purchases; Type: TABLE DATA; Schema: stream_panel_bot_live; Owner: -
--

COPY stream_panel_bot_live.rs_purchases (id, reseller_id, package_snapshot, amount_pence, credits, payment_reference, status, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: rs_resellers; Type: TABLE DATA; Schema: stream_panel_bot_live; Owner: -
--

COPY stream_panel_bot_live.rs_resellers (id, telegram_id, username, status, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: rs_settings; Type: TABLE DATA; Schema: stream_panel_bot_live; Owner: -
--

COPY stream_panel_bot_live.rs_settings (key, value) FROM stdin;
\.


--
-- Data for Name: rs_subscriptions; Type: TABLE DATA; Schema: stream_panel_bot_live; Owner: -
--

COPY stream_panel_bot_live.rs_subscriptions (id, reseller_id, provider_id, customer_ref, kind, connections, adult, starts_at, expires_at, status, credentials, confirmed_at, created_at, contact, converted_at, deleted_at) FROM stdin;
\.


--
-- Data for Name: rs_web_codes; Type: TABLE DATA; Schema: stream_panel_bot_live; Owner: -
--

COPY stream_panel_bot_live.rs_web_codes (code_hash, reseller_id, expires_at) FROM stdin;
\.


--
-- Data for Name: rs_web_sessions; Type: TABLE DATA; Schema: stream_panel_bot_live; Owner: -
--

COPY stream_panel_bot_live.rs_web_sessions (token_hash, reseller_id, created_at, expires_at, last_seen) FROM stdin;
\.


--
-- Data for Name: tk_messages; Type: TABLE DATA; Schema: stream_panel_bot_live; Owner: -
--

COPY stream_panel_bot_live.tk_messages (id, ticket_id, sender, body, actor, created_at) FROM stdin;
\.


--
-- Data for Name: tk_tickets; Type: TABLE DATA; Schema: stream_panel_bot_live; Owner: -
--

COPY stream_panel_bot_live.tk_tickets (id, telegram_id, username, topic, status, channel, reseller, created_at, updated_at, closed_at) FROM stdin;
\.


--
-- Name: sessions sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.sessions
    ADD CONSTRAINT sessions_pkey PRIMARY KEY (sid);


--
-- Name: users users_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: account_links account_links_order_id_key; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.account_links
    ADD CONSTRAINT account_links_order_id_key UNIQUE (order_id);


--
-- Name: account_links account_links_pkey; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.account_links
    ADD CONSTRAINT account_links_pkey PRIMARY KEY (telegram_id, order_id);


--
-- Name: links links_pkey; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.links
    ADD CONSTRAINT links_pkey PRIMARY KEY (code_hash);


--
-- Name: metadata metadata_pkey; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.metadata
    ADD CONSTRAINT metadata_pkey PRIMARY KEY (key);


--
-- Name: nt_campaigns nt_campaigns_pkey; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.nt_campaigns
    ADD CONSTRAINT nt_campaigns_pkey PRIMARY KEY (id);


--
-- Name: nt_contacts nt_contacts_pkey; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.nt_contacts
    ADD CONSTRAINT nt_contacts_pkey PRIMARY KEY (telegram_id);


--
-- Name: nt_deliveries nt_deliveries_pkey; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.nt_deliveries
    ADD CONSTRAINT nt_deliveries_pkey PRIMARY KEY (id);


--
-- Name: orders orders_pkey; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.orders
    ADD CONSTRAINT orders_pkey PRIMARY KEY (id);


--
-- Name: orders orders_telegram_id_key; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.orders
    ADD CONSTRAINT orders_telegram_id_key UNIQUE (telegram_id);


--
-- Name: orders orders_token_hash_key; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.orders
    ADD CONSTRAINT orders_token_hash_key UNIQUE (token_hash);


--
-- Name: payments payments_order_id_key; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.payments
    ADD CONSTRAINT payments_order_id_key UNIQUE (order_id);


--
-- Name: payments payments_pkey; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.payments
    ADD CONSTRAINT payments_pkey PRIMARY KEY (network, txid);


--
-- Name: rs_accounts rs_accounts_pkey; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_accounts
    ADD CONSTRAINT rs_accounts_pkey PRIMARY KEY (reseller_id);


--
-- Name: rs_audit rs_audit_pkey; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_audit
    ADD CONSTRAINT rs_audit_pkey PRIMARY KEY (id);


--
-- Name: rs_costs rs_costs_pkey; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_costs
    ADD CONSTRAINT rs_costs_pkey PRIMARY KEY (months, connections);


--
-- Name: rs_extensions rs_extensions_operation_id_key; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_extensions
    ADD CONSTRAINT rs_extensions_operation_id_key UNIQUE (operation_id);


--
-- Name: rs_extensions rs_extensions_pkey; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_extensions
    ADD CONSTRAINT rs_extensions_pkey PRIMARY KEY (id);


--
-- Name: rs_ledger rs_ledger_pkey; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_ledger
    ADD CONSTRAINT rs_ledger_pkey PRIMARY KEY (id);


--
-- Name: rs_ledger rs_ledger_reference_key; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_ledger
    ADD CONSTRAINT rs_ledger_reference_key UNIQUE (reference);


--
-- Name: rs_login_requests rs_login_requests_code_hash_key; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_login_requests
    ADD CONSTRAINT rs_login_requests_code_hash_key UNIQUE (code_hash);


--
-- Name: rs_login_requests rs_login_requests_pkey; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_login_requests
    ADD CONSTRAINT rs_login_requests_pkey PRIMARY KEY (poll_hash);


--
-- Name: rs_logins rs_logins_email_key; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_logins
    ADD CONSTRAINT rs_logins_email_key UNIQUE (email);


--
-- Name: rs_logins rs_logins_pkey; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_logins
    ADD CONSTRAINT rs_logins_pkey PRIMARY KEY (reseller_id);


--
-- Name: rs_operations rs_operations_pkey; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_operations
    ADD CONSTRAINT rs_operations_pkey PRIMARY KEY (id);


--
-- Name: rs_operations rs_operations_request_key_key; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_operations
    ADD CONSTRAINT rs_operations_request_key_key UNIQUE (request_key);


--
-- Name: rs_packages rs_packages_pkey; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_packages
    ADD CONSTRAINT rs_packages_pkey PRIMARY KEY (id);


--
-- Name: rs_purchases rs_purchases_payment_reference_key; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_purchases
    ADD CONSTRAINT rs_purchases_payment_reference_key UNIQUE (payment_reference);


--
-- Name: rs_purchases rs_purchases_pkey; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_purchases
    ADD CONSTRAINT rs_purchases_pkey PRIMARY KEY (id);


--
-- Name: rs_resellers rs_resellers_pkey; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_resellers
    ADD CONSTRAINT rs_resellers_pkey PRIMARY KEY (id);


--
-- Name: rs_resellers rs_resellers_telegram_id_key; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_resellers
    ADD CONSTRAINT rs_resellers_telegram_id_key UNIQUE (telegram_id);


--
-- Name: rs_settings rs_settings_pkey; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_settings
    ADD CONSTRAINT rs_settings_pkey PRIMARY KEY (key);


--
-- Name: rs_subscriptions rs_subscriptions_pkey; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_subscriptions
    ADD CONSTRAINT rs_subscriptions_pkey PRIMARY KEY (id);


--
-- Name: rs_subscriptions rs_subscriptions_provider_id_key; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_subscriptions
    ADD CONSTRAINT rs_subscriptions_provider_id_key UNIQUE (provider_id);


--
-- Name: rs_web_codes rs_web_codes_pkey; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_web_codes
    ADD CONSTRAINT rs_web_codes_pkey PRIMARY KEY (code_hash);


--
-- Name: rs_web_sessions rs_web_sessions_pkey; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_web_sessions
    ADD CONSTRAINT rs_web_sessions_pkey PRIMARY KEY (token_hash);


--
-- Name: tk_messages tk_messages_pkey; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.tk_messages
    ADD CONSTRAINT tk_messages_pkey PRIMARY KEY (id);


--
-- Name: tk_tickets tk_tickets_pkey; Type: CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.tk_tickets
    ADD CONSTRAINT tk_tickets_pkey PRIMARY KEY (id);


--
-- Name: IDX_session_expire; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX "IDX_session_expire" ON public.sessions USING btree (expire);


--
-- Name: limits_bucket; Type: INDEX; Schema: stream_panel_bot_live; Owner: -
--

CREATE INDEX limits_bucket ON stream_panel_bot_live.limits USING btree (bucket, at);


--
-- Name: links_order; Type: INDEX; Schema: stream_panel_bot_live; Owner: -
--

CREATE INDEX links_order ON stream_panel_bot_live.links USING btree (order_id);


--
-- Name: nt_campaign_deliveries; Type: INDEX; Schema: stream_panel_bot_live; Owner: -
--

CREATE INDEX nt_campaign_deliveries ON stream_panel_bot_live.nt_deliveries USING btree (campaign_id, status);


--
-- Name: nt_delivery_due; Type: INDEX; Schema: stream_panel_bot_live; Owner: -
--

CREATE INDEX nt_delivery_due ON stream_panel_bot_live.nt_deliveries USING btree (status, due_at);


--
-- Name: orders_asset_expiry; Type: INDEX; Schema: stream_panel_bot_live; Owner: -
--

CREATE INDEX orders_asset_expiry ON stream_panel_bot_live.orders USING btree ((((asset_json)::jsonb ->> 'id'::text)), expires_at);


--
-- Name: orders_state; Type: INDEX; Schema: stream_panel_bot_live; Owner: -
--

CREATE INDEX orders_state ON stream_panel_bot_live.orders USING btree (status, last_check, created_at);


--
-- Name: orders_trial_created; Type: INDEX; Schema: stream_panel_bot_live; Owner: -
--

CREATE INDEX orders_trial_created ON stream_panel_bot_live.orders USING btree (created_at) WHERE (kind = 'trial'::text);


--
-- Name: rs_ledger_owner; Type: INDEX; Schema: stream_panel_bot_live; Owner: -
--

CREATE INDEX rs_ledger_owner ON stream_panel_bot_live.rs_ledger USING btree (reseller_id, created_at);


--
-- Name: rs_operations_state; Type: INDEX; Schema: stream_panel_bot_live; Owner: -
--

CREATE INDEX rs_operations_state ON stream_panel_bot_live.rs_operations USING btree (status, created_at);


--
-- Name: rs_subscriptions_owner; Type: INDEX; Schema: stream_panel_bot_live; Owner: -
--

CREATE INDEX rs_subscriptions_owner ON stream_panel_bot_live.rs_subscriptions USING btree (reseller_id, expires_at);


--
-- Name: tk_messages_ticket; Type: INDEX; Schema: stream_panel_bot_live; Owner: -
--

CREATE INDEX tk_messages_ticket ON stream_panel_bot_live.tk_messages USING btree (ticket_id, created_at);


--
-- Name: tk_tickets_owner; Type: INDEX; Schema: stream_panel_bot_live; Owner: -
--

CREATE INDEX tk_tickets_owner ON stream_panel_bot_live.tk_tickets USING btree (telegram_id, updated_at);


--
-- Name: tk_tickets_status; Type: INDEX; Schema: stream_panel_bot_live; Owner: -
--

CREATE INDEX tk_tickets_status ON stream_panel_bot_live.tk_tickets USING btree (status, updated_at);


--
-- Name: account_links account_links_order_id_fkey; Type: FK CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.account_links
    ADD CONSTRAINT account_links_order_id_fkey FOREIGN KEY (order_id) REFERENCES stream_panel_bot_live.orders(id);


--
-- Name: links links_order_id_fkey; Type: FK CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.links
    ADD CONSTRAINT links_order_id_fkey FOREIGN KEY (order_id) REFERENCES stream_panel_bot_live.orders(id);


--
-- Name: nt_deliveries nt_deliveries_campaign_id_fkey; Type: FK CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.nt_deliveries
    ADD CONSTRAINT nt_deliveries_campaign_id_fkey FOREIGN KEY (campaign_id) REFERENCES stream_panel_bot_live.nt_campaigns(id);


--
-- Name: nt_deliveries nt_deliveries_telegram_id_fkey; Type: FK CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.nt_deliveries
    ADD CONSTRAINT nt_deliveries_telegram_id_fkey FOREIGN KEY (telegram_id) REFERENCES stream_panel_bot_live.nt_contacts(telegram_id);


--
-- Name: payments payments_order_id_fkey; Type: FK CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.payments
    ADD CONSTRAINT payments_order_id_fkey FOREIGN KEY (order_id) REFERENCES stream_panel_bot_live.orders(id);


--
-- Name: rs_accounts rs_accounts_reseller_id_fkey; Type: FK CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_accounts
    ADD CONSTRAINT rs_accounts_reseller_id_fkey FOREIGN KEY (reseller_id) REFERENCES stream_panel_bot_live.rs_resellers(id);


--
-- Name: rs_extensions rs_extensions_operation_id_fkey; Type: FK CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_extensions
    ADD CONSTRAINT rs_extensions_operation_id_fkey FOREIGN KEY (operation_id) REFERENCES stream_panel_bot_live.rs_operations(id);


--
-- Name: rs_extensions rs_extensions_reseller_id_fkey; Type: FK CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_extensions
    ADD CONSTRAINT rs_extensions_reseller_id_fkey FOREIGN KEY (reseller_id) REFERENCES stream_panel_bot_live.rs_resellers(id);


--
-- Name: rs_extensions rs_extensions_subscription_id_fkey; Type: FK CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_extensions
    ADD CONSTRAINT rs_extensions_subscription_id_fkey FOREIGN KEY (subscription_id) REFERENCES stream_panel_bot_live.rs_subscriptions(id);


--
-- Name: rs_ledger rs_ledger_reseller_id_fkey; Type: FK CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_ledger
    ADD CONSTRAINT rs_ledger_reseller_id_fkey FOREIGN KEY (reseller_id) REFERENCES stream_panel_bot_live.rs_resellers(id);


--
-- Name: rs_login_requests rs_login_requests_reseller_id_fkey; Type: FK CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_login_requests
    ADD CONSTRAINT rs_login_requests_reseller_id_fkey FOREIGN KEY (reseller_id) REFERENCES stream_panel_bot_live.rs_resellers(id);


--
-- Name: rs_logins rs_logins_reseller_id_fkey; Type: FK CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_logins
    ADD CONSTRAINT rs_logins_reseller_id_fkey FOREIGN KEY (reseller_id) REFERENCES stream_panel_bot_live.rs_resellers(id);


--
-- Name: rs_operations rs_operations_reseller_id_fkey; Type: FK CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_operations
    ADD CONSTRAINT rs_operations_reseller_id_fkey FOREIGN KEY (reseller_id) REFERENCES stream_panel_bot_live.rs_resellers(id);


--
-- Name: rs_purchases rs_purchases_id_fkey; Type: FK CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_purchases
    ADD CONSTRAINT rs_purchases_id_fkey FOREIGN KEY (id) REFERENCES stream_panel_bot_live.orders(id);


--
-- Name: rs_purchases rs_purchases_reseller_id_fkey; Type: FK CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_purchases
    ADD CONSTRAINT rs_purchases_reseller_id_fkey FOREIGN KEY (reseller_id) REFERENCES stream_panel_bot_live.rs_resellers(id);


--
-- Name: rs_subscriptions rs_subscriptions_reseller_id_fkey; Type: FK CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_subscriptions
    ADD CONSTRAINT rs_subscriptions_reseller_id_fkey FOREIGN KEY (reseller_id) REFERENCES stream_panel_bot_live.rs_resellers(id);


--
-- Name: rs_web_codes rs_web_codes_reseller_id_fkey; Type: FK CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_web_codes
    ADD CONSTRAINT rs_web_codes_reseller_id_fkey FOREIGN KEY (reseller_id) REFERENCES stream_panel_bot_live.rs_resellers(id);


--
-- Name: rs_web_sessions rs_web_sessions_reseller_id_fkey; Type: FK CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.rs_web_sessions
    ADD CONSTRAINT rs_web_sessions_reseller_id_fkey FOREIGN KEY (reseller_id) REFERENCES stream_panel_bot_live.rs_resellers(id);


--
-- Name: tk_messages tk_messages_ticket_id_fkey; Type: FK CONSTRAINT; Schema: stream_panel_bot_live; Owner: -
--

ALTER TABLE ONLY stream_panel_bot_live.tk_messages
    ADD CONSTRAINT tk_messages_ticket_id_fkey FOREIGN KEY (ticket_id) REFERENCES stream_panel_bot_live.tk_tickets(id);


--
-- PostgreSQL database dump complete
--


