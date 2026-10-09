"""Export MTS S3 Tables via Athena and bulk-load an offline bundle into Postgres."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import time

TABLES = tuple(f"mts_table_{n}" for n in range(1, 10))


def pg_type(kind):
    mapping = {"varchar": "text", "string": "text", "date": "date",
               "timestamp": "timestamp without time zone", "bigint": "bigint",
               "integer": "integer", "int": "integer", "boolean": "boolean",
               "double": "double precision", "float": "real", "smallint": "smallint"}
    if kind in mapping:
        return mapping[kind]
    match = re.fullmatch(r"decimal\((\d+),\s*(\d+)\)", kind)
    if match and 1 <= int(match[1]) <= 38 and 0 <= int(match[2]) <= int(match[1]):
        return f"numeric({int(match[1])},{int(match[2])})"
    raise ValueError(f"Unsupported Athena type: {kind}")


def quote_athena(name):
    return '"' + name.replace('"', '""') + '"'


def wait_query(client, query_id, timeout):
    deadline = time.monotonic() + timeout
    try:
        while True:
            status = client.get_query_execution(QueryExecutionId=query_id)["QueryExecution"]["Status"]
            if status["State"] == "SUCCEEDED":
                return
            if status["State"] in ("FAILED", "CANCELLED"):
                raise RuntimeError(f"Athena {query_id}: {status.get('StateChangeReason', status['State'])}")
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Athena query timed out: {query_id}")
            time.sleep(1)
    except (TimeoutError, KeyboardInterrupt):
        client.stop_query_execution(QueryExecutionId=query_id)
        raise


def export_bundle(client, args):
    folder = Path(args.bundle)
    folder.mkdir(parents=True, exist_ok=False)
    manifest = {"version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
                "catalog": args.catalog, "namespace": args.namespace, "tables": []}
    for table in args.tables:
        query = f"SELECT * FROM {quote_athena(table)}"
        query_id = client.start_query_execution(
            QueryString=query, WorkGroup=args.workgroup,
            QueryExecutionContext={"Catalog": args.catalog, "Database": args.namespace},
            ResultReuseConfiguration={"ResultReuseByAgeConfiguration": {"Enabled": False}},
        )["QueryExecutionId"]
        wait_query(client, query_id, args.timeout)
        token, columns, count = None, None, 0
        digest = hashlib.sha256()
        with (folder / f"{table}.jsonl").open("wb") as output:
            while True:
                request = {"QueryExecutionId": query_id, "MaxResults": 1000}
                if token:
                    request["NextToken"] = token
                response = client.get_query_results(**request)
                result = response["ResultSet"]
                if columns is None:
                    columns = [{"name": c["Name"], "type": pg_type(c["Type"])}
                               for c in result["ResultSetMetadata"]["ColumnInfo"]]
                rows = result.get("Rows", [])[0 if token else 1:]
                for row in rows:
                    values = [cell.get("VarCharValue") for cell in row["Data"]]
                    if len(values) != len(columns):
                        raise ValueError(f"Unexpected row width in {table}")
                    data = (json.dumps(values, ensure_ascii=False) + "\n").encode("utf-8")
                    output.write(data)
                    digest.update(data)
                    count += 1
                token = response.get("NextToken")
                if not token:
                    break
        manifest["tables"].append({"name": table, "columns": columns, "rows": count,
                                   "sha256": digest.hexdigest(), "query_id": query_id})
        print(f"Exported {table}: {count} rows", flush=True)
    # A bundle without its final manifest is incomplete and cannot be imported.
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def bundle_rows(path, entry):
    digest, count = hashlib.sha256(), 0
    with path.open("rb") as source:
        for line in source:
            digest.update(line)
            row = json.loads(line)
            if (not isinstance(row, list) or len(row) != len(entry["columns"])
                    or any(v is not None and not isinstance(v, str) for v in row)):
                raise ValueError(f"Invalid row in {entry['name']}")
            count += 1
            yield row
    if count != entry["rows"] or digest.hexdigest() != entry["sha256"]:
        raise ValueError(f"Bundle count/checksum mismatch: {entry['name']}")


def load_bundle(args):
    import psycopg
    from psycopg import sql

    folder = Path(args.bundle)
    manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    if manifest["version"] != 1 or not manifest["tables"]:
        raise ValueError("Unsupported or empty bundle")
    names = [entry["name"] for entry in manifest["tables"]]
    if len(names) != len(set(names)) or any(name not in TABLES for name in names):
        raise ValueError("Invalid bundle tables")
    dsn = os.environ.get(args.dsn_env)
    if not dsn:
        raise ValueError(f"Set {args.dsn_env} to your PostgreSQL connection string")
    # A connection context commits only after every COPY and validation succeeds.
    with psycopg.connect(dsn) as conn, conn.cursor() as cursor:
        cursor.execute("SET LOCAL timezone = 'UTC'")
        cursor.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(args.schema)))
        targets = []
        for entry in manifest["tables"]:
            columns = entry["columns"]
            if not columns or len({c["name"] for c in columns}) != len(columns):
                raise ValueError("Invalid bundle columns")
            allowed = set(pg_type(t) for t in ("string", "date", "timestamp", "bigint", "int",
                                               "boolean", "double", "float", "smallint"))
            for column in columns:
                kind = column["type"]
                if kind not in allowed:
                    # Validate before using a type as SQL syntax.
                    pg_type(kind.replace("numeric", "decimal"))
            target = sql.Identifier(args.schema, entry["name"])
            definition = sql.SQL(", ").join(sql.SQL("{} {}").format(
                sql.Identifier(c["name"]), sql.SQL(c["type"])) for c in columns)
            cursor.execute(sql.SQL("CREATE TABLE IF NOT EXISTS {} ({})").format(target, definition))
            cursor.execute("SELECT a.attname, format_type(a.atttypid, a.atttypmod) "
                           "FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid "
                           "JOIN pg_namespace n ON n.oid = c.relnamespace "
                           "WHERE n.nspname = %s AND c.relname = %s AND a.attnum > 0 "
                           "AND NOT a.attisdropped ORDER BY a.attnum", (args.schema, entry["name"]))
            if cursor.fetchall() != [(c["name"], c["type"]) for c in columns]:
                raise ValueError(f"Existing PostgreSQL schema differs: {entry['name']}")
            targets.append(target)
        # Truncate all selected tables together, without cascading to other tables.
        cursor.execute(sql.SQL("TRUNCATE {}").format(sql.SQL(", ").join(targets)))
        for entry, target in zip(manifest["tables"], targets):
            columns = sql.SQL(", ").join(sql.Identifier(c["name"]) for c in entry["columns"])
            with cursor.copy(sql.SQL("COPY {} ({}) FROM STDIN").format(target, columns)) as copy:
                for row in bundle_rows(folder / f"{entry['name']}.jsonl", entry):
                    copy.write_row(row)
            cursor.execute(sql.SQL("SELECT count(*) FROM {}").format(target))
            if cursor.fetchone()[0] != entry["rows"]:
                raise ValueError(f"PostgreSQL row count mismatch: {entry['name']}")
    print(f"Committed {len(targets)} tables to PostgreSQL schema {args.schema}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="Export S3 Tables through the existing Athena workgroup")
    export.add_argument("--bundle", required=True, help="New output directory (must not exist)")
    export.add_argument("--region", required=True)
    export.add_argument("--profile")
    export.add_argument("--catalog", default="s3tablescatalog/acctguv-mts")
    export.add_argument("--namespace", default="silver_mts")
    export.add_argument("--workgroup", default="acctguv-mts-queries")
    export.add_argument("--tables", nargs="+", choices=TABLES, default=list(TABLES))
    export.add_argument("--timeout", type=int, default=900, help="Timeout seconds per query")
    load = commands.add_parser("load", help="Replace local tables atomically from an offline bundle")
    load.add_argument("--bundle", required=True)
    load.add_argument("--schema", default="mts")
    load.add_argument("--dsn-env", default="MTS_POSTGRES_DSN")
    args = parser.parse_args()
    if args.command == "export":
        if args.timeout <= 0 or len(args.tables) != len(set(args.tables)):
            parser.error("Timeout must be positive and tables must be unique")
        import boto3
        session = boto3.Session(profile_name=args.profile, region_name=args.region)
        export_bundle(session.client("athena"), args)
    else:
        load_bundle(args)


if __name__ == "__main__":
    main()
