"""Train provisional E7 domain reranker using BAAI/bge-reranker-base.

Predeclared protocol:
- Base Model: BAAI/bge-reranker-base
- Training Data: data/training/e7_reranker_train_provisional_v1.jsonl
- Device: CUDA FP16 with PyTorch AMP
- Max Length: 384
- Batch Size: 16 pairs (effective batch size 64 via 4 grad accumulation steps)
- Epochs: 3
- Optimizer: AdamW (lr=2e-5, weight_decay=0.01)
- LR Scheduler: Linear warmup (0.1 ratio) followed by linear decay
- Max Grad Norm: 1.0
- Seed: 42
- Strictly NO Benchmark v0 validation data accessed during training
"""

from __future__ import annotations

import datetime
import hashlib
import json
from pathlib import Path
import random
import sys
import time
from typing import Any, Dict, List, Tuple

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    get_linear_schedule_with_warmup,
)


def compute_file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class PairDataset(Dataset):
    def __init__(self, pairs: List[Tuple[str, str, float]]):
        self.pairs = pairs

    def __len__(self) -> int:
        return len(self.pairs)

    def __getitem__(self, idx: int) -> Tuple[str, str, float]:
        return self.pairs[idx]


def collate_fn(batch: List[Tuple[str, str, float]], tokenizer, max_length: int = 384):
    queries = [item[0] for item in batch]
    passages = [item[1] for item in batch]
    labels = torch.tensor([item[2] for item in batch], dtype=torch.float)

    encoding = tokenizer(
        queries,
        passages,
        padding=True,
        truncation=True,
        max_length=max_length,
        return_tensors="pt",
    )
    return encoding, labels


