-- Create and replace mts.mts_table_2 from the matching Athena CSV.
-- Pass -v csv_dir="C:/folder" or run from the directory containing mts_table_2_export.csv.
\set ON_ERROR_STOP on
\encoding UTF8
-- The combined loader owns the transaction when this variable is present.
\if :{?mts_load_all}
\else
\if :{?csv_dir}
\cd :csv_dir
\endif
BEGIN;
SET LOCAL timezone = 'UTC';
\endif

\ir create_mts_table_2.sql

\if :{?mts_load_all}
\else
TRUNCATE TABLE mts.mts_table_2;
\endif

\copy mts.mts_table_2 ("classification_desc", "classification_id", "current_fytd_budget_amt", "current_month_budget_amt", "current_year_budget_est_amt", "data_type_cd", "line_code_nbr", "next_year_budget_est_amt", "parent_id", "print_order_nbr", "prior_fytd_budget_amt", "record_calendar_day", "record_calendar_month", "record_calendar_quarter", "record_calendar_year", "record_date", "record_fiscal_quarter", "record_fiscal_year", "record_type_cd", "sequence_level_nbr", "sequence_number_cd", "src_line_nbr", "table_nbr", "source_bucket", "source_key", "source_version_id", "source_sha256", "source_url", "manifest_key", "manifest_version_id", "batch_id", "transform_version", "ingested_at") FROM 'mts_table_2_export.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')

\if :{?mts_load_all}
\else
COMMIT;
\echo 'Loaded mts_table_2 successfully.'
\endif
