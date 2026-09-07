from app.htmltext import html_to_text

SAMPLE = """
<html><head><title>ignore</title></head><body>
<h1>Alpha Chocolate</h1>
<p>Premium dark chocolate 70% made with cocoa butter.</p>
<script>var secret = 1;</script>
<table>
  <tr><th>Product</th><th>Price</th></tr>
  <tr><td>Classic Bar 100g</td><td>3.49 USD</td></tr>
</table>
<ul><li>Free shipping over 25 USD</li></ul>
</body></html>
"""


def test_drops_script_and_head():
    text = html_to_text(SAMPLE)
    assert "secret" not in text
    assert "ignore" not in text


def test_keeps_content_text():
    text = html_to_text(SAMPLE)
    assert "Alpha Chocolate" in text
    assert "Premium dark chocolate 70%" in text


def test_table_cells_present():
    text = html_to_text(SAMPLE)
    assert "Classic Bar 100g" in text
    assert "3.49 USD" in text


def test_heading_widget_is_plain_text():
    # Our extractor renders content as plain lines; it must not leak markup.
    text = html_to_text(SAMPLE)
    assert "<h1>" not in text
    assert "[heading]" in text  # semantic hint survives for readability


def test_list_item_survives():
    text = html_to_text(SAMPLE)
    assert "Free shipping over 25 USD" in text


def test_malformed_html_does_not_crash():
    assert html_to_text("<div><p>oops never closed") == "oops never closed"
    assert isinstance(html_to_text(""), str)