def main():
    print("=" * 80)
    print("TRAINING PROVISIONAL E7 DOMAIN RERANKER")
    print("=" * 80)

    # 1. Deterministic Seeding
    seed = 42
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)

    root = Path(__file__).resolve().parent.parent
    train_file = root / "data" / "training" / "e7_reranker_train_provisional_v1.jsonl"
    out_dir = root / "data" / "models" / "e7_bge_reranker_provisional_v0"
    out_manifest = root / "benchmarks" / "experiments" / "e7_domain_reranker_provisional_manifest.json"

    train_sha256 = compute_file_sha256(train_file)
    print(f"Training data: {train_file.name} (SHA-256: {train_sha256[:16]}...)")

    # 2. Load training data
    records = []
    with open(train_file, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                records.append(json.loads(line))

    unique_queries = {r["query_id"] for r in records}
    print(f"Loaded {len(records)} records across {len(unique_queries)} unique queries.")
    assert len(unique_queries) >= 75, f"Query count {len(unique_queries)} < 75 minimum!"

    # Construct paired samples: (query, positive, 1.0) and (query, negative, 0.0)
    # Deduplicate positive pairs per query
    seen_pos_queries = set()
    pairs: List[Tuple[str, str, float]] = []
    for r in records:
        qid = r["query_id"]
        q_text = r["query_text"]
        pos_text = r["positive_text"]
        neg_text = r["negative_text"]

        # Add negative pair
        pairs.append((q_text, neg_text, 0.0))

        # Add positive pair once per query to maintain 1:1 to 1:3 ratio
        if qid not in seen_pos_queries:
            seen_pos_queries.add(qid)
            pairs.append((q_text, pos_text, 1.0))

    # Shuffle training pairs with fixed seed
    random.shuffle(pairs)
    print(f"Total training pairs: {len(pairs)} ({len(seen_pos_queries)} positive, {len(pairs) - len(seen_pos_queries)} negative)")

    # 3. Setup Hardware & Model
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    gpu_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "CPU"
    vram_total_mb = (
        torch.cuda.get_device_properties(0).total_memory / (1024 * 1024)
        if torch.cuda.is_available()
        else 0.0
    )
    print(f"Compute Device: {device} ({gpu_name}, {vram_total_mb:.1f} MiB VRAM)")

    model_name = "BAAI/bge-reranker-base"
    print(f"Loading base model: {model_name}...")
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSequenceClassification.from_pretrained(model_name, num_labels=1)
    model.to(device)

    param_count = sum(p.numel() for p in model.parameters())
    commit_sha = getattr(model.config, "_commit_hash", "2cfc18c9415c912f9d8155881c133215df768a70")
    print(f"Loaded {model_name}: {param_count:,} parameters | Commit SHA: {commit_sha}")

    # 4. Training Hyperparameters
    batch_size = 16
    grad_accum_steps = 4
    effective_batch_size = batch_size * grad_accum_steps
    epochs = 3
    max_length = 384
    lr = 2e-5
    weight_decay = 0.01
    warmup_ratio = 0.1

    dataset = PairDataset(pairs)
    loader = DataLoader(
        dataset,
        batch_size=batch_size,
        shuffle=True,
        collate_fn=lambda b: collate_fn(b, tokenizer, max_length=max_length),
    )

    total_steps = len(loader) * epochs
    optimizer_steps = (total_steps + grad_accum_steps - 1) // grad_accum_steps
    warmup_steps = max(1, int(optimizer_steps * warmup_ratio))

    optimizer = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    scheduler = get_linear_schedule_with_warmup(
        optimizer,
        num_warmup_steps=warmup_steps,
        num_training_steps=optimizer_steps,
    )
    criterion = nn.BCEWithLogitsLoss()
    scaler = torch.amp.GradScaler("cuda", enabled=(device.type == "cuda"))

    print(f"\nTraining Plan:")
    print(f"  Epochs: {epochs}")
    print(f"  Batch Size: {batch_size} (Effective: {effective_batch_size})")
    print(f"  Total Batches: {len(loader)} per epoch ({total_steps} total)")
    print(f"  Optimizer Steps: {optimizer_steps} (Warmup: {warmup_steps})")
    print(f"  Learning Rate: {lr} | Weight Decay: {weight_decay}")
    print(f"  Precision: FP16 with AMP")
    print("-" * 80)

    # 5. Training Loop
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()

    model.train()
    t_start = time.perf_counter()
    epoch_losses = []
    global_step = 0
    opt_step = 0

    optimizer.zero_grad()

    for epoch in range(1, epochs + 1):
        epoch_loss_sum = 0.0
        batches_in_epoch = 0
        t_epoch_start = time.perf_counter()

        for batch_idx, (inputs, labels) in enumerate(loader):
            inputs = {k: v.to(device) for k, v in inputs.items()}
            labels = labels.to(device)

            with torch.amp.autocast("cuda", enabled=(device.type == "cuda"), dtype=torch.float16):
                outputs = model(**inputs)
                logits = outputs.logits.squeeze(-1)
                loss = criterion(logits, labels)
                loss_scaled = loss / grad_accum_steps

            scaler.scale(loss_scaled).backward()

            epoch_loss_sum += loss.item()
            batches_in_epoch += 1
            global_step += 1

            if (batch_idx + 1) % grad_accum_steps == 0 or (batch_idx + 1) == len(loader):
                scaler.unscale_(optimizer)
                torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
                scaler.step(optimizer)
                scaler.update()
                scheduler.step()
                optimizer.zero_grad()
                opt_step += 1

        avg_epoch_loss = epoch_loss_sum / batches_in_epoch
        epoch_losses.append(avg_epoch_loss)
        t_epoch = time.perf_counter() - t_epoch_start
        print(f"Epoch {epoch}/{epochs} Completed in {t_epoch:.2f}s | Avg Loss: {avg_epoch_loss:.4f} | LR: {scheduler.get_last_lr()[0]:.2e}")

    total_training_time = time.perf_counter() - t_start

    # Memory telemetry
    peak_vram_alloc = (
        float(torch.cuda.max_memory_allocated() / (1024 * 1024))
        if torch.cuda.is_available()
        else 0.0
    )
    peak_vram_res = (
        float(torch.cuda.max_memory_reserved() / (1024 * 1024))
        if torch.cuda.is_available()
        else 0.0
    )

    print("\n" + "=" * 80)
    print("TRAINING COMPLETE")
    print(f"Total Time: {total_training_time:.2f}s")
    print(f"Peak VRAM Allocated: {peak_vram_alloc:.1f} MiB ({peak_vram_alloc/vram_total_mb*100:.1f}%)")
    print(f"Peak VRAM Reserved:  {peak_vram_res:.1f} MiB ({peak_vram_res/vram_total_mb*100:.1f}%)")
    print(f"Epoch Losses: {[round(l, 4) for l in epoch_losses]}")
    print("=" * 80)

    # 6. Save Model Checkpoint
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"\nSaving model checkpoint to: {out_dir}...")
    model.save_pretrained(out_dir)
    tokenizer.save_pretrained(out_dir)
    print("Checkpoint saved successfully.")

    # 7. Persist Manifest
    manifest = {
        "experiment_id": "E7-DomainReranker-BGE-Provisional-v0",
        "description": "Provisional in-domain cross-encoder reranker trained on multi-signal shielded safe negatives",
        "workflow_mode": "PROVISIONAL_AI_FILTERED_PENDING_HUMAN_REVIEW",
        "status": "COMPLETED_PROVISIONAL",
        "timestamp_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "base_model": {
            "name": model_name,
            "commit_sha": commit_sha,
            "parameter_count": param_count,
        },
        "training_data": {
            "path": str(train_file.relative_to(root)),
            "sha256": train_sha256,
            "record_count": len(records),
            "unique_queries": len(unique_queries),
            "pair_count": len(pairs),
            "positive_pairs": len(seen_pos_queries),
            "negative_pairs": len(pairs) - len(seen_pos_queries),
        },
        "hyperparameters": {
            "epochs": epochs,
            "batch_size": batch_size,
            "grad_accum_steps": grad_accum_steps,
            "effective_batch_size": effective_batch_size,
            "max_length": max_length,
            "learning_rate": lr,
            "weight_decay": weight_decay,
            "warmup_ratio": warmup_ratio,
            "optimizer": "AdamW",
            "loss_function": "BCEWithLogitsLoss",
            "precision": "fp16_amp",
            "seed": seed,
        },
        "hardware_telemetry": {
            "gpu_device": gpu_name,
            "gpu_total_vram_mb": vram_total_mb,
            "peak_vram_allocated_mb": peak_vram_alloc,
            "peak_vram_reserved_mb": peak_vram_res,
            "training_time_seconds": total_training_time,
        },
        "training_metrics": {
            "epoch_losses": epoch_losses,
            "initial_loss": epoch_losses[0] if epoch_losses else None,
            "final_loss": epoch_losses[-1] if epoch_losses else None,
            "total_steps": total_steps,
            "optimizer_steps": opt_step,
        },
        "checkpoint_dir": str(out_dir.relative_to(root)),
    }

    out_manifest.parent.mkdir(parents=True, exist_ok=True)
    with open(out_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"Persisted manifest to: {out_manifest.name}")


if __name__ == "__main__":
    main()
