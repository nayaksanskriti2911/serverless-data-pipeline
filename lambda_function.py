"""
Serverless data pipeline: S3 (raw CSV) -> validate/clean -> S3 (curated Parquet) + Glue table.
Trigger: S3 ObjectCreated event on the raw bucket (suffix .csv).

Environment variables (set by the CDK stack):
  CURATED_BUCKET    destination bucket (must differ from the raw bucket)
  KEY_COLUMNS       comma-separated columns that must not be null
  REQUIRED_COLUMNS  comma-separated columns that must exist
  GLUE_DATABASE     default: pipeline_db
  GLUE_TABLE        default: sales_curated
"""
import json
import logging
import os
import urllib.parse

import awswrangler as wr
import pandas as pd

from validators import (
    build_summary,
    normalize_columns,
    parse_list,
    split_good_and_bad,
    validate_schema,
)

logger = logging.getLogger()
logger.setLevel(logging.INFO)

CURATED_BUCKET = os.environ["CURATED_BUCKET"]
KEY_COLUMNS = parse_list(os.environ.get("KEY_COLUMNS", ""))
REQUIRED_COLUMNS = parse_list(os.environ.get("REQUIRED_COLUMNS", ""))
GLUE_DATABASE = os.environ.get("GLUE_DATABASE", "pipeline_db")
GLUE_TABLE = os.environ.get("GLUE_TABLE", "sales_curated")


def lambda_handler(event, context):
    record = event["Records"][0]["s3"]
    raw_bucket = record["bucket"]["name"]
    key = urllib.parse.unquote_plus(record["object"]["key"])
    file_name = os.path.splitext(os.path.basename(key))[0]
    source = f"s3://{raw_bucket}/{key}"
    logger.info("Processing %s", source)

    if raw_bucket == CURATED_BUCKET:
        raise ValueError("Raw and curated buckets must differ (avoids an infinite trigger loop).")

    # 1. Read
    df = wr.s3.read_csv(source)
    rows_in = len(df)

    # 2. Normalize column names and check schema
    df = normalize_columns(df)
    validate_schema(df, REQUIRED_COLUMNS)

    # 3. Data quality: split clean vs rejected rows
    clean, rejected = split_good_and_bad(df, KEY_COLUMNS)

    # 4. Write curated Parquet and register the table in the Glue catalog (queryable in Athena)
    wr.catalog.create_database(GLUE_DATABASE, exist_ok=True)
    wr.s3.to_parquet(
        df=clean,
        path=f"s3://{CURATED_BUCKET}/curated/{GLUE_TABLE}/",
        dataset=True,
        mode="append",
        database=GLUE_DATABASE,
        table=GLUE_TABLE,
    )

    # 5. Keep rejected rows (with reason) for inspection
    if len(rejected) > 0:
        wr.s3.to_parquet(
            df=rejected.astype(str),
            path=f"s3://{CURATED_BUCKET}/rejected/{file_name}.parquet",
        )

    # 6. Summary / audit record
    summary = build_summary(source, rows_in, clean, rejected)
    logger.info("Summary: %s", json.dumps(summary))
    wr.s3.to_json(
        df=pd.DataFrame([summary]).astype(str),
        path=f"s3://{CURATED_BUCKET}/audit/{file_name}.json",
        orient="records",
    )
    return summary
