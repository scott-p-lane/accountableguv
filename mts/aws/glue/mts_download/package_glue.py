"""Build the shared Python library for the MTS Glue Python shell job."""

import argparse
from base64 import urlsafe_b64encode
import csv
import hashlib
from io import StringIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


HERE = Path(__file__).resolve().parent
LAMBDA = HERE.parents[1] / "lambda" / "mts_download"
DIST_INFO = "mts_glue_download-1.0.dist-info"
LIBRARY = "mts_glue_download-1.0-py3-none-any.whl"


def package(output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    library = output_dir / LIBRARY
    downloader_modules = (
        "mts_feeds_monthly_download.py",
        "mts_feeds_pre_march_2015_download.py",
        "mts_pre_march_2015_transform.py",
    )
    files = {name: (LAMBDA / name).read_bytes() for name in downloader_modules}
    files["mts/aws/glue/mts_load/mts_to_tables.py"] = (HERE.parent / "mts_load/mts_to_tables.py").read_bytes()
    # Include the loader schema at its existing import path.
    for package_name in ("mts", "mts/aws", "mts/aws/glue", "mts/aws/glue/mts_load"):
        files[f"{package_name}/__init__.py"] = b""
    files[f"{DIST_INFO}/METADATA"] = b"Metadata-Version: 2.1\nName: mts-glue-download\nVersion: 1.0\n"
    files[f"{DIST_INFO}/WHEEL"] = b"Wheel-Version: 1.0\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    record_path = f"{DIST_INFO}/RECORD"
    record = StringIO()
    writer = csv.writer(record, lineterminator="\n")
    for name, content in sorted(files.items()):
        digest = urlsafe_b64encode(hashlib.sha256(content).digest()).decode("ascii").rstrip("=")
        writer.writerow((name, f"sha256={digest}", len(content)))
    writer.writerow((record_path, "", ""))
    files[record_path] = record.getvalue().encode("utf-8")

    with ZipFile(library, "w", compression=ZIP_DEFLATED) as wheel:
        for name, content in sorted(files.items()):
            wheel.writestr(ZipInfo(name), content, compress_type=ZIP_DEFLATED)
    return library


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    print(package(parser.parse_args().output_dir).resolve())
