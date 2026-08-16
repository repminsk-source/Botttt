"""Минимальный HTTP inference-сервис для собственной TinyGPT-модели.

Запуск:
  python own_model/serve.py --checkpoint own_model/checkpoints/tiny-gpt.pt --port 8000

Endpoint POST /generate принимает {system, prompt, max_new_tokens, temperature}
и возвращает {text}. Сервис предназначен для отдельного процесса, а не для
обучения на Render Free.
"""
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import torch

from model import load_checkpoint
from tokenizer import encode, decode


class InferenceHandler(BaseHTTPRequestHandler):
    model = None
    device = "cpu"

    def _send(self, status: int, payload: dict):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/health":
            self._send(200, {"ok": True, "service": "own-model"})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if self.path != "/generate":
            self._send(404, {"error": "not found"})
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size > 64_000:
                raise ValueError("request too large")
            request = json.loads(self.rfile.read(size))
            system = str(request.get("system", ""))[:12_000]
            prompt = str(request.get("prompt", ""))[:12_000]
            max_new_tokens = min(max(int(request.get("max_new_tokens", 256)), 1), 512)
            temperature = min(max(float(request.get("temperature", 0.8)), 0.1), 1.5)
            text = f"Системные правила:\n{system}\n\nПользователь:\n{prompt}\nАссистент:"
            tokens = torch.tensor([encode(text)], dtype=torch.long, device=self.device)
            output = self.model.generate(tokens, max_new_tokens, temperature, top_k=40)
            generated = decode(output[0, tokens.shape[1] :].tolist()).strip()
            self._send(200, {"text": generated})
        except Exception as exc:
            self._send(400, {"error": str(exc)[:400]})

    def log_message(self, format, *args):
        return


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", required=True)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model, _, step = load_checkpoint(args.checkpoint, device)
    model.eval()
    InferenceHandler.model = model
    InferenceHandler.device = device
    print(f"own-model inference listening on {args.host}:{args.port}; step={step}; device={device}")
    ThreadingHTTPServer((args.host, args.port), InferenceHandler).serve_forever()


if __name__ == "__main__":
    main()
