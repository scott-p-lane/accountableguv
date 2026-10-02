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

    def load(self, version=None):
        return loader.load_report(self.s3, "feeds", self.key, version)

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
        self.load("manifest-version")
        self.assertEqual(self.s3.requests[0]["VersionId"], "manifest-version")
        self.assertEqual(self.s3.requests[1]["VersionId"], "table-version")

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


if __name__ == "__main__":
    unittest.main()
