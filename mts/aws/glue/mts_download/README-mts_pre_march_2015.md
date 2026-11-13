# MTS backfill from the pre-March-2015 archive

Use `mts_feeds_pre_march_2015_download.py` for Treasury's fixed-width STAR
archive, which covers October 1997 through February 2015. The downloader
preserves the text report byte for byte and runs
[`mts_pre_march_2015_transform.py`](../mts_load/mts_pre_march_2015_transform.py)
to map its printed columns to the MTS schema. Treasury's Fiscal Data API
begins with March 2015.

From the repository root, run the text archive backfill with Python:

```powershell
python mts/aws/glue/mts_download/mts_feeds_pre_march_2015_download.py --start-date 1997-10-01 --end-date 2015-02-28
```

Both bounds are required and inclusive. The script selects calendar month ends.
Run a single month by supplying the same month-end date twice.

Local output defaults to `mts/test/data/mts/YYYY/MM` inside the repository,
the same location the monthly API script uses. Use `--output-dir` to change
the data root. The script writes the original report under `raw/`, then
writes `mts_table_1.json` through `mts_table_9.json` in the month folder.
It publishes `manifest.json` last with the nine table keys, hashes, and row
counts. The original text is available for troubleshooting.

To stage directly to S3, use the same bucket, profile, region, and Boto3 setup
as the [API downloader](../../lambda/mts_download/README-mts_download_lambda.md):

```powershell
python mts/aws/glue/mts_download/mts_feeds_pre_march_2015_download.py --start-date 2015-02-28 --end-date 2015-02-28 --bucket YOUR_BUCKET --profile dev --region us-east-1
```

The existing [MTS Glue loader](../mts_load/README-mts_load.md) can
load these manifests into the same nine tables. Start with
`--base_prefix mts/2015/02` for the example above, then use the usual export
and refresh workflow for local reports.

## Archive differences

- The text reports publish whole millions. The transformer stores those
  figures in dollars for the existing schema. Amounts reported below the
  source's display threshold and blank cells are stored as null.
- The archive prints labels and line order. It omits Fiscal Data's internal
  classification, parent, line, and record type codes. The transformer creates
  report-scoped row identifiers, preserves the original source line for
  tracing, derives row types from printed headings and totals, and normalizes
  workbook labels where there is a direct match. Workbook filters based on
  unavailable codes or historical labels may need adjustment.
- Table 1 derives `sequence_level_nbr` and `sequence_number_cd` from the printed
  fiscal-year headings, months, and year-to-date rows. The prior fiscal year
  uses code `1` and the current fiscal year uses `2`. Their detail rows use
  codes such as `1.1` and `2.1` for October. To populate these fields in
  existing data, rerun the archive download and Glue load for the affected
  months, then refresh the exports and local reports.
- Table 9 derives the same fields from the receipts and net outlays sections.
  Receipts use `1`, net outlays use `2`, and the social insurance detail
  rows use `1.3.1` through `1.3.3` at sequence level `3`.

[Treasury's Previous Issues archive](https://fiscal.treasury.gov/accounting/monthly-treasury-statement/previous)
