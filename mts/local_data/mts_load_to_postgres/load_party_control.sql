-- Create and replace mts.party_control from political_control_monthly.csv.
-- Pass -v csv_dir="C:/folder" or run from the directory containing the CSV.
\set ON_ERROR_STOP on
\encoding UTF8
\if :{?csv_dir}
\cd :csv_dir
\endif

BEGIN;
\ir create_party_control.sql
TRUNCATE TABLE mts.party_control;

-- The Python loader sends validated rows without a header via process stdin.
\if :{?party_control_stdin}
\copy mts.party_control (year, month, president_name, president_party, house_majority_party, senate_majority_party) FROM pstdin WITH (FORMAT csv)
\else
\copy mts.party_control (year, month, president_name, president_party, house_majority_party, senate_majority_party) FROM 'political_control_monthly.csv' WITH (FORMAT csv, HEADER true, ENCODING 'UTF8')
\endif

COMMIT;
\echo 'Loaded party_control successfully.'
