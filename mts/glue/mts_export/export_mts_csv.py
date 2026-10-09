"""AWS Glue ETL driver: export nine Athena MTS tables as dated S3 CSVs."""

from datetime import datetime, timezone
import json
import logging
import time
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

LOGGER = logging.getLogger(__name__)
QUERIES = {
    'mts_table_1': '-- Run in Athena with the MTS catalog and namespace selected.\n-- Athena saves SELECT results as CSV in the workgroup results bucket.\nSELECT\n    "classification_desc",\n    "classification_id",\n    "current_month_dfct_sur_amt",\n    "current_month_gross_outly_amt",\n    "current_month_gross_rcpt_amt",\n    "data_type_cd",\n    "line_code_nbr",\n    "parent_id",\n    "print_order_nbr",\n    "record_calendar_day",\n    "record_calendar_month",\n    "record_calendar_quarter",\n    "record_calendar_year",\n    "record_date",\n    "record_fiscal_quarter",\n    "record_fiscal_year",\n    "record_type_cd",\n    "sequence_level_nbr",\n    "sequence_number_cd",\n    "src_line_nbr",\n    "table_nbr",\n    "source_bucket",\n    "source_key",\n    "source_version_id",\n    "source_sha256",\n    "source_url",\n    "manifest_key",\n    "manifest_version_id",\n    "batch_id",\n    "transform_version",\n    "ingested_at"\nFROM "mts_table_1";\n',
    'mts_table_2': '-- Run in Athena with the MTS catalog and namespace selected.\n-- Athena saves SELECT results as CSV in the workgroup results bucket.\nSELECT\n    "classification_desc",\n    "classification_id",\n    "current_fytd_budget_amt",\n    "current_month_budget_amt",\n    "current_year_budget_est_amt",\n    "data_type_cd",\n    "line_code_nbr",\n    "next_year_budget_est_amt",\n    "parent_id",\n    "print_order_nbr",\n    "prior_fytd_budget_amt",\n    "record_calendar_day",\n    "record_calendar_month",\n    "record_calendar_quarter",\n    "record_calendar_year",\n    "record_date",\n    "record_fiscal_quarter",\n    "record_fiscal_year",\n    "record_type_cd",\n    "sequence_level_nbr",\n    "sequence_number_cd",\n    "src_line_nbr",\n    "table_nbr",\n    "source_bucket",\n    "source_key",\n    "source_version_id",\n    "source_sha256",\n    "source_url",\n    "manifest_key",\n    "manifest_version_id",\n    "batch_id",\n    "transform_version",\n    "ingested_at"\nFROM "mts_table_2";\n',
    'mts_table_3': '-- Run in Athena with the MTS catalog and namespace selected.\n-- Athena saves SELECT results as CSV in the workgroup results bucket.\nSELECT\n    "classification_desc",\n    "classification_id",\n    "current_fytd_rcpt_outly_amt",\n    "current_month_rcpt_outly_amt",\n    "current_year_budget_est_amt",\n    "data_type_cd",\n    "line_code_nbr",\n    "parent_id",\n    "print_order_nbr",\n    "prior_fytd_rcpt_outly_amt",\n    "record_calendar_day",\n    "record_calendar_month",\n    "record_calendar_quarter",\n    "record_calendar_year",\n    "record_date",\n    "record_fiscal_quarter",\n    "record_fiscal_year",\n    "record_type_cd",\n    "sequence_level_nbr",\n    "sequence_number_cd",\n    "src_line_nbr",\n    "table_nbr",\n    "source_bucket",\n    "source_key",\n    "source_version_id",\n    "source_sha256",\n    "source_url",\n    "manifest_key",\n    "manifest_version_id",\n    "batch_id",\n    "transform_version",\n    "ingested_at"\nFROM "mts_table_3";\n',
    'mts_table_4': '-- Run in Athena with the MTS catalog and namespace selected.\n-- Athena saves SELECT results as CSV in the workgroup results bucket.\nSELECT\n    "classification_desc",\n    "classification_id",\n    "current_fytd_gross_rcpt_amt",\n    "current_fytd_net_rcpt_amt",\n    "current_fytd_refund_amt",\n    "current_month_gross_rcpt_amt",\n    "current_month_net_rcpt_amt",\n    "current_month_refund_amt",\n    "data_type_cd",\n    "line_code_nbr",\n    "parent_id",\n    "print_order_nbr",\n    "prior_fytd_gross_rcpt_amt",\n    "prior_fytd_net_rcpt_amt",\n    "prior_fytd_refund_amt",\n    "record_calendar_day",\n    "record_calendar_month",\n    "record_calendar_quarter",\n    "record_calendar_year",\n    "record_date",\n    "record_fiscal_quarter",\n    "record_fiscal_year",\n    "record_type_cd",\n    "sequence_level_nbr",\n    "sequence_number_cd",\n    "src_line_nbr",\n    "table_nbr",\n    "source_bucket",\n    "source_key",\n    "source_version_id",\n    "source_sha256",\n    "source_url",\n    "manifest_key",\n    "manifest_version_id",\n    "batch_id",\n    "transform_version",\n    "ingested_at"\nFROM "mts_table_4";\n',
    'mts_table_5': '-- Run in Athena with the MTS catalog and namespace selected.\n-- Athena saves SELECT results as CSV in the workgroup results bucket.\nSELECT\n    "classification_desc",\n    "classification_id",\n    "current_fytd_app_rcpt_amt",\n    "current_fytd_gross_outly_amt",\n    "current_fytd_net_outly_amt",\n    "current_month_app_rcpt_amt",\n    "current_month_gross_outly_amt",\n    "current_month_net_outly_amt",\n    "data_type_cd",\n    "line_code_nbr",\n    "parent_id",\n    "print_order_nbr",\n    "prior_fytd_app_rcpt_amt",\n    "prior_fytd_gross_outly_amt",\n    "prior_fytd_net_outly_amt",\n    "record_calendar_day",\n    "record_calendar_month",\n    "record_calendar_quarter",\n    "record_calendar_year",\n    "record_date",\n    "record_fiscal_quarter",\n    "record_fiscal_year",\n    "record_type_cd",\n    "sequence_level_nbr",\n    "sequence_number_cd",\n    "src_line_nbr",\n    "table_nbr",\n    "source_bucket",\n    "source_key",\n    "source_version_id",\n    "source_sha256",\n    "source_url",\n    "manifest_key",\n    "manifest_version_id",\n    "batch_id",\n    "transform_version",\n    "ingested_at"\nFROM "mts_table_5";\n',
    'mts_table_6': '-- Run in Athena with the MTS catalog and namespace selected.\n-- Athena saves SELECT results as CSV in the workgroup results bucket.\nSELECT\n    "begin_month_acct_bal_amt",\n    "begin_year_acct_bal_amt",\n    "classification_desc",\n    "classification_id",\n    "close_month_acct_bal_amt",\n    "current_month_net_txn_amt",\n    "data_type_cd",\n    "fytd_net_txn_amt",\n    "line_code_nbr",\n    "parent_id",\n    "print_order_nbr",\n    "prior_fytd_net_txn_amt",\n    "record_calendar_day",\n    "record_calendar_month",\n    "record_calendar_quarter",\n    "record_calendar_year",\n    "record_date",\n    "record_fiscal_quarter",\n    "record_fiscal_year",\n    "record_type_cd",\n    "sequence_level_nbr",\n    "sequence_number_cd",\n    "src_line_nbr",\n    "table_nbr",\n    "source_bucket",\n    "source_key",\n    "source_version_id",\n    "source_sha256",\n    "source_url",\n    "manifest_key",\n    "manifest_version_id",\n    "batch_id",\n    "transform_version",\n    "ingested_at"\nFROM "mts_table_6";\n',
    'mts_table_7': '-- Run in Athena with the MTS catalog and namespace selected.\n-- Athena saves SELECT results as CSV in the workgroup results bucket.\nSELECT\n    "apr_rcpt_outly_amt",\n    "aug_rcpt_outly_amt",\n    "classification_desc",\n    "classification_id",\n    "current_fytd_rcpt_outly_amt",\n    "data_type_cd",\n    "dec_rcpt_outly_amt",\n    "feb_rcpt_outly_amt",\n    "jan_rcpt_outly_amt",\n    "jul_rcpt_outly_amt",\n    "jun_rcpt_outly_amt",\n    "line_code_nbr",\n    "mar_rcpt_outly_amt",\n    "may_rcpt_outly_amt",\n    "nov_rcpt_outly_amt",\n    "oct_rcpt_outly_amt",\n    "parent_id",\n    "print_order_nbr",\n    "prior_fytd_rcpt_outly_amt",\n    "record_calendar_day",\n    "record_calendar_month",\n    "record_calendar_quarter",\n    "record_calendar_year",\n    "record_date",\n    "record_fiscal_quarter",\n    "record_fiscal_year",\n    "record_type_cd",\n    "sep_rcpt_outly_amt",\n    "sequence_level_nbr",\n    "sequence_number_cd",\n    "src_line_nbr",\n    "table_nbr",\n    "source_bucket",\n    "source_key",\n    "source_version_id",\n    "source_sha256",\n    "source_url",\n    "manifest_key",\n    "manifest_version_id",\n    "batch_id",\n    "transform_version",\n    "ingested_at"\nFROM "mts_table_7";\n',
    'mts_table_8': '-- Run in Athena with the MTS catalog and namespace selected.\n-- Athena saves SELECT results as CSV in the workgroup results bucket.\nSELECT\n    "begin_month_acct_bal_amt",\n    "begin_year_acct_bal_amt",\n    "classification_desc",\n    "classification_id",\n    "close_month_acct_bal_amt",\n    "current_month_excess_amt",\n    "current_month_outly_amt",\n    "current_month_rcpt_amt",\n    "data_type_cd",\n    "fytd_excess_amt",\n    "fytd_outly_amt",\n    "fytd_rcpt_amt",\n    "line_code_nbr",\n    "parent_id",\n    "print_order_nbr",\n    "record_calendar_day",\n    "record_calendar_month",\n    "record_calendar_quarter",\n    "record_calendar_year",\n    "record_date",\n    "record_fiscal_quarter",\n    "record_fiscal_year",\n    "record_type_cd",\n    "sequence_level_nbr",\n    "sequence_number_cd",\n    "src_line_nbr",\n    "table_nbr",\n    "source_bucket",\n    "source_key",\n    "source_version_id",\n    "source_sha256",\n    "source_url",\n    "manifest_key",\n    "manifest_version_id",\n    "batch_id",\n    "transform_version",\n    "ingested_at"\nFROM "mts_table_8";\n',
    'mts_table_9': '-- Run in Athena with the MTS catalog and namespace selected.\n-- Athena saves SELECT results as CSV in the workgroup results bucket.\nSELECT\n    "classification_desc",\n    "classification_id",\n    "current_fytd_rcpt_outly_amt",\n    "current_month_rcpt_outly_amt",\n    "data_type_cd",\n    "line_code_nbr",\n    "parent_id",\n    "print_order_nbr",\n    "prior_fytd_rcpt_outly_amt",\n    "record_calendar_day",\n    "record_calendar_month",\n    "record_calendar_quarter",\n    "record_calendar_year",\n    "record_date",\n    "record_fiscal_quarter",\n    "record_fiscal_year",\n    "record_type_cd",\n    "sequence_level_nbr",\n    "sequence_number_cd",\n    "src_line_nbr",\n    "table_nbr",\n    "source_bucket",\n    "source_key",\n    "source_version_id",\n    "source_sha256",\n    "source_url",\n    "manifest_key",\n    "manifest_version_id",\n    "batch_id",\n    "transform_version",\n    "ingested_at"\nFROM "mts_table_9";\n',
}


