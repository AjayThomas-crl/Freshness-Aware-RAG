import pytest

from app import llm


def _context():
    return {
        "source_name": "Alpha Cocoa",
        "url": "http://localhost:9000/alpha",
        "version_no": 4,
        "changed_at": "2026-09-07T12:00:00",
        "content": "Premium dark chocolate costs 6.80 USD.",
    }


def test_prompt_contains_question_context_and_freshness_metadata():
    prompt = llm.build_grounded_prompt("What is the price?", [_context()])

    assert "What is the price?" in prompt
    assert "Alpha Cocoa" in prompt
    assert "6.80 USD" in prompt
    assert "Version: 4" in prompt
    assert "Changed at: 2026-09-07T12:00:00" in prompt
    assert "only the retrieved contexts" in prompt


def test_missing_gemini_key_is_explicit(monkeypatch):
    monkeypatch.setattr(llm.settings, "gemini_api_key", "")

    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        llm.GeminiGenerator()


def test_transient_primary_uses_fallback_model(monkeypatch):
    calls = []

    class Response:
        text = "fallback answer"

    class Models:
        def generate_content(self, *, model, contents):
            calls.append(model)
            if model == "busy-model":
                raise RuntimeError("503 UNAVAILABLE")
            return Response()

    class Client:
        models = Models()

    monkeypatch.setattr(llm.settings, "gemini_model", "busy-model")
    monkeypatch.setattr(llm.settings, "gemini_fallback_model", "fallback-model")
    generator = object.__new__(llm.GeminiGenerator)
    generator._client = Client()

    assert generator.generate_answer("What is the price?", [_context()]) == "fallback answer"
    assert calls == ["busy-model", "fallback-model"]
