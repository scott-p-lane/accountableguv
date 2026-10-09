"""Read-only Treasury endpoint check; makes no AWS calls."""
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor

from mts_feeds_monthly_download import fetch_table, latest_report_date


def probe(number):
    payload = fetch_table(f"mts_table_{number}", REPORT_DATE)
    return number, payload["report_date"], len(payload["data"])


if __name__ == "__main__":
    REPORT_DATE = latest_report_date(datetime.now(timezone.utc).date())
    with ThreadPoolExecutor(max_workers=9) as pool:
        print(list(pool.map(probe, range(1, 10))))
