# Local Ollama setup for VPI GAVAN

Ollama is installed as a local service and the `llama3.2` model is downloaded.

## Start and verify

```bash
sudo systemctl start ollama
ollama list
curl http://127.0.0.1:11434/api/tags
```

The OpenAI-compatible endpoint used by the bot is:

```text
http://127.0.0.1:11434/v1
```

## Bot environment

```env
OLLAMA_ENABLED=1
OLLAMA_BASE_URL=http://127.0.0.1:11434/v1
OLLAMA_MODEL=llama3.2
OLLAMA_API_KEY=ollama-local
```

The API key is only a placeholder for OpenAI-compatible client compatibility; Ollama itself does not require authentication on localhost.

When `OLLAMA_ENABLED=1`, the bot tries Ollama first and then falls back to Grok and Gemini if the local model is unavailable or returns invalid JSON. When it is `0`, the existing remote-provider order remains active.

## Manual model lifecycle

```bash
ollama run llama3.2
ollama stop llama3.2
```

The model may consume several gigabytes of RAM while loaded. The service can remain installed and running while the model is unloaded between requests.

## Deployment warning

`127.0.0.1` refers to the machine where the bot process runs. A bot hosted on Render cannot reach Ollama running on a separate local computer through this address. For Render, keep `OLLAMA_ENABLED=0` unless Ollama is installed in the same deployment environment; otherwise use a reachable private Ollama host or the existing remote providers.
