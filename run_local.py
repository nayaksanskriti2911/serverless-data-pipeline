"""
Run the SAME validation logic as the Lambda locally, with local folders standing in for S3.

  raw CSV  ->  validate/clean  ->  curated Parquet + rejected rows + audit JSON  ->  SQL queries

Usage:
  python scripts/generate_sample_data.py && python scripts/generate_sample_data.py --dirty
  python scripts/run_local.py sample_data/sales_clean.csv sample_data/sales_dirty.csv

Needs: pandas. For Parquet + DuckDB SQL also: pip install pyarrow duckdb
(falls back to CSV + SQLite if those are missing).
This is a LOCAL simulation. The AWS deployment (CDK) is in infra/.
"""
import json
import os
import sqlite3
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambda_src"))
from validators import (  # noqa: E402
    build_summary,
    normalize_columns,
    parse_list,
    split_good_and_bad,
    validate_schema,
)

REQUIRED = parse_list("order_id,customer_id,order_date,category,city,payment_method,quantity,unit_price,total_amount")
KEYS = parse_list("order_id,total_amount")
OUT = "local_data"

try:
    import pyarrow  # noqa: F401
    HAVE_PARQUET = True
except ImportError:
    HAVE_PARQUET = False
try:
    import duckdb
except ImportError:
    duckdb = None

QUERIES = {
    "Total curated rows": "SELECT COUNT(*) AS rows FROM curated",
    "Revenue by category": (
        "SELECT category, ROUND(SUM(total_amount), 2) AS revenue FROM curated "
        "GROUP BY category ORDER BY revenue DESC"
    ),
    "Top city / payment combinations": (
        "SELECT city, payment_method, COUNT(*) AS orders FROM curated "
        "GROUP BY city, payment_method ORDER BY orders DESC LIMIT 5"
    ),
}


def write_table(df: pd.DataFrame, folder: str, name: str) -> str:
    os.makedirs(folder, exist_ok=True)
    ext = "parquet" if HAVE_PARQUET else "csv"
    path = os.path.join(folder, f"{name}.{ext}")
    df.to_parquet(path, index=False) if HAVE_PARQUET else df.to_csv(path, index=False)
    return path


def process(csv_path: str) -> dict:
    name = os.path.splitext(os.path.basename(csv_path))[0]
    start = time.time()
    df = normalize_columns(pd.read_csv(csv_path))
    rows_in = len(df)
    validate_schema(df, REQUIRED)
    clean, rejected = split_good_and_bad(df, KEYS)

    write_table(clean, f"{OUT}/curated", name)
    if len(rejected):
        write_table(rejected.astype(str), f"{OUT}/rejected", name)

    summary = build_summary(csv_path, rows_in, clean, rejected)
    summary["seconds"] = round(time.time() - start, 2)
    os.makedirs(f"{OUT}/audit", exist_ok=True)
    with open(f"{OUT}/audit/{name}.json", "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\n[{name}]\n{json.dumps(summary, indent=2)}")
    return summary


def run_queries() -> None:
    folder = f"{OUT}/curated"
    files = [os.path.join(folder, f) for f in sorted(os.listdir(folder))]
    print("\n=== SQL on curated data ===")
    if duckdb and HAVE_PARQUET:
        con = duckdb.connect()
        con.execute(f"CREATE VIEW curated AS SELECT * FROM read_parquet({files!r})")
        for title, sql in QUERIES.items():
            print(f"\n-- {title}\n{con.execute(sql).df().to_string(index=False)}")
    else:
        con = sqlite3.connect(":memory:")
        pd.concat([pd.read_csv(f) for f in files]).to_sql("curated", con, index=False)
        for title, sql in QUERIES.items():
            print(f"\n-- {title}\n{pd.read_sql(sql, con).to_string(index=False)}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    for path in sys.argv[1:]:
        process(path)
    run_queries()
    print(f"\nOutputs written under ./{OUT}/ (curated, rejected, audit)")
