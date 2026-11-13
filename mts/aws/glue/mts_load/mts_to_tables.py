"""Load selected MTS reports into S3 Tables using AWS Glue 5.0 / Iceberg.

Each report's source validation runs before its table writes. Each table's report date is
replaced atomically; the nine tables are not a single transaction.
"""

import argparse
from calendar import monthrange
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation, localcontext
import hashlib
import json
import logging
import re
import sys

LOGGER = logging.getLogger(__name__)
TABLES = tuple(f"mts_table_{number}" for number in range(1, 10))
MAX_OBJECT_BYTES = 32 * 1024 * 1024
TRANSFORM_VERSION = "4"
COMMON_TYPES = {
    **dict.fromkeys(("classification_desc", "classification_id", "data_type_cd",
                     "line_code_nbr", "parent_id", "print_order_nbr", "record_type_cd",
                     "sequence_level_nbr", "sequence_number_cd", "table_nbr"), "STRING"),
    "record_date": "DATE", "src_line_nbr": "INTEGER",
    "record_calendar_day": "DAY", "record_calendar_month": "MONTH",
    "record_calendar_quarter": "QUARTER", "record_calendar_year": "YEAR",
    "record_fiscal_quarter": "QUARTER", "record_fiscal_year": "YEAR",
}
# Reviewed against the existing August 2026 feed; source changes require review.
CURRENCY_FIELDS = {
    "mts_table_1": "current_month_dfct_sur_amt current_month_gross_outly_amt current_month_gross_rcpt_amt",
    "mts_table_2": "current_fytd_budget_amt current_month_budget_amt current_year_budget_est_amt next_year_budget_est_amt prior_fytd_budget_amt",
    "mts_table_3": "current_fytd_rcpt_outly_amt current_month_rcpt_outly_amt current_year_budget_est_amt prior_fytd_rcpt_outly_amt",
    "mts_table_4": "current_fytd_gross_rcpt_amt current_fytd_net_rcpt_amt current_fytd_refund_amt current_month_gross_rcpt_amt current_month_net_rcpt_amt current_month_refund_amt prior_fytd_gross_rcpt_amt prior_fytd_net_rcpt_amt prior_fytd_refund_amt",
    "mts_table_5": "current_fytd_app_rcpt_amt current_fytd_gross_outly_amt current_fytd_net_outly_amt current_month_app_rcpt_amt current_month_gross_outly_amt current_month_net_outly_amt prior_fytd_app_rcpt_amt prior_fytd_gross_outly_amt prior_fytd_net_outly_amt",
    "mts_table_6": "begin_month_acct_bal_amt begin_year_acct_bal_amt close_month_acct_bal_amt current_month_net_txn_amt fytd_net_txn_amt prior_fytd_net_txn_amt",
    "mts_table_7": "apr_rcpt_outly_amt aug_rcpt_outly_amt current_fytd_rcpt_outly_amt dec_rcpt_outly_amt feb_rcpt_outly_amt jan_rcpt_outly_amt jul_rcpt_outly_amt jun_rcpt_outly_amt mar_rcpt_outly_amt may_rcpt_outly_amt nov_rcpt_outly_amt oct_rcpt_outly_amt prior_fytd_rcpt_outly_amt sep_rcpt_outly_amt",
    "mts_table_8": "begin_month_acct_bal_amt begin_year_acct_bal_amt close_month_acct_bal_amt current_month_excess_amt current_month_outly_amt current_month_rcpt_amt fytd_excess_amt fytd_outly_amt fytd_rcpt_amt",
    "mts_table_9": "current_fytd_rcpt_outly_amt current_month_rcpt_outly_amt prior_fytd_rcpt_outly_amt",
}
SQL_TYPES = {"STRING": "string", "DATE": "date", "CURRENCY": "decimal(38,2)",
             "INTEGER": "bigint", "DAY": "int", "MONTH": "int", "QUARTER": "int", "YEAR": "int"}
LINEAGE_TYPES = {
    "source_bucket": "string", "source_key": "string", "source_version_id": "string",
    "source_sha256": "string", "source_url": "string", "manifest_key": "string",
    "manifest_version_id": "string", "batch_id": "string", "transform_version": "string",
    "ingested_at": "timestamp",
}


def source_types(table):
    return {**COMMON_TYPES, **dict.fromkeys(CURRENCY_FIELDS[table].split(), "CURRENCY")}


def normalize_classification(value):
    if value is None:
        return None

    def title_word(match):
        word = match.group().lower()
        if word == "fy":
            return "FY"
        if match.start() and word in {"and", "by", "the", "to"}:
            return word
        return word.capitalize()

    return re.sub(r"\w+(?:['’]\w+)*", title_word, value)


