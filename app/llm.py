from collections.abc import Sequence

from app.config import settings


class GeminiUnavailableError(RuntimeError):
    """Gemini was temporarily unavailable after fallback handling."""


def build_grounded_prompt(question: str, contexts: Sequence[dict]) -> str:
    formatted = []
    for index, context in enumerate(contexts, start=1):
        formatted.append(
            f"[Context {index}]\n"
            f"Source: {context['source_name']}\n"
            f"URL: {context['url']}\n"
            f"Version: {context['version_no']}\n"
            f"Changed at: {context['changed_at']}\n"
            f"Content:\n{context['content']}"
        )

    context_text = "\n\n".join(formatted) or "No context was retrieved."
    return f"""You are a careful competitive-analysis assistant.

Answer the user's question using only the retrieved contexts below.
- Do not invent facts that are not supported by the contexts.
- Cite sources by their source name when making claims.
- Mention the relevant version or changed-at date for time-sensitive claims.
- If the contexts do not contain enough information, say so clearly.
- Prefer a concise, direct answer.

User question:
{question}

Retrieved contexts:
{context_text}
"""


class GeminiGenerator:
    def __init__(self) -> None:
        if not settings.gemini_api_key:
            raise RuntimeError(
                "GEMINI_API_KEY is not set. Add it to .env to generate answers."
            )

        from google import genai

        self._client = genai.Client(api_key=settings.gemini_api_key)

    def generate_answer(self, question: str, contexts: Sequence[dict]) -> str:
        prompt = build_grounded_prompt(question, contexts)
        try:
            return self._generate(settings.gemini_model, prompt)
        except Exception as primary_error:
            if not _is_transient_provider_error(primary_error):
                raise

            fallback = settings.gemini_fallback_model
            if not fallback or fallback == settings.gemini_model:
                raise GeminiUnavailableError(str(primary_error)) from primary_error

            try:
                return self._generate(fallback, prompt)
            except Exception as fallback_error:
                raise GeminiUnavailableError(
                    f"Primary model unavailable: {primary_error}; "
                    f"fallback unavailable: {fallback_error}"
                ) from fallback_error

    def _generate(self, model: str, prompt: str) -> str:
        response = self._client.models.generate_content(model=model, contents=prompt)
        answer = (response.text or "").strip()
        if not answer:
            raise RuntimeError("Gemini returned an empty answer")
        return answer


def _is_transient_provider_error(error: Exception) -> bool:
    status = getattr(error, "code", None) or getattr(error, "status_code", None)
    if status in {429, 500, 502, 503, 504}:
        return True
    message = str(error).upper()
    return any(token in message for token in ("UNAVAILABLE", "RESOURCE_EXHAUSTED", "429"))
