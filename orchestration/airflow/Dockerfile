FROM apache/airflow:2.10.3

USER airflow

# TF/Keras for the drift-check task (training/drift/drift_detector.py).
# numpy pinned to match what the rest of the project uses.
RUN pip install --no-cache-dir \
        "numpy==1.26.4" \
        "tensorflow-cpu==2.17.0"