def convert_value(value, kind):
    if value is None or value == "null":
        return None
    if not isinstance(value, str):
        raise ValueError(f"Expected source string for {kind}, got {type(value).__name__}")
    if kind == "STRING":
        return value
    if kind == "DATE":
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("Expected ISO date")
        return date.fromisoformat(value)
    if kind == "CURRENCY":
        try:
            with localcontext() as context:
                context.prec = 50
                amount = Decimal(value)
                if not amount.is_finite() or abs(amount) >= Decimal(10) ** 36:
                    raise ValueError("Currency exceeds decimal(38,2)")
                rounded = amount.quantize(Decimal("0.01"))
                if rounded != amount:
                    raise ValueError("Currency would lose precision")
                return rounded
        except InvalidOperation as error:
            raise ValueError("Invalid currency") from error
    if not re.fullmatch(r"-?\d+", value):
        raise ValueError(f"Invalid {kind}")
    number = int(value)
    low, high = {"DAY": (1, 31), "MONTH": (1, 12), "QUARTER": (1, 4),
                 "YEAR": (1, 9999), "INTEGER": (-(2 ** 63), 2 ** 63 - 1)}[kind]
    if not low <= number <= high:
        raise ValueError(f"Out of range {kind}")
    return number


def read_object(s3, bucket, key, version_id=None):
    request = {"Bucket": bucket, "Key": key}
    if version_id:
        request["VersionId"] = version_id
    response = s3.get_object(**request)
    body = response["Body"]
    try:
        data = body.read(MAX_OBJECT_BYTES + 1)
    finally:
        body.close()
    if len(data) > MAX_OBJECT_BYTES:
        raise ValueError(f"Source exceeds {MAX_OBJECT_BYTES} bytes: {key}")
    return data, response.get("VersionId", "")


def read_verified_object(s3, bucket, item):
    key = item["key"]
    raw, version = read_object(s3, bucket, key, item.get("version_id"))
    if hashlib.sha256(raw).hexdigest() != item["sha256"]:
        raise ValueError(f"SHA-256 mismatch: {key}; source may have been corrected")
    return raw, version


def report_tables(s3, bucket, manifest, prefix, report_date):
    """Yield source rows and lineage per table or API page."""
    files = manifest["files"]
    source_format = manifest.get("format")
    if source_format == "treasury-star-text":
        if len(files) != 1:
            raise ValueError("Archive manifest must contain one Treasury text file")
        item = files[0]
        if not re.fullmatch(re.escape(f"{prefix}raw/mts{report_date:%m%y}-") + r"[0-9a-f]{64}\.txt",
                            item["key"]):
            raise ValueError("Invalid archive text object key")
        raw, version = read_verified_object(s3, bucket, item)
        from mts_pre_march_2015_transform import transform_report

        try:
            tables = transform_report(raw, report_date, item["source_url"], source_types)
        except ValueError as error:
            raise ValueError(f"{item['key']}: {error}") from error
        for table, payload in tables.items():
            yield table, payload["data"], item, version
        return

    if source_format == "treasury-fiscal-data-api":
        page_pattern = re.compile(re.escape(prefix) + r"raw/(mts_table_[1-9])/page-(\d{2})-[0-9a-f]{64}\.json")
        totals, counts, page_numbers = {}, {}, {}
        for item in sorted(files, key=lambda entry: entry["key"]):
            key = item["key"]
            match = page_pattern.fullmatch(key)
            if not match:
                raise ValueError(f"Invalid Treasury API page key: {key}")
            table, page = match[1], int(match[2])
            if page != page_numbers.get(table, 0) + 1:
                raise ValueError(f"Missing or duplicate Treasury API page: {key}")
            page_numbers[table] = page
            raw, version = read_verified_object(s3, bucket, item)
            payload = json.loads(raw)
            rows, meta = payload["data"], payload["meta"]
            if meta["dataTypes"] != source_types(table):
                raise ValueError(f"Source schema changed: {table}; review the schema before loading")
            total = int(meta["total-count"])
            if not isinstance(rows, list) or not rows or total <= 0 or totals.setdefault(table, total) != total:
                raise ValueError(f"Row count mismatch or empty Treasury API page: {key}")
            counts[table] = counts.get(table, 0) + len(rows)
            yield table, rows, item, version
        if set(totals) != set(TABLES) or counts != totals:
            raise ValueError("Treasury API manifest is missing tables or rows")
        return

    if source_format is not None:
        raise ValueError(f"Unsupported MTS manifest format: {source_format}")
    expected_keys = {prefix + table + ".json" for table in TABLES}
    if len(files) != len(TABLES) or {item["key"] for item in files} != expected_keys:
        raise ValueError("Manifest must contain exactly the nine MTS table keys")
    for item in files:
        key = item["key"]
        raw, version = read_verified_object(s3, bucket, item)
        payload = json.loads(raw)
        rows = payload["data"]
        if (not isinstance(rows, list) or not rows or
                type(item["row_count"]) is not int or len(rows) != item["row_count"] or
                len(rows) != payload["meta"]["count"]):
            raise ValueError(f"Row count mismatch or empty table: {key}")
        if payload["report_date"] != report_date.isoformat():
            raise ValueError(f"Report date mismatch: {key}")
        table = key.rsplit("/", 1)[1].removesuffix(".json")
        if payload["meta"]["dataTypes"] != source_types(table):
            raise ValueError(f"Source schema changed: {table}; review the schema before loading")
        if table == "mts_table_9" and payload["meta"].get("archive", {}).get("format") == "treasury-star-text":
            from mts_pre_march_2015_transform import assign_table_9_sequences

            # Older staged July 2003 JSON included the next page's heading.
            rows = [row for row in rows if not (
                report_date == date(2003, 7, 31)
                and row["classification_desc"] == "ONTHLY TREASURY STATEMENT of Receipts and Outlays of the United")]
            assign_table_9_sequences(rows)
        yield table, rows, {**item, "source_url": payload["source_url"]}, version


