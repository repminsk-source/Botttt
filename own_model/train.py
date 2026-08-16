"""Обучение TinyGPT с нуля.

Пример:
  python own_model/train.py --text own_model/data/corpus.txt --steps 2000

Для Colab можно синхронизировать own_model/checkpoints с Google Drive между
сессиями. Скрипт не скачивает модель и не использует платные API.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import random

import torch

from model import ModelConfig, TinyGPT, parameter_count, save_checkpoint
from tokenizer import VOCAB_SIZE, encode, tokenizer_state


def get_batch(data: torch.Tensor, block_size: int, batch_size: int, device: str):
    starts = torch.randint(0, len(data) - block_size - 1, (batch_size,))
    x = torch.stack([data[start : start + block_size] for start in starts])
    y = torch.stack([data[start + 1 : start + block_size + 1] for start in starts])
    return x.to(device), y.to(device)


def evaluate(model, train_data, val_data, config, batch_size, device, batches=10):
    model.eval()
    results = {}
    with torch.no_grad():
        for name, data in (("train", train_data), ("val", val_data)):
            losses = []
            for _ in range(batches):
                x, y = get_batch(data, config.block_size, batch_size, device)
                _, loss = model(x, y)
                losses.append(loss.item())
            results[name] = sum(losses) / len(losses)
    model.train()
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--text", required=True, help="UTF-8 corpus text file")
    parser.add_argument("--out", default="own_model/checkpoints/tiny-gpt.pt")
    parser.add_argument("--steps", type=int, default=2000)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--block-size", type=int, default=256)
    parser.add_argument("--layers", type=int, default=4)
    parser.add_argument("--heads", type=int, default=4)
    parser.add_argument("--embedding", type=int, default=256)
    parser.add_argument("--lr", type=float, default=3e-4)
    parser.add_argument("--eval-every", type=int, default=100)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    text = Path(args.text).read_text(encoding="utf-8")
    if len(text.encode("utf-8")) < args.block_size * 4:
        raise SystemExit("Корпус слишком мал: добавь больше текста перед обучением.")
    tokens = torch.tensor(encode(text, add_bos=True, add_eos=True), dtype=torch.long)
    split = int(0.9 * len(tokens))
    train_data, val_data = tokens[:split], tokens[split:]
    config = ModelConfig(
        vocab_size=VOCAB_SIZE,
        block_size=args.block_size,
        n_layer=args.layers,
        n_head=args.heads,
        n_embd=args.embedding,
        dropout=0.0,
    )
    model = TinyGPT(config).to(device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=0.1)
    print(f"device={device} parameters={parameter_count(model):,} tokens={len(tokens):,}")
    for step in range(1, args.steps + 1):
        x, y = get_batch(train_data, config.block_size, args.batch_size, device)
        _, loss = model(x, y)
        optimizer.zero_grad(set_to_none=True)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        if step == 1 or step % args.eval_every == 0 or step == args.steps:
            metrics = evaluate(model, train_data, val_data, config, args.batch_size, device)
            print(f"step={step} train_loss={metrics['train']:.4f} val_loss={metrics['val']:.4f}")
            save_checkpoint(args.out, model, optimizer, tokenizer_state(), step)


if __name__ == "__main__":
    main()