def s3_location(uri):
    parsed = urlparse(uri)
    if parsed.scheme != 's3' or not parsed.netloc or parsed.query or parsed.fragment:
        raise ValueError(f'Expected S3 URI: {uri}')
    return parsed.netloc, parsed.path.lstrip('/')


def wait_query(athena, query_id, timeout):
    deadline = time.monotonic() + timeout
    try:
        while True:
            execution = athena.get_query_execution(QueryExecutionId=query_id)['QueryExecution']
            status = execution['Status']
            if status['State'] == 'SUCCEEDED':
                return execution
            if status['State'] in ('FAILED', 'CANCELLED'):
                raise RuntimeError(f"Athena {query_id}: {status.get('StateChangeReason', status['State'])}")
            if time.monotonic() >= deadline:
                raise TimeoutError(f'Athena query timeout: {query_id}')
            time.sleep(2)
    except (TimeoutError, KeyboardInterrupt):
        athena.stop_query_execution(QueryExecutionId=query_id)
        raise


def export(athena, s3, args, now=None):
    # Capture the date once so a run spanning midnight has consistent filenames.
    started = now or datetime.now(timezone.utc)
    export_date = started.astimezone(ZoneInfo(args['export_timezone'])).strftime('%Y-%m-%d')
    bucket, prefix = s3_location(args['output_s3'])
    if not prefix.strip('/'):
        raise ValueError('Output must contain an export prefix')
    prefix = prefix.rstrip('/') + '/'
    timeout = int(args['query_timeout'])
    if timeout <= 0:
        raise ValueError('query_timeout must be positive')
    marker = prefix + f'export_complete_{export_date}.json'
    # A same-day rerun must not leave an old success marker for partial output.
    s3.delete_object(Bucket=bucket, Key=marker)
    completed = []
    # Complete every query before beginning replacement of the named CSVs.
    for table, query in QUERIES.items():
        query_id = athena.start_query_execution(
            QueryString=query, WorkGroup=args['workgroup'],
            QueryExecutionContext={'Catalog': args['catalog'], 'Database': args['namespace']},
            ResultReuseConfiguration={'ResultReuseByAgeConfiguration': {'Enabled': False}},
        )['QueryExecutionId']
        LOGGER.info('Querying table=%s query_id=%s', table, query_id)
        execution = wait_query(athena, query_id, timeout)
        source_uri = execution['ResultConfiguration'].get('OutputLocation')
        if not source_uri:
            raise ValueError('Athena workgroup must use S3 query results, not managed results')
        source_bucket, source_key = s3_location(source_uri)
        completed.append({'table': table, 'query_id': query_id,
                          'source_bucket': source_bucket, 'source_key': source_key,
                          'csv_key': prefix + f'{table}_{export_date}.csv'})
    for entry in completed:
        s3.copy({'Bucket': entry['source_bucket'], 'Key': entry['source_key']},
                bucket, entry['csv_key'], ExtraArgs={'ServerSideEncryption': 'AES256'})
        LOGGER.info('Exported s3://%s/%s', bucket, entry['csv_key'])
    manifest = {'export_date': export_date, 'timezone': args['export_timezone'],
                'started_at': started.isoformat(), 'job_name': args['JOB_NAME'],
                'tables': [{'table': e['table'], 'query_id': e['query_id'],
                            'csv': f"s3://{bucket}/{e['csv_key']}"} for e in completed]}
    s3.put_object(Bucket=bucket, Key=marker, Body=json.dumps(manifest, indent=2).encode('utf-8'),
                  ContentType='application/json', ServerSideEncryption='AES256')
    LOGGER.info('Completed nine exports: s3://%s/%s', bucket, marker)
    return manifest


def main():
    import sys
    import boto3
    from awsglue.utils import getResolvedOptions

    args = getResolvedOptions(sys.argv, ['JOB_NAME', 'region', 'catalog', 'namespace',
        'workgroup', 'output_s3', 'export_timezone', 'query_timeout'])
    logging.basicConfig(level=logging.INFO)
    session = boto3.Session(region_name=args['region'])
    export(session.client('athena'), session.client('s3'), args)


if __name__ == '__main__':
    main()
