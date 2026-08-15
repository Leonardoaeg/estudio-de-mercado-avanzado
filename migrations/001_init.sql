-- 001_init.sql
-- Documents the initial schema history. The tables themselves are created by
-- SQLAlchemy's Base.metadata.create_all() (see src/eci/database/migrate.py) since v1 targets
-- SQLite, whose ALTER TABLE support is limited. This file is safe to run repeatedly (it only
-- creates indices IF NOT EXISTS) and is the anchor for a future Alembic migration to Postgres.

CREATE INDEX IF NOT EXISTS ix_ads_page_id_active ON ads (page_id, active);
CREATE INDEX IF NOT EXISTS ix_advertisers_niche_market ON advertisers (niche, country);
CREATE INDEX IF NOT EXISTS ix_snapshots_page_taken ON snapshots (page_id, taken_at);
CREATE INDEX IF NOT EXISTS ix_rankings_niche_market_type ON rankings (niche, market, ranking_type);
