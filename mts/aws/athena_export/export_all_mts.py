"""Export all nine MTS tables to named Athena CSV files in S3 with one call."""

from pathlib import Path
import sys

# Resolve the shared exporter independently of the current working directory.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "mts_postgres"))
from export_athena_csv import main


if __name__ == "__main__":
    main(all_tables=True)
