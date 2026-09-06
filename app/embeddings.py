from sentence_transformers import SentenceTransformer

from app.config import settings


class LocalEmbedder:
    """Free local embeddings (sentence-transformers). Runs anywhere, no API cost."""

    def __init__(self) -> None:
        self._model = SentenceTransformer(settings.embedding_model)

    def embed(self, texts: list[str]) -> list[list[float]]:
        vectors = self._model.encode(
            texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return vectors.tolist()

    def embed_query(self, text: str) -> list[float]:
        return self.embed([text])[0]
