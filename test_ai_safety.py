import ai


def test_provider_error_redaction():
    raw = "Client error for https://example.test/v1?key=SECRET_KEY Bearer SECRET_BEARER GEMINI_API_KEY=SECRET_ENV"
    safe = ai._safe_error(RuntimeError(raw))
    assert "SECRET_KEY" not in safe
    assert "SECRET_BEARER" not in safe
    assert "SECRET_ENV" not in safe
    assert "[REDACTED]" in safe


if __name__ == "__main__":
    test_provider_error_redaction()
    print("AI_ERROR_REDACTION_OK")
