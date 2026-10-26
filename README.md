# Serverless Data Pipeline on AWS

Event-driven pipeline that ingests raw CSV files, runs data quality checks, and publishes
query-ready Parquet tables. Built with S3, Lambda, Glue Data Catalog and Athena, and deployed
as infrastructure-as-code with AWS CDK (Python).

## Architecture

```
 CSV upload            S3 event            Lambda (Python 3.12)                 S3 curated bucket
┌───────────┐  ObjectCreated  ┌──────────────────────────────┐   ┌──────────────────────────────────┐
│ Raw bucket│ ──────────────► │ 1. read CSV                  │──►│ curated/  clean Parquet          │
│  *.csv    │   (.csv filter) │ 2. normalize column names    │   │ rejected/ bad rows + reason      │
└───────────┘                 │ 3. schema check              │   │ audit/    run summary (JSON)     │
                              │ 4. null + duplicate checks   │   └──────────────┬───────────────────┘
                              │ 5. write Parquet, register   │                  │
                              │    Glue table                │                  ▼
                              └──────────────────────────────┘     Glue Data Catalog ──► Athena (SQL)
```

## What it does

- **Event-driven ingestion:** any `.csv` landing in the raw bucket triggers the pipeline.
- **Data quality checks:** required-column (schema) check, null check on key columns, duplicate-row check.
- **Quarantine, not delete:** rejected rows are saved to `rejected/` with a `reject_reason`.
- **Query-ready output:** clean data is written as Parquet and registered in the Glue catalog, so it is
  immediately queryable in Athena.
- **Audit trail:** every run writes rows in / rows out / rows rejected / rejection rate to `audit/`.
- **Infrastructure as code:** the whole stack deploys with `cdk deploy` and is removed with `cdk destroy`.
- **Unit tested:** validation logic is separated from AWS code and covered by pytest.

## Results

| Metric | Value |
|---|---|
| Rows ingested | 151,500 |
| Rows written to curated | 147,016|
| Rows rejected | 4,484|
| Rejection rate | 2.96 % |
| Run time (local) | 0.6 s |

Screenshots: synthetic data, local run

## Project structure

```
app.py                       CDK entry point
infra/pipeline_stack.py      S3, Lambda, IAM, S3 trigger, Athena workgroup
lambda_src/lambda_function.py  Lambda handler (AWS I/O)
lambda_src/validators.py       Pure pandas validation logic
tests/test_validators.py       Unit tests
scripts/generate_sample_data.py  Synthetic sales data generator
```

## Run it

Prerequisites: AWS account, AWS CLI configured (`aws configure`), Node.js (for the CDK CLI), Python 3.12.

```bash
# 1. Install
npm install -g aws-cdk
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# 2. Test locally
pytest -v

# 3. Generate data (150k rows) and a dirty copy with nulls and duplicates
python scripts/generate_sample_data.py
python scripts/generate_sample_data.py --dirty

# 4. Deploy (first time only: cdk bootstrap)
cdk bootstrap
cdk deploy

# 5. Upload and watch it run (use the bucket name printed by cdk deploy)
aws s3 cp sample_data/sales_clean.csv s3://<RawBucketName>/sales_clean.csv
aws s3 cp sample_data/sales_dirty.csv s3://<RawBucketName>/sales_dirty.csv
aws logs tail /aws/lambda/<function-name> --follow
```

## Run locally (no AWS account needed)

`scripts/run_local.py` runs the same validation logic as the Lambda, with local folders standing in
for S3, and queries the curated output with SQL (DuckDB on Parquet).

```bash
pip install pandas pyarrow duckdb
python scripts/generate_sample_data.py
python scripts/generate_sample_data.py --dirty
python scripts/run_local.py sample_data/sales_clean.csv sample_data/sales_dirty.csv
```

Outputs go to `local_data/curated`, `local_data/rejected` and `local_data/audit`.
This is a local simulation of the cloud pipeline; the AWS deployment is defined in `infra/`.

## Query in Athena

Use workgroup `pipeline-wg`, database `pipeline_db`:

```sql
SELECT COUNT(*) FROM pipeline_db.sales_curated;

SELECT category, ROUND(SUM(total_amount), 2) AS revenue
FROM pipeline_db.sales_curated
GROUP BY category
ORDER BY revenue DESC;

SELECT city, payment_method, COUNT(*) AS orders
FROM pipeline_db.sales_curated
GROUP BY city, payment_method
ORDER BY orders DESC
LIMIT 10;
```

## Clean up (avoid charges)

```bash
cdk destroy
```

## Possible next steps

- Partition curated data by `order_date` for cheaper, faster Athena queries
- Replace the Lambda with a Glue/Spark job for multi-GB files
- Add an SNS alert when the rejection rate crosses a threshold
- Stream events through Kinesis for near-real-time ingestion