def load_report(s3, bucket, manifest_key):
    """Return typed rows for all nine tables, or fail before any table writes."""
    if not re.fullmatch(r"mts/\d{4}/\d{2}/manifest\.json", manifest_key):
        raise ValueError("manifest_key must be mts/YYYY/MM/manifest.json")
    raw_manifest, manifest_version = read_object(s3, bucket, manifest_key)
    manifest = json.loads(raw_manifest)
    report_date = date.fromisoformat(manifest["report_date"])
    prefix = f"mts/{report_date:%Y/%m}/"
    if manifest_key != prefix + "manifest.json":
        raise ValueError("Manifest path and report date disagree")
    batch_id = hashlib.sha256(raw_manifest).hexdigest()
    loaded = {}
    ingested_at = datetime.now(timezone.utc)
    for table, rows, item, version in report_tables(s3, bucket, manifest, prefix, report_date):
        types = source_types(table)
        lineage = {
            "source_bucket": bucket, "source_key": item["key"], "source_version_id": version,
            "source_sha256": item["sha256"], "source_url": item["source_url"],
            "manifest_key": manifest_key, "manifest_version_id": manifest_version,
            "batch_id": batch_id, "transform_version": TRANSFORM_VERSION,
            "ingested_at": ingested_at,
        }
        typed_rows = loaded.setdefault(table, [])
        for index, row in enumerate(rows):
            if set(row) != set(types) or row.get("record_date") != report_date.isoformat():
                raise ValueError(f"Invalid columns or report date: {table} row {index}")
            try:
                typed = {name: convert_value(row[name], kind) for name, kind in types.items()}
                typed["classification_desc"] = normalize_classification(typed["classification_desc"])
                typed_rows.append({**typed, **lineage})
            except ValueError as error:
                raise ValueError(f"{table} row {index}: {error}") from error
    return report_date, batch_id, loaded


def table_columns(table):
    return {**{name: SQL_TYPES[kind] for name, kind in sorted(source_types(table).items())},
            **LINEAGE_TYPES}


def select_manifests(s3, bucket, base_prefix, *, start_date=None, end_date=None):
    start_date = None if start_date in (None, "", "unset") else start_date
    end_date = None if end_date in (None, "", "unset") else end_date
    if (start_date is None) != (end_date is None):
        raise ValueError("Supply --start_date and --end_date together")
    if start_date is not None:
        try:
            start, end = date.fromisoformat(start_date), date.fromisoformat(end_date)
            if (start.isoformat(), end.isoformat()) != (start_date, end_date):
                raise ValueError
        except ValueError as error:
            raise ValueError("--start_date and --end_date must be valid YYYY-MM-DD dates") from error
        if start > end:
            raise ValueError("--start_date must be on or before --end_date")
        if base_prefix in (None, "", "REQUIRED"):
            base_prefix = "mts"
    if not base_prefix:
        raise ValueError("Supply --base_prefix")
    prefix = base_prefix.rstrip("/")
    if not re.fullmatch(r"mts(?:/\d{4}(?:/(?:0[1-9]|1[0-2]))?)?", prefix):
        raise ValueError("base_prefix must be mts, mts/YYYY, or mts/YYYY/MM")
    prefix += "/"  # Directory boundary prevents matching sibling prefixes.
    keys = set()
    # No Delimiter: S3 lists all descendants, across every paginated response.
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for item in page.get("Contents", []):
            key = item["Key"]
            if key.startswith(prefix) and key.endswith("/manifest.json"):
                if not re.fullmatch(r"mts/\d{4}/(?:0[1-9]|1[0-2])/manifest\.json", key):
                    raise ValueError(f"Unexpected MTS manifest location: {key}")
                if start_date is not None:
                    year, month = int(key[4:8]), int(key[9:11])
                    report_date = date(year, month, monthrange(year, month)[1])
                    if not start <= report_date <= end:
                        continue
                keys.add(key)
    if not keys:
        date_filter = f" for report dates {start} through {end}" if start_date is not None else ""
        raise ValueError(f"No MTS manifests found under s3://{bucket}/{prefix}{date_filter}")
    return sorted(keys)


