import importlib.util
import json
import re
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

folder = Path(__file__).parents[1]
with patch.object(sys, "path", [str(folder), *sys.path]):
    spec = importlib.util.spec_from_file_location("export_athena_csv", folder / "export_athena_csv.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)


class CsvExportTests(unittest.TestCase):
    def args(self):
        return SimpleNamespace(s3_prefix="s3://destination/queries/exports/", tables=["mts_table_1"],
                               catalog="catalog", namespace="silver_mts", workgroup="workgroup", timeout=30)

    def client(self):
        client = Mock()
        client.start_query_execution.return_value = {"QueryExecutionId": "query"}
        client.get_query_execution.return_value = {"QueryExecution": {
            "Status": {"State": "SUCCEEDED"},
            "ResultConfiguration": {"OutputLocation": "s3://enforced-bucket/queries/query.csv"}}}
        return client

    def test_copies_actual_workgroup_result_and_marks_completion(self):
        athena, s3 = self.client(), Mock()
        result = m.export_csv(athena, s3, self.args())
        copy_args = s3.copy.call_args.args
        self.assertEqual(copy_args[0], {"Bucket": "enforced-bucket", "Key": "queries/query.csv"})
        self.assertEqual(copy_args[1], "destination")
        self.assertTrue(copy_args[2].endswith("/mts_table_1.csv"))
        self.assertEqual(json.loads(s3.put_object.call_args.kwargs["Body"]), result)
        athena.get_query_results.assert_not_called()

    def test_failed_copy_leaves_no_completion_file(self):
        s3 = Mock()
        s3.copy.side_effect = RuntimeError("copy denied")
        with self.assertRaisesRegex(RuntimeError, "copy denied"):
            m.export_csv(self.client(), s3, self.args())
        s3.put_object.assert_not_called()

    def test_all_table_export_runs_each_query_once(self):
        args = self.args()
        args.tables = list(m.TABLES)
        athena, s3 = self.client(), Mock()
        manifest = m.export_csv(athena, s3, args)
        self.assertEqual(athena.start_query_execution.call_count, 9)
        self.assertEqual(s3.copy.call_count, 9)
        self.assertEqual([t["name"] for t in manifest["tables"]], list(m.TABLES))

    def test_csv_loader_matches_exports_and_is_atomic(self):
        root = folder.parents[1]
        loader = (root / "local_data" / "load_mts_data.sql").read_text()
        self.assertIn("\\set ON_ERROR_STOP on", loader)
        self.assertLess(loader.index("BEGIN;"), loader.index("TRUNCATE TABLE"))
        self.assertGreater(loader.index("COMMIT;"), loader.rindex("\\ir load_"))
        self.assertNotIn("jsonl", loader)
        for table in m.TABLES:
            self.assertIn(f"\\ir load_{table}.sql", loader)
            individual = (root / "local_data" / f"load_{table}.sql").read_text()
            self.assertIn(f"\\ir create_{table}.sql", individual)
            self.assertIn("\\set ON_ERROR_STOP on", individual)
            self.assertLess(individual.index("BEGIN;"), individual.index("TRUNCATE TABLE"))
            self.assertGreater(individual.index("COMMIT;"), individual.index("\\copy"))
            self.assertIn(f"TRUNCATE TABLE mts.{table};", individual)
            query = (m.QUERY_FOLDER / f"export_{table}.sql").read_text()
            expected = [line.strip().rstrip(',') for line in query.splitlines()
                        if line.startswith('    ')]
            match = re.search(rf"\\copy mts\.{table} \((.*?)\) FROM '{table}\.csv'", individual)
            self.assertIsNotNone(match, table)
            self.assertEqual(match[1].split(', '), expected, table)

    def test_queries_match_ddl_column_order(self):
        root = folder.parents[1]
        for table in m.TABLES:
            query = (m.QUERY_FOLDER / f"export_{table}.sql").read_text()
            select_columns = [line.strip().rstrip(',') for line in query.splitlines()
                              if line.startswith('    ')]
            ddl = (root / "local_data" / f"create_{table}.sql").read_text()
            ddl_columns = [line.strip().split(' ')[0] for line in ddl.splitlines()
                           if line.startswith('    ')]
            self.assertEqual(select_columns, ddl_columns, table)

    def test_reject_invalid_s3_destination(self):
        for value in ("https://bucket/folder", "s3:///folder", "s3://bucket/path?query"):
            with self.assertRaises(ValueError):
                m.s3_location(value)


if __name__ == "__main__":
    unittest.main()
