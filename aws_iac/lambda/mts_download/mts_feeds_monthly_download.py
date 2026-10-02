"""Download all nine MTS JSON tables to their report-month S3 prefix."""

from datetime import date, datetime, timedelta, timezone
from calendar import monthrange
import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_BASE = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/mts"
TABLES = tuple(f"mts_table_{number}" for number in range(1, 10))
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
LOGGER = logging.getLogger(__name__)
LOGGER.setLevel(logging.INFO)


def download(url):
    """Bound the response size and retry temporary Treasury HTTP failures."""
    for attempt in range(3):
        try:
            request = Request(url, headers={"User-Agent": "accountableguv-mts-ingestion/1.0"})
            with urlopen(request, timeout=25) as response:
                body = response.read(MAX_DOWNLOAD_BYTES + 1)
            if not body or len(body) > MAX_DOWNLOAD_BYTES:
                raise ValueError("Treasury response is empty or exceeds the download limit")
            return body
        except HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
        except (URLError, TimeoutError):
            if attempt == 2:
                raise
        time.sleep(2 ** attempt)


def latest_report_date(today):
    query = urlencode({"fields": "record_date", "sort": "-record_date", "page[size]": "1"})
    payload = json.loads(download(f"{API_BASE}/mts_table_1?{query}"))
    rows = payload.get("data", [])
    if not rows:
        raise ValueError("Treasury returned no MTS report dates")
    report_date = date.fromisoformat(rows[0]["record_date"])
    previous_month_end = today.replace(day=1) - timedelta(days=1)
    # Fail visibly on a delayed release instead of claiming an old month was collected.
    if report_date != previous_month_end:
        raise ValueError(
            f"Expected report through {previous_month_end}, Treasury returned {report_date}"
        )
    return report_date


def fetch_table(table, report_date):
    rows = []
    total = None
    metadata = None
    source_url = f"{API_BASE}/{table}"
    for page in range(1, 21):
        query = urlencode({"filter": f"record_date:eq:{report_date.isoformat()}",
                           "page[size]": "1000", "page[number]": str(page)})
        payload = json.loads(download(f"{source_url}?{query}"))
        data, meta = payload["data"], payload["meta"]
        if total is None:
            total = int(meta["total-count"])
            metadata = {key: meta[key] for key in ("labels", "dataTypes", "dataFormats") if key in meta}
        if total <= 0 or int(meta["total-count"]) != total:
            raise ValueError(f"Missing or changing report data for {table}")
        if not data or any(row.get("record_date") != report_date.isoformat() for row in data):
            raise ValueError(f"Invalid report dates or empty page in {table}")
        rows.extend(data)
        if len(rows) >= total:
            if len(rows) != total:
                raise ValueError(f"Unexpected row count for {table}")
            return {"report_date": report_date.isoformat(), "source_url": source_url,
                    "data": rows, "meta": {**metadata, "count": total}}
    raise ValueError(f"Pagination limit exceeded for {table}")


def store_json(bucket, s3, key, payload, report_date):
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(body).hexdigest()
    existing = s3.list_objects_v2(Bucket=bucket, Prefix=key, MaxKeys=1)
    if any(item["Key"] == key for item in existing.get("Contents", [])):
        metadata = s3.head_object(Bucket=bucket, Key=key).get("Metadata", {})
        if metadata.get("sha256") == digest:
            return "unchanged", digest
    s3.put_object(
        Bucket=bucket, Key=key, Body=body, ContentType="application/json",
        ServerSideEncryption="AES256",
        Metadata={"report-date": report_date.isoformat(), "sha256": digest},
    )
    return "stored", digest


def report_dates_between(start, end):
    """Yield calendar month-end report dates within inclusive date bounds."""
    month = start.replace(day=1)
    while True:
        month_end = month.replace(day=monthrange(month.year, month.month)[1])
        if month_end > end:
            return
        if month_end >= start:
            yield month_end
        if month_end == date.max:
            return
        month = month_end + timedelta(days=1)


