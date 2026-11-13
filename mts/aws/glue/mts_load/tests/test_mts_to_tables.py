from datetime import date
from decimal import Decimal
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, Mock, patch, sentinel

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import mts_to_tables as loader


class FakeS3:
    def __init__(self):
        self.objects = {}
        self.requests = []

    def get_object(self, **request):
        self.requests.append(request)
        return {"Body": BytesIO(self.objects[request["Key"]]), "VersionId": "test-version"}


class LoadTests(unittest.TestCase):
    def setUp(self):
        self.s3 = FakeS3()
        self.key = "mts/2026/08/manifest.json"
        self.manifest = {"report_date": "2026-08-31", "files": []}
        self.payloads = {}
        examples = {"STRING": "001", "CURRENCY": "12345678901234567890.12",
                    "DATE": "2026-08-31", "INTEGER": "1", "DAY": "31", "MONTH": "08",
                    "QUARTER": "3", "YEAR": "2026"}
        for table in loader.TABLES:
            types = loader.source_types(table)
            payload = {"report_date": "2026-08-31", "source_url": "https://example.test/mts",
                       "meta": {"count": 1, "dataTypes": types},
                       "data": [{name: examples[kind] for name, kind in types.items()}]}
            self.payloads[table] = payload
            self.manifest["files"].append({"key": f"mts/2026/08/{table}.json", "row_count": 1})
        self.save()

    def save(self):
        for table, item in zip(loader.TABLES, self.manifest["files"]):
            raw = json.dumps(self.payloads[table]).encode()
            self.s3.objects[item["key"]] = raw
            item["sha256"] = hashlib.sha256(raw).hexdigest()
        self.s3.objects[self.key] = json.dumps(self.manifest).encode()

    def load(self):
        return loader.load_report(self.s3, "feeds", self.key)

    def test_loads_nine_typed_tables_with_precision_and_lineage(self):
        report_date, batch_id, tables = self.load()
        self.assertEqual(report_date, date(2026, 8, 31))
        self.assertEqual(set(tables), set(loader.TABLES))
        row = tables["mts_table_1"][0]
        self.assertEqual(row["current_month_dfct_sur_amt"], Decimal("12345678901234567890.12"))
        self.assertEqual(row["classification_id"], "001")
        self.assertEqual(row["record_calendar_month"], 8)
        self.assertEqual(row["record_date"], report_date)
        self.assertEqual(row["source_version_id"], "test-version")
        self.assertEqual(row["batch_id"], batch_id)
        self.assertEqual(self.load()[1], batch_id)

    def test_version_ids_are_passed_when_available(self):
        self.manifest["files"][0]["version_id"] = "table-version"
        self.save()
        self.load()
        self.assertNotIn("VersionId", self.s3.requests[0])
        self.assertEqual(self.s3.requests[1]["VersionId"], "table-version")

    def test_classification_descriptions_normalize_across_tables(self):
        examples = (
            ("Receipts", "Receipts"),
            ("RECEIPTS", "Receipts"),
            ("total -- SOCIAL INSURANCE AND RETIREMENT RECEIPTS",
             "Total -- Social Insurance and Retirement Receipts"),
            ("DEBT HELD BY THE PUBLIC", "Debt Held by the Public"),
            ("fy 2026", "FY 2026"),
            ("YEAR-TO-DATE", "Year-to-Date"),
            ("GOVERNMENT'S RECEIPTS", "Government's Receipts"),
            ("null", None),
            (None, None),
        )
        for table, (value, _) in zip(loader.TABLES, examples):
            self.payloads[table]["data"][0].update(
                classification_desc=value, classification_id="MixedCase001")
        self.save()
        _, _, tables = self.load()
        for table, (_, expected) in zip(loader.TABLES, examples):
            with self.subTest(table=table):
                row = tables[table][0]
                self.assertEqual(row["classification_desc"], expected)
                self.assertEqual(row["classification_id"], "MixedCase001")
                self.assertEqual(row["transform_version"], "4")

    def test_loads_raw_api_pages_with_per_page_lineage(self):
        files = []
        for table, payload in self.payloads.items():
            page_count = 2 if table == "mts_table_1" else 1
            for page in range(1, page_count + 1):
                row = dict(payload["data"][0], classification_desc="RECEIPTS")
                raw = json.dumps({"data": [row], "meta": {
                    "total-count": page_count, "dataTypes": loader.source_types(table)}}).encode()
                digest = hashlib.sha256(raw).hexdigest()
                key = f"mts/2026/08/raw/{table}/page-{page:02d}-{digest}.json"
                self.s3.objects[key] = raw
                files.append({"key": key, "sha256": digest, "source_url": f"https://example.test/{page}"})
        self.manifest.update(format="treasury-fiscal-data-api", files=files)
        self.s3.objects[self.key] = json.dumps(self.manifest).encode()
        _, _, loaded = self.load()
        self.assertEqual(set(loaded), set(loader.TABLES))
        self.assertEqual([row["classification_desc"] for row in loaded["mts_table_1"]],
                         ["Receipts", "Receipts"])
        self.assertEqual([row["source_key"] for row in loaded["mts_table_1"]],
                         [entry["key"] for entry in files[:2]])
        self.manifest["files"].pop(1)
        self.s3.objects[self.key] = json.dumps(self.manifest).encode()
        with self.assertRaisesRegex(ValueError, "missing tables or rows"):
            self.load()

    def test_loads_raw_archive_with_shared_text_lineage(self):
        import mts_pre_march_2015_transform

        raw = b"original Treasury text\r\n"
        digest = hashlib.sha256(raw).hexdigest()
        url = "https://example.test/mts0814.txt"
        key = f"mts/2014/08/raw/mts0814-{digest}.txt"
        self.s3.objects[key] = raw
        self.key = "mts/2014/08/manifest.json"
        self.s3.objects[self.key] = json.dumps({
            "format": "treasury-star-text", "report_date": "2014-08-31",
            "files": [{"key": key, "sha256": digest, "source_url": url}],
        }).encode()
        for payload in self.payloads.values():
            payload["data"][0].update(record_date="2014-08-31", sequence_number_cd="1.3.1")
        with patch.object(mts_pre_march_2015_transform, "transform_report",
                          return_value=self.payloads) as transform:
            _, _, loaded = self.load()
        transform.assert_called_once_with(raw, date(2014, 8, 31), url, loader.source_types)
        self.assertEqual(loaded["mts_table_9"][0]["sequence_number_cd"], "1.3.1")
        self.assertTrue(all(rows[0]["source_key"] == key for rows in loaded.values()))

    def test_legacy_archive_table_9_gets_api_compatible_filter_fields(self):
        payload = self.payloads["mts_table_9"]
        payload["meta"]["archive"] = {"format": "treasury-star-text"}
        template = payload["data"][0]
        expected = [
            ("Net Receipts", "1", "1", "SL"),
            ("INDIVIDUAL INCOME TAXES", "1.1", "2", "RSG"),
            ("CORPORATION INCOME TAXES", "1.2", "2", "RSG"),
            ("SOCIAL INSURANCE TAXES AND CONTRIBUTIONS:", "1.3", "2", "RSG"),
            ("EMPLOYMENT TAXES AND CONTRIBUTIONS", "1.3.1", "3", "RSG"),
            ("TOTAL", "1.4", "2", "SL"),
            ("NET OUTLAYS", "2", "1", "SL"),
            ("NATIONAL DEFENSE", "2.1", "2", "F"),
            ("TOTAL", "2.2", "2", "SL"),
        ]
        payload["data"] = [dict(template, classification_desc=label, sequence_number_cd=None,
                                sequence_level_nbr=None, record_type_cd=None)
                           for label, _, _, _ in expected]
        payload["meta"]["count"] = len(expected)
        self.manifest["files"][-1]["row_count"] = len(expected)
        self.save()
        _, _, tables = self.load()
        self.assertEqual([(row["sequence_number_cd"], row["sequence_level_nbr"], row["record_type_cd"])
                          for row in tables["mts_table_9"]],
                         [fields[1:] for fields in expected])

    def test_hash_mismatch_rejects_replaced_source(self):
        self.s3.objects[self.manifest["files"][-1]["key"]] += b" "
        with self.assertRaisesRegex(ValueError, "SHA-256 mismatch"):
            self.load()

    def test_manifest_cannot_reference_other_prefixes_or_duplicate_tables(self):
        for replacement in ("other/feed.json", self.manifest["files"][0]["key"]):
            with self.subTest(replacement=replacement):
                self.manifest["files"][-1]["key"] = replacement
                self.s3.objects[self.key] = json.dumps(self.manifest).encode()
                with self.assertRaisesRegex(ValueError, "exactly the nine"):
                    self.load()

    def test_invalid_manifest_path_is_rejected_without_s3_read(self):
        with self.assertRaisesRegex(ValueError, "manifest_key"):
            loader.load_report(self.s3, "feeds", "REQUIRED")
        self.assertEqual(self.s3.requests, [])

    def test_report_date_mismatch_is_rejected(self):
        self.payloads["mts_table_9"]["data"][0]["record_date"] = "2026-07-31"
        self.save()
        with self.assertRaisesRegex(ValueError, "report date"):
            self.load()

    def test_schema_drift_is_rejected(self):
        self.payloads["mts_table_9"]["meta"]["dataTypes"]["new_field"] = "STRING"
        self.save()
        with self.assertRaisesRegex(ValueError, "schema changed"):
            self.load()

    def test_row_count_mismatch_is_rejected(self):
        self.manifest["files"][-1]["row_count"] = 2
        self.save()
        with self.assertRaisesRegex(ValueError, "Row count"):
            self.load()

    def test_empty_report_is_rejected(self):
        self.payloads["mts_table_9"]["data"] = []
        self.payloads["mts_table_9"]["meta"]["count"] = 0
        self.manifest["files"][-1]["row_count"] = 0
        self.save()
        with self.assertRaisesRegex(ValueError, "empty table"):
            self.load()

    def test_currency_rejects_loss_of_precision_nonfinite_and_overflow(self):
        for value in ("1.001", "NaN", "Infinity", "1e36", "garbage"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                loader.convert_value(value, "CURRENCY")
        self.assertIsNone(loader.convert_value("null", "CURRENCY"))
        self.assertEqual(loader.convert_value("-1.20", "CURRENCY"), Decimal("-1.20"))

    def test_size_limit_rejects_large_source(self):
        with patch.object(loader, "MAX_OBJECT_BYTES", 8):
            with self.assertRaisesRegex(ValueError, "exceeds"):
                self.load()

    def test_writer_replaces_only_requested_period_and_preflights_all_schemas(self):
        report_date, _, loaded = self.load()
        spark = Mock()
        frames = [Mock() for _ in loader.TABLES]
        spark.createDataFrame.side_effect = frames

        def target_table(target):
            table = target.rsplit(".", 1)[1]
            frame = Mock()
            frame.schema = [SimpleNamespace(name=name, dataType=SimpleNamespace(
                simpleString=lambda kind=kind: kind))
                for name, kind in loader.table_columns(table).items()]
            frame.where.return_value.count.return_value = 1
            return frame

        spark.table.side_effect = target_table
        functions = MagicMock()
        functions.col.return_value.__eq__.return_value = sentinel.period_filter
        modules = {"pyspark": Mock(), "pyspark.sql": SimpleNamespace(functions=functions)}
        with patch.dict(sys.modules, modules):
            loader.write_report(spark, "silver_mts", report_date, loaded)
        functions.col.assert_called_with("record_date")
        functions.lit.assert_called_with(report_date)
        for table, frame in zip(loader.TABLES, frames):
            frame.coalesce.return_value.writeTo.assert_called_once_with(f"s3tables.silver_mts.{table}")
            frame.coalesce.return_value.writeTo.return_value.overwrite.assert_called_once_with(
                sentinel.period_filter)

        # A schema mismatch on the final table must prevent all data writes.
        for frame in frames:
            frame.reset_mock()
        spark.createDataFrame.side_effect = frames

        def mismatched_target(target):
            frame = target_table(target)
            if target.endswith("mts_table_9"):
                frame.schema = []
            return frame

        spark.table.side_effect = mismatched_target
        with patch.dict(sys.modules, modules), self.assertRaisesRegex(ValueError, "Target schema"):
            loader.write_report(spark, "silver_mts", report_date, loaded)
        for frame in frames:
            frame.coalesce.assert_not_called()


class DiscoveryTests(unittest.TestCase):
    def test_recursive_paginated_discovery_sorts_and_filters(self):
        s3 = Mock()
        s3.get_paginator.return_value.paginate.return_value = [
            {"Contents": [{"Key": "mts/2026/01/manifest.json"},
                          {"Key": "mts/2025/02/mts_table_1.json"}]},
            {},
            {"Contents": [{"Key": "mts/2025/01/manifest.json"},
                          {"Key": "mts/2025/02/manifest.json"}]},
        ]
        self.assertEqual(loader.select_manifests(s3, "feeds", "mts"), [
            "mts/2025/01/manifest.json", "mts/2025/02/manifest.json", "mts/2026/01/manifest.json"])
        s3.get_paginator.assert_called_once_with("list_objects_v2")
        s3.get_paginator.return_value.paginate.assert_called_once_with(Bucket="feeds", Prefix="mts/")

    def test_year_and_month_prefixes_have_directory_boundaries(self):
        for prefix in ("mts/2025", "mts/2025/", "mts/2025/01"):
            with self.subTest(prefix=prefix):
                s3 = Mock()
                s3.get_paginator.return_value.paginate.return_value = [{"Contents": [
                    {"Key": "mts/2025/01/manifest.json"},
                    {"Key": "mts/20250/01/manifest.json"},
                    {"Key": "mts/2026/01/manifest.json"}]}]
                self.assertEqual(loader.select_manifests(s3, "feeds", prefix),
                                 ["mts/2025/01/manifest.json"])
                s3.get_paginator.return_value.paginate.assert_called_once_with(
                    Bucket="feeds", Prefix=prefix.rstrip("/") + "/")

    def test_empty_discovery_fails(self):
        s3 = Mock()
        s3.get_paginator.return_value.paginate.return_value = [{}]
        with self.assertRaisesRegex(ValueError, "No MTS manifests"):
            loader.select_manifests(s3, "feeds", "mts")

    def test_date_range_selects_inclusive_month_ends_across_years(self):
        s3 = Mock()
        s3.get_paginator.return_value.paginate.return_value = [{"Contents": [
            {"Key": f"mts/{month}/manifest.json"}
            for month in ("2024/03", "2023/11", "2024/02", "2023/12")
        ]}]
        bounds = {"start_date": "2023-12-31", "end_date": "2024-02-29"}
        self.assertEqual(loader.select_manifests(s3, "feeds", "REQUIRED", **bounds), [
            "mts/2023/12/manifest.json", "mts/2024/02/manifest.json"])
        self.assertEqual(loader.select_manifests(s3, "feeds", "mts/2024", **bounds), [
            "mts/2024/02/manifest.json"])
        with self.assertRaisesRegex(ValueError, "No MTS manifests.*2024-02-28"):
            loader.select_manifests(s3, "feeds", "mts", start_date="2024-02-01",
                                    end_date="2024-02-28")

    def test_invalid_date_bounds_fail_before_listing(self):
        s3 = Mock()
        for start, end in (("2025-01-01", "unset"), ("2025-02-29", "2025-03-01"),
                           ("20250101", "2025-02-01"), ("2025-02-01", "2025-01-01")):
            with self.subTest(start=start, end=end), self.assertRaisesRegex(ValueError, "--start_date"):
                loader.select_manifests(s3, "feeds", "mts", start_date=start, end_date=end)
        s3.get_paginator.assert_not_called()

    def test_missing_or_invalid_prefix_fails_before_listing(self):
        for prefix in (None, "", "REQUIRED", "other", "s3://feeds/mts", "/mts",
                       "mts/2025/13", "mts/2025/../2026", "mts/2025/01/manifest.json"):
            with self.subTest(prefix=prefix):
                s3 = Mock()
                with self.assertRaises(ValueError):
                    loader.select_manifests(s3, "feeds", prefix)
                s3.get_paginator.assert_not_called()

    def test_reports_load_sequentially_and_stop_on_first_failure(self):
        keys = ["mts/2025/01/manifest.json", "mts/2025/02/manifest.json", "mts/2026/01/manifest.json"]
        events = []

        def read(s3, bucket, key):
            events.append(("read", key))
            return key, "batch", sentinel.rows

        def write(spark, namespace, report_date, rows):
            events.append(("write", report_date))
            if report_date == keys[1]:
                raise RuntimeError("write failed")

        with patch.object(loader, "load_report", side_effect=read), \
                patch.object(loader, "write_report", side_effect=write), \
                self.assertLogs(loader.LOGGER, level="ERROR"), \
                self.assertRaisesRegex(RuntimeError, "write failed"):
            loader.load_manifests(Mock(), Mock(), "feeds", "silver_mts", keys)
        self.assertEqual(events, [("read", keys[0]), ("write", keys[0]),
                                  ("read", keys[1]), ("write", keys[1])])

    def test_all_selected_reports_are_written(self):
        keys = ["mts/2025/01/manifest.json", "mts/2026/01/manifest.json"]
        with patch.object(loader, "load_report", return_value=(date(2025, 1, 31), "batch", {})) as read, \
                patch.object(loader, "write_report") as write:
            loader.load_manifests(sentinel.s3, sentinel.spark, "feeds", "silver_mts", keys)
        self.assertEqual([call.args[2] for call in read.call_args_list], keys)
        self.assertEqual(write.call_count, 2)


if __name__ == "__main__":
    unittest.main()
