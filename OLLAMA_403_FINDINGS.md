# Ollama Cloud 403 findings

Official sources checked on 2026-08-16:

- https://docs.ollama.com/cloud
  - Cloud models can be accessed directly through Ollama's API.
  - Direct API access requires an Ollama account and API key.
  - The official API-key settings page is https://ollama.com/settings/keys.
  - Ollama may retire cloud models over time.

- https://docs.ollama.com/api/authentication
  - Authentication is required for running cloud models via ollama.com.
  - Programmatic access uses an API key.

- https://docs.ollama.com/api/openai-compatibility
  - The OpenAI-compatible chat endpoint is /v1/chat/completions.
  - Local examples use localhost; cloud access uses the Ollama Cloud host and authentication.

Current repository configuration:
- OLLAMA_BASE_URL=https://ollama.com/v1
- OLLAMA_MODEL=qwen3.5:cloud
- Request uses Authorization: Bearer <OLLAMA_API_KEY>
- A missing cloud key is now rejected explicitly.
- Persistent user error remains HTTP 403; next diagnostic change includes the redacted response body and model name.
