"""Create a reproducible ZIP and print its modification-date-versioned S3 key."""

import argparse
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

HERE = Path(__file__).resolve().parent
PACKAGE_FILES = ("mts_feeds_monthly_download.py",)


def package(output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    sources = [HERE / name for name in PACKAGE_FILES]
    # Use the latest packaged source modification date in the local timezone.
    version = datetime.fromtimestamp(max(source.stat().st_mtime for source in sources)).strftime("%Y%m%d")
    # Normalize line endings and ZIP metadata for reproducible archive contents.
    buffer = BytesIO()
    with ZipFile(buffer, "w") as zipped:
        for source in sources:
            entry = ZipInfo(source.relative_to(HERE).as_posix(), date_time=(2020, 1, 1, 0, 0, 0))
            entry.compress_type = ZIP_DEFLATED
            entry.create_system = 3
            entry.external_attr = 0o100644 << 16
            zipped.writestr(entry, source.read_text(encoding="utf-8").encode("utf-8"))
    data = buffer.getvalue()
    archive = output_dir / f"mts_feeds_monthly_download_v{version}.zip"
    archive.write_bytes(data)
    return archive, f"lambda/{archive.name}"


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
