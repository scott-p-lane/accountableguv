import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import MagicMock, Mock, patch

spec = importlib.util.spec_from_file_location("mts_postgres", Path(__file__).parents[1] / "mts_postgres.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def page(rows, token=None):
    result = {"ResultSet": {"ResultSetMetadata": {"ColumnInfo": [
        {"Name": "identifier", "Type": "varchar"},
        {"Name": "amount", "Type": "decimal(38,2)"}]},
        "Rows": [{"Data": [{} if v is None else {"VarCharValue": v} for v in row]} for row in rows]}}
    if token:
        result["NextToken"] = token
    return result


class ExportTests(unittest.TestCase):
    def export(self, pages):
        client = Mock()
        client.start_query_execution.return_value = {"QueryExecutionId": "query-1"}
        client.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "SUCCEEDED"}}}
        client.get_query_results.side_effect = pages
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        folder = Path(temp.name) / "bundle"
        args = SimpleNamespace(bundle=str(folder), catalog="catalog", namespace="silver_mts",
                               tables=["mts_table_1"], workgroup="workgroup", timeout=30)
        m.export_bundle(client, args)
        manifest = json.loads((folder / "manifest.json").read_text())
        return client, folder, manifest["tables"][0]

    def test_pagination_and_value_fidelity(self):
        values = [["001", "999999999999999999999999999999999999.99"],
                  ["", None], ["null", "0.00"], ["\\N\n\t\"é", "-1.25"]]
        client, folder, entry = self.export([
            page([["identifier", "amount"], *values[:2]], "next"), page(values[2:])])
        self.assertEqual(list(m.bundle_rows(folder / "mts_table_1.jsonl", entry)), values)
        self.assertEqual(entry["rows"], 4)
        self.assertEqual(entry["columns"][1]["type"], "numeric(38,2)")
        self.assertEqual(client.get_query_results.call_args.kwargs["NextToken"], "next")

    def test_empty_table(self):
        _, folder, entry = self.export([page([["identifier", "amount"]])])
        self.assertEqual(list(m.bundle_rows(folder / "mts_table_1.jsonl", entry)), [])

    def test_corrupt_bundle(self):
        _, folder, entry = self.export([page([["identifier", "amount"], ["001", "1.00"]])])
        path = folder / "mts_table_1.jsonl"
        path.write_text('["002", "1.00"]\n', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "checksum"):
            list(m.bundle_rows(path, entry))

    def test_failed_export_has_no_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "bundle"
            args = SimpleNamespace(bundle=str(folder), catalog="catalog", namespace="db",
                                   tables=["mts_table_1"], workgroup="wg", timeout=30)
            client = Mock()
            client.start_query_execution.return_value = {"QueryExecutionId": "bad"}
            client.get_query_execution.return_value = {"QueryExecution": {"Status": {
                "State": "FAILED", "StateChangeReason": "denied"}}}
            with self.assertRaisesRegex(RuntimeError, "denied"):
                m.export_bundle(client, args)
            self.assertFalse((folder / "manifest.json").exists())

    def test_timeout_cancels(self):
        client = Mock()
        client.get_query_execution.return_value = {"QueryExecution": {"Status": {"State": "RUNNING"}}}
        with patch.object(m.time, "monotonic", side_effect=[0, 31]):
            with self.assertRaises(TimeoutError):
                m.wait_query(client, "query", 30)
        client.stop_query_execution.assert_called_once_with(QueryExecutionId="query")

    def test_reject_unsupported_types(self):
        for kind in ("array<string>", "decimal(39,2)", "decimal(2,3)", "text; DROP TABLE x"):
            with self.assertRaises(ValueError):
                m.pg_type(kind)

    def load_with_fake_database(self, folder, entry):
        driver = MagicMock()
        connection = driver.connect.return_value.__enter__.return_value
        cursor = connection.cursor.return_value.__enter__.return_value
        cursor.fetchall.return_value = [(c["name"], c["type"]) for c in entry["columns"]]
        cursor.fetchone.return_value = (entry["rows"],)
        args = SimpleNamespace(bundle=str(folder), schema="mts", dsn_env="TEST_MTS_DSN")
        return driver, cursor, args

    def test_load_uses_bulk_copy_and_finishes_transaction(self):
        values = [["001", "1.00"], [None, "-2.00"]]
        _, folder, entry = self.export([page([["identifier", "amount"], *values])])
        driver, cursor, args = self.load_with_fake_database(folder, entry)
        with patch.dict("sys.modules", {"psycopg": driver}), patch.dict(os.environ, TEST_MTS_DSN="local"):
            m.load_bundle(args)
        copy = cursor.copy.return_value.__enter__.return_value
        self.assertEqual([call.args[0] for call in copy.write_row.call_args_list], values)
        self.assertEqual(driver.connect.return_value.__exit__.call_args.args, (None, None, None))

    def test_corruption_propagates_to_transaction_rollback(self):
        _, folder, entry = self.export([page([["identifier", "amount"], ["001", "1.00"]])])
        (folder / "mts_table_1.jsonl").write_text('["002", "1.00"]\n', encoding="utf-8")
        driver, _, args = self.load_with_fake_database(folder, entry)
        # Context managers must propagate exceptions, as Psycopg does.
        driver.connect.return_value.__exit__.return_value = False
        with patch.dict("sys.modules", {"psycopg": driver}), patch.dict(os.environ, TEST_MTS_DSN="local"):
            with self.assertRaisesRegex(ValueError, "checksum"):
                m.load_bundle(args)
        self.assertIs(driver.connect.return_value.__exit__.call_args.args[0], ValueError)

    def test_schema_mismatch_propagates_before_copy(self):
        _, folder, entry = self.export([page([["identifier", "amount"]])])
        driver, cursor, args = self.load_with_fake_database(folder, entry)
        cursor.fetchall.return_value = [("identifier", "integer")]
        driver.connect.return_value.__exit__.return_value = False
        with patch.dict("sys.modules", {"psycopg": driver}), patch.dict(os.environ, TEST_MTS_DSN="local"):
            with self.assertRaisesRegex(ValueError, "schema differs"):
                m.load_bundle(args)
        cursor.copy.assert_not_called()


if __name__ == "__main__":
    unittest.main()
