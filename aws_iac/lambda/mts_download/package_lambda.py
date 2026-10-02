"""Create a reproducible ZIP and print its content-addressed S3 object key."""

import argparse
import hashlib
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

HERE = Path(__file__).resolve().parent


def package(output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    # Normalize line endings and ZIP metadata so unchanged code has the same hash.
    source = (HERE / "mts_feeds_monthly_download.py").read_text(encoding="utf-8").encode("utf-8")
    entry = ZipInfo("mts_feeds_monthly_download.py", date_time=(2020, 1, 1, 0, 0, 0))
    entry.compress_type = ZIP_DEFLATED
    entry.create_system = 3
    entry.external_attr = 0o100644 << 16
    buffer = BytesIO()
    with ZipFile(buffer, "w") as zipped:
        zipped.writestr(entry, source)
    data = buffer.getvalue()
    digest = hashlib.sha256(data).hexdigest()
    archive = output_dir / "mts_feeds_monthly_download.zip"
    archive.write_bytes(data)
    return archive, f"lambda/mts-feeds-monthly-download/{digest}/mts_feeds_monthly_download.zip"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=HERE / "build")
    args = parser.parse_args()
    archive, key = package(args.output_dir)
    print(f"ZIP file: {archive.resolve()}")
    print(f"MtsCodeObjectKey: {key}")
    print("Upload the ZIP to an existing S3 bucket in the Lambda region, using this object key.")


if __name__ == "__main__":
    main()
