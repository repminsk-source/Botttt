"""Генерация текста из checkpoint собственной модели."""
from __future__ import annotations

import argparse
import torch

from model import load_checkpoint
from tokenizer import encode, decode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", default="own_model/checkpoints/tiny-gpt.pt")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--tokens", type=int, default=160)
    parser.add_argument("--temperature", type=float, default=0.8)
    parser.add_argument("--top-k", type=int, default=40)
    args = parser.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model, _, step = load_checkpoint(args.checkpoint, device)
    prompt = torch.tensor([encode(args.prompt)], dtype=torch.long, device=device)
    output = model.generate(prompt, args.tokens, args.temperature, args.top_k)
    print(f"checkpoint_step={step} device={device}")
    print(decode(output[0].tolist()))


if __name__ == "__main__":
    main()
