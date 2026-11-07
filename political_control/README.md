# Political reference data, 1977 onward

Prepared November 6, 2026. Monthly files cover January 1977 through October
2026, the latest completed calendar month. November and future months are not
projected. CSV encoding is UTF-8, with a header and CRLF line endings.

## Files and grain

- `data/political_control_monthly.csv`: combined monthly file with `year`, `month`,
  `president_name`, `president_party`, `house_majority_party`, and
  `senate_majority_party`. Contains 598 months, January 1977 through October 2026.
  All three party columns contain only `Republican` or `Democrat`. President and
  Senate control follow the month-end observations; House control follows the
  initial election-result baseline for the Congress at month end. Senate control
  uses the source's majority designation, including tied chambers, rather than
  comparing party seat counts. The detailed files below retain provenance and
  transition flags omitted from this compact join.
- `data/presidents.csv`: 10 presidential service periods overlapping 1977 onward,
  with party and actual office start/end dates. Consecutive terms are combined;
  Trump's nonconsecutive presidencies are separate. Ford is included because he
  served during January 1977. Blank office end means ongoing, not unknown.
- `data/presidents_monthly.csv`: 598 rows, one per calendar month. The principal
  president/party columns identify the incumbent at month end. Start-of-month
  president/party and change flags expose transition months. Office dates remain
  on each record, so the January 20 transition is not lost.
- `data/house_party_counts_monthly.csv`: 598 rows. **Official initial election-result
  counts for the Congress containing that month's end**, repeated across the
  Congress's months as requested. These are a baseline, not actual monthly
  membership. The baseline ignores subsequent deaths, resignations, special
  elections and party changes. `controlling_party` is derived from the larger
  baseline party count. Nonvoting delegates and resident commissioners are excluded.
- `data/senate_party_counts_monthly.csv`: 598 rows. Latest composition reported in
  the Senate's historical division table on or before month end, carried forward
  between observations. This is a **source-reported composition series**, not a
  complete daily membership reconstruction. `controlling_party` follows the
  source's majority-party designation, rather than simply the larger party count.

The monthly files retain `year` for annual grouping. For a single annual record,
filter `month = 12`; 2026 has only January through October, so its latest observation
is October. Do not sum seat counts across months. An annual average of these
snapshots is not an exact daily weighted average.

## Joining Treasury monthly data

All monthly files have a unique `(year, month)` key and an ISO `year_month` key
such as `1977-01`. Join using **calendar** year/month, not fiscal year with calendar
month. The existing MTS loader recognizes `record_calendar_year` and
`record_calendar_month`; join these to `year` and `month` respectively (or their
renamed counterparts in your destination table).

`fiscal_year` and `fiscal_month` use the federal October–September year:
October 2025 has calendar keys 2025/10 and fiscal keys 2026/1. These fiscal keys
are provided for convenience and do not change the monthly observation date.

Example, after importing the files into tables:

```sql
SELECT b.*, p.president, p.party AS presidential_party,
       h.controlling_party AS house_party,
       s.controlling_party AS senate_party
FROM budget_monthly b
LEFT JOIN presidents_monthly p
  ON p.year = b.record_calendar_year AND p.month = b.record_calendar_month
LEFT JOIN house_party_counts_monthly h
  ON h.year = b.record_calendar_year AND h.month = b.record_calendar_month
LEFT JOIN senate_party_counts_monthly s
  ON s.year = b.record_calendar_year AND s.month = b.record_calendar_month;
```

Adjust budget table/column names to your destination schema. Each political
lookup is unique by month, so these joins do not multiply budget records.

## Definitions and limitations

- `Democrat` and `Republican` are the normalized party labels throughout.
  `independent_democrat_seats` remains distinct from both Democrat and Independent
  in the Senate. `other_seats` excludes categories already listed separately.
- House `unassigned_seats` is the difference between 435 authorized seats and
  the published party totals. It is not a measured monthly vacancy count. The
  source identifies an opening vacancy for the 99th Congress and uncertified
  seats for the 116th and 117th Congresses. These source-baseline differences
  persist throughout the repeated baseline, even after the seats were filled.
- The House source's labels are retained as published. Its two-party historical
  classification is not a reconstruction of every member's ballot designation.
- Senate `vacant_seats` is the source's reported vacancy count. The Senate
  explicitly omits vacancies lasting one month or less, uses seating dates, and
  records changes selectively when they affect party balance. Some end-of-session
  changes are absent. Therefore **do not interpret this file as an exact count
  of physically seated senators on every month-end date**.
- `source_observation_date` identifies the carried-forward Senate observation;
  repeated annual source observations may have the same composition. Undated
  opening observations are assigned January 3, the congressional term start.
  Explicit source dates are preserved.
- The Senate party-switch history supplements the main table for Bob Smith's
  July 13–November 1, 1999 Independent period. Sinema's party designation follows
  the division table's January 2023 observation. Her announcement was December 9,
  2022; the source-reported December snapshot is not an announcement-date series.
  Manchin's change follows the division table's May 31, 2024 observation, despite
  a different date in the separate party-switch history.
- `reported_composition_changed_in_month` flags a change in a reported party
  count, vacancy count, or controlling party after the month's first day and by
  its end. It is not a count of every membership event. It includes changes in
  the source between congressional terms, even when control remains the same.
- President `office_end_date` is the transfer date; date-range joins should use
  start inclusive/end exclusive. Actual scheduled transfers occur at noon, which
  does not affect month-end labels. This dataset does not allocate monthly
  receipts/outlays to different presidents within a transition month.
- Political control labels describe contemporaneous control, not responsibility
  for the month's fiscal outcomes. Use transition flags and policy lags when
  interpreting the overlay. The House baseline and Senate reported observations
  have different precision; avoid comparing them as exact membership counts.

## Official sources

- Presidential service dates:
  https://history.house.gov/Institution/Presidents-Coinciding/Presidents-Coinciding/
- Presidential party affiliations:
  https://history.house.gov/Institution/Presidents-Coinciding/Party-Government/
- House election-result counts and exclusions:
  https://history.house.gov/Institution/Party-Divisions/Party-Divisions/
- Senate dated party divisions and majority designations:
  https://www.senate.gov/about/parties-leadership/party-division.shtml
- Senate party-switch history:
  https://www.senate.gov/senators/SenatorsWhoChangedPartiesDuringSenateService.htm

Retrieved HTML snapshots are retained in `source/`. Row-level CSV source URLs and
`retrieved_on` identify provenance. A third-party member-term dataset was evaluated
and rejected because older records produced overlapping seat occupants; it is not
used in any delivered CSV.

## Rebuilding and validation

`prepare_data.py` parses the retained HTML and prepares the tables. It checks
coverage, unique month keys, and reconciliation to 435 House / 100 Senate seats.
`build_csv.mjs` authors typed cell matrices with the bundled Artifact Tool,
checks a cell-value round trip, and serializes CSV with RFC 4180 quoting. No XLSX
or chart is required for these plain-data deliverables. Run the Python preparer
and then the JavaScript builder. The builder's runtime path is local to the
current Codex environment and may need adjustment elsewhere.

Refresh is deliberate: retrieve and review new source snapshots, advance the
fixed as-of and completed-month cutoff, check current presidential service, then
rerun and validate. Existing data is not fetched or silently updated by the builder.

To rebuild only the combined CSV, run `prepare_data.py`, then
`node build_csv.mjs political_control_monthly.csv` from this directory using the
configured bundled runtime. Omitting the filename rebuilds all CSV outputs.
