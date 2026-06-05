from __future__ import annotations

import argparse
import time

import torch
from transformers import AutoModel, AutoProcessor, AutoTokenizer


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="/mnt/d/has_models/LocateAnything-3B-HF")
    parser.add_argument("--seconds", type=int, default=600)
    args = parser.parse_args()

    print(f"loading {args.model}", flush=True)
    AutoTokenizer.from_pretrained(args.model, trust_remote_code=True)
    AutoProcessor.from_pretrained(args.model, trust_remote_code=True)
    AutoModel.from_pretrained(
        args.model,
        torch_dtype=torch.bfloat16,
        trust_remote_code=True,
    ).to("cuda").eval()
    print("loaded", flush=True)
    time.sleep(args.seconds)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
