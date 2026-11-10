-- PASS D0 (inventory) — commands and queries actually executed, 2026-09-11 cluster date shown by stat as 2026-11-09.
-- DB opened strictly read-only every time:
--   sqlite3 not used; python3 sqlite3.connect("file:...?mode=ro&immutable=1", uri=True) + PRAGMA query_only=ON

-- 0. File enumeration
-- find releases/cdm_v3 -maxdepth 3 \( -name "*.db" -o -name "*.sqlite" \) -exec ls -la {}
-- find releases/frozen_output -name "*.db" -o -name "*.sqlite"
-- find releases/terminology/1.0.1 -type f | sort  (+ stat -c%s / -c%y per file)
-- find releases/frozen_output -maxdepth 2 -type d  (+ per-dir file count, du -sh)
-- find releases/frozen_output -type f | wc -l   -> 697 total files; 454 = segmented markdown (*count only*)
-- ls releases/data_catalogue_v3/{3.0.0,3.1.0,3.1.1}/{records,tables}

-- sha256 of every DB found (no check values yet):
-- for db in releases/cdm_v3/{3.0.0,3.0.1,3.0.2,3.0.3}/microbiome_cdm_v3.db \
--           releases/frozen_output/03_common_data_model/database/microbiome_cdm.db:
--   sha256sum "$db"

-- 1. FROZEN_DB schema (names + columns only; no data selected):
SELECT type, name, tbl_name FROM sqlite_master ORDER BY type, name;                 -- 44 tables + 57 autoindexes
-- per table (x44):
PRAGMA table_info("<table>");            -- column names only
-- count of declared FK constraints (PRAGMA foreign_key_list per table), informational for D2:
-- total across all 44 tables = 0
