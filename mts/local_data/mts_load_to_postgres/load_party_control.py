"""Load the monthly party-control CSV into local PostgreSQL."""

import argparse
import csv
import io
import os
from pathlib import Path
import subprocess


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CSV = (
    SCRIPT_DIR.parents[2]
    / "political_control" / "data" / "political_control_monthly.csv"
)
COLUMNS = (
    "year", "month", "president_name", "president_party",
    "house_majority_party", "senate_majority_party",
)
PARTIES = {"Democrat", "Republican"}


def read_csv(path):
    payload = io.StringIO(newline="")
    writer = csv.writer(payload, lineterminator="\n")
    months = set()
    with path.open(encoding="utf-8-sig", newline="") as source:
        reader = csv.reader(source, strict=True)
        if tuple(next(reader, ())) != COLUMNS:
            raise ValueError("CSV header must match the party-control columns")
        for row in reader:
            if len(row) != len(COLUMNS):
                raise ValueError(f"Line {reader.line_num}: expected six columns")
            year, month = map(int, row[:2])
            name = row[2]
            if not 1 <= year <= 9999 or not 1 <= month <= 12:
                raise ValueError(f"Line {reader.line_num}: invalid calendar month")
            if not name.strip() or any(char in name for char in "\r\n\x00"):
                raise ValueError(f"Line {reader.line_num}: invalid president name")
            if not PARTIES.issuperset(row[3:]):
                raise ValueError(f"Line {reader.line_num}: invalid party label")
            if (year, month) in months:
                raise ValueError(f"Line {reader.line_num}: duplicate calendar month")
            months.add((year, month))
            writer.writerow((year, month, *row[2:]))
    if not months:
        raise ValueError("CSV contains no party-control rows")
    return payload.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--psql", default="psql", help="psql executable path")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=5432)
    parser.add_argument("--user", default="postgres")
    parser.add_argument("--database", default="mts")
    parser.add_argument("--password", help="PostgreSQL password")
    args = parser.parse_args()

    try:
        rows = read_csv(args.csv)
        env = os.environ.copy()
        if args.password is not None:
            env["PGPASSWORD"] = args.password
        subprocess.run(
            [
                args.psql, "-X", "-w", "-v", "party_control_stdin=1",
                "-h", args.host, "-p", str(args.port), "-U", args.user,
                "-d", args.database, "-f", str(SCRIPT_DIR / "load_party_control.sql"),
            ],
            input=rows.encode("utf-8"),
            env=env,
            check=True,
        )
    except (OSError, ValueError, csv.Error) as exc:
        parser.exit(1, f"Party-control load failed: {exc}\n")
    except subprocess.CalledProcessError as exc:
        parser.exit(exc.returncode, "PostgreSQL party-control load failed.\n")


if __name__ == "__main__":
    main()
