from urllib.parse import urlparse

import httpx

from app.config import settings
from app.htmltext import html_to_text


class LocalHttpScraper:
    """Plain HTTP scraper for keyless demo/local sources. No Firecrawl involved."""

    def __init__(self) -> None:
        self._client = httpx.Client(follow_redirects=True, timeout=15.0)

    def scrape(self, url: str) -> str:
        resp = self._client.get(url, headers={"User-Agent": "freshness-rag/0.1"})
        resp.raise_for_status()
        text = html_to_text(resp.text)
        if not text.strip():
            raise RuntimeError(f"No readable text at {url}")
        return text


class FirecrawlScraper:
    """Scrape a real website via Firecrawl. Requires FIRECRAWL_API_KEY."""

    def __init__(self) -> None:
        if not settings.firecrawl_api_key:
            raise RuntimeError(
                "FIRECRAWL_API_KEY is not set. Set it to scrape external sites, "
                "or point a Source at a localhost/127.0.0.1 URL to use the keyless "
                "HTTP scraper."
            )
        from firecrawl.v2.client import FirecrawlClient

        self._client = FirecrawlClient(api_key=settings.firecrawl_api_key)

    def scrape(self, url: str) -> str:
        doc = self._client.scrape(url, formats=["markdown"])
        markdown = (doc.markdown or "").strip()
        if not markdown:
            raise RuntimeError(f"No extractable content for {url}")
        return markdown


def _is_local(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    local_hosts = {h.strip().lower() for h in settings.local_scrape_hosts.split(",") if h.strip()}
    return host in local_hosts


def get_scraper(url: str):
    """Pick the scraper for a URL: keyless HTTP for local/demo hosts, Firecrawl otherwise."""
    if _is_local(url):
        return LocalHttpScraper()
    return FirecrawlScraper()
