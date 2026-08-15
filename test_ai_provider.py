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
        assert raw and error is None and calls == ["ollama", "grok"]
    finally:
        ai.AI_PROVIDER, ai.OLLAMA_ENABLED = old_provider, old_enabled
        ai._call_ollama, ai._call_grok = old_ollama, old_grok


if __name__ == "__main__":
    asyncio.run(test_ollama_primary_only())
    asyncio.run(test_explicit_fallback_order())
    print("AI_PROVIDER_ROUTING_OK")