def report_objects(today, report_date=None):
    if report_date is None:
        report_date = latest_report_date(today)
    prefix = f"mts/{report_date:%Y}/{report_date:%m}"
    # Validate every table before starting uploads, preventing incomplete API downloads.
    tables = {table: fetch_table(table, report_date) for table in TABLES}
    files = []
    objects = []
    for table, payload in tables.items():
        key = f"{prefix}/{table}.json"
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
        objects.append((key, payload))
        files.append({"key": key, "sha256": digest, "row_count": len(payload["data"])})
    # Consumers can verify these hashes; this marker is updated only after all tables.
    manifest = {"report_date": report_date.isoformat(), "files": files}
    objects.append((f"{prefix}/manifest.json", manifest))
    return report_date, prefix, objects


def store_latest(bucket, s3, today, report_date=None):
    report_date, prefix, objects = report_objects(today, report_date)
    for key, payload in objects:
        status, _ = store_json(bucket, s3, key, payload, report_date)
        LOGGER.info("MTS object %s: %s", key, status)
    result = {"status": status, "bucket": bucket, "prefix": prefix,
              "report_date": report_date.isoformat(), "table_count": len(TABLES)}
    LOGGER.info("MTS result: %s", json.dumps(result))
    return result


def store_local(output_dir, today, report_date=None):
    report_date, prefix, objects = report_objects(today, report_date)
    output_dir = Path(output_dir).resolve()
    changed = False
    for key, payload in objects:
        destination = output_dir.joinpath(*key.split("/"))
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists() or destination.read_bytes() != body:
            destination.write_bytes(body)
            changed = True
        LOGGER.info("MTS file: %s", destination)
    return {"status": "stored" if changed else "unchanged",
            "directory": str(output_dir.joinpath(*prefix.split("/"))),
            "report_date": report_date.isoformat(), "table_count": len(TABLES)}


def lambda_handler(event, context):
    import boto3

    return store_latest(
        os.environ["STAGING_BUCKET_NAME"], boto3.client("s3"),
        datetime.now(timezone.utc).date(),
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    destination = parser.add_mutually_exclusive_group()
    destination.add_argument("--bucket", help="Explicitly upload to this existing S3 bucket instead of local files")
    destination.add_argument("--output-dir", type=Path,
                             help="Local data root; appends mts/YYYY/MM (default: project/test/data)")
    parser.add_argument("--profile", help="AWS profile for local execution, including SSO profiles")
    parser.add_argument("--region", help="AWS region (otherwise use your AWS configuration)")
    parser.add_argument("--start-date", type=date.fromisoformat, metavar="YYYY-MM-DD",
                        help="Inclusive earliest report date; requires --end-date")
    parser.add_argument("--end-date", type=date.fromisoformat, metavar="YYYY-MM-DD",
                        help="Inclusive latest report date; requires --start-date")
    args = parser.parse_args(argv)
    dates = None
    if (args.start_date is None) != (args.end_date is None):
        parser.error("--start-date and --end-date must be supplied together")
    if args.start_date is not None:
        if args.start_date > args.end_date:
            parser.error("--start-date must be on or before --end-date")
        dates = list(report_dates_between(args.start_date, args.end_date))
        if not dates:
            parser.error("The date range must include at least one month-end report date")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    today = datetime.now(timezone.utc).date()
    if not args.bucket:
        if args.profile or args.region:
            parser.error("--profile and --region apply only with --bucket")
        output_dir = args.output_dir or Path(__file__).resolve().parents[3] / "test" / "data"
        try:
            result = ([store_local(output_dir, today, report_date) for report_date in dates]
                      if dates is not None else store_local(output_dir, today))
        except (OSError, ValueError, KeyError) as error:
            LOGGER.error("MTS download failed: %s", error)
            return 1
        print(json.dumps(result, indent=2))
        return 0
    try:
        import boto3
        from botocore.exceptions import BotoCoreError, ClientError
    except ImportError:
        print("Install local dependencies: python -m pip install -r requirements.txt", file=sys.stderr)
        return 1
    try:
        session = boto3.Session(profile_name=args.profile, region_name=args.region)
        s3 = session.client("s3")
        result = ([store_latest(args.bucket, s3, today, report_date) for report_date in dates]
                  if dates is not None else store_latest(args.bucket, s3, today))
    except (BotoCoreError, ClientError, URLError, TimeoutError, ValueError, KeyError) as error:
        LOGGER.error("MTS download failed: %s", error)
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
