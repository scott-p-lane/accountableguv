from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from zipfile import ZipFile

import mts_feeds_monthly_download as handler
import package_lambda


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.writes = []

    def list_objects_v2(self, Bucket, Prefix, MaxKeys):
        return {"Contents": [{"Key": key} for key in sorted(self.objects) if key.startswith(Prefix)][:MaxKeys]}

    def head_object(self, Bucket, Key):
        return {"Metadata": self.objects[Key]["Metadata"]}

    def put_object(self, **kwargs):
        self.objects[kwargs["Key"]] = kwargs
        self.writes.append(kwargs)


class MtsDownloadTests(unittest.TestCase):
    def test_inclusive_report_range_handles_year_boundary_and_leap_year(self):
        self.assertEqual(list(handler.report_dates_between(date(2023, 12, 31), date(2024, 2, 29))),
                         [date(2023, 12, 31), date(2024, 1, 31), date(2024, 2, 29)])
        self.assertEqual(list(handler.report_dates_between(date(2024, 1, 1), date(2024, 2, 28))),
                         [date(2024, 1, 31)])
        self.assertEqual(list(handler.report_dates_between(date.max, date.max)), [date.max])

    def test_invalid_cli_ranges_fail_before_download(self):
        for arguments in (["--start-date", "2024-01-01"],
                          ["--end-date", "2024-01-31"],
                          ["--start-date", "invalid", "--end-date", "2024-01-31"],
                          ["--start-date", "2024-02-30", "--end-date", "2024-03-31"],
                          ["--start-date", "2024-02-01", "--end-date", "2024-01-31"],
                          ["--start-date", "2024-01-01", "--end-date", "2024-01-30"]):
            with self.subTest(arguments=arguments), patch.object(handler, "download") as download, \
                 patch("sys.stderr"), self.assertRaises(SystemExit) as error:
                handler.main(arguments)
            self.assertEqual(error.exception.code, 2)
            download.assert_not_called()

    def test_local_range_writes_each_month_without_latest_lookup(self):
        with TemporaryDirectory() as output, \
             patch.object(handler, "latest_report_date") as latest, \
             patch.object(handler, "fetch_table", side_effect=lambda table, day: {
                 "data": [{"record_date": str(day)}]}) as fetch, patch("builtins.print"):
            self.assertEqual(handler.main(["--output-dir", output, "--start-date", "2023-12-31",
                                           "--end-date", "2024-02-29"]), 0)
            for month, day in (("2023/12", "2023-12-31"), ("2024/01", "2024-01-31"),
                               ("2024/02", "2024-02-29")):
                directory = Path(output) / "mts" / month
                self.assertEqual(len(list(directory.glob("*.json"))), 10)
                self.assertEqual(json.loads((directory / "manifest.json").read_text())["report_date"], day)
            self.assertEqual(fetch.call_count, 27)
            latest.assert_not_called()

    def test_s3_cli_range_uses_explicit_report_dates(self):
        session = Mock()
        errors = SimpleNamespace(BotoCoreError=type("BotoCoreError", (Exception,), {}),
                                 ClientError=type("ClientError", (Exception,), {}))
        with patch.dict("sys.modules", {"boto3": SimpleNamespace(Session=Mock(return_value=session)),
                                        "botocore.exceptions": errors}), \
             patch.object(handler, "store_latest", return_value={}) as store, patch("builtins.print"):
            self.assertEqual(handler.main(["--bucket", "staging", "--start-date", "2024-01-31",
                                           "--end-date", "2024-02-29"]), 0)
        self.assertEqual([call.args[3] for call in store.call_args_list],
                         [date(2024, 1, 31), date(2024, 2, 29)])

    def test_report_month_is_calendar_month_not_download_or_fiscal_year(self):
        response = {"data": [{"record_date": "2025-12-31", "record_fiscal_year": "2026"}]}
        with patch.object(handler, "download", return_value=json.dumps(response).encode()):
            self.assertEqual(handler.latest_report_date(date(2026, 1, 20)), date(2025, 12, 31))

    def test_delayed_release_fails_instead_of_storing_stale_month(self):
        response = {"data": [{"record_date": "2026-07-31"}]}
        with patch.object(handler, "download", return_value=json.dumps(response).encode()):
            with self.assertRaisesRegex(ValueError, "Expected report through 2026-08-31"):
                handler.latest_report_date(date(2026, 9, 20))

    def test_pagination_downloads_all_rows(self):
        def page(value):
            return json.dumps({"data": [{"record_date": "2026-08-31", "value": value}],
                               "meta": {"total-count": 2, "labels": {"value": "Value"}}}).encode()
        with patch.object(handler, "download", side_effect=[page(1), page(2)]) as download:
            payload = handler.fetch_table("mts_table_5", date(2026, 8, 31))
        self.assertEqual(len(payload["data"]), 2)
        self.assertEqual(payload["meta"]["count"], 2)
        self.assertIn("record_date%3Aeq%3A2026-08-31", download.call_args_list[0].args[0])
        self.assertIn("page%5Bnumber%5D=2", download.call_args_list[1].args[0])

    def test_wrong_month_in_table_is_rejected(self):
        payload = {"data": [{"record_date": "2026-07-31"}], "meta": {"total-count": 1}}
        with patch.object(handler, "download", return_value=json.dumps(payload).encode()):
            with self.assertRaisesRegex(ValueError, "Invalid report dates"):
                handler.fetch_table("mts_table_1", date(2026, 8, 31))

    def test_failed_table_causes_no_uploads(self):
        s3 = FakeS3()
        with patch.object(handler, "latest_report_date", return_value=date(2026, 8, 31)), \
             patch.object(handler, "fetch_table", side_effect=ValueError("Unavailable table")):
            with self.assertRaises(ValueError):
                handler.store_latest("staging", s3, date(2026, 9, 20))
        self.assertEqual(s3.writes, [])

    def test_all_tables_manifest_and_duplicate_invocation(self):
        s3 = FakeS3()

        def table(name, report_date):
            return {"report_date": str(report_date), "data": [{"record_date": str(report_date), "table": name}]}

        with patch.object(handler, "latest_report_date", return_value=date(2025, 12, 31)), \
             patch.object(handler, "fetch_table", side_effect=table):
            result = handler.store_latest("staging", s3, date(2026, 1, 20))
            self.assertEqual(result["prefix"], "mts/2025/12")
            self.assertEqual(len(s3.writes), 10)
            self.assertEqual(s3.writes[-1]["Key"], "mts/2025/12/manifest.json")
            manifest = json.loads(s3.writes[-1]["Body"])
            self.assertEqual(len(manifest["files"]), 9)
            for entry in manifest["files"]:
                body = s3.objects[entry["key"]]["Body"]
                self.assertEqual(entry["sha256"], hashlib.sha256(body).hexdigest())
            again = handler.store_latest("staging", s3, date(2026, 1, 20))
            self.assertEqual(again["status"], "unchanged")
            self.assertEqual(len(s3.writes), 10)
        for write in s3.writes:
            self.assertEqual(write["ContentType"], "application/json")
            self.assertEqual(write["ServerSideEncryption"], "AES256")

    def test_corrected_data_creates_new_upload(self):
        s3 = FakeS3()
        key = "mts/2026/08/mts_table_1.json"
        for value in (1, 2):
            handler.store_json("staging", s3, key, {"value": value}, date(2026, 8, 31))
        self.assertEqual(len(s3.writes), 2)

    def test_package_contains_exact_source_with_stable_key(self):
        with TemporaryDirectory() as directory:
            archive, key = package_lambda.package(directory)
            original = archive.read_bytes()
            with ZipFile(archive) as zipped:
                self.assertEqual(zipped.namelist(), ["mts_feeds_monthly_download.py"])
                source = zipped.read("mts_feeds_monthly_download.py").decode()
                self.assertEqual(source, Path(handler.__file__).read_text(encoding="utf-8"))
                compile(source, "mts_feeds_monthly_download.py", "exec")
            repeated, repeated_key = package_lambda.package(directory)
            self.assertEqual(repeated.read_bytes(), original)
            self.assertEqual(repeated_key, key)
            self.assertTrue(key.endswith(archive.name))
            version = datetime.fromtimestamp(Path(handler.__file__).stat().st_mtime).strftime("%Y%m%d")
            self.assertEqual(key, f"lambda/mts_feeds_monthly_download_v{version}.zip")

    def test_package_version_uses_latest_packaged_file_modification_date(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            for name, modified in (("first.py", datetime(2025, 12, 31, 12)),
                                   ("second.py", datetime(2026, 1, 2, 12)),
                                   ("unpackaged.py", datetime(2026, 2, 3, 12))):
                source = root / name
                source.write_text("value = 1\n", encoding="utf-8")
                os.utime(source, (modified.timestamp(), modified.timestamp()))
            with patch.object(package_lambda, "HERE", root), \
                 patch.object(package_lambda, "PACKAGE_FILES", ("second.py", "first.py")):
                archive, key = package_lambda.package(root / "build")
            self.assertEqual(archive.name, "mts_feeds_monthly_download_v20260102.zip")
            self.assertEqual(key, "lambda/mts_feeds_monthly_download_v20260102.zip")
            with ZipFile(archive) as zipped:
                self.assertEqual(zipped.namelist(), ["second.py", "first.py"])

    def test_template_references_external_package(self):
        source = Path(handler.__file__).resolve()
        template = source.parents[2] / "cloud-formation-templates" / "feeds_staging" / "feeds_staging_iac.yaml"
        content = template.read_text(encoding="utf-8")
        self.assertNotIn("ZipFile:", content)
        self.assertIn("Handler: mts_feeds_monthly_download.lambda_handler", content)
        self.assertIn("S3Bucket: !Ref MtsCodeBucketName", content)
        self.assertIn("S3Key: !Ref MtsCodeObjectKey", content)

    def test_local_cli_uses_selected_profile_and_shared_download_logic(self):
        session = Mock()
        boto3 = SimpleNamespace(Session=Mock(return_value=session))
        errors = SimpleNamespace(BotoCoreError=type("BotoCoreError", (Exception,), {}),
                                 ClientError=type("ClientError", (Exception,), {}))
        with patch.dict("sys.modules", {"boto3": boto3, "botocore.exceptions": errors}), \
             patch.object(handler, "store_latest", return_value={"status": "stored"}) as store, \
             patch("builtins.print"):
            self.assertEqual(handler.main(["--bucket", "staging", "--profile", "dev", "--region", "us-east-1"]), 0)
        boto3.Session.assert_called_once_with(profile_name="dev", region_name="us-east-1")
        self.assertEqual(store.call_args.args[0], "staging")
        self.assertIs(store.call_args.args[1], session.client.return_value)

    def test_local_cli_failure_returns_nonzero(self):
        boto3 = SimpleNamespace(Session=Mock())
        errors = SimpleNamespace(BotoCoreError=type("BotoCoreError", (Exception,), {}),
                                 ClientError=type("ClientError", (Exception,), {}))
        with patch.dict("sys.modules", {"boto3": boto3, "botocore.exceptions": errors}), \
             patch.object(handler, "store_latest", side_effect=ValueError("stale report")):
            self.assertEqual(handler.main(["--bucket", "staging"]), 1)

    def test_local_files_use_report_month_and_have_no_aws_dependency(self):
        with TemporaryDirectory() as output, \
             patch.object(handler, "latest_report_date", return_value=date(2025, 12, 31)), \
             patch.object(handler, "fetch_table", return_value={"data": [{"record_date": "2025-12-31"}]}), \
             patch.dict("sys.modules", {"boto3": None}), \
             patch("builtins.print"):
            self.assertEqual(handler.main(["--output-dir", output]), 0)
            directory = Path(output) / "mts" / "2025" / "12"
            self.assertEqual(len(list(directory.glob("*.json"))), 10)
            manifest = json.loads((directory / "manifest.json").read_text())
            for entry in manifest["files"]:
                body = (Path(output) / entry["key"]).read_bytes()
                self.assertEqual(hashlib.sha256(body).hexdigest(), entry["sha256"])

    def test_default_local_destination_is_project_test_data(self):
        with patch.object(handler, "store_local", return_value={"status": "stored"}) as store, \
             patch("builtins.print"), patch.dict("os.environ", {"STAGING_BUCKET_NAME": "ignored-locally"}):
            self.assertEqual(handler.main([]), 0)
        self.assertEqual(store.call_args.args[0], Path(handler.__file__).resolve().parents[3] / "test" / "data")


if __name__ == "__main__":
    unittest.main()
