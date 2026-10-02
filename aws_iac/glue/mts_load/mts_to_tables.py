"""Load one validated MTS report into S3 Tables using AWS Glue 5.0 / Iceberg.

All source validation runs before table writes. Each table's report date is
replaced atomically; the nine tables are not a single transaction.
"""

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
TRANSFORM_VERSION = "1"
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


def load_report(s3, bucket, manifest_key, manifest_version_id=None):
    """Return typed rows for all nine tables, or fail before any table writes."""
    if not re.fullmatch(r"mts/\d{4}/\d{2}/manifest\.json", manifest_key):
        raise ValueError("manifest_key must be mts/YYYY/MM/manifest.json")
    raw_manifest, manifest_version = read_object(s3, bucket, manifest_key, manifest_version_id)
    manifest = json.loads(raw_manifest)
    report_date = date.fromisoformat(manifest["report_date"])
    prefix = f"mts/{report_date:%Y/%m}/"
    if manifest_key != prefix + "manifest.json":
        raise ValueError("Manifest path and report date disagree")
    files = manifest["files"]
    expected_keys = {prefix + table + ".json" for table in TABLES}
    if len(files) != len(TABLES) or {item["key"] for item in files} != expected_keys:
        raise ValueError("Manifest must contain exactly the nine MTS table keys")
    batch_id = hashlib.sha256(raw_manifest).hexdigest()
    loaded = {}
    ingested_at = datetime.now(timezone.utc)
    for item in files:
        key = item["key"]
        raw, version = read_object(s3, bucket, key, item.get("version_id"))
        digest = hashlib.sha256(raw).hexdigest()
        if digest != item["sha256"]:
            raise ValueError(f"SHA-256 mismatch: {key}; source may have been corrected")
        payload = json.loads(raw)
        rows = payload["data"]
        if (not isinstance(rows, list) or not rows or
                type(item["row_count"]) is not int or len(rows) != item["row_count"] or
                len(rows) != payload["meta"]["count"]):
            raise ValueError(f"Row count mismatch or empty table: {key}")
        if payload["report_date"] != report_date.isoformat():
            raise ValueError(f"Report date mismatch: {key}")
        table = key.rsplit("/", 1)[1].removesuffix(".json")
        types = source_types(table)
        if payload["meta"]["dataTypes"] != types:
            raise ValueError(f"Source schema changed: {table}; review the schema before loading")
        lineage = {
            "source_bucket": bucket, "source_key": key, "source_version_id": version,
            "source_sha256": digest, "source_url": payload["source_url"],
            "manifest_key": manifest_key, "manifest_version_id": manifest_version,
            "batch_id": batch_id, "transform_version": TRANSFORM_VERSION,
            "ingested_at": ingested_at,
        }
        typed_rows = []
        for index, row in enumerate(rows):
            if set(row) != set(types) or row.get("record_date") != report_date.isoformat():
                raise ValueError(f"Invalid columns or report date: {table} row {index}")
            try:
                typed_rows.append({**{name: convert_value(row[name], kind)
                                       for name, kind in types.items()}, **lineage})
            except ValueError as error:
                raise ValueError(f"{table} row {index}: {error}") from error
        loaded[table] = typed_rows
    return report_date, batch_id, loaded


def table_columns(table):
    return {**{name: SQL_TYPES[kind] for name, kind in sorted(source_types(table).items())},
            **LINEAGE_TYPES}


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
             "rest_endpoint", "manifest_key"]
    args = getResolvedOptions(sys.argv, names)
    version_args = getResolvedOptions(sys.argv, ["manifest_version_id"]) if any(
        arg == "--manifest_version_id" or arg.startswith("--manifest_version_id=")
        for arg in sys.argv) else {}
    logging.basicConfig(level=logging.INFO)
    s3 = boto3.client("s3", region_name=args["region"])
    report_date, batch_id, loaded = load_report(
        s3, args["feeds_bucket"], args["manifest_key"], version_args.get("manifest_version_id"))
    LOGGER.info("Validated report_date=%s batch_id=%s", report_date, batch_id)
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
        write_report(spark, args["namespace"], report_date, loaded)
        LOGGER.info("Completed all nine tables report_date=%s batch_id=%s", report_date, batch_id)
    finally:
        spark.stop()


if __name__ == "__main__":
    main()
