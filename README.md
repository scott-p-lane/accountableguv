# accountableguv

AWS infrastructure can be deployed directly through the AWS console using the
[feeds staging stack](aws_iac/cloud-formation-templates/feeds_staging/README.md) and
[MTS lakehouse stack](aws_iac/cloud-formation-templates/mts_lakehouse/README.md).
The lakehouse stack creates an S3 table bucket and Glue job to load the staged MTS
reports, plus an Athena workgroup and S3 storage for query results.

To export the loaded S3 Tables and bulk-load them into a local PostgreSQL
database, use the [MTS export/import routine](tools/mts_postgres/README.md).
For named CSV exports to the feeds bucket, deploy the
[lakehouse stack's Glue ETL export job](aws_iac/cloud-formation-templates/mts_lakehouse/EXPORT.md),
which provisions the job and its IAM permissions alongside ingestion and Athena.

Source Repo for accountable govt. site. This is essentially my hobby project that allows me to 
apply software and cloud skills that I don't get to apply at my day-to-day job as technology manager.

I chose this because I don't believe there is a greate accountability or clarity in our government. There 
is a good bit of transparency, but that only results in a lot of confusing and incoherent data that most 
don't have the time to process. 

I'm looking to tap into those data sources, correlate them to legislations or goverment operations and 
provide a clear, succinct view of the cause and effect of policies, regulations, and spending.

I'm also hoping to provide a platform where folks can have balanced, rationale discourse on the things our goverment
is doing and helping understanding what our elected officials have actually accomplished (you can't really know much by
watching election ads). 

Finally, if this ever takes off, it would be nice if our govt. leaders and their consituents could have open discussions/debates
on this platform for all to see and maybe tear down the walls of parties. Wouldn't it be interesting if "bi-partisan" wasn't
different parties working together but the people and our government working together (independent of party affiliations). 

Probably an idealistic pipe dream, but I've got the time so may as well make an effort to move the needle in a direction that
will lead to the next evolutionary leap for democracy.
