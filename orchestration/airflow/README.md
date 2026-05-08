# Airflow (Week 5)

Single-container `airflow standalone` (webserver + scheduler + triggerer in
one process). Custom image extends `apache/airflow:2.10.3` with
`tensorflow-cpu==2.17.0` so the drift-check task can import
`drift_detector.py`. Postgres metadata DB is shared from the main
`docker-compose.yml`.

## Bring-up

From `~/sentinelops`:

```bash
docker compose up -d --build airflow
# First boot: ~3-5 min — image build pulls tensorflow-cpu (~600MB).
# Subsequent boots: ~30s.
```

Watch boot logs (wait for "Airflow is ready"):

```bash
docker compose logs -f airflow
```

Healthcheck:

```bash
docker compose ps airflow      # STATUS should reach "healthy" after ~90s
curl -fsS http://localhost:8080/health
```

## UI

Open <http://localhost:8080>.

```
Username: admin
Password: docker exec sentinelops-airflow \
            cat /opt/airflow/standalone_admin_password.txt
```

(`airflow standalone` generates this on first boot. The volume-backed
metadata DB persists it across restarts.)

## Trigger weekly_retrain_dag

UI path: **DAGs → weekly_retrain_dag → toggle ON → ▶ Trigger DAG**.

CLI:

```bash
docker exec sentinelops-airflow airflow dags trigger weekly_retrain_dag
docker exec sentinelops-airflow airflow dags list-runs -d weekly_retrain_dag
```

## Force the high-drift branch (demo)

Default flow: `BASELINE_CORPUS == RECENT_CORPUS` → drift score ≈ 0 →
`no_retrain` branch. To make the `trigger_kaggle_retrain` branch fire:

```bash
docker exec sentinelops-airflow airflow variables set force_drift_score 0.85
# trigger DAG; run_drift_check will use the override
```

Reset to real computation:

```bash
docker exec sentinelops-airflow airflow variables delete force_drift_score
```

## Logs / state

- DAG task logs: UI (Grid view → task → Logs) or `docker compose logs airflow`.
- Postgres metadata: persists in `postgres-data` volume.
- Airflow run logs: persist in `airflow-logs` volume.

## Volumes mounted into the container

| Host path                       | Container path           | Purpose                                  |
|---------------------------------|--------------------------|------------------------------------------|
| `./orchestration/airflow/dags`  | `/opt/airflow/dags`      | DAG files (auto-discovered)              |
| `./training/drift`              | `/opt/airflow/drift`     | drift_detector.py, importable from DAGs  |
| `./data`                        | `/opt/airflow/data` (ro) | corpus.jsonl for drift features          |
| `airflow-logs` (named vol)      | `/opt/airflow/logs`      | task logs persistence                    |
