"""
Merge QLoRA adapter into base Mistral-7B-Instruct-v0.3 fp16, push merged to HF.
Run on Kaggle T4x2, ~20-25 min.

KAGGLE SETUP (Cell 1, run first, then Restart Kernel & Clear Outputs):
    !pip uninstall -y torch torchvision torchaudio bitsandbytes transformers peft \
        trl accelerate datasets huggingface_hub tokenizers wandb xformers
    !pip install --no-cache-dir --ignore-installed \
        bitsandbytes==0.45.0 peft==0.13.2 trl==0.12.2 accelerate==1.1.1 \
        datasets==3.1.0 huggingface_hub==0.27.1 tokenizers==0.20.3 wandb==0.18.7
    !pip install --no-cache-dir --ignore-installed \
        --index-url https://download.pytorch.org/whl/cu124 torch==2.5.1
    !pip install --no-cache-dir --force-reinstall --no-deps transformers==4.46.3

NOTE: Do NOT include torchvision — pulls broken cu130 wheel on Kaggle default env.
Secrets required: HF_TOKEN (write scope).
"""
import torch
from kaggle_secrets import UserSecretsClient
from huggingface_hub import login, HfApi
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer

login(token=UserSecretsClient().get_secret("HF_TOKEN"))

BASE = "mistralai/Mistral-7B-Instruct-v0.3"
ADAPTER = "ayushgupta7777/sentinelops-mistral7b-qlora-adapter"
MERGED_REPO = "ayushgupta7777/sentinelops-mistral7b-merged"
LOCAL = "/kaggle/working/merged"

print("Loading base in fp16...")
tok = AutoTokenizer.from_pretrained(BASE)
base = AutoModelForCausalLM.from_pretrained(
    BASE, torch_dtype=torch.float16, device_map="auto", low_cpu_mem_usage=True
)

print("Attaching adapter + merging...")
peft_model = PeftModel.from_pretrained(base, ADAPTER)
merged = peft_model.merge_and_unload()

print("Saving merged locally (14 GB)...")
merged.save_pretrained(LOCAL, safe_serialization=True, max_shard_size="4GB")
tok.save_pretrained(LOCAL)

del base, peft_model, merged
torch.cuda.empty_cache()

print("Uploading to HF...")
api = HfApi()
api.create_repo(MERGED_REPO, exist_ok=True, private=False)
api.upload_folder(folder_path=LOCAL, repo_id=MERGED_REPO, repo_type="model")
print(f"Done: https://huggingface.co/{MERGED_REPO}")