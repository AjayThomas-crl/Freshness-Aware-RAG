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
