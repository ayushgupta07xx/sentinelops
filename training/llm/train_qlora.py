"""QLoRA fine-tuning of Mistral-7B-Instruct-v0.3 on SentinelOps SFT corpus.
Kaggle-ready: checkpoints every 50 steps, resumes from latest, W&B logged.
Run 2-3 times to complete 3 epochs within the 9-hour Kaggle session cap.
"""
import os, json, torch
from pathlib import Path
from datasets import Dataset
from transformers import (
    AutoTokenizer, AutoModelForCausalLM, BitsAndBytesConfig, TrainingArguments,
)
from peft import LoraConfig, prepare_model_for_kbit_training, get_peft_model, PeftModel
from trl import SFTTrainer, SFTConfig

# ---------- paths (Kaggle layout) ----------
KAGGLE = Path("/kaggle").exists()
if KAGGLE:
    candidates = [
        Path("/kaggle/input/sentinelops-sft"),
        Path("/kaggle/input/datasets/ayushgupta07xx/sentinelops-sft"),
    ]
    DATA_DIR = next((p for p in candidates if (p / "sft_train.jsonl").exists()), candidates[0])
    OUT_DIR  = Path("/kaggle/working/qlora_out")
    print(f"Using DATA_DIR={DATA_DIR}")
else:
    DATA_DIR = Path("data/processed")
    OUT_DIR  = Path("training/llm/qlora_out")

TRAIN_FILE = DATA_DIR / "sft_train.jsonl"
VAL_FILE   = DATA_DIR / "sft_val.jsonl"
BASE_MODEL = "mistralai/Mistral-7B-Instruct-v0.3"

# ---------- hyperparams ----------
MAX_SEQ_LEN    = 2048
LORA_R         = 16
LORA_ALPHA     = 32
LORA_DROPOUT   = 0.05
EPOCHS         = 3
BATCH_SIZE     = 2
GRAD_ACCUM     = 8          # effective batch 16
LR             = 2e-4
WARMUP_RATIO   = 0.03
SAVE_STEPS     = 15
EVAL_STEPS     = 15
LOG_STEPS      = 10
SAVE_TOTAL     = 3          # keep last 3 checkpoints only (disk budget)

# ---------- W&B ----------
os.environ.setdefault("WANDB_PROJECT", "sentinelops")
os.environ.setdefault("WANDB_JOB_TYPE", "qlora_sft")

# ---------- dataset ----------
def load_jsonl(p): return [json.loads(l) for l in open(p)]

def format_example(ex):
    """Mistral-Instruct chat format. Single-turn: [INST] instr + input [/INST] output"""
    user = f"{ex['instruction']}\n\n{ex['input']}"
    return {"text": f"<s>[INST] {user} [/INST] {ex['output']}</s>"}

train_raw = load_jsonl(TRAIN_FILE)
val_raw   = load_jsonl(VAL_FILE)
print(f"Loaded {len(train_raw)} train / {len(val_raw)} val raw pairs")

train_ds = Dataset.from_list(train_raw).map(format_example, remove_columns=list(train_raw[0].keys()))
val_ds   = Dataset.from_list(val_raw).map(format_example,   remove_columns=list(val_raw[0].keys()))
print(f"Formatted. Train sample text[:300]: {train_ds[0]['text'][:300]!r}")

# ---------- tokenizer ----------
tok = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)
if tok.pad_token is None:
    tok.pad_token = tok.eos_token
tok.padding_side = "right"

# ---------- 4-bit quant config (NF4) ----------
bnb = BitsAndBytesConfig(
    load_in_4bit=True,
    bnb_4bit_quant_type="nf4",
    bnb_4bit_compute_dtype=torch.bfloat16,
    bnb_4bit_use_double_quant=True,
)

# ---------- model ----------
print("Loading base model in 4-bit NF4...")
model = AutoModelForCausalLM.from_pretrained(
    BASE_MODEL,
    quantization_config=bnb,
    device_map="auto",
    trust_remote_code=True,
)
model.config.use_cache = False
model.config.pretraining_tp = 1
model = prepare_model_for_kbit_training(model)

# ---------- LoRA config (all linear layers) ----------
lora_cfg = LoraConfig(
    r=LORA_R,
    lora_alpha=LORA_ALPHA,
    lora_dropout=LORA_DROPOUT,
    bias="none",
    task_type="CAUSAL_LM",
    target_modules=["q_proj","k_proj","v_proj","o_proj","gate_proj","up_proj","down_proj"],
)
model = get_peft_model(model, lora_cfg)
model.print_trainable_parameters()

# ---------- check for existing checkpoint to resume ----------
OUT_DIR.mkdir(parents=True, exist_ok=True)
ckpts = sorted(OUT_DIR.glob("checkpoint-*"), key=lambda p: int(p.name.split("-")[1]))
resume_from = str(ckpts[-1]) if ckpts else None
print(f"Resume from: {resume_from}" if resume_from else "No prior checkpoint; fresh start.")

# ---------- training args ----------
args = SFTConfig(
    output_dir=str(OUT_DIR),
    num_train_epochs=EPOCHS,
    per_device_train_batch_size=BATCH_SIZE,
    per_device_eval_batch_size=BATCH_SIZE,
    gradient_accumulation_steps=GRAD_ACCUM,
    gradient_checkpointing=True,
    gradient_checkpointing_kwargs={"use_reentrant": False},
    learning_rate=LR,
    lr_scheduler_type="cosine",
    warmup_ratio=WARMUP_RATIO,
    optim="paged_adamw_8bit",
    bf16=True,
    logging_steps=LOG_STEPS,
    save_strategy="steps",
    save_steps=SAVE_STEPS,
    save_total_limit=SAVE_TOTAL,
    eval_strategy="steps",
    eval_steps=EVAL_STEPS,
    report_to="wandb",
    run_name="mistral7b-qlora-sentinelops",
    max_seq_length=MAX_SEQ_LEN,
    packing=False,
    dataset_text_field="text",
    seed=42,
)

trainer = SFTTrainer(
    model=model,
    args=args,
    train_dataset=train_ds,
    eval_dataset=val_ds,
    processing_class=tok,
)

print("Starting training...")
trainer.train(resume_from_checkpoint=resume_from)

# ---------- save final adapter ----------
final_dir = OUT_DIR / "final_adapter"
trainer.model.save_pretrained(final_dir)
tok.save_pretrained(final_dir)
print(f"Saved final adapter to {final_dir}")