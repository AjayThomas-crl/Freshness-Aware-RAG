"""Tiny HTML -> readable-text extractor (stdlib only).

Renders a simple HTML document into plain lines good enough for chunking:
block elements become their own lines, headings keep their text, tables render
one cell per line, links show their text. Scripts/styles are dropped.
"""

from html.parser import HTMLParser

_BLOCK_TAGS = {
    "p", "div", "section", "article", "li", "h1", "h2", "h3", "h4",
    "h5", "h6", "tr", "br", "header", "footer", "blockquote",
}
_SKIP_TAGS = {"script", "style", "noscript", "template", "head"}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._lines: list[str] = []
        self._buf: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag in _BLOCK_TAGS or tag in ("td", "th"):
            self._flush()
            if tag in _HEADING_TAGS:
                self._buf.append("\n[heading] ")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag in _BLOCK_TAGS or tag in ("td", "th"):
            self._flush()

    def handle_data(self, data):
        if self._skip_depth == 0 and data.strip():
            self._buf.append(data.strip())

    def _flush(self) -> None:
        if self._buf:
            self._lines.append(" ".join(self._buf).strip())
            self._buf = []

    def text(self) -> str:
        self._flush()
        return "\n".join(line for line in self._lines if line)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - malformed HTML must never break scraping
        return ""
    return parser.text()
