"""Run MTS SELECT queries and copy Athena's CSV results to a named S3 export folder."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

from mts_postgres import TABLES, wait_query

QUERY_FOLDER = Path(__file__).resolve().parents[2] / "local_data" / "athena_export"


def s3_location(uri):
    location = urlparse(uri)
    if location.scheme != "s3" or not location.netloc or location.query or location.fragment:
        raise ValueError("Expected an s3://bucket/prefix URI")
    return location.netloc, location.path.lstrip("/")


def export_csv(athena, s3, args):
    bucket, prefix = s3_location(args.s3_prefix)
    run = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:12]
    folder = (prefix.rstrip("/") + "/" if prefix else "") + run + "/"
    manifest = {"format": "athena-select-csv", "catalog": args.catalog,
                "namespace": args.namespace, "tables": []}
    print(f"Export folder: s3://{bucket}/{folder}", flush=True)
    for table in args.tables:
        query = (QUERY_FOLDER / f"export_{table}.sql").read_text(encoding="utf-8")
        query_id = athena.start_query_execution(
            QueryString=query, WorkGroup=args.workgroup,
            QueryExecutionContext={"Catalog": args.catalog, "Database": args.namespace},
            ResultReuseConfiguration={"ResultReuseByAgeConfiguration": {"Enabled": False}},
        )["QueryExecutionId"]
        wait_query(athena, query_id, args.timeout)
        execution = athena.get_query_execution(QueryExecutionId=query_id)["QueryExecution"]
        source_uri = execution["ResultConfiguration"]["OutputLocation"]
        source_bucket, source_key = s3_location(source_uri)
        target_key = folder + table + ".csv"
        # Server-side S3 copy: the CSV never passes through the local machine.
        # The managed copy supports multipart copying for large result files.
        s3.copy({"Bucket": source_bucket, "Key": source_key}, bucket, target_key,
                ExtraArgs={"ServerSideEncryption": "AES256"})
        manifest["tables"].append({"name": table, "query_id": query_id,
                                   "csv": f"s3://{bucket}/{target_key}"})
        print(f"Exported {table}: s3://{bucket}/{target_key}", flush=True)
    # Written only after all selected table exports succeed.
    s3.put_object(Bucket=bucket, Key=folder + "export_complete.json",
                  Body=json.dumps(manifest, indent=2).encode("utf-8"),
                  ContentType="application/json", ServerSideEncryption="AES256")
    return manifest


def main(argv=None, *, all_tables=False):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--s3-prefix", required=True, help="Destination s3://bucket/prefix")
    parser.add_argument("--region", required=True)
    parser.add_argument("--profile")
    parser.add_argument("--catalog", default="s3tablescatalog/acctguv-mts")
    parser.add_argument("--namespace", default="silver_mts")
    parser.add_argument("--workgroup", default="acctguv-mts-queries")
    if all_tables:
        parser.set_defaults(tables=list(TABLES))
    else:
        parser.add_argument("--tables", nargs="+", choices=TABLES, default=list(TABLES))
    parser.add_argument("--timeout", type=int, default=900)
    args = parser.parse_args(argv)
    if args.timeout <= 0 or len(args.tables) != len(set(args.tables)):
        parser.error("Timeout must be positive and tables must be unique")
    try:
        s3_location(args.s3_prefix)
    except ValueError as error:
        parser.error(str(error))
    import boto3
    session = boto3.Session(profile_name=args.profile, region_name=args.region)
    export_csv(session.client("athena"), session.client("s3"), args)


if __name__ == "__main__":
    main()