def load_manifests(s3, spark, bucket, namespace, keys):
    for index, key in enumerate(keys, 1):
        LOGGER.info("Loading manifest %s/%s: %s", index, len(keys), key)
        try:
            report_date, batch_id, loaded = load_report(s3, bucket, key)
            write_report(spark, namespace, report_date, loaded)
            LOGGER.info("Completed manifest=%s report_date=%s batch_id=%s", key, report_date, batch_id)
            del loaded  # Keep only one month's source rows in memory.
        except Exception:
            LOGGER.exception("Failed manifest=%s; completed %s/%s reports", key, index - 1, len(keys))
            raise


def write_report(spark, namespace, report_date, loaded):
    from pyspark.sql import functions as functions

    if not re.fullmatch(r"[a-z][a-z0-9_]{0,254}", namespace):
        raise ValueError("Invalid namespace")
    frames = {}
    # Preflight every existing schema before replacing any report data. Separate
    # CREATE and write operations are required by the S3 Tables REST endpoint.
    for table in TABLES:
        target = f"s3tables.{namespace}.{table}"
        columns = table_columns(table)
        ddl = ", ".join(f"`{name}` {kind}" for name, kind in columns.items())
        spark.sql(f"CREATE TABLE IF NOT EXISTS {target} ({ddl}) USING iceberg "
                  "PARTITIONED BY (record_date) TBLPROPERTIES ('format-version'='2')")
        actual = {field.name: field.dataType.simpleString() for field in spark.table(target).schema}
        if actual != columns:
            raise ValueError(f"Target schema differs: {target}; migrate it explicitly")
        frames[table] = spark.createDataFrame(loaded[table], ddl)
    for table in TABLES:
        target = f"s3tables.{namespace}.{table}"
        predicate = functions.col("record_date") == functions.lit(report_date)
        # Whole-period replacement removes rows that disappeared in a correction
        # and makes reruns safe without inventing a business key for Treasury rows.
        frames[table].coalesce(1).writeTo(target).overwrite(predicate)
        count = spark.table(target).where(predicate).count()
        if count != len(loaded[table]):
            raise ValueError(f"Target row count mismatch: {target}")
        LOGGER.info("Loaded %s report_date=%s rows=%s", target, report_date, count)


def main():
    import boto3
    from awsglue.utils import getResolvedOptions
    from pyspark.sql import SparkSession

    names = ["JOB_NAME", "feeds_bucket", "table_bucket_arn", "namespace", "region",
             "rest_endpoint", "base_prefix"]
    args = getResolvedOptions(sys.argv, names)
    date_options = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    date_options.add_argument("--start_date")
    date_options.add_argument("--end_date")
    bounds, _ = date_options.parse_known_args(sys.argv[1:])
    logging.basicConfig(level=logging.INFO)
    s3 = boto3.client("s3", region_name=args["region"])
    keys = select_manifests(s3, args["feeds_bucket"], args["base_prefix"],
                            start_date=bounds.start_date, end_date=bounds.end_date)
    LOGGER.info("Selected %s manifests", len(keys))
    builder = SparkSession.builder.appName(args["JOB_NAME"])
    settings = {
        "spark.sql.catalog.s3tables": "org.apache.iceberg.spark.SparkCatalog",
        "spark.sql.catalog.s3tables.type": "rest",
        "spark.sql.catalog.s3tables.uri": args["rest_endpoint"],
        "spark.sql.catalog.s3tables.warehouse": args["table_bucket_arn"],
        "spark.sql.catalog.s3tables.rest.sigv4-enabled": "true",
        "spark.sql.catalog.s3tables.rest.signing-name": "s3tables",
        "spark.sql.catalog.s3tables.rest.signing-region": args["region"],
        "spark.sql.catalog.s3tables.io-impl": "org.apache.iceberg.aws.s3.S3FileIO",
        "spark.sql.catalog.s3tables.rest-metrics-reporting-enabled": "false",
        "spark.sql.session.timeZone": "UTC",
    }
    for key, value in settings.items():
        builder = builder.config(key, value)
    spark = builder.getOrCreate()
    try:
        load_manifests(s3, spark, args["feeds_bucket"], args["namespace"], keys)
        LOGGER.info("Completed all %s reports", len(keys))
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
