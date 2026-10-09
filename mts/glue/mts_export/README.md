# MTS named CSV export script

`export_mts_csv.py` is a self-contained Glue 5.0 **ETL** script. It queries all
nine MTS tables through Athena and saves named CSVs in the configured S3 prefix.

Use the [lakehouse export deployment instructions](../../cloud-formation-templates/mts_lakehouse/EXPORT.md)
to upload the script and create the job with its dedicated IAM role. The script
does not require local SQL files or additional Python modules at runtime.
