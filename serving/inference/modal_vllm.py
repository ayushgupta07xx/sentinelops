"""
Modal vLLM deployment — serves the Week 2 fine-tuned merged FP16 model on A10G
as an OpenAI-compatible endpoint, by spawning vLLM's official OpenAI server
as a subprocess. This is the pattern vLLM and Modal both recommend.

Deploy:    modal deploy serving/inference/modal_vllm.py
Tear down: modal app stop sentinelops-vllm
Logs:      modal app logs sentinelops-vllm

Why subprocess instead of importing init_app_state directly:
- vLLM's internal API (init_app_state, AsyncLLMEngine wiring) shifts every
  minor release. The CLI entrypoint `vllm serve` is the stable contract.
- The 0.6.4 init_app_state is sync; older code awaiting it crashes.

The container exposes port 8000 internally; Modal's @web_server wraps it.
"""
import subprocess

import modal

# ── Image: vLLM 0.6.4.post1 + fast HF download ──
vllm_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "vllm==0.6.4.post1",
        "huggingface_hub[hf_transfer]==0.26.2",
    )
    .env({"HF_HUB_ENABLE_HF_TRANSFER": "1"})
)

app = modal.App("sentinelops-vllm")

# Persistent volume so we don't re-download 14 GB every cold start.
model_cache = modal.Volume.from_name("sentinelops-hf-cache", create_if_missing=True)
MODEL_CACHE_DIR = "/root/.cache/huggingface"

MODEL_NAME = "ayushgupta7777/sentinelops-mistral7b-merged"
SERVED_NAME = "sentinelops-mistral7b"
PORT = 8000


@app.function(
    image=vllm_image,
    gpu="A10G",
    volumes={MODEL_CACHE_DIR: model_cache},
    secrets=[
        modal.Secret.from_name("huggingface-secret"),
        modal.Secret.from_name("sentinelops-vllm-secret"),
    ],
    scaledown_window=5 * 60,        # warm 5 min after last request
    timeout=20 * 60,                # cold start ceiling (first download = 5-10 min)
)
@modal.concurrent(max_inputs=8)
@modal.web_server(port=PORT, startup_timeout=15 * 60)
def serve():
    """
    Spawn `vllm serve` as a subprocess. Modal's @web_server wraps port 8000.
    Auth: vLLM's `--api-key` flag enforces Bearer token on /v1/* routes.
    """
    import os

    api_key = os.environ["VLLM_API_KEY"]

    cmd = [
        "vllm", "serve", MODEL_NAME,
        "--served-model-name", SERVED_NAME,
        "--host", "0.0.0.0",
        "--port", str(PORT),
        "--dtype", "float16",
        "--max-model-len", "4096",
        "--gpu-memory-utilization", "0.90",
        "--download-dir", MODEL_CACHE_DIR,
        "--api-key", api_key,
    ]
    # Popen so the subprocess inherits stdout/stderr → Modal logs.
    # Modal's @web_server keeps the function alive while subprocess runs.
    subprocess.Popen(" ".join(cmd), shell=True)
