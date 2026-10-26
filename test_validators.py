import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambda_src"))

from validators import (  # noqa: E402
    build_summary,
    normalize_columns,
    parse_list,
    split_good_and_bad,
    validate_schema,
)


def make_df():
    return pd.DataFrame(
        {
            "Order ID": [1, 2, 3, 3, None],
            "Amount ($)": [100.0, None, 50.0, 50.0, 20.0],
            "Category": ["a", "b", "c", "c", "d"],
        }
    )


def test_parse_list_handles_spaces_case_and_empty():
    assert parse_list(" Order_ID , Amount ,, ") == ["order_id", "amount"]
    assert parse_list("") == []
    assert parse_list(None) == []


def test_normalize_columns_makes_snake_case():
    df = normalize_columns(make_df())
    assert list(df.columns) == ["order_id", "amount", "category"]


def test_validate_schema_passes_when_columns_present():
    df = normalize_columns(make_df())
    validate_schema(df, ["order_id", "amount"])  # should not raise


def test_validate_schema_raises_on_missing_column():
    df = normalize_columns(make_df())
    with pytest.raises(ValueError, match="missing_col"):
        validate_schema(df, ["order_id", "missing_col"])


def test_null_key_rows_are_rejected_with_reason():
    df = normalize_columns(make_df())
    clean, rejected = split_good_and_bad(df, ["order_id", "amount"])
    reasons = rejected["reject_reason"].tolist()
    assert "null_amount" in reasons  # row 2
    assert "null_order_id" in reasons  # last row


def test_duplicate_rows_are_rejected_keeping_first():
    df = normalize_columns(make_df())
    clean, rejected = split_good_and_bad(df, ["order_id", "amount"])
    assert (rejected["reject_reason"] == "duplicate_row").sum() == 1
    assert (clean["order_id"] == 3).sum() == 1  # first copy kept


def test_row_counts_add_up():
    df = normalize_columns(make_df())
    clean, rejected = split_good_and_bad(df, ["order_id", "amount"])
    assert len(clean) + len(rejected) == len(df)


def test_clean_output_has_no_reject_reason_column():
    df = normalize_columns(make_df())
    clean, _ = split_good_and_bad(df, ["order_id"])
    assert "reject_reason" not in clean.columns


def test_build_summary_values():
    df = normalize_columns(make_df())
    clean, rejected = split_good_and_bad(df, ["order_id", "amount"])
    summary = build_summary("s3://b/k.csv", len(df), clean, rejected)
    assert summary["rows_in"] == 5
    assert summary["rows_out"] == 2
    assert summary["rows_rejected"] == 3
    assert summary["rejection_rate_pct"] == 60.0
    assert sum(summary["reject_reasons"].values()) == 3


def test_empty_file_summary_does_not_divide_by_zero():
    df = normalize_columns(pd.DataFrame({"Order ID": [], "Amount": []}))
    clean, rejected = split_good_and_bad(df, ["order_id"])
    summary = build_summary("s3://b/empty.csv", 0, clean, rejected)
    assert summary["rejection_rate_pct"] == 0
