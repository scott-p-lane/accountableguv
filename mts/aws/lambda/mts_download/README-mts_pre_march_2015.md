# MTS backfill from the pre-March-2015 archive

Use `mts_feeds_pre_march_2015_download.py` for Treasury's fixed-width STAR
archive, which covers October 1997 through February 2015. The companion
`mts_pre_march_2015_transform.py` maps the archive's printed columns to the
existing MTS schema. Treasury's Fiscal Data API begins with March 2015.

From `mts/aws/lambda`, run the text archive backfill with Python:

```powershell
python mts_download/mts_feeds_pre_march_2015_download.py --start-date 1997-10-01 --end-date 2015-02-28
```

Both bounds are required and inclusive. The script selects calendar month ends.
Run a single month by supplying the same month-end date twice.

Local output defaults to `mts/test/data/mts/YYYY/MM` inside the repository,
the same location the monthly API script uses. Use `--output-dir` to change
the data root. The script writes `mts_table_1.json` through `mts_table_9.json`
and `manifest.json` under each month. It validates the report before writing
files and leaves byte-identical files in place on reruns.

To stage directly to S3, use the same bucket, profile, region, and Boto3 setup
as the [API downloader](README-mts_download_lambda.md):

```powershell
python mts_download/mts_feeds_pre_march_2015_download.py --start-date 2015-02-28 --end-date 2015-02-28 --bucket YOUR_BUCKET --profile dev --region us-east-1
```

The existing [MTS Glue loader](../../glue/mts_load/README-mts_load.md) can
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

[Treasury's Previous Issues archive](https://fiscal.treasury.gov/accounting/monthly-treasury-statement/previous)
