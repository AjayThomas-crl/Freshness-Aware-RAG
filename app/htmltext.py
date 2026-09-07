"""Tiny HTML -> readable-text extractor (stdlib only).

Renders a simple HTML document into plain paragraphs good enough for chunking:
- block elements become their own paragraphs (blank-line separated)
- headings keep a "[heading]" marker
- tables render one line per row: "cell1 | cell2 | cell3"
- scripts/styles are dropped
"""

from html.parser import HTMLParser

_BLOCK_TAGS = {
    "p",
    "div",
    "section",
    "article",
    "li",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "tr",
    "br",
    "header",
    "footer",
    "blockquote",
}
_SKIP_TAGS = {"script", "style", "noscript", "template", "head"}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._paragraphs: list[str] = []
        self._buf: list[str] = []
        self._skip_depth = 0
        self._in_row = False
        self._row_cells: list[str] = []
        self._row_buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
        elif tag == "tr":
            self._in_row = True
            self._row_cells = []
        elif tag in ("td", "th"):
            self._flush_inline()
        elif tag in _BLOCK_TAGS:
            self._flush_paragraph()
            if tag in _HEADING_TAGS:
                self._buf.append("[heading] ")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
        elif tag == "tr":
            self._finish_row()
        elif tag in _BLOCK_TAGS:
            self._flush_paragraph()

    def handle_data(self, data):
        if self._skip_depth == 0 and data.strip():
            self._buf.append(data.strip())

    def _flush_inline(self) -> None:
        # A single cell's text, buffered until its row ends.
        if self._buf:
            self._row_cells.append(" ".join(self._buf))
            self._buf = []

    def _finish_row(self) -> None:
        self._flush_inline()
        if self._row_cells:
            self._paragraphs.append(" | ".join(self._row_cells))
            self._row_cells = []
        self._in_row = False

    def _flush_paragraph(self) -> None:
        self._flush_inline()
        if self._row_cells:
            self._finish_row()
        if self._buf:
            self._paragraphs.append(" ".join(self._buf))
            self._buf = []

    def text(self) -> str:
        self._flush_paragraph()
        return "\n\n".join(p for p in self._paragraphs if p)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - malformed HTML must never break scraping
        return ""
    return parser.text()
