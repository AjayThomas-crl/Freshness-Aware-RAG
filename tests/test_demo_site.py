from app.htmltext import html_to_text
from demo import competitor_site as site


class TestDeterminism:
    def test_same_epoch_same_page(self):
        assert site.render_page("alpha", 5) == site.render_page("alpha", 5)
        assert site.render_page("beta", 12) == site.render_page("beta", 12)

    def test_epoch_difference_changes_page(self):
        a0 = site.render_page("alpha", 0)
        a5 = site.render_page("alpha", 5)
        a20 = site.render_page("alpha", 20)
        assert a0 != a5  # promo/price drift
        assert a0 != a20

    def test_limited_product_rotates(self):
        # ROTATE_PERIOD=3, cycle of 6 ticks: present for 3, absent for 3.
        def has_limited(e):
            return "Limited" in site.render_page("alpha", e)

        present = [e for e in range(6) if has_limited(e)]
        assert present == [0, 1, 2]  # rotation cadence is stable


class TestHtmlToTextEndToEnd:
    def test_extracts_stable_and_drifting_content(self):
        text = html_to_text(site.render_page("alpha", 1))
        assert "Alpha Cocoa" in text
        assert "Classic Cocoa Bar 100g" in text  # stable product always present
        assert "market tick 1" in text


class TestAgainstPipelineContract:
    """The mock site's output must flow cleanly through the real chunker."""

    def test_chunks_are_stable_within_an_epoch(self):
        from app.chunker import chunk_text

        t0 = chunk_text(html_to_text(site.render_page("alpha", 3)), min_chars=5)
        assert len(t0) >= 1
        # Same epoch -> identical chunks -> hashes identical (no spurious change).
        assert chunk_text(html_to_text(site.render_page("alpha", 3)), min_chars=5) == t0

    def test_prices_drift_between_epochs(self):
        import re

        def prices(epoch):
            text = html_to_text(site.render_page("beta", epoch))
            return re.findall(r"\d+\.\d{2}", text)

        # Across ticks the drifting product's price must move (stable one stays).
        seen = {tuple(prices(e)) for e in (0, 1, 2, 3, 4, 5)}
        assert len(seen) > 1
