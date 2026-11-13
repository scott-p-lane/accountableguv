"""Read-only Treasury endpoint check; makes no AWS calls."""
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor
import json

from mts_feeds_monthly_download import fetch_table_pages, latest_report_date


def probe(number):
    pages = fetch_table_pages(f"mts_table_{number}", REPORT_DATE)
    return number, REPORT_DATE.isoformat(), sum(len(json.loads(body)["data"]) for _, body in pages)


if __name__ == "__main__":
    REPORT_DATE = latest_report_date(datetime.now(timezone.utc).date())
    with ThreadPoolExecutor(max_workers=9) as pool:
        print(list(pool.map(probe, range(1, 10))))
