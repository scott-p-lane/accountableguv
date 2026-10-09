-- PostgreSQL schema for mts_table_2; matches the MTS lakehouse loader.
-- ingested_at contains UTC timestamps.
CREATE SCHEMA IF NOT EXISTS "mts";

CREATE TABLE IF NOT EXISTS "mts"."mts_table_2" (
    "classification_desc" text,
    "classification_id" text,
    "current_fytd_budget_amt" numeric(38,2),
    "current_month_budget_amt" numeric(38,2),
    "current_year_budget_est_amt" numeric(38,2),
    "data_type_cd" text,
    "line_code_nbr" text,
    "next_year_budget_est_amt" numeric(38,2),
    "parent_id" text,
    "print_order_nbr" text,
    "prior_fytd_budget_amt" numeric(38,2),
    "record_calendar_day" integer,
    "record_calendar_month" integer,
    "record_calendar_quarter" integer,
    "record_calendar_year" integer,
    "record_date" date,
    "record_fiscal_quarter" integer,
    "record_fiscal_year" integer,
    "record_type_cd" text,
    "sequence_level_nbr" text,
    "sequence_number_cd" text,
    "src_line_nbr" bigint,
    "table_nbr" text,
    "source_bucket" text,
    "source_key" text,
    "source_version_id" text,
    "source_sha256" text,
    "source_url" text,
    "manifest_key" text,
    "manifest_version_id" text,
    "batch_id" text,
    "transform_version" text,
    "ingested_at" timestamp without time zone
);
