"""Backfill MTS reports from the October 1997 through February 2015 text archive."""

from datetime import date
import hashlib
import json
from pathlib import Path
import sys

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
    sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "lambda" / "mts_download"))
import mts_feeds_monthly_download as monthly

from mts.aws.glue.mts_load.mts_pre_march_2015_transform import transform_report
from mts.aws.glue.mts_load.mts_to_tables import source_types

ARCHIVE = "https://fiscal.treasury.gov/system/files/files/reports-statements/mts"
ARCHIVE_BOUNDS = date(1997, 10, 31), date(2015, 2, 28)


def archive_report_objects(today, report_date, *, base_prefix="mts"):
    source_url = f"{ARCHIVE}/mts{report_date:%m%y}.txt"
    try:
        body = monthly.download(source_url)
        tables = transform_report(body, report_date, source_url, source_types)
    except (OSError, ValueError) as error:
        raise ValueError(f"{report_date} ({source_url}): {error}") from error
    prefix = f"{base_prefix}/{report_date:%Y/%m}"
    raw_key = f"{prefix}/raw/mts{report_date:%m%y}-{hashlib.sha256(body).hexdigest()}.txt"
    objects = [(raw_key, body)]
    files = []
    for table, payload in tables.items():
        key = f"{prefix}/{table}.json"
        table_body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        objects.append((key, table_body))
        files.append({"key": key, "sha256": hashlib.sha256(table_body).hexdigest(),
                      "row_count": len(payload["data"])})
    manifest = {"report_date": report_date.isoformat(), "files": files}
    objects.append((f"{prefix}/manifest.json", json.dumps(
        manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")))
    return report_date, prefix, objects


def main(argv=None):
    return monthly.main(argv, prepare_report=archive_report_objects, report_bounds=ARCHIVE_BOUNDS,
                        description=__doc__)


if __name__ == "__main__":
    sys.exit(main())
