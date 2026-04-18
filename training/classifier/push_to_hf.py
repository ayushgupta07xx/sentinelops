"""Push fine-tuned classifier artifacts to HF Hub.

Uploads 253 MB model.pt via huggingface_hub.upload_file (NOT git LFS).
Expects docs/model_card.md to exist; uploads it as README.md.

Run from repo root with venv active, HF_TOKEN in env:
    export HF_TOKEN=$(grep ^HF_TOKEN sentinelops.env | cut -d= -f2)
    python -m training.classifier.push_to_hf
"""
import os
from pathlib import Path

from huggingface_hub import HfApi, create_repo

REPO_ID = "ayushgupta7777/sentinelops-classifier"
ART = Path("training/classifier/kaggle_outputs/classifier")
MODEL_CARD = Path("docs/model_card.md")


def main():
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise SystemExit("HF_TOKEN not set. Export it from sentinelops.env first.")

    create_repo(REPO_ID, exist_ok=True, token=token, repo_type="model")
    api = HfApi(token=token)

    # Root-level files
    for fname in ["model.pt", "label_mappings.json", "config.json", "eval_report.json"]:
        fp = ART / fname
        if not fp.exists():
            print(f"SKIP (missing): {fp}")
            continue
        print(f"Uploading {fname} ({fp.stat().st_size / 1e6:.1f} MB)...")
        api.upload_file(
            path_or_fileobj=str(fp),
            path_in_repo=fname,
            repo_id=REPO_ID,
            repo_type="model",
        )

    # Confusion matrices into assets/
    for fname in ["confusion_matrix_severity.png", "confusion_matrix_category.png"]:
        fp = ART / fname
        if fp.exists():
            print(f"Uploading assets/{fname}...")
            api.upload_file(
                path_or_fileobj=str(fp),
                path_in_repo=f"assets/{fname}",
                repo_id=REPO_ID,
                repo_type="model",
            )

    # Tokenizer folder
    tok_dir = ART / "tokenizer"
    if tok_dir.is_dir():
        print("Uploading tokenizer/ ...")
        api.upload_folder(
            folder_path=str(tok_dir),
            path_in_repo="tokenizer",
            repo_id=REPO_ID,
            repo_type="model",
        )

    # Model card → README.md
    if MODEL_CARD.exists():
        print("Uploading model card as README.md...")
        api.upload_file(
            path_or_fileobj=str(MODEL_CARD),
            path_in_repo="README.md",
            repo_id=REPO_ID,
            repo_type="model",
        )
    else:
        print(f"WARN: {MODEL_CARD} not found; skipping README upload")

    print(f"\nDone: https://huggingface.co/{REPO_ID}")


if __name__ == "__main__":
    main()
