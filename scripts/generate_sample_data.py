"""
Generate a synthetic e-commerce sales CSV (no download needed).

  python scripts/generate_sample_data.py              -> sample_data/sales_clean.csv  (150,000 rows)
  python scripts/generate_sample_data.py --dirty      -> sample_data/sales_dirty.csv  (same + nulls + duplicates)
"""
import argparse
import os

import numpy as np
import pandas as pd

CATEGORIES = ["Electronics", "Fashion", "Home & Kitchen", "Books", "Beauty", "Sports", "Grocery"]
CITIES = ["Bengaluru", "Mumbai", "Delhi", "Hyderabad", "Chennai", "Pune", "Kolkata", "Ahmedabad"]
PAYMENTS = ["UPI", "Credit Card", "Debit Card", "Net Banking", "Cash on Delivery"]


def generate(n_rows: int, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    order_dates = pd.to_datetime("2025-01-01") + pd.to_timedelta(rng.integers(0, 365, n_rows), unit="D")
    quantity = rng.integers(1, 6, n_rows)
    unit_price = np.round(rng.uniform(99, 49999, n_rows), 2)
    return pd.DataFrame(
        {
            "Order ID": np.arange(1, n_rows + 1),
            "Customer ID": rng.integers(1000, 60000, n_rows),
            "Order Date": order_dates.strftime("%Y-%m-%d"),
            "Category": rng.choice(CATEGORIES, n_rows),
            "City": rng.choice(CITIES, n_rows),
            "Payment Method": rng.choice(PAYMENTS, n_rows),
            "Quantity": quantity,
            "Unit Price": unit_price,
            "Total Amount": np.round(quantity * unit_price, 2),
        }
    )


def make_dirty(df: pd.DataFrame, seed: int = 7) -> pd.DataFrame:
    """Inject ~1% null Order IDs, ~1% null amounts and ~1% duplicate rows."""
    rng = np.random.default_rng(seed)
    df = df.copy()
    n = len(df)
    df.loc[rng.choice(n, n // 100, replace=False), "Order ID"] = np.nan
    df.loc[rng.choice(n, n // 100, replace=False), "Total Amount"] = np.nan
    dupes = df.sample(n // 100, random_state=seed)
    return pd.concat([df, dupes], ignore_index=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=150_000)
    parser.add_argument("--dirty", action="store_true")
    args = parser.parse_args()

    os.makedirs("sample_data", exist_ok=True)
    data = generate(args.rows)
    if args.dirty:
        data = make_dirty(data)
        path = "sample_data/sales_dirty.csv"
    else:
        path = "sample_data/sales_clean.csv"
    data.to_csv(path, index=False)
    print(f"Wrote {len(data):,} rows to {path}")
