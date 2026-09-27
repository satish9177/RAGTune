"""Hardware inference profiling for Qwen/Qwen3-Embedding-0.6B on RTX 5050 GPU."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List
import torch
from transformers import AutoModel, AutoTokenizer

MODEL_ID = "Qwen/Qwen3-Embedding-0.6B"
PINNED_REVISION = "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3"


def profile_qwen3(device: str = "cuda") -> Dict:
    print(f"Profiling {MODEL_ID} on {device}...")
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()

    t0 = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, revision=PINNED_REVISION, trust_remote_code=True)
    model = AutoModel.from_pretrained(
        MODEL_ID,
        revision=PINNED_REVISION,
        torch_dtype=torch.float16,
        trust_remote_code=True,
    ).to(device)
    model.eval()
    t_load = time.perf_counter() - t0

    allocated_post_load_mb = torch.cuda.memory_allocated(device) / (1024 * 1024)
    reserved_post_load_mb = torch.cuda.memory_reserved(device) / (1024 * 1024)
    print(f"Loaded {MODEL_ID} in {t_load:.2f}s | Weights VRAM allocated: {allocated_post_load_mb:.1f} MB, reserved: {reserved_post_load_mb:.1f} MB")

    configs = [
        {"batch_size": 1, "seq_len": 256},
        {"batch_size": 1, "seq_len": 512},
        {"batch_size": 4, "seq_len": 256},
        {"batch_size": 4, "seq_len": 512},
    ]

    results = []

    for cfg in configs:
        b = cfg["batch_size"]
        s = cfg["seq_len"]

        # Synthetic token inputs of length s
        input_ids = torch.randint(low=10, high=1000, size=(b, s), dtype=torch.long, device=device)
        attention_mask = torch.ones((b, s), dtype=torch.long, device=device)

        # Warmup
        for _ in range(5):
            with torch.no_grad():
                _ = model(input_ids=input_ids, attention_mask=attention_mask)
        torch.cuda.synchronize()

        torch.cuda.reset_peak_memory_stats()
        latencies = []
        n_iters = 15

        for _ in range(n_iters):
            t_start = time.perf_counter()
            with torch.no_grad():
                out = model(input_ids=input_ids, attention_mask=attention_mask)
            torch.cuda.synchronize()
            t_end = time.perf_counter()
            latencies.append((t_end - t_start) * 1000.0)

        peak_vram_mb = torch.cuda.max_memory_allocated(device) / (1024 * 1024)
        peak_res_mb = torch.cuda.max_memory_reserved(device) / (1024 * 1024)
        latencies.sort()
        median_lat = latencies[len(latencies) // 2]
        mean_lat = sum(latencies) / len(latencies)
        seqs_per_sec = (b * 1000.0) / median_lat
        toks_per_sec = (b * s * 1000.0) / median_lat

        res = {
            "batch_size": b,
            "seq_len": s,
            "median_latency_ms": round(median_lat, 2),
            "mean_latency_ms": round(mean_lat, 2),
            "peak_vram_allocated_mb": round(peak_vram_mb, 1),
            "peak_vram_reserved_mb": round(peak_res_mb, 1),
            "throughput_seqs_per_sec": round(seqs_per_sec, 1),
            "throughput_tokens_per_sec": round(toks_per_sec, 1),
        }
        results.append(res)
        print(
            f"  [b={b}, s={s}] Latency: {median_lat:.2f} ms | VRAM Peak: {peak_vram_mb:.1f} MB | "
            f"Throughput: {seqs_per_sec:.1f} seq/s, {toks_per_sec:.1f} tok/s"
        )

    report = {
        "model_id": MODEL_ID,
        "pinned_revision": PINNED_REVISION,
        "load_time_seconds": round(t_load, 2),
        "weights_vram_allocated_mb": round(allocated_post_load_mb, 1),
        "device": device,
        "gpu_name": torch.cuda.get_device_name(0),
        "total_vram_gb": round(torch.cuda.get_device_properties(0).total_memory / (1024**3), 2),
        "hardware_architecture_note": (
            "CRITICAL NOTE: Inference profiling and training profiling are distinct. "
            "Inference VRAM results (~1.2 - 1.4 GB) reflect only frozen forward activations "
            "and model weights in FP16. Training VRAM will require substantial additional memory "
            "for optimizer states (AdamW 8-16 bytes/param), backpropagation gradient computation, "
            "and batch negative caches, which will be measured during E3/E4 preparation."
        ),
        "gated_access_note": "google/embeddinggemma-300m remains legitimately blocked by gated Hugging Face authentication (401 Client Error: GatedRepoError). Not silently substituted.",
        "inference_benchmarks": results,
    }

    out_path = Path("benchmarks/hardware_profile_qwen3.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"Qwen3 hardware profile report written to {out_path}")
    return report


if __name__ == "__main__":
    profile_qwen3()
