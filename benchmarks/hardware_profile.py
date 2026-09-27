"""Hardware profiling suite measuring peak VRAM, throughput, and latency across candidate models."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List
import torch
from transformers import AutoModel, AutoModelForSequenceClassification, AutoTokenizer


MODELS_TO_PROFILE = [
    {
        "name": "BAAI/bge-small-en-v1.5",
        "type": "bi_encoder",
        "revision": "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a",
        "precisions": ["float16"],
        "seq_lengths": [256, 512],
        "batch_sizes": [1, 4, 8, 16],
    },
    {
        "name": "BAAI/bge-reranker-base",
        "type": "cross_encoder",
        "revision": "2cfc18c9415c912f9d8155881c133215df768a70",
        "precisions": ["float16"],
        "seq_lengths": [256, 512],
        "batch_sizes": [1, 4, 8, 16],
    },
]


def profile_model(config: Dict, device: torch.device) -> List[Dict]:
    results = []
    model_name = config["name"]
    model_type = config["type"]

    print(f"\n--- Profiling {model_name} on {device} ---")

    try:
        tokenizer = AutoTokenizer.from_pretrained(model_name)
    except Exception as e:
        print(f"Failed to load tokenizer for {model_name}: {e}")
        return [{"model": model_name, "error": f"Tokenizer load failure: {e}"}]

    for precision_str in config["precisions"]:
        dtype = torch.float16 if precision_str == "float16" else torch.bfloat16

        print(f"Loading {model_name} in {precision_str}...")
        try:
            if model_type == "bi_encoder":
                model = AutoModel.from_pretrained(model_name, torch_dtype=dtype).to(device)
            else:
                model = AutoModelForSequenceClassification.from_pretrained(model_name, torch_dtype=dtype).to(device)
            model.eval()
        except Exception as e:
            print(f"Failed to load model {model_name}: {e}")
            return [{"model": model_name, "error": f"Model load failure: {e}"}]

        for seq_len in config["seq_lengths"]:
            for batch_size in config["batch_sizes"]:
                torch.cuda.empty_cache()
                torch.cuda.reset_peak_memory_stats()

                # Generate dummy input tensors
                input_ids = torch.randint(low=100, high=20000, size=(batch_size, seq_len), device=device)
                attention_mask = torch.ones((batch_size, seq_len), device=device)

                oom = False
                throughput = 0.0
                per_batch_ms = 0.0
                peak_alloc_mb = 0.0
                peak_res_mb = 0.0

                try:
                    # Warmup
                    with torch.no_grad():
                        _ = model(input_ids=input_ids, attention_mask=attention_mask)
                    torch.cuda.synchronize()

                    # Benchmarking
                    num_iters = 5
                    t0 = time.perf_counter()
                    with torch.no_grad():
                        for _ in range(num_iters):
                            _ = model(input_ids=input_ids, attention_mask=attention_mask)
                    torch.cuda.synchronize()
                    t1 = time.perf_counter()

                    total_time = t1 - t0
                    throughput = round((batch_size * num_iters) / total_time, 2)
                    per_batch_ms = round((total_time / num_iters) * 1000.0, 2)

                    peak_alloc_mb = round(torch.cuda.max_memory_allocated(device) / (1024**2), 2)
                    peak_res_mb = round(torch.cuda.max_memory_reserved(device) / (1024**2), 2)

                    print(
                        f"  seq={seq_len:3d} | bs={batch_size:2d} | "
                        f"alloc={peak_alloc_mb:6.1f} MB | res={peak_res_mb:6.1f} MB | "
                        f"latency={per_batch_ms:5.1f} ms | throughput={throughput:6.1f} q/s"
                    )

                except torch.cuda.OutOfMemoryError:
                    print(f"  seq={seq_len} | bs={batch_size} -> OOM!")
                    oom = True
                    torch.cuda.empty_cache()
                except Exception as e:
                    print(f"  seq={seq_len} | bs={batch_size} -> Error: {e}")
                    oom = True

                record = {
                    "model_id": model_name,
                    "model_type": model_type,
                    "precision": precision_str,
                    "sequence_length": seq_len,
                    "batch_size": batch_size,
                    "peak_allocated_vram_mb": peak_alloc_mb,
                    "peak_reserved_vram_mb": peak_res_mb,
                    "per_batch_latency_ms": per_batch_ms,
                    "throughput_samples_per_sec": throughput,
                    "oom": oom,
                }
                results.append(record)

                if oom:
                    break  # Stop increasing batch size for this sequence length

        del model
        torch.cuda.empty_cache()

    return results


def main() -> None:
    if not torch.cuda.is_available():
        print("CUDA is not available. Hardware profiling requires a local GPU.")
        return

    device = torch.device("cuda:0")
    device_name = torch.cuda.get_device_name(0)
    total_vram_gb = round(torch.cuda.get_device_properties(0).total_memory / (1024**3), 2)
    print(f"Starting hardware profiling on: {device_name} ({total_vram_gb} GB VRAM)")

    all_results = []
    for cfg in MODELS_TO_PROFILE:
        res = profile_model(cfg, device)
        all_results.extend(res)

    report = {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "device_name": device_name,
        "total_vram_gb": total_vram_gb,
        "cuda_version": torch.version.cuda,
        "profiling_results": all_results,
    }

    out_path = Path("benchmarks/hardware_profile_report.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"\nHardware profiling report saved to {out_path}")


if __name__ == "__main__":
    main()
