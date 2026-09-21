-- Runs once, on an empty data directory.
--
-- The application connects as veracity_app, which owns nothing and has no
-- BYPASSRLS, so the row-level security policies actually bind to it. Pointing
-- both connection strings at the owner installs every policy and enforces none,
-- and the only symptom is a reassuring line in the startup log.
--
-- The password is interpolated by the entrypoint from APP_PASSWORD.
\set app_password `echo "$APP_PASSWORD"`

CREATE ROLE veracity_app LOGIN PASSWORD :'app_password';
GRANT CONNECT ON DATABASE veracity TO veracity_app;
GRANT USAGE ON SCHEMA public TO veracity_app;

-- Table grants are issued by the application at startup, after migrations have
-- created the tables. Granting here would fail: none of them exist yet.

CREATE EXTENSION IF NOT EXISTS vector;
