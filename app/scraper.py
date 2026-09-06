from firecrawl.v2.client import FirecrawlClient

from app.config import settings


class FirecrawlScraper:
    """Thin wrapper around Firecrawl. Returns cleaned markdown for a URL."""

    def __init__(self) -> None:
        if not settings.firecrawl_api_key:
            raise RuntimeError("FIRECRAWL_API_KEY is not set")
        self._client = FirecrawlClient(api_key=settings.firecrawl_api_key)

    def scrape(self, url: str) -> str:
        doc = self._client.scrape(url, formats=["markdown"])
        markdown = (doc.markdown or "").strip()
        if not markdown:
            raise RuntimeError(f"No extractable content for {url}")
        return markdown
