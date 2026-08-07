-- Extensions required by Doc 04 (Database Design & Data Dictionary):
--   gen_random_uuid()      -> pgcrypto
--   EXCLUDE USING gist on non-geometric types (daterange overlap checks) -> btree_gist
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS btree_gist;

-- Row-Level Security (Doc 03 §3.1) is enabled per-table in the Prisma migration that creates each
-- tenant table, not here — this file only prepares the extensions the migrations depend on.
