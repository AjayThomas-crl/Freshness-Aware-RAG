from app.chunker import chunk_text, content_hash, normalize_ws


class TestContentHash:
    def test_same_content_same_hash(self):
        assert content_hash("Nestle milk 1L price 3.99") == content_hash(
            "Nestle milk 1L price 3.99"
        )

    def test_different_content_different_hash(self):
        assert content_hash("price 3.99") != content_hash("price 4.49")

    def test_hash_is_sha256_hex(self):
        h = content_hash("anything")
        assert len(h) == 64
        int(h, 16)  # hex

    def test_whitespace_insensitive_after_normalization(self):
        # content_hash is raw, but chunk_text normalizes first; hashing the
        # normalized text must agree regardless of the raw whitespace.
        assert chunk_text("a  b\n\n c d") == chunk_text("a b\n\nc d")


class TestNormalizeWs:
    def test_collapses_whitespace(self):
        assert normalize_ws("a\n\n b   c") == "a b c"

    def test_strips_edges(self):
        assert normalize_ws("  hello  ") == "hello"


class TestChunkText:
    def test_empty_input_returns_no_chunks(self):
        assert chunk_text("") == []
        assert chunk_text("\n\n\n  \n\n") == []

    def test_short_text_is_single_chunk(self):
        text = "Only one paragraph here, long enough to survive the min length filter."
        assert chunk_text(text, min_chars=10) == [text.strip()]

    def test_paragraphs_merged_up_to_max(self):
        # Each paragraph alone is below min_chars-ish; total <= max -> one block.
        a = "Paragraph alpha with a bit of length to it."
        b = "Paragraph beta with a bit of length to it."
        text = f"{a}\n\n{b}"
        out = chunk_text(text, min_chars=5, max_chars=600)
        assert len(out) == 1
        assert "alpha" in out[0] and "beta" in out[0]

    def test_large_text_yields_multiple_bounded_blocks(self):
        paras = [
            f"This is paragraph number {i} with enough words to keep each "
            f"block reasonably sized for embedding purposes."
            for i in range(30)
        ]
        out = chunk_text("\n\n".join(paras), min_chars=20, max_chars=200)
        assert len(out) > 1
        assert all(len(c) <= 200 for c in out)
        assert all(len(c) >= 20 for c in out)

    def test_single_oversized_paragraph_split_on_sentences(self):
        text = ". ".join(f"Sentence {i} of a very long run-on" for i in range(40)) + "."
        out = chunk_text(text, min_chars=20, max_chars=200)
        assert len(out) > 1
        assert all(len(c) <= 200 for c in out)

    def test_very_short_paragraph_dropped_by_min_chars(self):
        text = "tiny.\n\nThis is a proper longer paragraph that should be kept."
        out = chunk_text(text, min_chars=10)
        assert "tiny." not in out
        assert len(out) == 1

    def test_normalization_makes_hash_stable_across_whitespace(self):
        raw = "Price is  4.49 USD.\n\nIn stock now."
        out = chunk_text(raw, min_chars=5)
        assert content_hash(out[0]) == content_hash("Price is 4.49 USD. In stock now.")
