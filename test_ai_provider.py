import asyncio

import ai


async def test_ollama_primary_only():
    old_provider, old_enabled = ai.AI_PROVIDER, ai.OLLAMA_ENABLED
    calls = []

    async def ollama(system, user):
        calls.append("ollama")
        return '{"success": true}'

    async def grok(system, user):
        calls.append("grok")
        return '{"success": true}'

    async def gemini(system, user):
        calls.append("gemini")
        return '{"success": true}'

    ai.AI_PROVIDER, ai.OLLAMA_ENABLED = "ollama", True
    ai._call_ollama, old_ollama = ollama, ai._call_ollama
    ai._call_grok, old_grok = grok, ai._call_grok
    ai._call_gemini, old_gemini = gemini, ai._call_gemini
    try:
        raw, error = await ai._get_raw("system", "user")
        assert raw and error is None and calls == ["ollama"]
    finally:
        ai.AI_PROVIDER, ai.OLLAMA_ENABLED = old_provider, old_enabled
        ai._call_ollama, ai._call_grok, ai._call_gemini = old_ollama, old_grok, old_gemini


async def test_parser_repairs_common_model_wrappers():
    parsed = ai._extract_json('```json\\n{"outcome":"draw","verdict_text":"Первая строка\\nВторая строка",}\\n```')
    assert parsed["outcome"] == "draw"
    assert "Вторая строка" in parsed["verdict_text"]


async def test_parser_retries_malformed_ollama_response():
    old_provider, old_enabled = ai.AI_PROVIDER, ai.OLLAMA_ENABLED
    calls = []

    async def ollama(system, user):
        calls.append("ollama")
        if len(calls) == 1:
            return '{"outcome":"draw",'
        return '{"outcome":"draw","verdict_text":"ok"}'

    old_ollama = ai._call_ollama
    ai.AI_PROVIDER, ai.OLLAMA_ENABLED = "ollama", True
    ai._call_ollama = ollama
    try:
        raw, error = await ai._get_raw("system", "user")
        assert raw and error is None and calls == ["ollama", "ollama"]
    finally:
        ai.AI_PROVIDER, ai.OLLAMA_ENABLED = old_provider, old_enabled
        ai._call_ollama = old_ollama


async def test_explicit_fallback_order():
    old_provider, old_enabled = ai.AI_PROVIDER, ai.OLLAMA_ENABLED
    calls = []

    async def ollama(system, user):
        calls.append("ollama")
        raise RuntimeError("offline")

    async def grok(system, user):
        calls.append("grok")
        return '{"success": true}'

    ai.AI_PROVIDER, ai.OLLAMA_ENABLED = "fallback", True
    old_ollama, old_grok = ai._call_ollama, ai._call_grok
    ai._call_ollama, ai._call_grok = ollama, grok
    try:
        raw, error = await ai._get_raw("system", "user")
        assert raw and error is None and calls == ["ollama", "ollama", "grok"]
    finally:
        ai.AI_PROVIDER, ai.OLLAMA_ENABLED = old_provider, old_enabled
        ai._call_ollama, ai._call_grok = old_ollama, old_grok


async def test_cloud_http_error_is_descriptive():
    old_enabled, old_base, old_key, old_model = ai.OLLAMA_ENABLED, ai.OLLAMA_BASE_URL, ai.OLLAMA_API_KEY, ai.OLLAMA_MODEL
    class FakeResponse:
        status_code = 403
        text = '{"error":"invalid api key"}'
        def raise_for_status(self):
            request = __import__('httpx').Request('POST', 'https://ollama.com/v1/chat/completions')
            response = __import__('httpx').Response(403, request=request, text=self.text)
            raise __import__('httpx').HTTPStatusError('403', request=request, response=response)
    class FakeClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
        async def post(self, *args, **kwargs):
            return FakeResponse()
    original_client = ai.httpx.AsyncClient
    ai.OLLAMA_ENABLED = True
    ai.OLLAMA_BASE_URL = 'https://ollama.com/v1'
    ai.OLLAMA_API_KEY = 'valid-looking-key'
    ai.OLLAMA_MODEL = 'qwen3.5:cloud'
    ai.httpx.AsyncClient = lambda *args, **kwargs: FakeClient()
    try:
        try:
            await ai._call_ollama('system', 'user')
        except RuntimeError as exc:
            assert 'Ollama HTTP 403' in str(exc)
            assert 'qwen3.5:cloud' in str(exc)
            assert 'invalid api key' in str(exc)
        else:
            raise AssertionError('HTTP 403 was not classified')
    finally:
        ai.httpx.AsyncClient = original_client
        ai.OLLAMA_ENABLED, ai.OLLAMA_BASE_URL, ai.OLLAMA_API_KEY, ai.OLLAMA_MODEL = old_enabled, old_base, old_key, old_model


async def test_cloud_requires_api_key():
    old_enabled, old_base, old_key = ai.OLLAMA_ENABLED, ai.OLLAMA_BASE_URL, ai.OLLAMA_API_KEY
    ai.OLLAMA_ENABLED = True
    ai.OLLAMA_BASE_URL = "https://ollama.com/v1"
    ai.OLLAMA_API_KEY = ""
    try:
        try:
            await ai._call_ollama("system", "user")
        except RuntimeError as exc:
            assert "OLLAMA_API_KEY" in str(exc)
        else:
            raise AssertionError("missing cloud key was not rejected")
    finally:
        ai.OLLAMA_ENABLED, ai.OLLAMA_BASE_URL, ai.OLLAMA_API_KEY = old_enabled, old_base, old_key


if __name__ == "__main__":
    asyncio.run(test_cloud_requires_api_key())
    asyncio.run(test_ollama_primary_only())
    asyncio.run(test_explicit_fallback_order())
    asyncio.run(test_parser_repairs_common_model_wrappers())
    asyncio.run(test_parser_retries_malformed_ollama_response())
    print("AI_PROVIDER_ROUTING_OK")
