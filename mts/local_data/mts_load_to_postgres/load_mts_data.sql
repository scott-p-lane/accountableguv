-- Create and load all nine tables from Athena CSV exports with psql.
-- Pass -v csv_dir="C:/folder" or run from the CSV folder. Replaces rows atomically.
\set ON_ERROR_STOP on
\encoding UTF8
\if :{?csv_dir}
\cd :csv_dir
\endif
BEGIN;
SET LOCAL timezone = 'UTC';
\set mts_load_all true

\ir create_mts_table_1.sql
\ir create_mts_table_2.sql
\ir create_mts_table_3.sql
\ir create_mts_table_4.sql
\ir create_mts_table_5.sql
\ir create_mts_table_6.sql
\ir create_mts_table_7.sql
\ir create_mts_table_8.sql
\ir create_mts_table_9.sql

TRUNCATE TABLE mts.mts_table_1, mts.mts_table_2, mts.mts_table_3, mts.mts_table_4, mts.mts_table_5, mts.mts_table_6, mts.mts_table_7, mts.mts_table_8, mts.mts_table_9;

\ir load_mts_table_1.sql
\ir load_mts_table_2.sql
\ir load_mts_table_3.sql
\ir load_mts_table_4.sql
\ir load_mts_table_5.sql
\ir load_mts_table_6.sql
\ir load_mts_table_7.sql
\ir load_mts_table_8.sql
\ir load_mts_table_9.sql

COMMIT;
\unset mts_load_all
\echo 'Loaded all nine Athena CSV exports successfully.'
