"""Детерминированный UTF-8 byte-level tokenizer.

Специальные токены занимают значения 256–259, поэтому словарь всегда имеет
размер 260 и не требует скачивания готового tokenizer-а.
"""
from __future__ import annotations

BOS = 256
EOS = 257
USER = 258
ASSISTANT = 259
VOCAB_SIZE = 260


def encode(text: str, add_bos: bool = False, add_eos: bool = False) -> list[int]:
    tokens = list(text.encode("utf-8"))
    if add_bos:
        tokens.insert(0, BOS)
    if add_eos:
        tokens.append(EOS)
    return tokens


def decode(tokens: list[int]) -> str:
    raw = bytes(token for token in tokens if 0 <= token < 256)
    return raw.decode("utf-8", errors="replace")


def tokenizer_state() -> dict:
    return {
        "type": "utf8-byte-level",
        "vocab_size": VOCAB_SIZE,
        "special_tokens": {"bos": BOS, "eos": EOS, "user": USER, "assistant": ASSISTANT},
    }
