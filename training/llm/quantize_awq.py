"""
AWQ 4-bit quantize merged Mistral-7B for vLLM serving (Week 4).
Domain-matched calibration from sentinelops-sft val split.
Run on Kaggle T4x2 with sentinelops-sft attached. ~45-60 min.
"""
import os
os.environ["PYTORCH_CUDA_ALLOC_CONF"] = "expandable_segments:True"

import json
from kaggle_secrets import UserSecretsClient
from huggingface_hub import login, HfApi
from awq import AutoAWQForCausalLM
from transformers import AutoTokenizer

login(token=UserSecretsClient().get_secret("HF_TOKEN"))

MERGED_REPO = "ayushgupta7777/sentinelops-mistral7b-merged"
AWQ_REPO    = "ayushgupta7777/sentinelops-mistral7b-awq"
AWQ_PATH    = "/kaggle/working/awq"

CALIB = None
for p in [
    "/kaggle/input/sentinelops-sft/sft_val.jsonl",
    "/kaggle/input/datasets/ayushgupta07xx/sentinelops-sft/sft_val.jsonl",
]:
    if os.path.exists(p):
        CALIB = p; break
if CALIB is None:
    raise FileNotFoundError("Attach dataset ayushgupta07xx/sentinelops-sft")

print("Loading tokenizer for calib truncation...")
tok = AutoTokenizer.from_pretrained(MERGED_REPO)

calib = []
with open(CALIB) as f:
    for line in f:
        d = json.loads(line)
        full = f"{d['instruction']}\n\n{d['input']}\n\n{d['output']}"
        # Truncate each sample to 1024 tokens to fit T4 VRAM during quantize
        ids = tok.encode(full, truncation=True, max_length=1024)
        calib.append(tok.decode(ids, skip_special_tokens=True))
print(f"Calibration samples: {len(calib)} (truncated to ≤1024 tokens each)")

quant_config = {"zero_point": True, "q_group_size": 128, "w_bit": 4, "version": "GEMM"}

print("Loading merged model...")
model = AutoAWQForCausalLM.from_pretrained(MERGED_REPO, safetensors=True)

print("Running AWQ quantization (~45 min, T4 VRAM-safe)...")
model.quantize(
    tok,
    quant_config=quant_config,
    calib_data=calib,
    max_calib_samples=28,
    max_calib_seq_len=1536,
    n_parallel_calib_samples=1,  # <-- T4 VRAM-safe; was OOM at 4
)

print("Saving quantized (~4 GB) to /kaggle/working/awq...")
model.save_quantized(AWQ_PATH, safetensors=True, shard_size="4GB")
tok.save_pretrained(AWQ_PATH)

print("Uploading to HF...")
api = HfApi()
api.create_repo(AWQ_REPO, exist_ok=True, private=False)
api.upload_folder(folder_path=AWQ_PATH, repo_id=AWQ_REPO, repo_type="model")
print(f"Done: https://huggingface.co/{AWQ_REPO}")