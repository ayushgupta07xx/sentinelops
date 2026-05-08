"""SentinelOps weekly retrain DAG.

Flow:
    scrape_postmortems -> preprocess -> load_to_duckdb -> run_drift_check
        -> branch_on_drift
             |-> trigger_kaggle_retrain -> register_in_mlflow -> end
             |-> no_retrain -> end

Most tasks are skeleton (log-only) — Week 5 demo target is "DAG runnable
end-to-end manually with drift task producing a real number."

run_drift_check is real: it imports the TF/Keras drift detector mounted at
/opt/airflow/drift/drift_detector.py.

Demo override: set Airflow Variable `force_drift_score=0.85` to force the
retrain branch without needing two distinct corpora.
"""
from __future__ import annotations

import sys
from datetime import datetime

from airflow import DAG
from airflow.models import Variable
from airflow.operators.empty import EmptyOperator
from airflow.operators.python import BranchPythonOperator, PythonOperator

# drift_detector.py lives at /opt/airflow/drift (host: ./training/drift)
sys.path.insert(0, "/opt/airflow/drift")

# Both default to the same path → low drift → no_retrain branch.
# Swap RECENT_CORPUS to a perturbed sample to trigger real high-drift behavior.
BASELINE_CORPUS = "/opt/airflow/data/processed/corpus.jsonl"
RECENT_CORPUS = "/opt/airflow/data/processed/corpus.jsonl"
DRIFT_THRESHOLD = 0.5

DEFAULT_ARGS = {"owner": "sentinelops", "retries": 0, "depends_on_past": False}


def _scrape_postmortems(**_):
    sources = [
        "danluu/post-mortems (curated link list)",
        "Cloudflare blog (post-mortem tag)",
        "GitHub status incidents (Atom feed)",
        "AWS public post-event summaries",
    ]
    for s in sources:
        print(f"[skeleton] would scrape new postmortems from: {s}")
    print("[skeleton] would write deltas to data/raw/<source>/<date>.jsonl")


def _preprocess(**_):
    print("[skeleton] would: HTML->text, MinHash dedupe (threshold=0.85),")
    print("[skeleton]        Presidio + regex PII scrub, normalize whitespace")
    print("[skeleton] output: data/processed/corpus.jsonl + corpus_chunks.jsonl")


def _load_to_duckdb(**_):
    print("[skeleton] would upsert into fact_incidents in DuckDB warehouse")
    print("[skeleton] would refresh dim_services + dim_categories")


def _run_drift_check(**ctx):
    """Real task. Returns drift score in [0, 1]."""
    force = Variable.get("force_drift_score", default_var=None)
    if force is not None:
        score_val = float(force)
        print(f"[FORCE] using Airflow Variable force_drift_score = {score_val}")
    else:
        from drift_detector import score
        score_val = score(BASELINE_CORPUS, RECENT_CORPUS)
        print(f"[REAL] drift_detector.score(baseline, recent) = {score_val:.4f}")
        print(f"[REAL] baseline={BASELINE_CORPUS}")
        print(f"[REAL] recent  ={RECENT_CORPUS}")
    print(f"threshold = {DRIFT_THRESHOLD}")
    print(f"drifted   = {score_val >= DRIFT_THRESHOLD}")
    ctx["ti"].xcom_push(key="drift_score", value=score_val)
    return score_val


def _branch_on_drift(**ctx):
    score_val = ctx["ti"].xcom_pull(task_ids="run_drift_check", key="drift_score")
    if score_val is not None and score_val >= DRIFT_THRESHOLD:
        print(f"drift {score_val:.4f} >= {DRIFT_THRESHOLD} -> trigger_kaggle_retrain")
        return "trigger_kaggle_retrain"
    print(f"drift {score_val:.4f} < {DRIFT_THRESHOLD} -> no_retrain")
    return "no_retrain"


def _trigger_kaggle_retrain(**_):
    print("[skeleton] would call Kaggle API:")
    print("[skeleton]   kaggle kernels push training/llm/train_qlora.py")
    print("[skeleton] would poll until run completes (~6-8 hrs on 2xT4)")
    print("[skeleton] would pull merged adapter from HF Hub")


def _register_in_mlflow(**_):
    print("[skeleton] would register new adapter in MLflow Model Registry")
    print("[skeleton] would tag canonical revision; bump serving config")
    print("[skeleton] would emit Prometheus metric: model_version_promoted_total")


with DAG(
    dag_id="weekly_retrain_dag",
    description="SentinelOps weekly retrain pipeline (Week 5)",
    default_args=DEFAULT_ARGS,
    schedule="@weekly",
    start_date=datetime(2025, 1, 1),
    catchup=False,
    tags=["sentinelops", "ml", "retrain"],
) as dag:

    scrape = PythonOperator(
        task_id="scrape_postmortems", python_callable=_scrape_postmortems
    )
    preprocess = PythonOperator(
        task_id="preprocess", python_callable=_preprocess
    )
    load_duckdb = PythonOperator(
        task_id="load_to_duckdb", python_callable=_load_to_duckdb
    )
    drift_check = PythonOperator(
        task_id="run_drift_check", python_callable=_run_drift_check
    )
    branch = BranchPythonOperator(
        task_id="branch_on_drift", python_callable=_branch_on_drift
    )
    retrain = PythonOperator(
        task_id="trigger_kaggle_retrain", python_callable=_trigger_kaggle_retrain
    )
    register = PythonOperator(
        task_id="register_in_mlflow", python_callable=_register_in_mlflow
    )
    no_retrain = EmptyOperator(task_id="no_retrain")
    end = EmptyOperator(task_id="end", trigger_rule="none_failed_min_one_success")

    scrape >> preprocess >> load_duckdb >> drift_check >> branch
    branch >> retrain >> register >> end
    branch >> no_retrain >> end
