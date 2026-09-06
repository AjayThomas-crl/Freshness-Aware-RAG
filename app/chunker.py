import hashlib
import re


def normalize_ws(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def chunk_text(text: str, min_chars: int = 80, max_chars: int = 600) -> list[str]:
    """
    Simple, dependency-free block chunker.

    Splits on paragraph boundaries (blank lines). Small blocks are merged up to
    `max_chars`; oversized paragraphs are split on sentence boundaries.
    """
    paragraphs = [normalize_ws(p) for p in re.split(r"\n\s*\n", text)]
    paragraphs = [p for p in paragraphs if p]

    chunks: list[str] = []
    buf = ""
    for p in paragraphs:
        if len(p) > max_chars:
            if buf:
                chunks.append(buf)
                buf = ""
            chunks.extend(_split_long(p, max_chars))
            continue
        if buf and len(buf) + len(p) + 1 > max_chars:
            chunks.append(buf)
            buf = p
        else:
            buf = f"{buf} {p}".strip()
    if buf:
        chunks.append(buf)
    return [c for c in chunks if len(c) >= min_chars]


def _split_long(paragraph: str, max_chars: int) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", paragraph)
    out: list[str] = []
    buf = ""
    for s in sentences:
        if buf and len(buf) + len(s) + 1 > max_chars:
            out.append(buf)
            buf = s
        else:
            buf = f"{buf} {s}".strip()
    if buf:
        out.append(buf)
    return out


def content_hash(text: str) -> str:
    """Stable content fingerprint. Same content -> same hash -> 'no change'."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
