import pytest

from app import scraper
from app.scraper import LocalHttpScraper, get_scraper


def test_local_host_uses_http_scraper(monkeypatch):
    monkeypatch.setattr(scraper.settings, "local_scrape_hosts", "localhost,127.0.0.1")
    assert isinstance(get_scraper("http://localhost:9000/products"), LocalHttpScraper)
    assert isinstance(get_scraper("http://127.0.0.1:9000/products"), LocalHttpScraper)


def test_external_host_uses_firecrawl(monkeypatch):
    monkeypatch.setattr(scraper.settings, "local_scrape_hosts", "localhost,127.0.0.1")
    s = get_scraper("https://www.nestle.com/products")
    assert not isinstance(s, LocalHttpScraper)
    # Constructing the real FirecrawlScraper without a key must raise helpfully.
    monkeypatch.setattr(scraper.settings, "firecrawl_api_key", "")
    with pytest.raises(RuntimeError, match="FIRECRAWL_API_KEY"):
        get_scraper("https://www.nestle.com/products")


def test_demo_competitor_host_via_env(monkeypatch):
    monkeypatch.setattr(scraper.settings, "local_scrape_hosts", "competitors")
    assert isinstance(get_scraper("http://competitors:9000/a"), LocalHttpScraper)


class TestLocalHttpScraper:
    def test_extracts_text_from_html(self, monkeypatch):
        captured = {}

        class FakeResp:
            @property
            def text(self):
                return "<html><body><h1>Tasty</h1><p>A description.</p></body></html>"

            def raise_for_status(self):
                pass

        class FakeClient:
            def __init__(self, **kw):
                pass

            def get(self, url, **kw):
                captured["url"] = url
                return FakeResp()

            def close(self):
                pass

        monkeypatch.setattr(scraper.httpx, "Client", FakeClient)
        out = LocalHttpScraper().scrape("http://localhost:9000/a")
        assert captured["url"] == "http://localhost:9000/a"
        assert "Tasty" in out
        assert "A description." in out

    def test_empty_page_raises(self, monkeypatch):
        class FakeResp:
            @property
            def text(self):
                return "<html><body></body></html>"

            def raise_for_status(self):
                pass

        monkeypatch.setattr(
            scraper.httpx,
            "Client",
            lambda **kw: type(
                "C", (), {"get": lambda self, url, **k: FakeResp(), "close": lambda self: None}
            )(),
        )
        with pytest.raises(RuntimeError, match="No readable text"):
            LocalHttpScraper().scrape("http://localhost:9000/empty")
