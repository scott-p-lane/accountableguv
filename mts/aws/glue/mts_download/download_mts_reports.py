"""Download an inclusive range of Treasury MTS reports from AWS Glue."""

import argparse
from calendar import monthrange
from datetime import date, datetime, timezone
from functools import partial
import logging

import mts_feeds_monthly_download as monthly
from mts_feeds_pre_march_2015_download import ARCHIVE_BOUNDS, archive_report_objects


LOGGER = logging.getLogger(__name__)


def optional_int(value):
    value = value.strip()
    return None if value in ("", "unset") else int(value)


def parse_run(argv, today):
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--start_year", type=optional_int)
    parser.add_argument("--start_month", type=optional_int)
    parser.add_argument("--end_year", type=optional_int)
    parser.add_argument("--end_month", type=optional_int)
    parser.add_argument("--destination", help="S3 URI of the report prefix")
    parser.add_argument("--default_bucket", required=True)
    parser.add_argument("--alternate_destination")
    # Glue injects runtime arguments in addition to the job's own options.
    args, _ = parser.parse_known_args(argv)

    if args.start_year is None or args.start_month is None:
        parser.error("Supply --start_year and --start_month")
    if (args.end_year is None) != (args.end_month is None):
        parser.error("Supply --end_year and --end_month together")
    try:
        start = date(args.start_year, args.start_month, 1)
        end_year = args.end_year if args.end_year is not None else start.year
        end_month = args.end_month if args.end_month is not None else start.month
        end = date(end_year, end_month, monthrange(end_year, end_month)[1])
    except ValueError as error:
        parser.error(str(error))
    if start < ARCHIVE_BOUNDS[0].replace(day=1):
        parser.error("The earliest supported report month is October 1997")
    if start > end:
        parser.error("The start month must be on or before the end month")
    if end >= today.replace(day=1):
        parser.error("The end month must be a completed calendar month")

    default = f"s3://{args.default_bucket}/mts"
    destination = (args.destination or "").strip()
    destination = default if destination in ("", "default") else destination.rstrip("/")
    if destination not in (default, args.alternate_destination):
        parser.error(f"Destination must be {default} or the stack's configured alternate destination")
    bucket, _, prefix = destination[len("s3://"):].partition("/")
    return start, end, bucket, prefix


def download_reports(s3, today, start, end, bucket, prefix):
    for report_date in monthly.report_dates_between(start, end):
        prepare_report = archive_report_objects if report_date <= ARCHIVE_BOUNDS[1] else monthly.report_objects
        try:
            monthly.store_latest(bucket, s3, today, report_date,
                                 prepare_report=partial(prepare_report, base_prefix=prefix))
        except Exception:
            LOGGER.exception("MTS download failed for report date %s", report_date)
            raise


def main(argv=None):
    import boto3

    logging.basicConfig(level=logging.INFO)
    today = datetime.now(timezone.utc).date()
    start, end, bucket, prefix = parse_run(argv, today)
    download_reports(boto3.client("s3"), today, start, end, bucket, prefix)


if __name__ == "__main__":
    main()
