-- Create and replace mts.mts_table_7 from the matching Athena CSV.
-- Pass -v csv_dir="C:/folder" or run from the directory containing mts_table_7_export.csv.
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

\ir create_mts_table_7.sql

\if :{?mts_load_all}
\else
TRUNCATE TABLE mts.mts_table_7;
\endif

\copy mts.mts_table_7 ("apr_rcpt_outly_amt", "aug_rcpt_outly_amt", "classification_desc", "classification_id", "current_fytd_rcpt_outly_amt", "data_type_cd", "dec_rcpt_outly_amt", "feb_rcpt_outly_amt", "jan_rcpt_outly_amt", "jul_rcpt_outly_amt", "jun_rcpt_outly_amt", "line_code_nbr", "mar_rcpt_outly_amt", "may_rcpt_outly_amt", "nov_rcpt_outly_amt", "oct_rcpt_outly_amt", "parent_id", "print_order_nbr", "prior_fytd_rcpt_outly_amt", "record_calendar_day", "record_calendar_month", "record_calendar_quarter", "record_calendar_year", "record_date", "record_fiscal_quarter", "record_fiscal_year", "record_type_cd", "sep_rcpt_outly_amt", "sequence_level_nbr", "sequence_number_cd", "src_line_nbr", "table_nbr", "source_bucket", "source_key", "source_version_id", "source_sha256", "source_url", "manifest_key", "manifest_version_id", "batch_id", "transform_version", "ingested_at") FROM 'mts_table_7_export.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')

\if :{?mts_load_all}
\else
COMMIT;
\echo 'Loaded mts_table_7 successfully.'
\endif
