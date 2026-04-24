-- Initial Postgres schemas for local dev. Prod uses Alembic migrations.
-- Runs once on first container start (from docker-entrypoint-initdb.d).

CREATE SCHEMA IF NOT EXISTS masters;
CREATE SCHEMA IF NOT EXISTS entries;
CREATE SCHEMA IF NOT EXISTS facts;
CREATE SCHEMA IF NOT EXISTS audit;
CREATE SCHEMA IF NOT EXISTS alerts;
CREATE SCHEMA IF NOT EXISTS dims;

-- Required for comp_agreements GIST exclusion constraint (no overlapping date ranges per physician)
CREATE EXTENSION IF NOT EXISTS btree_gist;
