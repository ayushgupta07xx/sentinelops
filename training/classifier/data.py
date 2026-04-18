"""Load labeled incidents from DuckDB, tokenize, stratified split."""
from __future__ import annotations
from typing import Tuple

import duckdb
import numpy as np
import pandas as pd
from sklearn.model_selection import train_test_split

from .model import SEVERITIES, CATEGORIES


def load_labeled(db_path: str) -> pd.DataFrame:
    """Return only rows where BOTH labels are present (LLM + weak + manual)."""
    con = duckdb.connect(db_path, read_only=True)
    df = con.execute("""
        SELECT
            f.incident_id,
            f.title,
            f.body,
            f.severity,
            c.category_name AS category
        FROM fact_incidents f
        JOIN dim_categories c ON f.category_id = c.category_id
        WHERE f.severity IS NOT NULL AND f.category_id IS NOT NULL
    """).fetchdf()
    con.close()

    bad_sev = set(df.severity.unique()) - set(SEVERITIES)
    bad_cat = set(df.category.unique()) - set(CATEGORIES)
    assert not bad_sev, f"Unknown severities in DB: {bad_sev}"
    assert not bad_cat, f"Unknown categories in DB: {bad_cat}"

    return df


def tokenize(texts: list, tokenizer, max_length: int) -> Tuple[np.ndarray, np.ndarray]:
    enc = tokenizer(
        texts,
        padding="max_length",
        truncation=True,
        max_length=max_length,
        return_tensors="np",
    )
    return enc["input_ids"], enc["attention_mask"]


def make_splits(y_sev: np.ndarray, seed: int = 42):
    """Stratified 80/10/10 on severity (primary label, less sparse than category)."""
    idx = np.arange(len(y_sev))
    train_idx, tmp_idx = train_test_split(
        idx, test_size=0.2, stratify=y_sev, random_state=seed
    )
    val_idx, test_idx = train_test_split(
        tmp_idx, test_size=0.5, stratify=y_sev[tmp_idx], random_state=seed
    )
    return train_idx, val_idx, test_idx