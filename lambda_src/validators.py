"""Pure-pandas validation logic (no AWS imports, so it is easy to unit test)."""
import re

import pandas as pd


def parse_list(value: str) -> list:
    """'Order_ID, Amount' -> ['order_id', 'amount']"""
    return [c.strip().lower() for c in (value or "").split(",") if c.strip()]


def normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Lowercase snake_case column names (Athena/Glue friendly)."""
    df = df.copy()
    df.columns = [re.sub(r"[^0-9a-zA-Z]+", "_", str(c)).strip("_").lower() for c in df.columns]
    return df


def validate_schema(df: pd.DataFrame, required_columns: list) -> None:
    """Raise if any required column is missing."""
    missing = [c for c in required_columns if c not in df.columns]
    if missing:
        raise ValueError(f"Schema check failed. Missing columns: {missing}")


def split_good_and_bad(df: pd.DataFrame, key_columns: list):
    """
    Return (clean_df, rejected_df).
    Rejected rows carry a reject_reason column: null_<col> or duplicate_row.
    """
    df = df.copy()
    df["reject_reason"] = ""

    # Null check on key columns (first failing column wins)
    for col in key_columns:
        if col in df.columns:
            mask = df[col].isna() & (df["reject_reason"] == "")
            df.loc[mask, "reject_reason"] = f"null_{col}"

    # Duplicate check (keep first occurrence of fully identical rows)
    data_cols = [c for c in df.columns if c != "reject_reason"]
    dup_mask = df.duplicated(subset=data_cols, keep="first") & (df["reject_reason"] == "")
    df.loc[dup_mask, "reject_reason"] = "duplicate_row"

    rejected = df[df["reject_reason"] != ""].copy()
    clean = df[df["reject_reason"] == ""].drop(columns=["reject_reason"])
    return clean, rejected


def build_summary(source: str, rows_in: int, clean: pd.DataFrame, rejected: pd.DataFrame) -> dict:
    return {
        "source": source,
        "rows_in": rows_in,
        "rows_out": len(clean),
        "rows_rejected": len(rejected),
        "rejection_rate_pct": round(100 * len(rejected) / rows_in, 2) if rows_in else 0,
        "reject_reasons": rejected["reject_reason"].value_counts().to_dict() if len(rejected) else {},
    }
