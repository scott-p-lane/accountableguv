from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

spec = importlib.util.spec_from_file_location('export_job', Path(__file__).parents[1] / 'export_mts_csv.py')
job = importlib.util.module_from_spec(spec)
spec.loader.exec_module(job)


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.athena, self.s3 = Mock(), Mock()
        self.athena.start_query_execution.side_effect = [
            {'QueryExecutionId': f'query-{n}'} for n in range(1, 10)]
        self.athena.get_query_execution.side_effect = lambda **kw: {'QueryExecution': {
            'Status': {'State': 'SUCCEEDED'},
            'ResultConfiguration': {'OutputLocation': f"s3://results/queries/{kw['QueryExecutionId']}.csv"}}}
        self.args = dict(JOB_NAME='export-job', export_timezone='America/New_York',
            output_s3='s3://acctguv-feeds-us-east-2/exports/mts_exports/',
            query_timeout='900', workgroup='workgroup', catalog='catalog', namespace='silver_mts')
        self.now = datetime(2026, 10, 9, 2, tzinfo=timezone.utc)

    def export(self):
        # Fixed offset avoids depending on the Windows host's tzdata installation.
        with patch.object(job, 'ZoneInfo', return_value=timezone(timedelta(hours=-4))):
            return job.export(self.athena, self.s3, self.args, self.now)

    def test_all_nine_dated_files_and_final_marker(self):
        manifest = self.export()
        self.assertEqual(manifest['export_date'], '2026-10-08')
        self.assertEqual(self.athena.start_query_execution.call_count, 9)
        self.assertEqual([c.args[2] for c in self.s3.copy.call_args_list], [
            f'exports/mts_exports/mts_table_{n}_2026-10-08.csv' for n in range(1, 10)])
        self.s3.delete_object.assert_called_once_with(Bucket='acctguv-feeds-us-east-2',
            Key='exports/mts_exports/export_complete_2026-10-08.json')
        self.assertEqual(self.s3.put_object.call_args.kwargs['Key'],
            'exports/mts_exports/export_complete_2026-10-08.json')
        for call in self.athena.start_query_execution.call_args_list:
            self.assertFalse(call.kwargs['ResultReuseConfiguration']['ResultReuseByAgeConfiguration']['Enabled'])

    def test_query_failure_never_replaces_csvs(self):
        self.athena.get_query_execution.side_effect = None
        self.athena.get_query_execution.return_value = {'QueryExecution': {
            'Status': {'State': 'FAILED', 'StateChangeReason': 'denied'}}}
        with self.assertRaisesRegex(RuntimeError, 'denied'):
            self.export()
        self.s3.copy.assert_not_called()
        self.s3.put_object.assert_not_called()

    def test_copy_failure_has_no_completion_marker(self):
        self.s3.copy.side_effect = RuntimeError('copy failed')
        with self.assertRaises(RuntimeError):
            self.export()
        self.s3.put_object.assert_not_called()
        self.s3.delete_object.assert_called_once()

    def test_all_queries_complete_before_copy(self):
        self.s3.copy.side_effect = lambda *a, **kw: self.assertEqual(
            self.athena.get_query_execution.call_count, 9)
        self.export()

    def test_timeout_cancels_query(self):
        self.athena.get_query_execution.side_effect = None
        self.athena.get_query_execution.return_value = {'QueryExecution': {'Status': {'State': 'RUNNING'}}}
        with patch.object(job.time, 'monotonic', side_effect=[0, 901]):
            with self.assertRaises(TimeoutError):
                job.wait_query(self.athena, 'running', 900)
        self.athena.stop_query_execution.assert_called_once_with(QueryExecutionId='running')

    def test_queries_match_individual_exports(self):
        root = Path(__file__).resolve().parents[4]
        for table, query in job.QUERIES.items():
            self.assertEqual(query, (root / 'local_data/athena_export' / f'export_{table}.sql').read_text())


if __name__ == '__main__':
    unittest.main()
