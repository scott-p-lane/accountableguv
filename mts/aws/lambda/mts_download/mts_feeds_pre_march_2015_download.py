"""Backfill MTS reports from the October 1997 through February 2015 text archive."""

from datetime import date
from pathlib import Path
import sys

import mts_feeds_monthly_download as monthly

# Direct CLI execution needs the repository root to import the loader's schema.
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from mts.aws.glue.mts_load.mts_to_tables import source_types
from mts_pre_march_2015_transform import transform_report


ARCHIVE = "https://fiscal.treasury.gov/system/files/files/reports-statements/mts"
ARCHIVE_BOUNDS = date(1997, 10, 31), date(2015, 2, 28)


def archive_report_objects(today, report_date, *, base_prefix="mts"):
    source_url = f"{ARCHIVE}/mts{report_date:%m%y}.txt"
    try:
        tables = transform_report(monthly.download(source_url), report_date, source_url, source_types)
    except (OSError, ValueError) as error:
        raise ValueError(f"{report_date} ({source_url}): {error}") from error
    return monthly.build_report_objects(report_date, tables, base_prefix=base_prefix)


def main(argv=None):
    return monthly.main(argv, prepare_report=archive_report_objects, archive_bounds=ARCHIVE_BOUNDS,
                        description=__doc__)


if __name__ == "__main__":
    sys.exit(main())
