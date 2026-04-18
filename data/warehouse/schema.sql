-- data/warehouse/schema.sql
-- Star schema for SentinelOps incident corpus.

CREATE TABLE IF NOT EXISTS dim_categories (
    category_id   INTEGER PRIMARY KEY,
    category_name VARCHAR UNIQUE NOT NULL,
    description   VARCHAR
);

CREATE TABLE IF NOT EXISTS dim_services (
    service_id     INTEGER PRIMARY KEY,
    service_name   VARCHAR UNIQUE NOT NULL,
    service_source VARCHAR
);

CREATE TABLE IF NOT EXISTS fact_incidents (
    incident_id         VARCHAR PRIMARY KEY,
    title               VARCHAR,
    body                TEXT,
    source              VARCHAR,
    url                 VARCHAR,
    published_date      DATE,
    service_id          INTEGER,
    category_id         INTEGER,
    severity            VARCHAR,          -- P0 | P1 | P2 | P3 | NULL
    severity_confidence DOUBLE,
    category_confidence DOUBLE,
    label_source        VARCHAR,          -- 'weak' | 'manual' | NULL
    body_char_len       INTEGER
);

CREATE TABLE IF NOT EXISTS fact_chunks (
    chunk_id     VARCHAR PRIMARY KEY,
    incident_id  VARCHAR NOT NULL,
    chunk_index  INTEGER,
    chunk_text   TEXT,
    chunk_tokens INTEGER
);

INSERT INTO dim_categories (category_id, category_name, description) VALUES
    (1, 'networking', 'DNS, BGP, load balancer, CDN, routing, connectivity'),
    (2, 'database',   'DB down, replication lag, query perf, corruption'),
    (3, 'deploy',     'Bad deploy, rollback, config change, release'),
    (4, 'capacity',   'OOM, CPU saturation, disk full, quota, autoscale'),
    (5, 'auth',       'Auth outage, cert expiry, token/SSO failures'),
    (6, 'other',      'Uncategorized or mixed')
ON CONFLICT (category_id) DO NOTHING;